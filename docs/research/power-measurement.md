# S03 Power Measurement Report — Pre-Tag Power Calibration

**Sprint:** S03 (pre-tag power)
**Date:** 2026-10-04
**Status:** Complete
**Branch:** `feat/s03-pre-tag-power`

## Verdict

The preregistered Q1 (§2.1) and Q2/Q3 (§3.2) tests can detect the minimum effects they are intended to detect. The 24-month §2.1 MDE at the S02 planning qualification rate (17.5%) is **8.9 bp**, well below the 25 bp minimum effect. The 24-month §3.2 MDE is **4.3 bp**, within the realistic 3–8 bp range. **prereg-v1 is clear to proceed.**

## What was measured

S03 calibrates the statistical power of the two primary preregistered tests before the `prereg-v1` tag, using only unconditional second moments and synthetic effects. No real signal was used at any point.

### T1 — Access check

Alpaca paper API: bars and news endpoints returned HTTP 200 with active account status. Bar fields: `c,h,l,n,o,t,v,vw`. News requested with `include_content=false`; response still included a `content` key, so the T2 collector strips content fields defensively and never persists raw responses.

### T2 — Data panels

**Bars:** 504/504 symbols (503 S&P 500 constituents + SPY), 1,310,296 rows, 2016-01-04 to 2026-10-02. All symbols have data from 2016. Manifest with SHA-256 at `/home/hatch/arcis-data/raw/bars/manifest.json`. Nothing under the data root is tracked by git.

**News metadata:** 504/504 symbols, 45,397 stock-days with news, 2025-10-04 to 2026-10-04. Metadata only: per stock-day article count and earliest `created_at`. No text, headlines, summaries, URLs, or raw responses retained. Manifest at `/home/hatch/arcis-data/raw/news_metadata/manifest.json`.

### T3 — Second moments

Computed by `tools/measure_second_moments.py`. Beta-adjusted forward-return dispersion (252-session rolling betas vs SPY):

| Horizon | Beta-adj. dispersion | Within-date resid. corr. |
|---|---|---|
| 1 session | 1.69% | −0.0065 |
| 2 sessions | 2.40% | −0.0015 |
| 5 sessions | 3.80% | +0.0002 |
| 10 sessions | 5.35% | −0.0030 |
| 15 sessions | 6.56% | −0.0022 |

- Per-stock lag-1 autocorrelation (1-day): median −0.037 (IQR: −0.089 to +0.018).
- News-bearing share: **8.0%** of stock-days (45,397 of 567,000 in the 12-month window).
- Within-date residual correlations are near zero, consistent with beta adjustment removing most common variation.

### T4 — Power simulations

Computed by `tools/run_power_sims.py`. Date-block bootstrap (20-session blocks, 2,000 replications per cell, fixed seeds 304–315 and 416). All effects synthetic and randomly assigned.

**Family A (§2.1, Q1):** outcome is 10-session beta-adjusted forward return (closest to R01's 8.5-session average hold). Model: date-FE regression of return on synthetic qualification indicator. One-sided α=2.5%.

| Window | q=0.5% | q=1% | q=2% | q=5% | q=10% | q=17.5% (planning) |
|---|---|---|---|---|---|---|
| 12 mo MDE | 68.1 bp | 46.2 bp | 33.8 bp | 21.1 bp | 16.9 bp | 14.0 bp |
| 24 mo MDE | 46.6 bp | 34.4 bp | 23.0 bp | 16.5 bp | 11.9 bp | **8.9 bp** |
| 24 mo power at 25 bp | 0.34 | 0.58 | 0.87 | 0.99 | 1.00 | **1.00** |

The planning qualification rate (17.5%) is the midpoint of S02's 15–20% range (`docs/research/old-platform-inventory.md`), derived from legacy candidate counts, not from applying the strategy historically.

**Family B (§3.2, Q2/Q3):** outcome is one-day beta-adjusted forward return. Synthetic 8% news-bearing share (the measured share) with synthetic N(0,1) scores. Two-way (stock + date) FE, two-way clustered SE. Holm family α=2.5% (per-test 1.25%).

| Window | MDE (80% power) |
|---|---|
| 24 mo | **4.3 bp** |

This sits within R03's realistic one-day effect range of 3–8 bp: the test can detect effects at the low end of the realistic range.

### Opposing biases (stated, not netted)

1. **Unbracketed returns overstate dispersion.** The simulations use unbracketed forward returns; the §2.1 label is bracketed (stop/target). Bracketed labels have lower dispersion, so the true MDE is lower than measured. This bias pushes the MDE **up**.
2. **Current-constituent survivorship understates dispersion.** The panel uses current S&P 500 members; delisted names (typically more volatile) are missing. This bias pushes the MDE **down**.

Neither bias is called conservative. They oppose each other; the net direction is unknown.

## Figures recorded in PREREGISTRATION.md

- §2.1 "Power" bullet: full MDE table, the 8.9 bp planning-rate figure, power at 25 bp, and both biases.
- §3.2 "Planning power" bullet: 4.3 bp MDE at 24 months, Holm 1.25% per-test threshold, 8% synthetic news share.

## Clean-room compliance

- `tools/measure_second_moments.py` and `tools/run_power_sims.py` never open `config/incumbent_v1.yaml` (assert-guarded via `ARCIS_ALLOW_INCUMBENT`).
- No statistic conditions on incumbent qualification, ranker score, text score, or any real signal.
- Planning qualification rate from S02 legacy counts, not from historical strategy application.
- Only aggregate statistics enter git; bars, news metadata, and per-stock series stay under `/home/hatch/arcis-data`.

## Dependencies

Research group additions (justified per S03 acceptance): `pandas` + `pyarrow` (panel I/O), `scipy` (normal quantiles for test thresholds), `numpy` (already present). `requests` was already a project dependency.
