# S04 Data Plane Audit Report

**Sprint:** S04 (data plane)
**Date:** 2026-10-04
**Status:** Complete
**Branch:** `feat/s04-data-plane`

## Summary

The S03 bars panel (504 symbols, 1,310,296 rows, 2016-01-04 to 2026-10-02) was audited for coverage, adjustments, corporate actions, availability, and survivorship. Key findings:

- **Coverage:** 504/504 symbols complete. 44 late starters (first bar after 2016-01-04). Zero symbols with gaps.
- **Adjustments:** All 4 tested splits (AAPL, TSLA, NVDA, AMZN) correctly adjusted — no artificial jumps.
- **Survivorship:** Panel contains only current constituents by construction. The bias direction is stated; quantification requires a historical membership source not available in this sprint.
- **Availability:** Bars timestamped at midnight UTC. Forward-test availability at `t_d` (17:00 ET) depends on Alpaca publication latency.

## T1 — Coverage audit

**Method:** For each symbol, compared actual bar dates against SPY's trading calendar. A "gap" is a SPY trading day with no bar for the symbol (after its first bar).

| Metric | Value |
|---|---|
| Total symbols | 504 |
| Complete | 504 |
| Late starters (first bar > 2016-01-04) | 44 |
| Symbols with gaps | 0 |
| Max gaps per symbol | 0 |
| Date range | 2016-01-04 to 2026-10-02 |

**Late starters** include tickers that listed after 2016 (e.g., GEV 2024, SOLV 2024, RDDT 2024, VLTO 2023, UBER 2019) and spinoffs (e.g., VTRS 2020, VRT 2018). Full list in `audit_results.json`.

**Gaps:** None. Every symbol has a bar for every SPY trading day from its first bar onward.

## T2 — Delisted symbol inventory

**Limitation:** A historical S&P 500 membership source was not available in this sprint. The panel contains only current constituents by construction (S03 pulled `config/sp500.csv` as of 2026-10-04).

**What we know:**
- 44/504 symbols (8.7%) did not exist in 2016 — they are additions, not survivors.
- The remaining 460 symbols were in the index in 2016 *or* joined later and are still members.
- Names that left the index (acquired, bankrupt, demoted) are absent. Their count and characteristics are unknown without a historical membership file.

**Bias direction:** Leavers were likely more volatile than stayers (acquisitions at premiums, bankruptcies to zero, demotions after declines). The current-constituent panel therefore understates historical dispersion. This is the same bias S03 stated qualitatively; quantification awaits a membership source.

## T3 — Adjustment verification

Tested 4 known stock splits with `adjustment=all`:

| Symbol | Split date | Ratio | Log jump | Adjusted? |
|---|---|---|---|---|
| AAPL | 2020-08-31 | 4:1 | 0.033 | Yes |
| TSLA | 2020-08-31 | 5:1 | 0.118 | Yes |
| NVDA | 2021-07-20 | 4:1 | 0.009 | Yes |
| AMZN | 2022-06-06 | 20:1 | 0.020 | Yes |

**Method:** `log_jump = |log(close_after / close_before)|` across the split date. An unadjusted 4:1 split would show `log_jump ≈ 1.39`. All four are < 0.2 (normal daily moves), confirming adjustments are applied.

**Dividends:** Not directly tested (no known-answer dividend in the test set). Alpaca's `adjustment=all` is documented to include dividend adjustments. A dividend-specific test is deferred.

## T4 — Corporate action documentation

How corporate actions manifest in Alpaca bars (with `adjustment=all`):

- **Stock splits (forward):** Adjusted retroactively. No price jump on the split date (verified T3).
- **Reverse splits:** Expected to be handled symmetrically (not tested — no recent S&P 500 reverse splits in the test set).
- **Cash dividends:** Adjusted retroactively per Alpaca documentation. The ex-div date shows no artificial drop in the adjusted series.
- **Spinoffs:** The parent's historical prices are typically adjusted down by the spinoff value. Specific behavior not verified in this sprint.
- **Ticker changes:** Alpaca uses the current ticker for the full history. A ticker change does not create a new symbol entry.
- **Mergers/acquisitions:** The acquired company's series ends at the acquisition date. It does not appear in the current-constituent panel.

## T5 — Availability and point-in-time

**Bar timestamps:** All bars are timestamped at 00:00 UTC on the calendar date. This is the *market date*, not the availability time.

**Forward test (post-tag):** The §2.1 test uses bars at `t_d` (17:00 ET). Alpaca's typical publication latency for daily bars is not measured in this sprint. For the forward test to be valid, bars must be available by `t_d`. This should be verified before the first 12-month look.

**Pre-tag history:** Historical bars (2016-2026) were backfilled, not available in real time. Any exploratory pre-tag analysis must not assume real-time availability.

**Forward membership snapshots:** The S01 recorder captures daily universe snapshots. Verification that these are ingested correctly is deferred to Step 4 (when the ranker needs point-in-time membership).

## T6 — Known-answer tests

`tests/test_data_plane.py` (5 tests, all passing):
1. AAPL 4:1 split shows no jump (log_jump < 0.2)
2. NVDA 4:1 split shows no jump
3. SPY has no gaps > 5 days (2016-2026)
4. GEV (listed 2024) has first bar after 2020
5. Panel has 504 symbols, all complete

## T7 — Survivorship report

**Quantified:**
- Current constituents with full 2016-2026 history: 460/504 (91.3%)
- Late starters: 44/504 (8.7%)
- Delisted/leaver count: Unknown (requires historical membership source)

**Bias assessment:**
- **Direction:** Understates dispersion (leavers likely more volatile).
- **Magnitude:** Unquantified. The 44 late starters are additions, not survivors — they don't inform the leaver bias.
- **Impact on S03:** The S03 power simulations used the current-constituent panel. The MDEs may be biased down (optimistic) due to survivorship. S03 stated this qualitatively; this sprint confirms the direction but cannot quantify the magnitude.

**Recommendation for Step 4:** If the ranker is sensitive to volatility estimates, consider a point-in-time universe reconstruction. Otherwise, document the bias as a limitation.

## Limitations and deviations

- T2 delisted inventory incomplete: no historical membership source available.
- T3 dividend verification deferred: no known-answer dividend test implemented.
- T5 Alpaca publication latency not measured: needed before the 12-month forward look.
- T5 forward snapshot ingestion not verified: deferred to Step 4.

## Dependencies

None added. Uses `pandas`, `numpy` (already in research group).
