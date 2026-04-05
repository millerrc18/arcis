# Sprint: Gap Analysis Rectification — 23 Issues in 3 Tiers

> **Priority:** CRITICAL — 6 issues affect live trading correctness and training data integrity
> **Estimated time:** 6-10 hours CC time
> **Access:** Remote only — all fixes are pure code changes, no local runtime needed
> **Tag as v0.13.0 after merge.**

> ⚠️ **Tier 1 issues affect REAL MONEY or TRAINING DATA QUALITY. Fix these first, in order. Do not start Tier 2 until all Tier 1 issues pass tests.**

---

## Pre-Flight

1. Read `MASTER.md` — current state
2. Run `python -m pytest tests/ -x -q` — record baseline pass count
3. Read this ENTIRE prompt before starting. Tier 1 issues interact with each other.

---

## Tier 1: CRITICAL — Money at Risk + Training Data Integrity (6 issues)

These issues can cause incorrect trades, unprotected positions, or poisoned training data. Fix in this exact order because later fixes depend on earlier ones.

### 1.1 #272: Live trading bypasses RiskGovernor and LLM validator entirely
**File:** `src/shadow_trading/executor.py` — `open_live_trade()` (~line 965)
**Impact:** CRITICAL — live trades skip the 8-check risk governor and LLM output validation. Paper trading enforces both (lines 106-130). A trade that paper rejects can still execute with real money.
**Fix:** Add the same `RiskGovernor.check_trade()` and `validate_llm_output()` calls that exist in `open_shadow_trade()` to `open_live_trade()`. Extract the validation block into a shared helper to avoid duplication:
```python
def _validate_trade_candidate(ticker, features, packet, config, db_path):
    """Shared validation for paper and live trades. Returns (passed, reason)."""
    # Risk governor check
    from src.risk.governor import RiskGovernor
    governor = RiskGovernor(config, db_path)
    passed, reason = governor.check_trade(ticker, features, packet)
    if not passed:
        return False, f"Governor rejected: {reason}"
    # LLM output validation
    from src.llm.validator import validate_llm_output
    valid, issues = validate_llm_output(packet, ticker, features)
    if not valid:
        return False, f"Validation failed: {issues}"
    return True, "passed"
```
Call this from BOTH `open_shadow_trade()` and `open_live_trade()`.
**Test:** Add test verifying `open_live_trade()` rejects when governor rejects.

### 1.2 #274: Bracket order fallback to simple market leaves trade without stop-loss
**File:** `src/shadow_trading/executor.py` (~line 329)
**Impact:** CRITICAL — when bracket order fails, the fallback places a naked market buy with NO stop-loss. The position is protected only by the polling loop (15-min checks). If the system sleeps or crashes, the position has zero downside protection.
**Fix:** Two options (implement BOTH):
1. After fallback market entry succeeds, immediately submit a standalone stop-loss order:
```python
# Fallback: market entry + separate stop order
order = place_paper_entry(ticker, planned_shares)
# Immediately place stop protection
try:
    place_paper_exit(ticker, planned_shares, stop_price=stop_price, order_type="stop")
except Exception as e:
    logger.error("[SHADOW] CRITICAL: Entry filled but stop-loss failed for %s: %s", ticker, e)
    # Send Telegram alert — position is unprotected
```
2. If BOTH bracket AND stop-loss submission fail, CLOSE the position immediately and log an error. An unprotected position is worse than no position.
**Test:** Add test for bracket failure fallback path.

### 1.3 #275: Live daily loss guard uses all-time unrealized P&L, not today's realized losses
**File:** `src/shadow_trading/executor.py` (~line 1042)
**Impact:** CRITICAL — the -5% daily loss limit sums ALL open trades' unrealized P&L (including positions opened weeks ago) and excludes today's realized losses from closed trades. This means:
- A trade closed for -$500 today doesn't count toward the daily loss limit
- An old trade showing -$3,000 unrealized (from last week) triggers the limit even if today was profitable
**Fix:** Query today's realized P&L from closed trades:
```python
today = datetime.now(ET).strftime("%Y-%m-%d")
today_realized = conn.execute(
    "SELECT COALESCE(SUM(pnl_dollars), 0) FROM shadow_trades "
    "WHERE status='closed' AND source='live' AND actual_exit_time LIKE ?",
    (f"{today}%",)
).fetchone()[0]
daily_loss = float(today_realized)  # Negative = losses
```
Use `daily_loss` for the guard, not unrealized P&L from open positions.
**Test:** Add test with mock closed trades showing daily loss guard triggers correctly.

### 1.4 #277: Feature snapshot sanitized AFTER LLM generation — potential self-blinding leak
**File:** `src/training/data_collector.py` (~line 186)
**Impact:** CRITICAL for training data quality — `_sanitize_feature_snapshot()` removes outcome-correlated data, but it's called AFTER the unsanitized features were already sent to Claude for commentary generation (lines 174, 181). If the raw features contain any outcome-leaking fields (e.g., `pnl_dollars`, `exit_reason`), the LLM saw them during generation.
**Fix:** Call `_sanitize_feature_snapshot()` BEFORE passing features to the LLM:
```python
# BEFORE (broken):
commentary = generate_example(raw_features)  # LLM sees everything
sanitized = _sanitize_feature_snapshot(raw_features)  # Too late

# AFTER (correct):
sanitized = _sanitize_feature_snapshot(raw_features)  # Clean first
commentary = generate_example(sanitized)  # LLM only sees clean data
```
**Verify:** Check what `_sanitize_feature_snapshot` actually removes. Does it strip `pnl_dollars`, `exit_reason`, `actual_exit_price`? If not, add those to the sanitizer.
**Test:** Add test verifying sanitized snapshot contains no outcome fields.

### 1.5 #273: Empty-output training templates contaminate fine-tuning dataset
**File:** `src/training/trainer.py` (~line 486)
**Impact:** HIGH — outcome-conditioned templates stored with `output_text=''` are included in the training dataset. Training on empty outputs teaches the model to produce empty responses.
**Fix:** Filter out empty outputs in the training export:
```python
# In the query that builds the training dataset:
WHERE output_text IS NOT NULL AND output_text != '' AND LENGTH(output_text) > 50
```
Also verify: does the source prefix `outcome_template_` filter work? Check if the export query already excludes by source.
**Test:** Add test verifying training export excludes empty output_text rows.

### 1.6 #278: Partially filled exit orders recorded as fully closed with wrong P&L
**File:** `src/shadow_trading/executor.py` (~line 47)
**Impact:** HIGH — `FILLED_ORDER_STATUSES` includes `'partially_filled'`. A 50/100 share exit is treated as fully closed. P&L is calculated on full shares, not filled shares. The remaining 50 shares become an orphaned position with no tracking.
**Fix:** Handle partial fills explicitly:
```python
if order_status == "partially_filled":
    filled_qty = order.get("filled_qty", 0)
    total_qty = order.get("total_qty", planned_shares)
    if filled_qty < total_qty:
        # Don't close the trade — update shares remaining
        remaining = total_qty - filled_qty
        logger.warning("[SHADOW] Partial fill for %s: %d/%d shares. %d remaining.",
                       ticker, filled_qty, total_qty, remaining)
        # Record partial P&L but keep trade open with reduced shares
        # ... or resubmit exit for remaining shares
```
Remove `'partially_filled'` from `FILLED_ORDER_STATUSES`.
**Test:** Add test for partial fill handling.

---

## Tier 2: HIGH — Reliability + Correctness (8 issues)

These cause incorrect behavior but don't directly risk money.

### 2.1 #271: MR exit calls close_shadow_trade with missing arguments
**File:** `src/shadow_trading/executor.py` (~line 674, 696)
**Fix:** Add `exit_time=datetime.now(ET).isoformat()` and compute `pnl_pct` from `(exit_price - entry_price) / entry_price * 100`. Both MR exit paths (RSI-based and timeout) need this.

### 2.2 #276: Duplicate position check lock released before trade insert — race window
**File:** `src/shadow_trading/executor.py` (~line 167)
**Fix:** Move the INSERT inside the same BEGIN IMMEDIATE transaction as the duplicate check, or use a separate mutex. The current pattern: BEGIN → check → ROLLBACK → (230 lines later) → INSERT leaves a race window.

### 2.3 #267: Traffic light multiplier defaults to 1.0 when feature missing
**File:** `src/shadow_trading/executor.py` (~line 123)
**Fix:** Default to a conservative multiplier (0.5) when traffic light data is missing, not 1.0 (full size). Missing data should reduce position size, not maintain it. Or log a warning and block the trade entirely if regime data is stale.

### 2.4 #257: _safe_run done-flags set on failure — failed tasks never retry
**File:** `src/scheduler/watch.py`
**Fix:** Only set `self._xxx_done = True` INSIDE the try block, not unconditionally. Currently, if morning watchlist fails, `self._morning_done = True` is still set, and it never retries.

### 2.5 #258: 220+ sqlite3.connect() calls bypass connect_db helper
**File:** Throughout `src/`
**Fix:** This is a bulk refactor. Create a `from src.utils.db import connect_db` call that sets WAL mode + busy_timeout, and replace the raw `sqlite3.connect()` calls. Start with the 10 highest-traffic files (executor, watch, render_sync, data_collector, alpaca_adapter). The rest can be a follow-up.

### 2.6 #259: pull_commands marks all claimed even if local insert fails
**File:** `src/sync/render_sync.py` (~line 473)
**Fix:** Only UPDATE the Postgres `claimed=TRUE` for command IDs that were successfully inserted into local SQLite. Track which IDs succeeded and which failed.

### 2.7 #269: _notify_exit_trade missing parameters at call sites
**File:** `src/shadow_trading/executor.py` (~lines 655, 677)
**Fix:** Add `exit_time` and `pnl_pct` to all call sites. These were likely added to the function signature but not all callers were updated.

### 2.8 #264: open_shadow_trade returns dict on buying power failure
**File:** `src/shadow_trading/executor.py` (~line 303)
**Fix:** Return `None` (or `trade_data.get("trade_id")`) consistently. Currently returns the full dict on one error path, which breaks callers expecting a string trade_id.

---

## Tier 3: MEDIUM — Improvements + Polish (9 issues)

These are correctness improvements and technical debt. Fix after Tiers 1-2.

### 3.1 #256: Options metrics query uses wrong column names — pipeline dead
**Fix:** Check the schema registry for `options_metrics` column names and update the query. The entire options pipeline is silently producing nothing.

### 3.2 #260: Options chains table no retention — unbounded growth
**Fix:** Add `options_chains` to `RETENTION_RULES` in `retention.py`. 30 days is sufficient (chains are re-fetched nightly). Estimate current size and log the cleanup.

### 3.3 #261: Options flow collected but never used in training
**Fix:** This is a feature gap, not a bug. File as future enhancement — options features feed into training when Strategy #3 (options desk) starts. No code change needed now, just acknowledge in the issue.

### 3.4 #262: earnings_signals swallows all computation errors
**Fix:** Replace `except: pass` with `except Exception as e: logger.warning(...)` in all 4 computation blocks. Same pattern as #82 fix.

### 3.5 #263: Duplicate log in place_bracket_order
**Fix:** Remove the duplicate `logger.info` line. One-liner.

### 3.6 #265: review_scorecard and review_postmortems are stubs
**Fix:** Either implement (wire to cto_report data) or document as "Phase 2" and return `{"status": "not_implemented", "message": "Available in Phase 2"}` instead of empty dict.

### 3.7 #266: shadow_account queries different columns than shadow_open
**Fix:** Unify the queries so both endpoints return consistent data for the same trades.

### 3.8 #268: compute_canary_score import path broken
**Fix:** Either fix the import path or remove the dead code. Check if `src.strategy.canary` exists.

### 3.9 #270: No market holiday calendar
**Fix:** Add a `MARKET_HOLIDAYS` list for NYSE holidays in 2026 (10 dates). Check against it in `_should_scan()`. Can use the `exchange_calendars` pip package if available, or hardcode the 2026 dates.

---

## Verification

After ALL tiers complete:
```bash
python -m pytest tests/ -x -q  # Pass count ≥ baseline + new tests
cd frontend && npm run build    # Still succeeds
```

**Tier 1 specific checks:**
```bash
# #272: Verify live trades go through governor
grep -n "check_trade\|validate_llm" src/shadow_trading/executor.py | grep -c "open_live"
# Should be ≥1

# #274: Verify bracket fallback places stop
grep -n "stop_price\|stop_loss" src/shadow_trading/executor.py | grep -i "fallback"

# #277: Verify sanitize is called BEFORE LLM generation
grep -n "sanitize\|generate_example" src/training/data_collector.py
# sanitize line number should be LOWER than generate line number

# #273: Verify training export filters empty outputs
grep -n "output_text.*!=" src/training/trainer.py
```

**Close all 23 issues after fixing:**
```bash
for issue in $(seq 256 278); do
  gh issue close $issue --comment "Fixed in v0.13.0 rectification sprint"
done
```

---

## Commit

3 commits by tier:

```bash
# Commit 1: Tier 1 — CRITICAL fixes
git add -A
git commit -m "fix: 6 critical gap-analysis issues — live trading safety + training integrity

CRITICAL (money at risk):
- #272: Live trading now enforces RiskGovernor + LLM validator (was bypassed)
- #274: Bracket fallback places standalone stop + closes if stop fails
- #275: Daily loss guard uses today's realized P&L, not all-time unrealized
- #278: Partial fills tracked correctly, not recorded as full close

CRITICAL (training data):
- #277: Feature sanitization BEFORE LLM generation (self-blinding fixed)
- #273: Empty-output templates excluded from training dataset

Closes #272, #273, #274, #275, #277, #278"

# Commit 2: Tier 2 — HIGH reliability fixes
git add -A
git commit -m "fix: 8 high-priority gap-analysis issues — reliability + correctness

- #271: MR exit passes all required args to close_shadow_trade
- #276: Duplicate position check + insert in same transaction
- #267: Traffic light defaults to 0.5 (conservative) when missing
- #257: _safe_run only sets done-flag on success
- #258: Top 10 files migrated to connect_db helper (busy_timeout)
- #259: pull_commands only claims successfully inserted commands
- #269: _notify_exit_trade call sites pass all required params
- #264: open_shadow_trade returns None consistently on failure

Closes #257, #258, #259, #264, #267, #269, #271, #276"

# Commit 3: Tier 3 — MEDIUM improvements
git add -A
git commit -m "fix: 9 medium gap-analysis issues — polish + technical debt

- #256: Options metrics query column names fixed
- #260: options_chains retention rule added (30 days)
- #261: Documented as future enhancement (options desk Phase 3)
- #262: earnings_signals logs errors instead of swallowing
- #263: Duplicate bracket order log removed
- #265: Stub endpoints return not_implemented status
- #266: shadow_account queries unified with shadow_open
- #268: Dead canary_score import removed
- #270: NYSE 2026 holiday calendar added to watch loop

Closes #256, #260, #261, #262, #263, #265, #266, #268, #270"
```

Tag and push:
```bash
git tag -a v0.13.0 -m "v0.13.0 — 23 gap-analysis issues rectified

Tier 1 (CRITICAL): Live trading safety — governor enforcement, bracket
protection, daily loss guard, self-blinding fix, training data filters.
Tier 2 (HIGH): Reliability — retry logic, race conditions, type safety.
Tier 3 (MEDIUM): Polish — options pipeline, holidays, error logging."
git push origin main && git push origin v0.13.0
```

Update MASTER.md Section 2 and RELEASES.md.
