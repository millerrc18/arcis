# Hotfix Sprint: Critical Safety Fixes
# Fire BETWEEN Sprint 1 and Sprint 2. Do not skip.

> **CONTEXT:** Automated audit agents (CC + Codex) found 3 critical and 4 high-severity
> bugs in the execution pipeline. These affect live trading safety and data integrity.
> The system is mostly paper trading ($100K paper + $100 live), but these bugs will
> compound as live capital increases.
>
> **SCOPE:** 7 fixes. No new features. No refactoring. Fix the bugs, add tests, push.
>
> **Pre-read (mandatory, IN FULL):**
> ```
> cat src/shadow_trading/executor.py
> cat src/shadow_trading/alpaca_adapter.py
> cat src/llm/validator.py
> cat src/api/routes/shadow.py
> cat src/risk/governor.py
> cat src/council/agents.py
> ```
>
> **Run before starting:** `python -m pytest tests/ -x -q`

---

## Fix 1: CRITICAL — Safety checks fail open on errors (#42)

**File:** `src/shadow_trading/executor.py` (and anywhere else safety checks exist)
**Bug:** When a safety check query errors (DB failure, missing table, etc.), the
except block catches the error and CONTINUES toward order submission.
**Correct behavior:** Safety checks must FAIL CLOSED. Any error = do not trade.

**Find every pattern like this:**
```python
try:
    # safety check query
    result = check_something()
except Exception:
    pass  # ← BUG: continues to order submission
```

**Replace with:**
```python
try:
    result = check_something()
except Exception as e:
    logger.error("[SAFETY] Check failed, blocking trade: %s", e)
    return None  # or raise, or set a blocking flag
```

**Search the entire execution path:**
```bash
grep -n "except.*:" src/shadow_trading/executor.py src/risk/governor.py | grep -v "logger"
```

Every bare except or except-pass in the execution pipeline must either log+block or log+raise.

**Test:** Write a test that mocks a DB failure during safety check and verifies the trade is NOT submitted.

---

## Fix 2: CRITICAL — Journal closes before broker confirmation (#41)

**File:** `src/shadow_trading/executor.py` (close/exit paths)
**Bug:** When closing a trade, the system marks it closed in the local DB BEFORE
the broker confirms the exit order. If the broker fails, the DB says "closed"
but the position is still open on Alpaca. State desync.

**Correct pattern:**
```python
# WRONG:
update_trade_status(trade_id, "closed")  # ← writes DB first
broker_result = submit_exit_order(ticker)  # ← might fail
# Now DB says closed but position still open

# RIGHT:
broker_result = submit_exit_order(ticker)
if broker_result and broker_result.status == "filled":
    update_trade_status(trade_id, "closed")
elif broker_result:
    update_trade_status(trade_id, "exit_pending")
    logger.warning("[EXIT] Order submitted but not filled: %s", broker_result.id)
else:
    logger.error("[EXIT] Broker exit failed for %s — position still open", ticker)
    # DO NOT update DB — trade remains "open"
```

**Find all close paths:**
```bash
grep -n "status.*closed\|closed.*status\|update.*closed" src/shadow_trading/executor.py src/api/routes/shadow.py
```

**Test:** Mock a broker exit failure and verify the trade stays "open" in the DB.

---

## Fix 3: CRITICAL — LLM validator rejects real TradePacket schema (#40)

**File:** `src/llm/validator.py`
**Bug:** The validator checks against a legacy packet shape, not the actual
`TradePacket` dataclass. In bootcamp mode, this blocks valid shadow trades
from executing. The system may not be opening trades it should be opening.

**Fix:**
1. Read the actual `TradePacket` definition (likely in `src/packets/template.py` or similar)
2. Update `validator.py` to validate against the ACTUAL fields
3. If the validator is doing structural validation (required keys, types), align with reality
4. If it's doing content validation (conviction range, direction values), keep that logic

**Find the actual packet shape:**
```bash
grep -rn "class TradePacket\|class Packet\|@dataclass" src/packets/ src/llm/ | head -10
```

**Test:** Create a valid TradePacket from the current pipeline and verify the validator accepts it.

---

## Fix 4: HIGH — Paper trades recorded as open on submission failure (#46)

**File:** `src/shadow_trading/executor.py`
**Bug:** If both bracket order AND fallback simple order fail, the trade is still
logged locally as "open". Creates phantom positions in the database.

**Fix:**
```python
# WRONG:
log_trade(trade_id, status="open")  # ← logged before submission
bracket_result = submit_bracket_order(...)
if not bracket_result:
    simple_result = submit_simple_order(...)
    if not simple_result:
        pass  # ← trade is still "open" in DB with no Alpaca order

# RIGHT:
bracket_result = submit_bracket_order(...)
if bracket_result:
    log_trade(trade_id, status="open", alpaca_order_id=bracket_result.id)
else:
    simple_result = submit_simple_order(...)
    if simple_result:
        log_trade(trade_id, status="open", alpaca_order_id=simple_result.id)
    else:
        log_trade(trade_id, status="failed")
        logger.error("[EXEC] Both bracket and simple order failed for %s", ticker)
```

**Test:** Mock both order types failing and verify the trade is logged as "failed", not "open".

---

## Fix 5: HIGH — /shadow/close can close live trades without broker exit (#45)

**File:** `src/api/routes/shadow.py`
**Bug:** The local API route updates journal state for any open trade by ticker,
including live trades, without sending a broker exit order. Could mark a live
trade as "closed" while the position stays open on Alpaca.

**Fix:**
```python
@router.post("/shadow/close")
async def close_shadow_trade(ticker: str):
    trade = get_open_trade(ticker)
    if not trade:
        return {"error": "No open trade found"}

    if trade["source"] == "live":
        # MUST send broker exit
        broker_result = submit_exit_order(ticker)
        if not broker_result:
            return {"error": "Broker exit failed — trade remains open"}

    # Only update DB after broker confirms (or if paper-only)
    update_trade_status(trade["trade_id"], "closed", exit_reason="manual_close")
    return {"status": "closed"}
```

**Test:** Mock a live trade close request and verify the broker exit is attempted before DB update.

---

## Fix 6: HIGH — Council agents query wrong database schema (#44)

**File:** `src/council/agents.py`
**Bug:** Three confirmed column mismatches cause silent failures:

| Query | Expected Column | Actual Column | Agent Affected |
|---|---|---|---|
| `SELECT vix_close FROM vix_term_structure` | `vix_close` | `vix` | tactical_operator |
| `ORDER BY date` (vix_term_structure) | `date` | `collected_date` | tactical_operator |
| `SELECT value, date FROM macro_snapshots` | `date` | `collected_date` | macro_navigator |
| `ORDER BY date` (macro_snapshots) | `date` | `collected_date` | macro_navigator |
| `WHERE sector IS NOT NULL` (shadow_trades) | `sector` | DOES NOT EXIST | red_team |

**Fixes (exact):**

```python
# tactical_operator: vix query
# OLD:
"SELECT vix_close, vix9d, vix3m FROM vix_term_structure ORDER BY date DESC LIMIT 1"
# NEW:
"SELECT vix, vix9d, vix3m FROM vix_term_structure ORDER BY collected_date DESC LIMIT 1"

# Also fix the field access:
# OLD: vix['vix_close']
# NEW: vix['vix']

# macro_navigator: all macro queries
# OLD:
"SELECT value, date FROM macro_snapshots WHERE series_id = ? ORDER BY date DESC LIMIT 1"
# NEW:
"SELECT value, collected_date FROM macro_snapshots WHERE series_id = ? ORDER BY collected_date DESC LIMIT 1"

# Also fix field access:
# OLD: row['date']
# NEW: row['collected_date']

# red_team: sector concentration
# OLD:
"SELECT sector, COUNT(*) as n ... FROM shadow_trades WHERE status = 'open' AND sector IS NOT NULL GROUP BY sector"
# NEW: Join with recommendations table which has sector_context:
"SELECT r.sector_context as sector, COUNT(*) as n, SUM(st.planned_allocation) as alloc "
"FROM shadow_trades st LEFT JOIN recommendations r ON st.recommendation_id = r.recommendation_id "
"WHERE st.status = 'open' AND r.sector_context IS NOT NULL "
"GROUP BY r.sector_context ORDER BY n DESC"
```

**Test:** Each agent gather function returns non-empty data on a populated test database.

---

## Fix 7: MEDIUM — Telegram trade-open notification uses nonexistent fields (#48)

**File:** `src/scheduler/watch.py` (or `src/notifications/telegram.py`)
**Bug:** The watch loop builds open-trade Telegram notifications from `PositionSizing`
attributes that don't exist, so the notification silently fails.

**Fix:**
1. Find the notification code that references PositionSizing
2. Check the actual PositionSizing class/dict fields
3. Map to correct field names
4. Add a try/except with fallback message so notification always sends

```bash
grep -n "PositionSizing\|position_sizing\|notify.*trade.*open\|notify.*entry" src/scheduler/watch.py src/notifications/telegram.py | head -10
```

**Test:** Mock a trade open event and verify the Telegram notification is constructed without errors.

---

# Verification Gate

```bash
# All tests pass
python -m pytest tests/ -v --tb=short

# No bare excepts in safety-critical code
grep -rn "except.*:" src/shadow_trading/ src/risk/ --include="*.py" -A1 | grep "pass$"
# Must return EMPTY

# Council agents query correct columns
python3 -c "
from src.council.agents import gather_tactical_data, gather_risk_data, gather_macro_data
print('Tactical:', gather_tactical_data()[:50])
print('Risk:', gather_risk_data()[:50])
print('Macro:', gather_macro_data()[:50])
"
# All should return non-empty strings (not 'No X data available')
```

---

# Sprint Documentation Checklist

### Tier 1 (MANDATORY):
- [ ] All 7 fixes implemented
- [ ] Tests added for each fix
- [ ] All tests pass
- [ ] CHANGELOG.md — hotfix entry
- [ ] No bare except:pass in execution pipeline
- [ ] Council agents return real data (not fallback strings)
