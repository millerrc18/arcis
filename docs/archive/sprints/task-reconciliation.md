# Task: Automated Daily Reconciliation — Local Ledger vs Alpaca (Issue #170)

> **Executor:** Claude Code
> **Scope:** 1 focused task — add postclose reconciliation to the watch loop
> **Read first:** AGENTS.md, docs/conventions.md
> **Key files:** src/shadow_trading/reconcile.py, src/shadow_trading/alpaca_adapter.py, src/scheduler/watch.py
> **Test baseline:** 1,125 tests. Must not decrease.

---

## Context

Arcis trades autonomously via Alpaca paper trading. The local SQLite `shadow_trades` table tracks all open positions. But there is NO automated checkpoint that compares the local ledger against what Alpaca actually shows. If a bracket order fills overnight while the watch loop is down (computer sleep, crash), or if Alpaca rejects/cancels an order, the local DB silently drifts from reality.

The existing `reconcile_live_trades()` in `src/shadow_trading/reconcile.py` only covers `source='live'` trades and is manual-only. Paper trades (`source='paper'`) — which are 99% of all trades — are never reconciled.

---

## Implementation

### Step 1: Extend reconcile.py to support paper trades

File: `src/shadow_trading/reconcile.py`

Add a new function `reconcile_paper_trades()` modeled on the existing `reconcile_live_trades()`:

```python
def reconcile_paper_trades(
    db_path: str = "ai_research_desk.sqlite3", dry_run: bool = False
) -> dict:
    """Reconcile Alpaca paper positions with local shadow_trades.

    Returns:
        {
            "alpaca_count": int,
            "local_count": int,
            "matched": int,
            "orphaned": [{"ticker": str, "qty": int, "avg_price": float}],  # on Alpaca, not in local DB
            "stale": [{"ticker": str, "trade_id": str}],  # in local DB, not on Alpaca
            "discrepancies": [{"ticker": str, "issue": str}],  # qty or price mismatch
            "backfilled": [str],  # tickers auto-backfilled (if not dry_run)
        }
    """
```

**Logic:**
1. Call Alpaca paper API to get all positions (`GET /v2/positions` via existing `get_paper_positions()` or similar)
2. Query local `shadow_trades WHERE source='paper' AND status='open'`
3. Compare by ticker:
   - Alpaca has it, local doesn't → **orphaned** (backfill into local DB with `order_type='reconciled'`)
   - Local has it, Alpaca doesn't → **stale** (send Telegram alert, do NOT auto-close)
   - Both have it but qty differs → **discrepancy** (log + alert)
   - Both have it and match → **matched**
4. Return summary dict

**Important:** Check if `get_paper_positions()` exists in `alpaca_adapter.py`. If not, add it — it's the same as `get_live_positions()` but using the paper API client. The paper client should already be initialized since that's what `place_bracket_order()` uses.

### Step 2: Add postclose reconciliation to watch loop

File: `src/scheduler/watch.py`

Add a `_run_postclose_reconciliation()` method that:
1. Calls `reconcile_paper_trades()`
2. Sends Telegram summary:
   - If all matched: `✅ Reconciliation: {count} local / {count} Alpaca — all matched`
   - If discrepancies: `❌ Reconciliation: {orphaned} orphaned, {stale} stale, {discrepancies} mismatched`
3. Uses a `_postclose_reconcile_done` flag (same pattern as `_postclose_bracket_check_done`) to run once daily

**Where to hook it:** In the postclose block (after `_run_eod_recap()` and bracket check), add:

```python
if not self._postclose_reconcile_done:
    self._run_postclose_reconciliation()
    self._postclose_reconcile_done = True
```

Reset the flag at midnight (same place where other daily flags reset).

### Step 3: Add Alpaca paper positions getter (if missing)

File: `src/shadow_trading/alpaca_adapter.py`

If `get_paper_positions()` doesn't exist, add:

```python
def get_paper_positions() -> list[dict]:
    """Get all open positions from Alpaca paper account."""
    client = _get_paper_client()
    positions = client.get_all_positions()
    return [
        {
            "symbol": p.symbol,
            "qty": int(p.qty),
            "avg_entry_price": float(p.avg_entry_price),
            "market_value": float(p.market_value),
            "current_price": float(p.current_price),
            "unrealized_pl": float(p.unrealized_pl),
        }
        for p in positions
    ]
```

### Step 4: Tests

File: `tests/test_reconcile.py` (extend existing or create)

Add ≥3 tests:
1. **All matched:** Mock Alpaca returning same tickers as local DB → summary shows 0 discrepancies
2. **Orphaned position:** Mock Alpaca has AAPL but local DB doesn't → backfilled into local DB
3. **Stale position:** Local DB has AAPL open but Alpaca doesn't → flagged as stale, NOT auto-closed

### Step 5: Documentation

- Add entry to CHANGELOG.md
- Update AGENTS.md if any counts changed
- Verify tests pass: `python -m pytest tests/ -x -q`

---

## Pre-Task Checks

```bash
find tests -name "test_*.py" -exec grep -c "def test_" {} + | awk -F: '{s+=$2}END{print "Tests:", s}'
# Must be ≥ 1125
```

---

## What NOT to do

- Do NOT auto-close stale trades — only alert. We'll enable auto-fix after gaining confidence.
- Do NOT reconcile `source='live'` trades — the existing `reconcile_live_trades()` handles that separately.
- Do NOT run reconciliation during market hours — only postclose.
- Do NOT fail the watch loop if Alpaca API is unreachable — log a warning and skip.
