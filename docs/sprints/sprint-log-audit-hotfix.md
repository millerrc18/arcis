# Sprint: Log Audit Hotfix — Production Issues from arcis.log

> **Priority:** CRITICAL — positions may be unprotected, earnings signals completely dead
> **Estimated time:** 4-6 hours CC time
> **Access:** LOCAL — CC has full access to logs, database, and runtime
> **Tag as v0.14.1 after merge.**

> ⚠️ **Log files are in the local repo.** Read these before starting:
> - `logs/arcis.log` — main production log (15K+ lines, March 30 – April 4)
> - `logs/training_overnight.log` — overnight training failure
> - `logs/training_test_task.log` — empty (training task never ran)
> 
> CC has local access to the SQLite database, the running system, and all log files. Use this access to verify fixes work on the actual data, not just in tests.

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

## Issue 7: Full log audit — CC reads the entire log, files issues, fixes them, closes them

**After fixing Issues 1-6, read the ENTIRE `logs/arcis.log` file. This is 15K+ lines. Do not skim — read it systematically.**

**Step 1: Categorize every unique ERROR and WARNING pattern.**

```bash
# Get unique error patterns
grep "ERROR" logs/arcis.log | sed 's/^.*\] //' | sort -u
# Get unique warning patterns (deduped by ticker)
grep "WARNING" logs/arcis.log | sed 's/for [A-Z]*:/for TICKER:/' | sort -u
```

**Step 2: For each pattern, determine if it's:**
- Already fixed by Issues 1-6 above → skip
- A new bug → file a GitHub issue with label `log-audit`
- A known limitation → note but don't file
- Noise (expected behavior) → skip

**Step 3: Look specifically for:**
- Any ERROR or WARNING patterns not covered by Issues 1-6
- Silent failures (functions that return without doing anything)
- Timing anomalies (gaps in the scan schedule — computer sleep killed scans before)
- Trade actions: how many trades opened/closed during this period? Do the numbers match the dashboard?
- Scan metrics: how many scans ran? How many found packet-worthy setups? Are there gaps?
- Data collection: which of the 15 collectors are succeeding vs failing?
- Council sessions: are they running daily at 8:30 AM? What's the traffic light state?
- Buying power: is the account fully invested? Should we reduce max_positions?
- Duplicate operations: are any tasks running twice?
- Schema drift: are there "no such column" or "no such table" errors beyond the ones in Issues 1-6?

**Step 4: File GitHub issues for every new problem.**

```bash
# Example
gh issue create \
  --title "[log-audit] Council session not running — no 8:30 AM entries in log" \
  --body "Log analysis shows zero council session entries between March 30 - April 4. Expected: daily at 8:30 AM ET. The AI Council traffic light is not being set, which means the regime sizing multiplier defaults to 1.0 (no protection)." \
  --label "bug,log-audit"
```

**Step 5: FIX every issue you just filed.** Do not leave issues open. This sprint resolves everything — file → fix → close in one pass.

```bash
# After fixing each issue
gh issue close <number> --comment "Fixed in v0.14.1 log audit sprint. [description of fix]"
```

**Step 6: Write a log audit summary.** Create `docs/audits/log-audit-2026-04-04.md` with:
- Total errors: N (by category)
- Total warnings: N (by category)
- Issues filed: N (list with numbers)
- Issues fixed: N (all of them)
- Scan schedule gaps: any detected?
- Trade activity summary: opens/closes during the period
- Collector health: which succeeded, which failed, which never ran
- Recommendations for monitoring improvements

---

## Verification

```bash
python -m pytest tests/ -x -q  # Pass count ≥ baseline
cd frontend && npm run build   # Succeeds

# Issue 1: Bracket check should show N/N (not 0/N) on next run
# Issue 2: No "no such column" errors in enrichment
# Issue 3: python -c "from scripts.overnight_train import *" succeeds

# All log-audit issues closed
gh issue list --state open --label "log-audit" --limit 20
# Expected: 0 open

# Audit report exists
cat docs/audits/log-audit-2026-04-04.md | head -5
```

---

## Commit

3 commits for clean history:

```bash
# Commit 1: Known issues (1-6)
git add -A
git commit -m "fix: 6 production issues from log analysis

CRITICAL:
- Bracket monitor correctly identifies protected positions (#248 follow-up)
- Earnings signals column names fixed — eps_actual, revenue_actual, eps_estimate

HIGH:
- Overnight training script import fixed (src.scheduler.overnight)
- Live trade check type error — float() cast on SQLite TEXT

MEDIUM:
- Postgres sync: ON CONFLICT DO UPDATE for options_metrics/macro_snapshots
- Postgres sync: NULL id guard for research_docs/traffic_light_state
- Stress test VIX symbol handling"

# Commit 2: Log audit discoveries — all filed AND fixed
git add -A
git commit -m "fix: N log-audit issues discovered and resolved from full 15K-line audit

Issues filed, fixed, and closed:
- #NNN: [description]
- #NNN: [description]
...

Full audit report: docs/audits/log-audit-2026-04-04.md
Closes #NNN, #NNN, ..."

# Commit 3: Audit report + doc updates
git add -A
git commit -m "docs: log audit report + MASTER.md + RELEASES.md for v0.14.1"
```

Tag and push:
```bash
git tag -a v0.14.1 -m "v0.14.1 — log audit: bracket protection, earnings signals, overnight training, N audit fixes"
git push origin main && git push origin v0.14.1
```

Update MASTER.md Section 2 (issues count, test count) and add v0.14.1 to RELEASES.md.
