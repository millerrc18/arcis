# Regime Diagnostic v1 — 2026-04-18

**N = 27** closed trades | **Decision: CONTAMINATED**

## Executive Summary

**Recommendation: CONTAMINATED.** Cell(s) Defensive, 09:30-10:30 survive FDR correction (q=0.10), indicating non-uniform excess return.

The incumbent pullback-in-uptrend strategy produced a mean excess return of 0.721% vs SPY across 27 closed trades (95% CI: [-0.890, 2.294], p = 0.3826).

**Quarantine note:** Analysis excludes quarantined trades per --exclude-quarantined flag.

## Methodology

- **Data source:** `shadow_trades` table (closed trades with exit and P&L)
- **Excess return:** `pnl_pct - (spy_return_over_hold * 100)` (computed by D1 backfill)
- **VIX:** ^VIX close on `entry_date - 1` trading day (yfinance, no look-ahead)
- **Bootstrap:** 10,000 resamples, percentile method, 95% CI
- **FDR:** Benjamini-Hochberg at q = 0.10
- **Power:** Minimum detectable effect at 80% power, 5% significance
- **Minimum cell size:** n >= 5 (cells below this are marked 'insufficient data')

**Bootcamp-mode caveat:** These trades were generated under bootcamp-mode relaxed thresholds (e.g., no conviction floors, no sector caps). Findings about regime contamination or null hypothesis apply to the bootcamp-mode strategy, not necessarily to the strict-mode version that would trade real capital. The diagnostic tests whether the bootcamp-mode strategy has any alpha signal worth filtering for.

## Aggregate Statistics

| Metric | Value |
|---|---|
| N (closed trades) | 27 |
| Mean excess return | 0.721% |
| 95% CI | [-0.890, 2.294] |
| p-value (H0: mean = 0) | 0.3826 |

## A1: VIX Regression

OLS: `excess_return = 0.742 * vix + -16.404`

| Metric | Value |
|---|---|
| r | 0.606 |
| r-squared | 0.3674 |
| Slope | 0.742 |
| Slope 95% CI | [0.379, 1.132] |
| p-value | 0.0008 |
| VIX range | 19.2 - 27.4 |
| MDE (slope) | 0.710 %/VIX-point |
| Benchmark | 0.3 %/VIX-point |
| Underpowered? | Yes |


**Note:** MDE (0.710 %/VIX-point) exceeds benchmark (0.3 %/VIX-point). This analysis is underpowered — its null result should be interpreted as 'insufficient evidence', not 'no relationship'.


![VIX Regression](a1_vix_regression.png)

## A2: Trade-Day Clustering

### Per-Day Results

| Cell | n | Mean Excess (%) | 95% CI | p-value | FDR-adj p | Survives FDR | MDE | Underpowered |
|---|---|---|---|---|---|---|---|---|
| 2026-03-24 | 13 | 3.678 | [1.900, 5.188] | 0.0000 | 0.0000 | Yes | 2.607 | Yes |
| 2026-03-27 | 1 | — | — | — | — | — | — | insufficient data |
| 2026-04-01 | 1 | — | — | — | — | — | — | insufficient data |
| 2026-04-13 | 12 | -2.158 | [-4.301, -0.335] | 0.0176 | 0.0176 | Yes | 3.207 | Yes |

### Contiguous Bad Runs (mean excess < -1%)

- **2026-03-27, 2026-04-01, 2026-04-13** (n=14, mean excess=-2.025%)
  - No matched macro events
  - Repeatable category: No

- **2026-04-01, 2026-04-13** (n=13, mean excess=-2.158%)
  - No matched macro events
  - Repeatable category: No


![Day Clustering](a2_day_clustering.png)

![Cumulative P&L](a2_cumulative_pnl.png)

## A3: Sector Rotation

| Cell | n | Mean Excess (%) | 95% CI | p-value | FDR-adj p | Survives FDR | MDE | Underpowered |
|---|---|---|---|---|---|---|---|---|
| Cyclical | 7 | -1.067 | [-5.727, 3.519] | 0.6646 | 0.6646 | No | 8.348 | Yes |
| Defensive | 12 | 1.939 | [0.412, 3.618] | 0.0118 | 0.0236 | Yes | 2.606 | Yes |
| Financials | 4 | — | — | — | — | — | — | insufficient data |
| Tech+Comm | 4 | — | — | — | — | — | — | insufficient data |


![A3: Sector Rotation](a3_sector.png)

## A4: Entry Time-of-Day

| Cell | n | Mean Excess (%) | 95% CI | p-value | FDR-adj p | Survives FDR | MDE | Underpowered |
|---|---|---|---|---|---|---|---|---|
| 09:30-10:30 | 23 | 1.413 | [-0.205, 2.966] | 0.0876 | 0.0876 | Yes | 2.397 | Yes |
| 10:30-12:00 | 2 | — | — | — | — | — | — | insufficient data |
| 12:00-14:00 | 1 | — | — | — | — | — | — | insufficient data |
| 14:00-16:00 | 1 | — | — | — | — | — | — | insufficient data |


![A4: Entry Time-of-Day](a4_entry_time.png)

## A5: Holding Period

| Cell | n | Mean Excess (%) | 95% CI | p-value | FDR-adj p | Survives FDR | MDE | Underpowered |
|---|---|---|---|---|---|---|---|---|
| long | 8 | 2.021 | [-0.057, 3.443] | 0.0602 | 0.1204 | No | 3.142 | Yes |
| medium | 3 | — | — | — | — | — | — | insufficient data |
| short | 16 | 0.437 | [-2.043, 2.801] | 0.7204 | 0.7204 | No | 3.831 | Yes |


![A5: Holding Period](a5_holding_period.png)

## Power Analysis

| Cell | n | MDE (excess-Sharpe) | Underpowered (MDE > 0.5)? |
|---|---|---|---|

| Cyclical | 7 | 8.348 | Yes |

| Defensive | 12 | 2.606 | Yes |

| 09:30-10:30 | 23 | 2.397 | Yes |

| long | 8 | 3.142 | Yes |

| short | 16 | 3.831 | Yes |


VIX regression MDE: 0.710 %/VIX-point (benchmark: 0.3 %/VIX-point, underpowered: Yes)

## Decision

**CONTAMINATED**

Cell(s) Defensive, 09:30-10:30 survive FDR correction (q=0.10), indicating non-uniform excess return.
