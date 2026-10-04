# S03 Power Measurement Report — Pre-Tag Power Calibration

**Sprint:** S03 (pre-tag power)
**Date:** 2026-10-04
**Status:** Complete
**Branch:** `feat/s03-pre-tag-power`

## Verdict

The preregistered Q1 (§2.1) and Q2/Q3 (§3.2) tests can detect the minimum effects they are intended to detect. The 24-month §2.1 MDE at the 5% forward planning qualification rate (set by the CEO on 2026-10-04) is **18.3 bp**, below the 25 bp minimum effect (power at 25 bp is 0.98). The §3.2 MDE is **2.9 bp at 12 months** and **2.0 bp at 24 months**, within the realistic 3–8 bp range. **prereg-v1 is clear to proceed.**

## What was measured

S03 calibrates the statistical power of the two primary preregistered tests before the `prereg-v1` tag, using only unconditional second moments and synthetic effects. No real signal was used at any point.

### T1 — Access check

Alpaca paper API: bars and news endpoints returned HTTP 200 with active account status. Bar fields: `c,h,l,n,o,t,v,vw`. News requested with `include_content=false`; response still included a `content` key, so the T2 collector strips content fields defensively and never persists raw responses. Data feed: `sip`.

### T2 — Data panels

**Bars:** 504/504 symbols (503 S&P 500 constituents + SPY), 1,310,296 rows, 2016-01-04 to 2026-10-02. Not all symbols have data from 2016: late starters include tickers that listed after 2016 (e.g., GEV, SOLV, KVUE, VLTO, CEG, ABNB). The manifest records per-symbol first/last dates; see `/home/hatch/arcis-data/raw/bars/manifest.json`. Nothing under the data root is tracked by git.

**News metadata:** 504/504 symbols, 45,397 stock-days with news, 2025-10-04 to 2026-10-04. Metadata only: per stock-day article count and earliest `created_at` (America/New_York). No text, headlines, summaries, URLs, or raw responses retained. Manifest at `/home/hatch/arcis-data/raw/news_metadata/manifest.json`.

### T3 — Second moments

Computed by `tools/measure_second_moments.py`. Beta-adjusted forward-return dispersion (252-session rolling betas vs SPY):

| Horizon | Raw disp. | Mkt-adj. disp. | Beta-adj. disp. | Resid. corr. |
|---|---|---|---|---|
| 1 session | 1.73% | 1.73% | 1.69% | +0.0485 |
| 2 sessions | 2.46% | 2.46% | 2.40% | +0.0490 |
| 5 sessions | 3.89% | 3.89% | 3.80% | +0.0499 |
| 10 sessions | 5.47% | 5.47% | 5.35% | +0.0488 |
| 15 sessions | 6.71% | 6.71% | 6.56% | +0.0481 |

Median per-stock lag-1 autocorrelation (1-day returns): −0.0370.

**Residual correlation methodology:** average pairwise time-series correlation over 2,000 random stock pairs (minimum 30 overlapping sessions). The prior z-score method was mechanically −1/(n−1) and has been replaced.

**News-bearing share methodology (reproducible):** article `created_at` converted to America/New_York, bucketed by NY calendar date, intersected with trading days from the bars panel. Window from manifest (2025-10-04 to 2026-10-04), not data min. Measured share: **32.15%** (40,396 news-bearing stock-days / 125,644 total stock-days in window).

**Note:** the raw and market-adjusted dispersion columns are identical by construction: subtracting a per-date constant (the SPY return) does not change the cross-sectional standard deviation.

### T4 — Power simulations

Computed by `tools/run_power_sims.py` (core in `tools/s03_power_lib.py`). Date-block bootstrap (20-session blocks), 2,000 replications per cell, seeds fixed and recorded. All effects synthetic and randomly assigned. Power SEs are binomial: sqrt(p(1−p)/2000) ≈ 0.9pp at 80% power.

**Family A (§2.1):** label = b_Q·Qualified + ε, date FE, date-clustered SE, one-sided α=2.5%. Label proxy: **15-session beta-adjusted forward return** (per S03 spec T4). Qualification rates: 0.5%, 1%, 2%, 5%, 10%.

| Window | q=0.5% | q=1% | q=2% | q=5% (planning) | q=10% |
|---|---|---|---|---|---|
| 12 mo | 78.1 bp | 58.4 bp | 42.3 bp | 25.2 bp | 18.8 bp |
| 24 mo | 58.7 bp | 41.2 bp | 27.9 bp | **18.3 bp** | 15.3 bp |

Power at 25 bp (24 mo, q=5%): 0.98.

**Family B (§3.2):** r = α_i + δ_t + b·(N·F) + ε, Holm at family α=2.5% (per-test 1.25%). Outcome: 1-day beta-adjusted forward return. News share: 7.74% (measured).

| Window | MDE (80% power) |
|---|---|
| 12 mo | 2.9 bp |
| 24 mo | **2.0 bp** |

**Planning qualification rate:** 5% of S&P 500 stock-days (≈25 names/day), set by the CEO on 2026-10-04 as a preregistered forward design parameter. This replaces the S02 15–20% figure, which was a rough estimate on the S&P 100 universe that could not be verified from available legacy data (only closed trades, not daily qualification records). The legacy trade series implies a lower bound of ~4% on S&P 100 (median 4 trades/day); the 5% S&P 500 rate is a forward-looking design choice.

**Opposing biases:** unbracketed 15-session returns overstate dispersion versus bracketed labels (MDE biased up); current-constituent survivorship understates dispersion (MDE biased down). Neither is called conservative.

**Limitations:** synthetic qualification is iid per stock-day; real qualifiers persist across consecutive days and cluster in time, so the MDE may be understated. The two-way demeaning in Family B uses the approximation x − x̄_d − x̄_s + x̄ rather than alternating projections; on the ~13% unbalanced bootstrap panel this leaves small residual date means. The effect on the MDEs is expected to be small but is not verified.

## Deviations from spec (carried over)

- T1 access facts: per-call status codes, earliest bar date, and rate-limit headers are not recorded in the report (available in logs).
- T2: no full gap analysis; late-starter list is in the manifest, not the report.
- T3: by-year dispersion tables and by-year correlation are computed but not tabulated in the report (in `second_moments.json`).

## Clean-room compliance

- No S03 script opens `config/incumbent_v1.yaml` (verified by `tests/test_s03_cleanroom.py`: AST check for file I/O on the incumbent path, plus runtime guard using `raise` not `assert`).
- Planning rate is a preregistered forward parameter, not derived from historical strategy application.
- Raw panels stay under `/home/hatch/arcis-data` (outside the repo); only aggregates in git.

## Deviations from spec

1. **Four scripts instead of one** `tools/measure_power.py`: split into `pull_bars_panel.py`, `pull_news_metadata.py`, `measure_second_moments.py`, `run_power_sims.py` (+ `s03_power_lib.py`) for size-limit compliance and separation of concerns.
2. **Planning rate 5% (forward parameter)** instead of S02's 15–20%: the legacy figure could not be verified; 5% is preregistered for the S&P 500 universe.
3. All scripts pass the 400-line / 60-line function size checks (`tools/checks.py` now checks `tools/` as well as `src/`).

## Dependencies

Research group: `numpy`, `pandas`, `pyarrow` (parquet I/O), `requests` (Alpaca API), `scipy` (normal quantiles for power thresholds). All justified: numpy/pandas for panel math, pyarrow for parquet, requests for the Alpaca REST calls, scipy for `stats.norm.ppf`.
