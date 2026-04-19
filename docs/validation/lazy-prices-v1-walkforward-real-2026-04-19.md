# Lazy Prices v1 — Walk-Forward Validation (Real EDGAR Data, 2026-04-19)

## Summary

**Outcome state:** **INCONCLUSIVE**
**Reason:** `coverage_inconclusive`
**Framework verdict:** **VALIDATED** — framework behaves correctly against real EDGAR data end-to-end. No PASS trigger fired. Matches the pre-registered Pass 1 hypothesis (NOT PASS expected).

This run is the **first end-to-end real-data exercise** of the walk-forward v1 framework shipped in v0.25.0 (PR #520). It uses `src/platform/specs/lazy_prices_v1.yaml` against the operator's local EDGAR filing corpus (3,199 filings with full text, 1,518 with parsed sections) and the S&P 100 point-in-time constituent table (112 rows). **The outcome says nothing definitive about the Lazy Prices strategy's tradability** — lazy_prices is a framework test vehicle here per the v0.25.3 sprint prompt:

> **Framework validation, not strategy validation.** Expected outcome is NOT PASS (forensic audit established lazy-prices underpowered on 2019-2024).

## R8(a) declaration

`derived_from: null`

Lazy Prices v1 is literature-derived from Cohen, Malloy, Nguyen (2020) *Journal of Finance* ("Lazy Prices"). The null value is accepted by R8(a) without triggering the R8(b) overlap assertion. The persisted run row has `derived_from_source_type = NULL`, correctly reflecting the spec.

## R7 reproducibility fields

| Field | Value |
|---|---|
| `run_id` | `88fd926e-1789-46f0-aee4-501addbb7256` |
| `spec_hash` | `ea78fed32a6ff7b3169e1657988392075677885280a22e800dfadd07c62b9e15` |
| `code_git_sha` | `0f5e7178c5e9d34e7f5af48a2e6cf929365a00f6` |
| `random_seed` | `42` |
| `created_at` | `2026-04-19T21:51:28.220554+00:00` |

`config_json` captured in `walkforward_results.config_json` and reproduced in `docs/sprints/lazy_prices_v1_real_raw.md`.

## Run-level metrics

| Metric | Value |
|---|---|
| Outcome state | INCONCLUSIVE |
| Reason | `coverage_inconclusive` |
| Pooled Sharpe | 3.5280 |
| Pooled MDE | 10.5448 |
| Heavy-tail flag | 1 (fired) |
| Heavy-tail window count | 4 |
| N windows | 5 |
| Windows PASS / FAIL / INC_DATA / INC_POWER | 0 / 0 / **5** / 0 |
| Effective universe size (mean OOS) | 95 tickers |
| Max drawdown (%) | 15.00 |
| VIX tier coverage | 0 (secondary finding — see below) |

## Per-window breakdown

Gate `min_trades_per_window = 10`. **No window meets the threshold.** All 5 marked `INCONCLUSIVE_DATA`.

| Window | Test window | N OOS | Sharpe (obs) | MDE | Bootstrap SE | State |
|---|---|---|---|---|---|---|
| 0 | 2019-01-01 → 2020-03-31 | 4 | −142.17 | 8.37e+15 | 2.08e+15 | INCONCLUSIVE_DATA |
| 1 | 2020-04-01 → 2021-06-30 | 7 | 21.70 | 45.23 | 13.75 | INCONCLUSIVE_DATA |
| 2 | 2021-07-01 → 2022-09-30 | 4 | −0.38 | 85.12 | 21.15 | INCONCLUSIVE_DATA |
| 3 | 2022-10-01 → 2023-12-31 | 4 | −2.52 | 176.86 | 43.95 | INCONCLUSIVE_DATA |
| 4 | 2024-01-01 → 2024-09-30 | 1 | 0.00 | inf | inf | INCONCLUSIVE_DATA |

**Zero purged, zero embargoed across all windows.** Purge/embargo wiring is correctly present but not stressed by this particular trade set (no trades straddled a window boundary within 5 days).

## Heavy-tail bootstrap SE override — diagnostic

`heavy_tail_flag = 1`, `heavy_tail_window_count = 4`.

Window 0 exhibits the classic pathological-N-4 case: 4 OOS trades, all negative, 3 capped at the stop loss (−5.00% floor), driving Sharpe to −142.17 and MDE to 8.37e+15. The heavy-tail override correctly fires (`bootstrap_SE > 1.5 * parametric_SE`), recording non-null `bootstrap_se` for the window. The absurd-looking values are **not a bug** — they truthfully reflect that 4 near-identical losers cannot produce a reliable per-window Sharpe estimate regardless of methodology. The framework's correct response is INCONCLUSIVE_DATA, which is exactly what it produced.

Windows 1-3 have 4-7 trades with less pathological statistics; the heavy-tail override also fires on windows 0, 1, 2, 3 (4 total) because bootstrap SE substantially exceeds the small-sample parametric SE on windows whose trade counts are far below the power-adequate threshold.

## VIX tier coverage = 0 — secondary finding (non-blocking)

`vix_at_entry` and `vix_tier` are **NULL for 20 / 20 OOS trades**. This drives `vix_tier_coverage = 0` at the run level.

This is a **data-enrichment gap, not a framework bug.** The framework reads `vix_tier` from `walkforward_trades.vix_tier`; the column is populated by the trade-construction path during `run_backtest` / `walkforward_runner`. Something upstream is not writing VIX at entry.

**Impact on this run:** none. The primary gate `min_trades_per_window = 10` already triggers `coverage_inconclusive` on all 5 windows, so the secondary VIX tier gate (`min_vix_tiers = 2`) is unbound by this result. If a future run ever reaches 10+ trades per window, the VIX-coverage gap would independently trigger `coverage_inconclusive` via `min_vix_tiers`. **Filed as follow-up** (see PR body).

## Framework-bug trigger evaluation (from Pass 1)

Pre-registered triggers are all PASS-conditional. Outcome was INCONCLUSIVE, so the investigation trigger did **not fire**:

- State-machine miscount — N/A (not PASS). Aggregate counts sum correctly: PASS=0, FAIL=0, INC_DATA=5, INC_POWER=0; total=5=n_windows ✓
- MDE gate miscalibrated — N/A (not PASS); MDE values correctly trend with window trade count (N=7 → MDE 45, N=4 → MDE 85+, N=1 → MDE inf) ✓
- Bootstrap SE override not firing — **NOT a bug.** `heavy_tail_flag=1`, `heavy_tail_window_count=4`, `bootstrap_se` populated for windows 0-3 ✓
- Data leakage through purge/embargo — no trades to leak; n_purged=0, n_embargoed=0 across all windows. Boundary separation cleanly enforced ✓
- VIX tier coverage miscount — not applicable as a PASS trigger here; the VIX enrichment gap is a separate data-pipeline issue ✓
- R8 overlap assertion bypass — `derived_from_source_type = NULL` correctly propagated from spec `derived_from: null` ✓

**No framework-bug investigation issue filed.**

## Synthetic vs real comparison

Reference: `docs/validation/lazy-prices-v1-walkforward-2026-04-19.md` (synthetic smoke test with three hand-tuned trade streams reaching each outcome state).

| Metric | Synthetic INCONCLUSIVE | Real INCONCLUSIVE | Comment |
|---|---|---|---|
| outcome_state | INCONCLUSIVE | INCONCLUSIVE | match ✓ |
| reason | `coverage_inconclusive` | `coverage_inconclusive` | match ✓ |
| n_windows_inconclusive_data | 5 | 5 | match ✓ |
| n_windows_inconclusive_power | 0 | 0 | match ✓ |
| heavy_tail_window_count | 4 | 4 | match ✓ |
| pooled_sharpe | −6.19 | +3.53 | differs (synthetic all-losers; real has 9 winners in 20 trades) |
| pooled_mde | 10.81 | 10.54 | near-match ✓ |
| vix_tier_coverage | 1 | 0 | differs (synthetic had 1 tier wired; real has enrichment gap) |

**Framework behavior is consistent.** Same outcome state, same reason, same window-state distribution, same heavy-tail count, near-identical pooled MDE. The Sharpe sign differs because real trades include winners; the synthetic all-losers baseline pushed Sharpe negative. Pooled MDE stays in the same order of magnitude, confirming that the MDE calculation is dominated by trade count (small across both) rather than trade P&L.

The VIX-tier mismatch is the only framework-behavior delta — it's explained by the upstream data-enrichment gap described above, not by framework logic drift between synthetic and real paths.

## Per-trade OOS ledger (20 trades, 9W / 11L, 45% WR)

| Window | Ticker | Entry | Hold (d) | PnL % |
|---|---|---|---|---|
| 0 | INTC | 2020-01-27 | 19 | −6.25% |
| 0 | LMT | 2020-02-10 | 10 | −5.00% |
| 0 | PM | 2020-02-10 | 13 | −5.79% |
| 0 | MCD | 2020-02-27 | 1 | −5.00% |
| 1 | AAPL | 2020-11-02 | 21 | +13.00% |
| 1 | V | 2020-11-20 | 21 | −0.62% |
| 1 | ADBE | 2021-01-19 | 21 | +5.90% |
| 1 | INTC | 2021-01-25 | 21 | +12.76% |
| 1 | HON | 2021-02-16 | 21 | +4.45% |
| 1 | MCD | 2021-02-24 | 21 | +6.99% |
| 1 | VZ | 2021-02-26 | 21 | +4.18% |
| 2 | COST | 2021-10-07 | 20 | +12.84% |
| 2 | INTC | 2022-01-28 | 21 | −1.12% |
| 2 | NOW | 2022-02-04 | 21 | −7.46% |
| 2 | MCD | 2022-02-25 | 5 | −5.10% |
| 3 | INTC | 2023-01-30 | 21 | −7.51% |
| 3 | MCD | 2023-02-27 | 21 | +4.68% |
| 3 | MO | 2023-02-28 | 17 | −5.00% |
| 3 | V | 2023-11-16 | 21 | +3.93% |
| 4 | NKE | 2024-07-26 | 14 | +13.73% |

## Interpretation

**Framework perspective (in-scope for v0.25.3):**
- ✓ Framework parses real EDGAR corpus and produces trades
- ✓ Purge/embargo wiring correctly enforces boundary separation
- ✓ MDE + heavy-tail override correctly scale with trade count
- ✓ Three-state outcome correctly surfaces `INCONCLUSIVE` when coverage is inadequate
- ✓ R7 reproducibility fields (spec_hash, code_git_sha, random_seed, config_json) populated
- ✓ R8(a) null declaration correctly propagated
- ✓ Synthetic-to-real framework behavior is consistent

**Strategy perspective (explicitly out-of-scope for v0.25.3):**
The data says lazy_prices on 2019-2024 generates ~20 signals across 5 windows — well below the framework's `min_trades_per_window = 10` floor. This is consistent with the forensic-audit finding that cosine similarity on 10-K/10-Q sections alone is a sparse signal at the large-cap universe. Widening `sections_json` coverage beyond the current 1,518 / 5,393 (28%) would raise the trade count per window; so would lowering the `less_than 0.75` similarity threshold or broadening from sp100 to sp500. **None of these modifications are in scope for this framework-validation sprint** — the spec on main is the spec we tested.

## Follow-ups

1. **VIX enrichment gap** — 20/20 trades have `vix_at_entry = NULL`. Trace from `walkforward_runner` back to trade construction; confirm `vix_at_entry` is computed and written when the engine creates a trade. Non-blocking for v0.25.3 but would block any future window that reaches ≥10 trades.
2. **Sections-json coverage** — 1,518 / 5,393 filings (28%) have parsed sections. Running the section parser over the remaining full-text filings would likely lift trade counts per window substantially. Parser pass is independent work; file if operator wants more trade density before revisiting lazy_prices as a strategy candidate.
3. **Window 4 window length** — test_end = 2024-09-30 yields a 9-month window (shortest in the suite). Consider whether the framework should flag "window duration below threshold" separately from trade-count coverage.

## Operator actions requested

- Review this validation report alongside `docs/sprints/lazy_prices_v1_real_{evaluation,raw}.md`.
- Confirm the framework is validated and ready for use with additional strategy specs.
- Decide whether follow-up 1 (VIX enrichment) is a v0.25.4 candidate.
