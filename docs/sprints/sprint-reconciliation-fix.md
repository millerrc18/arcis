# Sprint: Reconciliation Data Integrity Fix — 4 Bugs, 6 Steps

> **Priority:** CRITICAL — closed trades are invisible to 10+ query locations across the system.
> **Root cause:** `reconcile.py` uses raw SQL that sets `status = 'closed'` but never sets `actual_exit_time`. Every query that filters on `actual_exit_time >= ?` misses these trades.
> **Impact:** Dashboard, Shadow Ledger, CTO Report, Build Score, Gate Evaluator, Training Data Collector, Risk Governor, Watch Loop — all undercount closed trades.

**CRITICAL: Run `python -m pytest tests/ -x -q` before AND after all changes. Do NOT break existing data connections — the dashboard, Render sync, and training pipeline all depend on `shadow_trades` and `recommendations` tables.**

---

## Pre-Flight

1. Read `SYSTEM_STATE.md` and `AGENTS.md`
2. Read `src/journal/store.py` — especially `close_shadow_trade()` at line 385
3. Read `src/shadow_trading/reconcile.py` — the two reconciliation functions
4. Read `src/shadow_trading/executor.py` — `FILLED_ORDER_STATUSES` and bracket detection
5. Run `python -m pytest tests/ -x -q` — record baseline test count
6. Verify current data: `sqlite3 ai_research_desk.sqlite3 "SELECT COUNT(*) FROM shadow_trades WHERE status='closed' AND actual_exit_time IS NULL"` — this is the count of invisible trades

---

## Step 1: Fix `reconcile_live_trades()` — Bug 1 (CRITICAL)

**File:** `src/shadow_trading/reconcile.py`

The raw SQL UPDATE at lines 138-152 sets `status = 'closed'` but never sets `actual_exit_time`. This makes reconciled trades invisible to 10+ queries.

**Fix:**
1. Add `close_shadow_trade` to the import from `src.journal.store` (around line 68)
2. Replace the raw SQL UPDATE blocks (lines 138-152) with:

```python
# Compute P&L percent
pnl_pct = 0.0
if pnl_dollars is not None and entry_px and shares:
    cost_basis = entry_px * shares
    if cost_basis > 0:
        pnl_pct = round((pnl_dollars / cost_basis) * 100, 2)

close_shadow_trade(
    trade_id=trade_id,
    exit_price=exit_price or 0.0,
    exit_time=now.isoformat(),
    exit_reason="reconciled_stale",
    pnl_dollars=pnl_dollars or 0.0,
    pnl_pct=pnl_pct,
    db_path=db_path,
)
```

3. Handle the case where yfinance/price lookup fails: use `0.0` for unknown values. A trade with `pnl_dollars=0.0` and `actual_exit_time` set is better than an invisible trade.

**Why `close_shadow_trade()` instead of raw SQL:** It's the single function that correctly sets ALL required fields: `status`, `actual_exit_price`, `actual_exit_time`, `exit_reason`, `pnl_dollars`, `pnl_pct`. Every other close path in the system already uses it.

---

## Step 2: Fix `reconcile_paper_trades()` — Bug 2 (HIGH)

**File:** `src/shadow_trading/reconcile.py`

When a bracket leg fills on Alpaca and the position is sold, but the executor misses it, the trade stays "open" in SQLite forever. Currently reconciliation only logs a warning for paper trades.

**Fix:** In the `if not dry_run:` block, after the backfill loop, add auto-close logic for stale paper trades:

1. Same P&L estimation pattern as live trades (yfinance 5-day close lookup)
2. Call `close_shadow_trade()` with `exit_reason='reconciled_stale'`
3. Track in `marked_closed` list
4. Add `"marked_closed": marked_closed` to the return dict

**SAFETY GUARD:** Only auto-close a paper trade if:
- The position is confirmed gone from Alpaca (not just a single API check failure)
- The trade has been open for at least 1 hour (prevents closing on brief API blips)

```python
# Safety: only close if trade has been open for >1 hour
created_at = trade.get("created_at", "")
if created_at:
    try:
        created = datetime.fromisoformat(created_at)
        if (now - created).total_seconds() < 3600:
            logger.info("[RECONCILE] Skipping recent trade %s (< 1 hour old)", ticker)
            continue
    except (ValueError, TypeError):
        pass
```

---

## Step 3: Fix bracket status constant — Bug 3 (MEDIUM)

**File:** `src/shadow_trading/executor.py`

Line 512 uses hardcoded `("filled", "partially_filled")` but `FILLED_ORDER_STATUSES` at line 27 also includes `"closed"` — which Alpaca returns when a bracket order lifecycle completes.

**Fix:** Change line 512 from:
```python
if parent_status in ("filled", "partially_filled"):
```
to:
```python
if parent_status in FILLED_ORDER_STATUSES:
```

---

## Step 4: Improve bracket error logging — Bug 4 (LOW)

**File:** `src/shadow_trading/executor.py`

Line 534 logs bracket status check failures at DEBUG level. Operators never see when bracket detection fails and the system silently falls back to price polling.

**Fix:** Change `logger.debug` to `logger.warning` at line 534.

---

## Step 5: Backfill migration for existing data

**File:** `src/journal/store.py`

Add a migration in `initialize_database()` (or a new migration function) to fix existing invisible trades:

```sql
UPDATE shadow_trades 
SET actual_exit_time = COALESCE(updated_at, created_at)
WHERE status = 'closed' AND actual_exit_time IS NULL
```

This uses `updated_at` (which was set when the raw SQL ran) as a reasonable approximation of exit time. If `updated_at` is also NULL, falls back to `created_at`.

**IMPORTANT:** After this migration runs locally, the Render sync will automatically push the corrected `actual_exit_time` values to Postgres within 2 minutes. No manual sync needed.

---

## Step 6: Update tests

**File:** `tests/test_reconcile.py`

1. **Update `test_reconcile_marks_stale`** (line ~77): Add assertion that `actual_exit_time` is set (not NULL)
2. **Rename and update `test_paper_reconcile_stale_not_auto_closed`** (line ~238): Rename to `test_paper_reconcile_stale_auto_closed`. Change assertions to verify trade IS closed with `exit_reason='reconciled_stale'` and `actual_exit_time` is set.
3. **Add new test: `test_reconcile_stale_without_yfinance`** — verify trade is closed even when price lookup fails (pnl_dollars=0.0, actual_exit_time still set)
4. **Add new test: `test_reconcile_skips_recent_trade`** — verify the 1-hour safety guard prevents closing fresh trades

---

## Data Connection Safety Checklist

These are the active data connections that depend on `shadow_trades`. Verify NONE are broken:

| Query location | Column used | Verify after fix |
|---|---|---|
| `store.py:379` — `get_closed_shadow_trades()` | `actual_exit_time >= ?` | Returns reconciled trades |
| `trades.py:65` — `/api/shadow/closed` | `st.actual_exit_time >= ?` | Dashboard shows all closed |
| `trades.py:93` — `/api/shadow/metrics` | `actual_exit_time >= ?` | Metrics include all trades |
| `analytics.py:376` — `/api/cto-report` | `st.actual_exit_time >= ?` | CTO report accurate |
| `build_score.py:57` — Build Score | `actual_exit_time >= ?` | Score reflects all trades |
| `governor.py:355` — Risk Governor | `actual_exit_time >= ?` | Daily P&L correct |
| `watch.py:2734` — Weekly digest | `actual_exit_time >= ?` | Digest counts correct |
| Render sync → Postgres | All `shadow_trades` columns | Postgres gets corrected data |
| Training data collector | Joins `shadow_trades` → `recommendations` | Closed trades generate examples |

---

## Verification

After all changes:

1. `python -m pytest tests/test_reconcile.py -v` — all tests pass including new ones
2. `python -m pytest tests/ -x -q` — no regressions (must stay >= 1235 tests)
3. `sqlite3 ai_research_desk.sqlite3 "SELECT COUNT(*) FROM shadow_trades WHERE status='closed' AND actual_exit_time IS NULL"` — returns **0**
4. `sqlite3 ai_research_desk.sqlite3 "SELECT trade_id, ticker, exit_reason, actual_exit_time FROM shadow_trades WHERE status='closed'"` — all rows have `actual_exit_time` set
5. Dashboard check: `curl localhost:8000/api/shadow/closed?days=90` — returns all closed trades

---

## Backlog Note

The React Flow interactive diagrams sprint (`docs/sprints/sprint-react-flow.md`) is queued as the NEXT sprint after this data integrity fix ships. Do not combine.
