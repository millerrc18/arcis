# Regime Diagnostic v1 — Design Spec

**Date:** 2026-04-18
**Branch:** `feat/regime-diagnostic-v1`
**Authority:** SD#41 REVISED — forensic audit finding (excess-Sharpe ~ 0 at N=88)
**Decision weight:** Gates 6 months of capital allocation strategy

---

## Objective

Determine whether the incumbent pullback-in-uptrend strategy's zero excess-Sharpe
is driven by a specific identifiable contaminant (sector, time-of-day, day cluster)
or is uniformly distributed across all subsample cuts.

**Output:** One of three decisions:
- **CONTAMINATED** — a specific, repeatable contaminant drives the null. Apply
  corresponding filter. Incumbent is resurrectable.
- **UNIFORMLY_NULL** — null is evenly distributed across all subsample cuts.
  Incumbent has no edge. Pivot capital slot to new strategy.
- **PENDING** — promising signal in continuous analysis (e.g., VIX regression)
  but underpowered at N=88. Re-run at N=150+ with broader regime window.

---

## Background

Forensic audit (2026-04-16) found per-trade Sharpe of 3.38 is SPY beta during a
bull run. Mean excess vs SPY = +0.039%, t = 0.098 over 75 matched periods —
statistically indistinguishable from zero.

**Critical constraint discovered during design:** All 88 closed trades span just
3 weeks (entries 2026-03-24 to 2026-04-13, exits to 2026-04-17). This invalidates
the original spec's regime-stratification premise — there is insufficient regime
variation across a 3-week single-regime window to populate regime × VIX × breadth
cells meaningfully. The design was reframed to test dimensions that DO vary within
this window.

---

## Data Layer Status

| Data point | Status | Action |
|---|---|---|
| excess_return | 88/88 populated (D1 backfill) | Use as-is |
| spy_return_over_hold | 88/88 populated | Use as-is |
| realized_sector | 88/88 populated (GICS lookup) | Use as-is |
| vix_at_entry | 36/88 populated (52 NULL) | Backfill in-memory via yfinance ^VIX |
| actual_entry_time | 88/88 populated (ISO timestamps with TZ) | Parse for hour + calendar day |
| duration_days | 88/88 populated | Use for holding-period bucketing |

**No schema changes.** VIX backfill is in-memory only — diagnostic reads from DB,
computes missing values, never writes back. Cross-check: the 36 existing vix_at_entry
values are validated against yfinance; discrepancies >0.5 points flagged in report
under "Data quality notes."

**S&P 100 roster:** Current roster from `data/reference/sp100-gics-lookup.csv` (102
tickers). Valid as point-in-time roster because the 3-week trade window has zero
constituent changes. Future diagnostics at longer horizons require point-in-time
rosters from FMP or SPDR archives.

---

## Rigor Requirements

### R1 — Point-in-time data

VIX values use ^VIX close on `entry_date - 1` trading day. No look-ahead.

### R2 — Intra-window stratification (5 analyses)

**A1: Continuous VIX regression**
- OLS: `excess_return ~ vix_at_entry` across all 88 trades
- Report: r, p-value, 95% CI on slope, scatter plot with regression line + CI band
- Power analysis: minimum detectable slope at 80% power given observed VIX range
  and excess_return variance. Report in units of "bps of excess return per VIX point."
  Benchmark: ~0.3% per VIX point. If MDE exceeds this, A1 is underpowered — report
  its null as underpowered, not as "no relationship detected."

**A2: Trade-day clustering**
- Primary: group by entry calendar day (~15 trading days). Per-day mean excess
  return + CI. Bar chart with error bars.
- Secondary: detect contiguous 2-3 day runs where mean excess < -1% (standardized).
- Tertiary (only if cluster identified): cross-reference with known macro events
  from `src/diagnostics/known_events.py` (FOMC, CPI, NFP, OPEX, tariff dates for
  the 3-week window). CONTAMINATED diagnosis requires the contaminant to map to a
  repeatable event category — "April 10 was bad" alone is not actionable.
- Cumulative P&L curve with calendar-day annotations as companion plot.

**A3: Sector rotation**
- Stratify by realized_sector collapsed to 4 buckets:
  - Tech+Comm (Technology, Communication Services)
  - Financials
  - Defensive (Health Care, Consumer Staples, Utilities)
  - Cyclical (Industrials, Energy, Materials, Consumer Discretionary, Real Estate)
- Per-bucket: n, mean excess return, excess-Sharpe, 95% bootstrap CI, p-value.
- Cells with n < 5: "insufficient data" — no computed stats.

**A4: Entry time-of-day**
- 4 buckets: 9:30-10:30, 10:30-12:00, 12:00-14:00, 14:00-16:00
- Per-bucket: n, mean excess return, excess-Sharpe, 95% bootstrap CI, p-value.

**A5: Holding-period outcomes**
- 3 buckets: short (1-3 days), medium (4-6 days), long (7+ days)
- Per-bucket: n, mean excess return, excess-Sharpe, 95% bootstrap CI, p-value.

### R3 — Bootstrap confidence intervals

For every cell with n >= 5:
- 10,000 resamples with replacement
- 95% CI (percentile method)
- p-value for H0: excess-Sharpe = 0 (two-sided, proportion of resamples crossing 0)

### R4 — Multiple testing correction

Benjamini-Hochberg FDR at q = 0.10 across all cell-level p-values (~12 tests total:
4 sector + 4 hour + 3 holding-period + 1 VIX regression slope). Report which cells
survive FDR correction.

### R5 — Robustness (scoped down)

Original R5 (alternative regime specifications) is moot — no regime variation in
a 3-week window. Replaced by the day-clustering secondary/tertiary analysis (A2)
which tests whether findings are driven by a single event vs. distributed.

### R6 — Power analysis

Two forms:
1. **Per-cell MDE:** For each cell with n >= 5, compute minimum detectable
   excess-Sharpe at 80% power, 5% significance. If MDE > 0.5, cell is underpowered.
2. **VIX regression MDE:** Minimum detectable slope (bps per VIX point) at 80% power
   given N=88, observed VIX range, and observed excess_return variance. Benchmark:
   0.3% per VIX point.

---

## File Structure

```
src/diagnostics/
  __init__.py           ~10 lines
  dimensions.py         ~150 lines   VIX backfill, sector/hour/holding bucketing
  known_events.py       ~40 lines    Dict of dates -> event labels (3-week window)
  bootstrap.py          ~80 lines    Bootstrap CI engine
  fdr.py                ~40 lines    Benjamini-Hochberg
  power.py              ~80 lines    MDE for cells + regression slope
  analyses.py           ~250 lines   A1-A5 analysis functions
  report.py             ~250 lines   Markdown report generation
  plots.py              ~250 lines   6 matplotlib figures

scripts/diagnostics/
  regime_diagnostic_v1.py  ~80 lines   CLI entry point

tests/diagnostics/
  __init__.py
  test_regime_diagnostic.py  ~300 lines   >= 10 tests
```

All files under 400 lines. No functions over 60 lines.

---

## Tests (>= 10)

1. VIX backfill produces no NULLs for valid date range
2. VIX cross-check flags values differing by >0.5 from yfinance
3. Sector collapse maps all 11 GICS sectors to exactly 4 buckets
4. Entry hour bucketing handles timezone-aware ISO timestamps
5. Holding period bucketing: edge cases (0, 1, 3, 4, 6, 7, 15 days)
6. Bootstrap CI coverage: synthetic N(0,1), CI contains 0 ~95% of time over 1000 trials
7. Bootstrap CI with known shift: synthetic N(1,1), CI does NOT contain 0
8. FDR: 20 uniform p-values, ~2 survive at q=0.10
9. FDR: inject p=0.001 into uniform array, it survives
10. Power calculation matches scipy reference for known parameters
11. VIX regression power: known slope + noise -> MDE is below actual slope
12. Report generation produces markdown with all required sections
13. Cells with n < 5 produce no computed stats (marked "insufficient data")

---

## Commit Sequence

1. `dimensions.py` + `known_events.py` + VIX backfill + dimension tests
2. `bootstrap.py` + `fdr.py` + `power.py` + statistical tests
3. `analyses.py` (A1-A5) + analysis tests
4. `plots.py` + plot smoke tests
5. `report.py` + integration test
6. CLI script `regime_diagnostic_v1.py` + docs update

---

## Decision Framework

The report concludes with one of:

- **CONTAMINATED:** A specific subsample (sector, time-of-day, day-cluster) drives
  the aggregate null, AND the contaminant maps to a repeatable event category (not
  just "one bad day"). Action: apply corresponding filter in a separate sprint.
- **UNIFORMLY_NULL:** Null is evenly distributed across all A1-A5 cuts. No subsample
  shows excess-Sharpe distinguishable from zero after FDR correction. Action: pivot
  capital slot to new strategy.
- **PENDING:** VIX regression or a cell-level test shows a promising signal, but
  power analysis confirms underpowered at N=88. Action: re-run diagnostic at N=150+
  with broader regime window.

---

## Explicit Non-Goals

- No strategy code changes (do not touch `src/strategies/`)
- No schema changes (no new columns, no DB writes)
- No dashboard page (report lives in `docs/diagnostics/`)
- No filter implementation (even if CONTAMINATED — filter sprint is separate)
- No version bump (diagnostic, not production code)
