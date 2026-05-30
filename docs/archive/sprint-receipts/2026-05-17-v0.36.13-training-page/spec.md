# v0.36.13 Hotfix Bundle — Training Page + Audit Hardening

**Date:** 2026-05-17
**Release type:** PATCH (0.36.x line)
**Branch:** `hotfix/v0.36.13-training-page-fixes` (integration branch)
**Base:** `origin/main` at `e1ad3e58` (v0.36.12 tagged)
**Sprint ID:** `2026-05-17-v0.36.13-training-page`

## Context

After today's restart of the watch loop onto v0.36.11+ code (PID 1149180, restarted ~15:21 ET 2026-05-17), the operator's training-page review surfaced three classes of issue that all share a common root cause: **legacy data archaeology + writer/reader contract drift**. The deterministic audit added in v0.36.11 is correctly firing alerts on the symptoms but the underlying anomalies are data-quality issues, not model degradation.

This sprint bundles six independent tracks into one PATCH release. All scope is operator-authorized (2026-05-17 conversation, AskUserQuestion confirmations).

## Six tracks

### Track (a): Training outcome bucketing fix

**Three stacked bugs:**

1. `src/training/data_collector.py:311-326` queries `SELECT st.*, r.* FROM shadow_trades st LEFT JOIN recommendations r ...`. **11 columns collide** between the two tables: `ticker, target_1, target_2, setup_type, setup_confidence, max_favorable_excursion, max_adverse_excursion, created_at, updated_at, llm_timeout_days, recommendation_id`. For **48 of 88 closed trades** with `recommendation_id=NULL` (post-MO/BK manual cleanups), the LEFT JOIN misses and `r.ticker=NULL` overrides `st.ticker`. Every such trade is logged as `[TRAINING] Skipping None trade_id=... — no feature data available for training` and dropped. Half the corpus silently lost.

2. `_classify_outcome()` maps `pnl_dollars > 0 → WIN` else `LOSS`. Does not handle `reconciled_stale` (49 trades), `unknown` (11), `manual` (3), `qty_mismatch_partial_fill` — all pnl=$0 → mis-classified as LOSS. The training pipeline then writes "why this was a bad trade" theses for trades we never measured.

3. Dashboard `src/api/cloud_routes/training.py:138-144` uses `COALESCE(trade_outcome, outcome_type, outcome)` but `trade_outcome` column stores the verbose `_build_outcome_text()` blob:
   ```
   === ACTUAL OUTCOME ===
   Exit Reason: stop_loss
   P&L: $-186.69 (-4.6%)
   ...
   ```
   And `outcome_type`/`outcome` are NULL for all 75 rows. So the GROUP BY key is a unique multi-line blob per trade → 40 distinct buckets, none matching `WIN/LOSS/TIMEOUT/PASS` → chart renders empty/"all unknown."

**Fixes:**

- Rewrite `data_collector.py:311-326` to use **explicit column list**:
  ```sql
  SELECT
      st.*,
      r.enriched_prompt,
      r.price_at_recommendation,
      r.trend_state,
      r.pullback_depth_pct,
      r.created_at AS scan_created_at
  FROM shadow_trades st
  LEFT JOIN recommendations r ON st.recommendation_id = r.recommendation_id
  WHERE ...
  ```
  Update downstream `trade.get("created_at")` to prefer `scan_created_at` for rec_date semantic, falling back to st.created_at.

- Add `_UNMEASURED_EXIT_REASONS = frozenset({"reconciled_stale", "unknown", "manual", "qty_mismatch_partial_fill"})`. Update `_classify_outcome` to return `"UNMEASURED"` for these. In the main loop after classify, skip UNMEASURED trades with a clear info log (don't write training examples for unmeasurable outcomes).

- Add `outcome_type` column to BOTH INSERTs:
  - Primary INSERT (`data_collector.py:486`): writes `outcome_type=WIN/LOSS/TIMEOUT`
  - Contrastive INSERT (`data_collector.py:265`): writes `outcome_type=NULL` (synthetic, no real outcome)

- Reorder dashboard COALESCE to `COALESCE(outcome_type, outcome, trade_outcome)` so clean labels win.

- One-shot backfill SQL (via psql against PG halcyon@localhost:5433):
  ```sql
  UPDATE training_examples SET outcome_type = 'WIN'     WHERE outcome_type IS NULL AND source = 'blinded_win';
  UPDATE training_examples SET outcome_type = 'LOSS'    WHERE outcome_type IS NULL AND source = 'blinded_loss';
  UPDATE training_examples SET outcome_type = 'TIMEOUT' WHERE outcome_type IS NULL AND source = 'blinded_timeout';
  -- Leave contrastive_* rows with outcome_type=NULL.
  ```

**Regression-lock tests (minimum 5):**
- Column collision absence (verify explicit SELECT in source)
- UNMEASURED skip behavior
- Primary INSERT includes outcome_type column + value
- Contrastive INSERT writes outcome_type=NULL
- Dashboard COALESCE order pin (assertion against the SQL string in cloud_routes/training.py)

### Track (b): FED scraper fix

**Root cause:** `_parse_href_date` regex `r"(\d{8})"` requires 8 consecutive digits. Fed website link format changed — no `20260128`-style tokens in current page HTML. Selectors (`div#article`, `div.col-xs-12`) still match. Page returns 200. Just the date extraction is broken.

**Live probe results (2026-05-17 PM):**
- `https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm` → 200 OK, 162887 bytes
- `div#article`: present
- `div.col-xs-12`: present
- `<main>`: NOT present
- `fomcMinutes`: present
- 8-digit date tokens: **0**

**Fix:**

- Probe `https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm` with a realistic UA. Find actual href patterns. Likely formats: `/2026/0128.htm`, `/monetarypolicy/fomcminutes20260128.htm` (the old `20260128` substring may exist in URL path components other than where the regex was looking).
- Update `_parse_href_date` to handle observed format(s). Must still return None for non-date hrefs.
- IF HTML structure changed beyond date format, fall back to RSS at `https://www.federalreserve.gov/feeds/press_all.xml` (much more durable).
- Existing tests in `tests/test_data_collectors.py` may need fixture updates.

### Track (c): FINRA short-volume collector (replaces Finnhub short_interest)

**Background:** Finnhub `/stock/short-interest` returns 403 across all 102 tickers — plan no longer entitles. v0.36.12 added an early-exit so the overnight cycle doesn't threshold-fail. `short_interest` table has 0 rows.

**Substitute source — FINRA bulk regsho:** `https://cdn.finra.org/equity/regsho/daily/CNMSshvol{YYYYMMDD}.txt`. Pipe-delimited, no auth, ~500KB. Probe confirmed working (2026-05-17 PM): status 200, format `Date|Symbol|ShortVolume|ShortExemptVolume|TotalVolume|Market`.

**Important caveat:** FINRA daily short-VOLUME ≠ Finnhub settlement-date short-INTEREST. Daily volume tracks executed short sales per day; settlement interest tracks total short positions reported by member firms bi-monthly. Same fundamental signal direction; different metric. Document the substitution in CHANGELOG.

**Fix:**

- New module `src/data_collection/short_volume_finra.py` with `collect_finra_short_volume(target_date)`. Filters to SP100. Stores daily.
- New table `short_volume_daily` in `src/schema/registry.py`:
  - Columns: `ticker (TEXT NOT NULL)`, `trade_date (TEXT NOT NULL)`, `short_volume (REAL)`, `short_exempt_volume (REAL)`, `total_volume (REAL)`, `short_ratio (REAL)` (computed `short_volume / total_volume`), `source (TEXT)` default 'finra', `collected_at (TEXT NOT NULL)`.
  - Composite PK: `(ticker, trade_date)`.
  - Index: `(ticker, trade_date DESC)`.
  - `sync_to_postgres=True`, `sync_mode="incremental"`, `sync_time_column="trade_date"`, `sync_conflict_col="ticker, trade_date"`.
- Wire into overnight schedule in `src/scheduler/overnight.py` — alongside (or replacing) `short_interest_collector`. Run daily Mon-Fri (FINRA publishes T+1).
- `short_interest` table: leave in place, mark deprecated in schema description.
- Dashboard's "short_interest" panel rendering updated to read from `short_volume_daily` instead (operator may also rename label).
- Tests: regression-lock URL format, pipe-delimited parser, SP100 filtering. **Mock the HTTP layer — do not hit FINRA in pytest** (per CLAUDE.md mock-all-external-APIs rule).

### Track (d): Audit hardening — make false-positive alerts go away

Four audit alerts firing daily, all on polluted data:

1. **"75% good process → bad outcome (41 of 57)"** — `cto_report.py:583-601` `is_win = "win" in source` buckets `contrastive_win` (synthetic, 10 rows) as wins. Required fix: filter `WHERE source IN ('blinded_win', 'blinded_loss', 'blinded_timeout', 'blinded_pass')` — exclude `contrastive_*` entirely from quadrant analysis. Also require `quality_score_auto IS NOT NULL` (currently `score is not None and ... >= 3.0` — the None branch falls into bad_process_*_outcome which is misleading).

2. **"All trades classified as 'unknown' regime"** — audit coalesces NULL `regime_at_entry` → 'unknown'. Skip NULL rows from the percentage calc, don't fold them into 'unknown'. PG state: 45 GREEN / 0 'unknown' / 398 NULL.

3. **"Avg hold period 336 days"** — `cto_report.py:440, 756; model_monitor.py:85`. Exclude trades where `duration_days = 999` (sentinel from old backfill) OR `exit_reason IN ('unknown', 'reconciled_stale', 'manual', 'qty_mismatch_partial_fill')`. Real-data check: filter should drop PG avg from 137.7 → ~1.5 days (matches pullback intent).

4. **"0% confidence calibration + no rubric ≥70"** — `_compute_confidence_calibration` filters: exclude trades with `recommendation_id IS NULL` (48 of 88) and exclude unmeasurable exit reasons.

Each fix needs a regression-lock test with fixture data containing both polluted and clean rows.

### Track (e): Data archaeology backfill (one-shot)

Path: `scripts/backfill_v0.36.13_archaeology.py`. **Interactive** — uses `input()` to confirm before commit.

Actions:
1. 11 trades with `exit_reason='unknown'` and `duration_days=999` (all share synthetic `actual_entry_time='2026-05-05T12:09:43.107835'`): set `duration_days=NULL` and `actual_entry_time=NULL`. Leave `exit_reason='unknown'` — we don't know what happened — but the sentinel 999 is removed from stats.
2. 3 trades with `exit_reason='manual'` and `duration_days=999`: same treatment.
3. 49 `reconciled_stale` trades: no change (real durations 0-7 days).
4. Backfill `regime_at_entry` for NULL trades where possible. NOTE: `regime_snapshots` table does NOT exist in PG (confirmed via probe). Check `src/schema/registry.py` for the real table — likely `market_regime` or `regimes`. If no historical regime exists for the trade's entry timestamp, leave NULL.

Script behavior: prints pre-state counts, runs updates in a single transaction, prints post-state counts, prompts operator with `input()` before commit. Cancellation rolls back.

### Track (f): Regime capture fix on live path

13 of 18 OPEN trades have `regime_at_entry=NULL`. Capture is breaking on live scans. `src/services/scan_service.py:370` does `regime_at_entry=feat.get("regime") or feat.get("market_regime")` — at least one Friday scan succeeded (5 GREEN open trades) and 13 failed.

**Fix:** trace which feature pipeline computes regime, and identify why it's None for 13 of 18 scans. Acceptable scope:
- Find root cause and fix if isolated to a single bug
- If root cause crosses subsystems, file a follow-up issue + add explicit logging at scan_service.py:370 that fires when `feat["regime"]` is None (so the next overnight cycle leaves a forensic trail)

**Hard non-goal:** do NOT add a new `regime_snapshots` table or rebuild the regime engine.

## Versioning + CHANGELOG

- `src/version.py`: bump to `v0.36.13` (current `v0.36.12`)
- `tests/test_version.py`: match
- CHANGELOG `## [v0.36.13] — 2026-05-17` section with six subsections (one per track)
- Sibling-search receipts in each subsection documenting which other sites were swept

## Discipline (operator memory enforcement)

- TDD: regression-lock tests written FIRST, verified RED, then green
- Worktree isolation for parallel agent dispatch
- Sibling-search after each fix (operator memory `feedback_review_sibling_search` 2026-04-26)
- PM-side verification (operator memory `feedback_strict_rigor_no_handwave` 2026-04-26)
- After all tracks land: minimum test sweep:
  ```
  pytest tests/test_collectors_pg_dialect_residuals.py \
         tests/test_db_engine_aware_upsert.py \
         tests/test_version.py \
         tests/test_data_collectors.py \
         tests/data_collection/ \
         tests/test_self_blinding.py \
         tests/test_leakage_detector.py \
         tests/evaluation/
  ```
- Live PG regression sweep: query updated stats (avg_hold_period, quadrant_distribution, regime_coverage) — confirm post-fix avg_hold ~1.5d, quadrants without contrastive contamination, regime % computed against non-NULL denominator
- QA + Security reviewers in parallel before merge
- Auto-merge if both APPROVE with no Critical/Important findings, then tag v0.36.13
- Telegram completion message to chat_id `8653844512`

## Non-goals

- Do NOT add a fresh `regime_snapshots` table or rebuild regime engine (out of scope)
- Do NOT touch live trading or risk governor code paths (sacred)
- Do NOT mass-rewrite `unknown` exit reasons to target/stop based on P&L (hardening doc rule, operator memory)
- Do NOT skip hooks or bypass tests
- Do NOT auto-restart NSSM service (operator does manually)

## Source data evidence (PG queries from 2026-05-17 PM)

### Closed trade exit distribution
```
   exit_reason    | count
------------------+-------
 reconciled_stale |    49
 stop_loss        |    12
 unknown          |    11
 target_1         |     8
 timeout          |     5
 manual           |     3
```

### Duration sentinel pollution
```
 exit_reason     | avg_dur | min | max | count
-----------------+---------+-----+-----+------
 unknown         |     999 | 999 | 999 |    11
 manual          |     336 |   0 | 999 |     3
```

### Training examples — outcome columns
```
 source            | outcome_type | outcome | count
-------------------+--------------+---------+------
 blinded_loss      |              |         |    11
 blinded_timeout   |              |         |    15
 blinded_win       |              |         |    14
 contrastive_loss  |              |         |    25
 contrastive_win   |              |         |    10
(all outcome_type, outcome = NULL)
```

### Regime capture state
```
 regime  | total trades
---------+-------------
 GREEN   |      45
 NULL    |     398
(no 'unknown' — audit coalesces NULL→'unknown')

Open positions (18): 5 GREEN, 13 NULL
```

### LEFT JOIN orphan distribution
```
 null_rec_id | orphaned_rec_id | matched | total_closed
-------------+-----------------+---------+-------------
          48 |               0 |      40 |           88
```
