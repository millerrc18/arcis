# Sprint: Log Audit Hotfix — Production Issues from arcis.log

> **Priority:** CRITICAL — positions may be unprotected, earnings signals completely dead
> **Estimated time:** 3-4 hours CC time
> **Access:** Remote OK — all fixes are code + schema changes
> **Tag as v0.14.1 after merge.**

> ⚠️ **Read the attached log file first.** Ryan will paste key sections below. The log is 15,031 lines from March 30 – April 4, 2026. There are 1,644 ERROR lines.

---

## Pre-Flight

1. Read `MASTER.md`
2. Run `python -m pytest tests/ -x -q` — record baseline
3. Read `src/schema/registry.py` — check `analyst_estimates` and `earnings_calendar` column definitions

---

## Issue 1: Bracket check shows 0/N protected — EVERY CHECK (CRITICAL)

**Log evidence:**
```
2026-04-01 09:04:35 [WATCH] Bracket check (premarket): 0/9 protected
2026-04-01 09:53:06 [WATCH] Bracket check (intraday): 0/8 protected
2026-04-01 13:25:05 [WATCH] Bracket check (intraday): 0/10 protected
2026-04-03 16:31:19 [WATCH] Bracket check (postclose): 0/9 protected
2026-04-04 16:30:44 [WATCH] Bracket check (postclose): 0/9 protected
```

Every single bracket check across 5 days shows 0 positions protected. This means no open positions have active stop-loss/take-profit orders recognized by the monitor.

**Root cause:** Likely #248 — Alpaca order status enum returns `orderstatus.held` instead of `held`. The bracket monitor compares against bare strings.

**Fix:** 
1. Find the bracket check logic in `src/shadow_trading/bracket_monitor.py`
2. Verify the status comparison strips the enum prefix: `status = str(order.status).split(".")[-1]` or uses `.value`
3. If #248 was already fixed in v0.13.0, check whether the fix is actually in the bracket monitor file (not just the serializer)
4. Add a test that verifies bracket check correctly identifies protected positions
5. **CRITICAL**: After fixing, the next bracket check should show N/N protected, not 0/N

---

## Issue 2: Earnings signals — 3 missing columns (HIGH)

**Log evidence (fires 300+ times per scan, 3 per ticker × 102 tickers):**
```
[EARNINGS] last_surprise signal failed for AAPL: no such column: eps_actual
[EARNINGS] revenue_eps_concordance signal failed for AAPL: no such column: revenue_actual
[EARNINGS] analyst_revision_velocity signal failed for AAPL: no such column: eps_estimate
```

**Root cause:** `earnings_signals.py` queries columns `eps_actual`, `revenue_actual`, `eps_estimate` from the `analyst_estimates` table, but those columns don't exist in the schema.

**Fix:**
1. Check `src/schema/registry.py` for the `analyst_estimates` table definition — what columns actually exist?
2. Check `src/data_collection/analyst_collector.py` — what columns does it write?
3. Either:
   a. Add the missing columns to the schema registry (`eps_actual`, `revenue_actual`, `eps_estimate`) and populate them from the Finnhub analyst endpoint, OR
   b. Fix `earnings_signals.py` to use the correct column names that already exist in the table
4. Run `python -m src.main validate-schema --fix` after any schema changes
5. Add a test that verifies earnings signals compute without error

---

## Issue 3: Overnight training script — missing module (HIGH)

**Log evidence:**
```
ModuleNotFoundError: No module named 'src.scheduler.overnight'
```

**Root cause:** `scripts/overnight_train.py` line 15 imports `from src.scheduler.overnight import OvernightPipeline` — this module doesn't exist.

**Fix:**
1. Check what `overnight_train.py` actually needs to do (read the full script)
2. Either:
   a. Create `src/scheduler/overnight.py` with an `OvernightPipeline` class that wraps the training workflow, OR
   b. Fix the import to use the correct existing module (likely `src/training/trainer.py`)
3. Verify the script runs without import errors: `python -c "import scripts.overnight_train"` (don't actually run training)

---

## Issue 4: Postgres sync — persistent failures (MEDIUM)

**Log evidence (latest run, April 4):**
```
Postgres replace failed for options_metrics: duplicate key value violates unique constraint "options_metrics_pkey" — Key (id)=(36) already exists.
Postgres replace failed for macro_snapshots: duplicate key value violates unique constraint "macro_snapshots_pkey" — Key (id)=(36) already exists.
Postgres upsert failed for research_docs: null value in column "id" — Failing row contains (null, ...)
Postgres upsert failed for traffic_light_state: null value in column "id" — Failing row contains (null, ...)
```

**Root cause:** Multiple issues:
- `options_metrics` and `macro_snapshots`: SERIAL id columns conflict — SQLite uses autoincrement that doesn't match Postgres sequences
- `research_docs` and `traffic_light_state`: Rows have NULL `id` — SQLite ROWID is not being synced

**Fix:**
1. For duplicate PK: Use `ON CONFLICT (id) DO UPDATE` instead of `ON CONFLICT DO NOTHING` for these tables
2. For null ID: Ensure `render_sync.py` excludes rows where `id IS NULL`, or assigns IDs before sync
3. Run `DATABASE_URL=... python scripts/render_migrate.py` to add missing columns to Postgres (shadow_trades.broker, shadow_trades.regime_at_entry, etc.)
4. Add the null-id guard: `WHERE id IS NOT NULL` to the sync query for affected tables

---

## Issue 5: Live trade check type error (MEDIUM)

**Log evidence:**
```
2026-04-03 13:43:42 [POSITION] Live trade check failed: '<=' not supported between instances of 'str' and 'int'
```

**Root cause:** A string value from SQLite is being compared to an integer without casting. Likely a `days_open` or `pnl_dollars` field read as TEXT.

**Fix:**
1. Find the comparison in `position_monitor.py` or `executor.py` that triggers on `source_filter="live"`
2. Add `float()` or `int()` cast to the value read from SQLite
3. Reference #195 pattern (same root cause — SQLite TEXT columns in numeric operations)

---

## Issue 6: VIX fetch failure in stress test (LOW)

**Log evidence:**
```
[STRESS] VIX fetch failed, using fixed brackets: could not convert string to float: '^VIX'
```

**Root cause:** The stress test script passes `"^VIX"` as a ticker to a price fetcher that tries to convert the string to float before fetching.

**Fix:** Check `scripts/stress_test.py` — the VIX symbol handling needs to strip the `^` prefix or use the correct yfinance symbol (`^VIX` is correct for yfinance but may be parsed wrong).

---

## Issue 7: Full log audit — CC reads the entire log

**After fixing Issues 1-6, scan the full 15K-line log for any additional issues CC identifies. Look for:**

- Any ERROR or WARNING patterns not covered above
- Silent failures (functions that return without doing anything)
- Timing anomalies (gaps in the scan schedule — did the computer sleep?)
- Trade actions: how many trades opened/closed during this period?
- Scan metrics: how many scans ran, how many found packet-worthy setups?
- Data collection: which collectors are succeeding vs failing?
- Council sessions: are they running? What's the traffic light state?

**File GitHub issues for anything new with the label `log-audit`.**

---

## Verification

```bash
python -m pytest tests/ -x -q  # Pass count ≥ baseline
cd frontend && npm run build   # Succeeds

# Issue 1: Bracket check should show N/N (not 0/N) on next run
# Issue 2: No "no such column" errors in enrichment
# Issue 3: python -c "from scripts.overnight_train import *" succeeds
```

---

## Commit

```bash
git add -A
git commit -m "fix: 6 production issues from log audit

CRITICAL:
- Bracket monitor now correctly identifies protected positions (#248 follow-up)
- Earnings signals column names fixed — eps_actual, revenue_actual, eps_estimate

HIGH:
- Overnight training script import fixed (src.scheduler.overnight)
- Live trade check type error — float() cast on SQLite TEXT

MEDIUM:
- Postgres sync: ON CONFLICT DO UPDATE for options_metrics/macro_snapshots
- Postgres sync: NULL id guard for research_docs/traffic_light_state
- Stress test VIX symbol handling

Log audit: N additional issues filed with log-audit label."

git tag -a v0.14.1 -m "v0.14.1 — log audit hotfix: bracket protection, earnings signals, overnight training"
git push origin main && git push origin v0.14.1
```

Update MASTER.md and RELEASES.md.
