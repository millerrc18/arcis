# S04 Data Plane Audit Report

**Sprint:** S04 (data plane)
**Date:** 2026-10-04 (revised 2026-10-04)
**Status:** Partial. T1, T3, T6 complete. T2, T4, T7 incomplete (see Limitations).
**Branch:** `feat/s04-data-plane`

## Summary

The S03 bars panel (504 symbols = 503 constituents + SPY, 1,310,296 rows, 2016-01-04 to 2026-10-02) was audited for coverage, adjustments, corporate actions, availability, and survivorship.

| Task | Status |
|---|---|
| T1 Coverage audit | ✅ Complete |
| T2 Delisted inventory | ❌ UNRESOLVED — no membership source |
| T3 Adjustment verification | ✅ Complete (splits only; dividends deferred) |
| T4 Corporate actions | ❌ UNRESOLVED — documented from Alpaca docs, not verified |
| T5 Availability | ⚠️ Partial — timestamps characterized; latency not measured |
| T6 Known-answer tests | ✅ Complete (synthetic fixtures, CI-safe) |
| T7 Survivorship report | ❌ UNRESOLVED — direction known, magnitude unquantified |

## T1 — Coverage audit ✅

**Method:** For each constituent (excluding SPY), compared actual bar dates against SPY's trading calendar. SPY is validated to exist before the audit runs. A "gap" is a SPY trading day with no bar for the symbol (after its first bar).

| Metric | Value |
|---|---|
| Constituents (excl. SPY) | 503 |
| Late starters (first bar > 2016-01-04) | 44 (8.7%) |
| Full history (2016-01-04 to 2026-10-02) | 459 (91.3%) |
| Symbols with gaps | 0 |
| Max gaps per symbol | 0 |
| Date range | 2016-01-04 to 2026-10-02 |

**Late starters** include tickers that listed after 2016 (e.g., GEV 2024, SOLV 2024, RDDT 2024, VLTO 2023, UBER 2019) and spinoffs (e.g., VTRS 2020, VRT 2018). Full list in `audit_results.json`.

**Gaps:** None. Every constituent has a bar for every SPY trading day from its first bar onward.

**Note on SPY as reference:** The audit validates that SPY exists in the panel. It does not validate SPY against an independent exchange calendar. A day missing from both SPY and a constituent would be invisible. This is a known limitation.

## T2 — Delisted symbol inventory ❌ UNRESOLVED

**Status:** Could not be completed. No historical S&P 500 membership source is available (D-013: no paid vendor).

**What we know:**
- 44/503 constituents (8.7%) did not exist in 2016 — they are additions, not survivors.
- The remaining 459 constituents were in the index in 2016 *or* joined later and are still members.
- Names that left the index (acquired, bankrupt, demoted) are absent. Their count and characteristics are unknown.

**Proposed fix:** Obtain a free point-in-time S&P 500 membership change list (e.g., from Wikipedia's "List of S&P 500 companies" revision history, or a public dataset). Store under the data root (not in the repo). Re-run T2 and T7.

**Impact:** The survivorship bias magnitude — the deliverable SCOPE §5 Step 3 names — is unquantified. This is a blocker for claiming the data plane is "sound for ranker development."

## T3 — Adjustment verification ✅ (splits only)

Tested 4 known stock splits with `adjustment=all`:

| Symbol | Split date | Ratio | Log jump | Adjusted? |
|---|---|---|---|---|
| AAPL | 2020-08-31 | 4:1 | 0.033 | Yes |
| TSLA | 2020-08-31 | 5:1 | 0.118 | Yes |
| NVDA | 2021-07-20 | 4:1 | 0.009 | Yes |
| AMZN | 2022-06-06 | 20:1 | 0.020 | Yes |

**Method:** `log_jump = |log(close_after / close_before)|` across the split date. An unadjusted 4:1 split would show `log_jump ≈ 1.39`. All four are < 0.2 (normal daily moves), confirming adjustments are applied.

**Dividends:** Deferred. No known-answer dividend test implemented. Alpaca's `adjustment=all` is documented to include dividend adjustments, but this is unverified.

## T4 — Corporate action documentation ❌ UNRESOLVED

**Status:** Written from Alpaca documentation and general knowledge, not verified against the data. Per CLAUDE.md, this is a stated result without evidence.

**What was documented (UNVERIFIED):**
- Stock splits (forward): Adjusted retroactively. No price jump on split date (this part IS verified by T3).
- Reverse splits: Expected to be handled symmetrically (not tested).
- Cash dividends: Adjusted retroactively per Alpaca docs (not verified).
- Spinoffs: Parent's historical prices typically adjusted down (not verified).
- Ticker changes: Alpaca uses current ticker for full history (not verified).
- Mergers/acquisitions: Acquired company's series ends at acquisition date (not verified).

**Proposed fix:** Verify each against the data (e.g., find a spinoff in the panel and check the parent's price series; find a ticker change and verify continuity).

## T5 — Availability and point-in-time ⚠️ Partial

**Bar timestamps:** Bars are stamped at **New York midnight**, not UTC midnight:
- 04:00 UTC during EDT (summer): 873,681 bars
- 05:00 UTC during EST (winter): 436,615 bars

This is the DST split. The timestamp reflects the market date in New York time.

**Forward test (post-tag):** The §2.1 test uses bars at `t_d` (17:00 ET). Alpaca's typical publication latency for daily bars is **not measured**. For the forward test to be valid, bars must be available by `t_d`. **This must be verified before the first 12-month look.**

**Pre-tag history:** Historical bars (2016-2026) were backfilled, not available in real time. Any exploratory pre-tag analysis must not assume real-time availability.

**Forward membership snapshots:** The S01 recorder captures daily universe snapshots. Verification that these are ingested correctly is deferred to Step 4 (when the ranker needs point-in-time membership). SCOPE §5 Step 3 lists this as part of Step 3; the deferral is noted here.

## T6 — Known-answer tests ✅

`tests/test_data_plane.py` (5 tests, all passing, CI-safe):
1. Trading-day helper generates weekdays only
2. Gap detection finds a single missing weekday (not hidden by weekend logic)
3. Split-adjustment logic: adjusted shows small jump, unadjusted shows large jump
4. Late-starter detection: GEV (2024) > cutoff, AAPL (2016) not
5. Coverage ratios exclude SPY: 459/503 = 91.3% (not 460/504)

These are synthetic-fixture tests. They verify the audit *logic*, not the real data. Real-data verification is done by `tools/audit_data_plane.py` (requires `--data-root`, not run in CI).

## T7 — Survivorship report ❌ UNRESOLVED

**Quantified:**
- Constituents with full 2016-2026 history: 459/503 (91.3%)
- Late starters: 44/503 (8.7%)
- Delisted/leaver count: Unknown (requires historical membership source — see T2)

**Bias assessment:**
- **Direction:** Understates dispersion (leavers likely more volatile than stayers).
- **Magnitude:** Unquantified. The 44 late starters are additions, not survivors — they don't inform the leaver bias.

**Impact on S03:** The S03 power simulations used the current-constituent panel. The MDEs may be biased down (optimistic) due to survivorship. S03 stated this qualitatively; this sprint confirms the direction but cannot quantify the magnitude.

## Limitations and deviations

1. **T2 UNRESOLVED:** No historical membership source. Proposed fix documented above.
2. **T4 UNRESOLVED:** Documented from Alpaca docs, not verified. Proposed fix documented above.
3. **T7 UNRESOLVED:** Magnitude unquantified (depends on T2).
4. **T3 dividends deferred:** No known-answer dividend test.
5. **T5 latency not measured:** Must verify before 12-month forward look.
6. **T5 forward snapshots deferred to Step 4:** Noted as deviation from SCOPE §5.
7. **SPY reference not validated against exchange calendar:** A day missing from both SPY and constituents is invisible.

## Blockers for Step 4

**T2/T7 are UNRESOLVED.** The survivorship bias magnitude is the deliverable SCOPE §5 Step 3 names. Without a membership source, Step 4 builds a ranker on data whose survivorship bias is unquantified.

**Recommendation:** Obtain a free membership change list (see T2 proposed fix) before starting Step 4. If unavailable, document the bias as a limitation and proceed with caution.

## Dependencies

None added. Uses `pandas`, `numpy` (research group, not in CI).
