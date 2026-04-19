# Pass 1 — v0.25.3 lazy_prices_v1 real-data walk-forward evaluation (#532)

**Branch:** `validation/lazy-prices-v1-real-walkforward`
**Date:** 2026-04-19
**Sprint kind:** Execution sprint. Framework validation, not strategy validation.

## Scope

Per the v0.25.3 sprint prompt:

> Run walk-forward v1 against `lazy_prices_v1.yaml` with real EDGAR data to prove the framework works end-to-end on real data. **Framework validation, not strategy validation.** Expected outcome is NOT PASS (forensic audit established lazy-prices underpowered on 2019-2024).

Pass 1 verifies the 4 prerequisites, forms the outcome hypothesis, and pre-registers the framework-bug trigger rules.

## Prerequisite verification

### Prereq 1 — spec exists with `derived_from: null`

```
$ ls -la src/platform/specs/lazy_prices_v1.yaml
-rw-r--r-- 1 mille 197609 1898 Apr 19 13:53 src/platform/specs/lazy_prices_v1.yaml

$ grep "^derived_from:" src/platform/specs/lazy_prices_v1.yaml
derived_from: null
```

**PASS.**

### Prereq 2 — `sp100_historical_constituents` loaded from CSV

Initial check failed — table did not exist locally despite schema registry entry (`src/schema/registry.py:2207-2233`). Resolution:

```
$ python -m src.main validate-schema --fix
[SCHEMA] Created/verified 67 tables in C:/arcis/data/ai_research_desk.sqlite3
Schema OK — no issues found.

$ python -c "from src.platform.rigor.walkforward_universe import populate_constituents_table; \
             from src.config import DB_PATH; \
             print(populate_constituents_table(DB_PATH))"
Loaded 112 rows into sp100_historical_constituents
```

Post-resolution counts:

```
rows: 112
added_date range: ('2000-01-01', '2023-09-18')
```

**PASS** after idempotent schema-fix + CSV load. Note: the runner auto-populates this table (`scripts/backtest/run_walkforward.py:141-145`), so a fresh DB would self-heal on first run. I did it eagerly here for verification cleanliness.

### Prereq 3 — `edgar_filings` populated with `full_text` + `sections_json`

Live DB counts against `C:/arcis/data/ai_research_desk.sqlite3`:

| Column | Count |
|---|---|
| total rows | 5,393 |
| with `full_text IS NOT NULL AND length > 0` | 3,199 |
| with `sections_json IS NOT NULL AND length > 0` | 1,518 |
| filing_date range (with full_text) | 2019-01-08 → 2026-04-17 |

**PASS.** 3,199 filings with full text span the walk-forward OOS window (2019-01-01 → 2024-09-30). `sections_json` coverage (1,518) is lower than full-text coverage — confirms the v0.25.1 backfill did prioritize section extraction for key filings but did not run the full section-parser pass across every full-text row. The walk-forward engine queries `sections_json` per-ticker for Item 1A (Risk Factors) and Item 7 (MD&A); tickers/filings without parsed sections will simply not generate signals on those dates.

### Prereq 4 — daily OHLCV coverage 2019-01-01 → 2024-09-30 for S&P 100

**Prereq language drift — no `daily_bars` SQLite table exists.** Actual mechanism: `src/platform/data_loader.py:26-28` delegates to `src/simulation/cache.py:fetch_cached_ohlcv`, which reads parquet files from `data/simulation_cache/` (12,869 files present as of this check) and falls back to `yf.download` on cache miss, persisting the result.

This is expected per the v0.24.0 platform spec (parquet cache was the delivery mechanism; no dedicated daily_bars table was added). Prereq 4 in the sprint prompt should be read as "OHLCV available for 2019-2024" rather than "specific table populated."

**PASS** — cache has 12,869 parquet files; any cache miss triggers yfinance download transparently. The first walk-forward run may be slow if many cache entries are missing for the OOS window; subsequent runs are fast.

Note: for R7 reproducibility, the random seed is passed to the walk-forward config; data-fetch nondeterminism (yfinance download ordering, cache-write race) does not affect per-trade deterministic scoring because fills are computed from the cached/downloaded series, not live.

## Runner invocation — prompt command vs actual CLI

Prompt says:
```
python scripts/backtest/run_walkforward.py \
  --spec src/platform/specs/lazy_prices_v1.yaml \
  --output-tag lazy-prices-v1-real
```

Actual CLI (per `scripts/backtest/run_walkforward.py:29-55`):
- Takes `--strategy lazy_prices_v1` (not `--spec` or path), resolves against `src/platform/specs/` by default
- Has no `--output-tag` flag; run_id is auto-generated per-run and persisted to `walkforward_results`
- Exit codes: 0 = PASS, 1 = FAIL, 3 = INCONCLUSIVE, 2 = config error

**Adapted invocation for Pass 2:**
```
python scripts/backtest/run_walkforward.py \
  --strategy lazy_prices_v1 \
  --json
```

The `--json` flag prints structured summary to stdout — captures run_id + outcome_state + reason + pooled metrics + per-window counts for the raw-output doc.

## Outcome hypothesis

Per the synthetic reference doc (`docs/validation/lazy-prices-v1-walkforward-2026-04-19.md:11`):

> Real-data expected outcome: **must NOT report PASS**. The forensic audit established that cosine-similarity signal alone is underpowered at the trade counts obtained on 2019-2024 data. A real-data PASS indicates a framework bug.

**Predicted outcome state:** INCONCLUSIVE (most likely INCONCLUSIVE_DATA or INCONCLUSIVE_POWER, not INCONCLUSIVE_COVERAGE) OR FAIL.

**Rationale:**
1. `sections_json` coverage is 1,518 rows across 2019-2026 — spread across 5 windows gives ~250-400 rows per window (roughly), so window-level trade counts will likely be in the low double digits, not 40+.
2. Forensic audit: cosine-similarity on 10-K/10-Q sections vs prior-year is a weak signal at the 14-28 day horizon after filing; effect size below the MDE gate at N ~ 20-40.
3. Heavy-tail flag likely elevated: small trade counts + occasional large moves (earnings overreaction, one-off M&A) drive bootstrap SE to override parametric SE.

**If outcome is PASS:** framework-bug investigation triggered (see below).
**If outcome is FAIL:** expected — lazy-prices' underpowered nature on this window will manifest as criterion-failure (drawdown, loss rate, or pooled Sharpe below gate).
**If outcome is INCONCLUSIVE_*:** expected — captures the "not enough data / signal too weak to make a call" state the framework was designed to surface.

## Framework-bug trigger rules (pre-registered)

If the real-data run outputs `outcome_state = PASS`, at least one of the following framework defects is in play:

1. **State-machine miscount:** `n_windows_pass` off-by-one or incorrect aggregation across windows.
2. **MDE gate miscalibrated:** pooled MDE computation too permissive — false PASS on noisy small-N window data.
3. **Bootstrap SE override not firing:** heavy-tail detection threshold set too loose, parametric SE overstates significance.
4. **Data leakage through purge/embargo:** the R2 purge window (7 days) or embargo (5 days) is not eliminating overlap between IS and OOS.
5. **VIX tier coverage miscount:** framework reports ≥ 3 VIX tiers covered when only 1-2 were actually observed, unlocking the PASS gate inappropriately.
6. **Filter-leak / overlap assertion bypass:** R8 (derived_from + overlap assertion) permits what it shouldn't for `derived_from: null` specs.

**Action on PASS outcome:**
- Do NOT merge the PR
- Write the validation doc with evidence
- File a blocking investigation issue
- Link in PR body, hold for operator review

**Action on non-PASS outcome:**
- Write validation doc with per-window breakdown
- Capture R7 reproducibility fields (spec_hash, code_git_sha, random_seed, config_json)
- Compare state distribution to synthetic runs (5 INCONCLUSIVE_DATA windows in synthetic INCONCLUSIVE run; 1 INCONCLUSIVE_POWER + 4 PASS in synthetic FAIL run; 5 PASS in synthetic PASS run)
- Ship PR for operator approval

## Non-goals

Per prompt's anti-goals section:
- No spec modifications.
- No rerunning with different seeds to get a different outcome.
- No collapsing INCONCLUSIVE sub-states.
- Do NOT interpret the outcome as a strategy verdict for lazy_prices. This is a framework test vehicle.

## Pass 2 plan

1. Execute the adapted invocation above (with `--json`).
2. Capture stdout + stderr full text.
3. Query `walkforward_results` for the persisted run-level row to extract R7 fields + per-window metrics.
4. Write `docs/sprints/lazy_prices_v1_real_raw.md` with:
   - Command + exit code
   - JSON summary
   - Per-window table (from `walkforward_trades` / `walkforward_results` joins)
   - R7 fields (spec_hash, code_git_sha, random_seed, config_json)
   - Heavy-tail window count, VIX tier coverage, bootstrap SE override count
5. Fold all findings into the validation doc in Pass 3.
