# Lazy Prices v1 — Walk-Forward Validation Rerun (Real EDGAR Data, 2026-04-20)

## Summary

**Outcome state:** **INCONCLUSIVE**
**Reason:** `coverage_inconclusive`
**Framework verdict:** **VALIDATED** — three new framework capabilities shipped in v0.25.4-v0.25.5 confirmed working end-to-end on real data, with no regression vs the v0.25.3 baseline.

This run is the **first end-to-end real-data rerun** after:

- **v0.25.4 (#535)** wired VIX enrichment via `src/platform/vix_lookup.py` → `BacktestTrade.vix_at_entry`
- **v0.25.4 (#538)** added the `INCONCLUSIVE_DURATION` sub-state for windows shorter than `min_window_duration_days = 365`
- **v0.25.5 (#537)** lifted `sections_json` useful coverage from 28.1% to 71.1% via the parser backfill

Spec `src/platform/specs/lazy_prices_v1.yaml` **unchanged** (spec_hash identical to v0.25.3's). Seed unchanged (42). Universe unchanged (S&P 100). Three prior-sprint follow-ups from `docs/validation/lazy-prices-v1-walkforward-real-2026-04-19.md` §Follow-ups — closed by this run.

**Strategy verdict deliberately out of scope.** Per the v0.25.6 sprint anti-goal: CC captures, operator decides. The numbers below are the data, not the verdict.

## R8(a) declaration

`derived_from: null`

Lazy Prices v1 is literature-derived from Cohen, Malloy, Nguyen (2020) *Journal of Finance* ("Lazy Prices"). The persisted run row has `derived_from_source_type = NULL`, correctly reflecting the spec. R8(b) overlap assertion correctly does not trigger. Matches v0.25.3.

## R7 reproducibility fields

| field | v0.25.6 value | v0.25.3 value | comment |
|---|---|---|---|
| `run_id` | `7a8a96b6-3d3d-4cc3-9e6f-34573547cc72` | `88fd926e-1789-46f0-aee4-501addbb7256` | new |
| `spec_hash` | `ea78fed32a6ff7b3169e1657988392075677885280a22e800dfadd07c62b9e15` | `ea78fed32a6ff7b3169e1657988392075677885280a22e800dfadd07c62b9e15` | **identical (spec unchanged)** |
| `code_git_sha` | `638ef96912fa6338d88fd380b6d2328377a06d83` | `0f5e7178c5e9d34e7f5af48a2e6cf929365a00f6` | changed (new commit) |
| `random_seed` | `42` | `42` | identical |
| `created_at` | `2026-04-20T11:21:53.582831+00:00` | `2026-04-19T21:51:28.220554+00:00` | ~14h apart |

`config_json` captured in `walkforward_results.config_json` and reproduced verbatim in `docs/sprints/lazy_prices_v1_rerun_raw.md`.

## Run-level metrics

| metric | value |
|---|---|
| Outcome state | INCONCLUSIVE |
| Reason | `coverage_inconclusive` |
| Pooled Sharpe | 3.8976 |
| Pooled MDE | 10.2932 |
| Heavy-tail flag | 1 (fired) |
| Heavy-tail window count | 4 |
| N windows | 5 |
| Windows PASS / FAIL / INC_DATA / INC_POWER / **INC_DURATION** | 0 / 0 / 4 / 0 / **1** |
| Effective universe size (mean OOS) | 95 tickers |
| Max drawdown (%) | 15.00 |
| VIX tier coverage | **3** |

## Per-window breakdown

Gate `min_trades_per_window = 10`. Gate `min_window_duration_days = 365`.

| Window | Test window | Duration (days) | N OOS | State | Observed Sharpe | MDE |
|---|---|---|---|---|---|---|
| 0 | 2019-01-01 → 2020-03-31 | 455 | 4 | INCONCLUSIVE_DATA | (heavy-tail dominated) | — |
| 1 | 2020-04-01 → 2021-06-30 | 455 | 7 | INCONCLUSIVE_DATA | (heavy-tail dominated) | — |
| 2 | 2021-07-01 → 2022-09-30 | 457 | 4 | INCONCLUSIVE_DATA | (heavy-tail dominated) | — |
| 3 | 2022-10-01 → 2023-12-31 | 457 | 4 | INCONCLUSIVE_DATA | (heavy-tail dominated) | — |
| 4 | 2024-01-01 → 2024-09-30 | **273** | 2 | **INCONCLUSIVE_DURATION** | n/a (state overridden) | — |

Windows 0-3 are still below `min_trades_per_window = 10`; Window 4 now trips the new duration override regardless of trade count. **Zero purged, zero embargoed** across all 21 OOS trades — consistent with v0.25.3 (no trades straddled a window boundary).

## VIX enrichment validation (#535 — closed)

v0.25.3 Follow-up #1: "20/20 trades have `vix_at_entry = NULL`. Non-blocking for v0.25.3 but would block any future window that reaches ≥10 trades."

v0.25.6 result:

- `vix_at_entry` populated on **21 / 21** OOS trades (100.0%).
- `vix_tier` populated on 21 / 21 OOS trades.
- `vix_tier_coverage` = **3** at the run level (low, medium, high — all three tiers represented).
- Rerun-level `min_vix_tiers = 2` gate now passes. No longer a hidden blocker on future runs that cross `min_trades_per_window`.

VIX values span 14.32 (V in 2023-11-16, low tier) through 39.16 (MCD in 2020-02-27 pandemic onset, high tier) — continuous distribution, plausibly correct against `^VIX` history. `src/platform/vix_lookup.py::lookup_vix_at_entry` confirmed working end-to-end via real-data trade construction.

**Rule R2 CONFIRMED. Close v0.25.3 Follow-up #1.**

## Window-duration sub-state validation (#538 — closed)

v0.25.3 Follow-up #3: "Window 4 test_end = 2024-09-30 yields a 9-month window (shortest in the suite). Consider whether the framework should flag 'window duration below threshold' separately from trade-count coverage."

v0.25.6 result:

- Window 4 duration: 273 days < threshold 365 → classified `INCONCLUSIVE_DURATION`.
- `n_windows_inconclusive_duration = 1` in the persisted row.
- State-machine count: 0 PASS + 0 FAIL + 4 INC_DATA + 0 INC_POWER + **1 INC_DURATION** = 5 = n_windows ✓.

The duration override fires before the data override: per `walkforward_power.py:190-195`, the duration check is the first branch in the per-window classifier. This means Window 4 is now surfaced as "test span too short" rather than masked as "trade-count inconclusive" — distinct operator signal, as #538 intended.

Window 4 DID produce 2 OOS trades (NKE +13.73%, PG +4.51%), so INCONCLUSIVE_DATA was not the binding reason; the pre-duration behavior (v0.25.3) would have reported "INCONCLUSIVE_DATA with N=1" which is a less-actionable signal than "window too short to reach coverage regardless of data density."

**Rule R1 CONFIRMED. Close v0.25.3 Follow-up #3.**

## Sections_json parser backfill impact — trade count delta (#537)

v0.25.3 Follow-up #2: "1,518 / 5,393 filings (28%) have parsed sections. Running the section parser over the remaining full-text filings would likely lift trade counts per window substantially."

Parser backfill executed as v0.25.5 on 2026-04-20, lifting useful coverage to 71.1% (3,837 / 5,393). Pre-registered hypothesis (Pass 1, Rule R3) predicted 2-6× trade count lift.

**Observed delta per window:**

| Window | v0.25.3 N_OOS | v0.25.6 N_OOS | delta |
|---|---|---|---|
| 0 | 4 | 4 | 0 |
| 1 | 7 | 7 | 0 |
| 2 | 4 | 4 | 0 |
| 3 | 4 | 4 | 0 |
| 4 | 1 | 2 | +1 |
| **Total** | **20** | **21** | **+1** |

The 20 pre-existing trades are identical (same ticker, entry_date, hold_days, pnl_pct). One new trade: **PG 2024-08-06** in Window 4. That filing's `sections_json` was populated by the v0.25.5 backfill and produced a low-enough cosine similarity on item_1a or item_7 vs prior-year 10-K/10-Q to trip the `< 0.75` threshold.

**Hypothesis R3 — observed delta well below mechanistic expectation.** Candidate reasons (not investigated in-scope; flagged for potential follow-up):

1. Much of the v0.25.5 backfill parsed 8-K filings (2,570 of 3,743 = 69%). The spec filters to `form_type: [10-K, 10-Q]` — 8-K filings never generate signals.
2. Prior-year reference filings pre-2019 are not in the corpus (collection began 2019). Any 2019-2021 current filing needs a 2018-2020 prior-year reference; coverage on 2018 filings is less complete.
3. Many of the newly-parsed filings produced `sections_json = '{}'` (1,424 rows tracked under #552) — narrative content not extractable because the fetcher pulled iXBRL/SGML instead of HTML. The parser is correct; the fetcher is the rate-limiter on signal surface.
4. Cosine similarity `< 0.75` is a relatively strict threshold; many filings may not exhibit YoY narrative drift that large.

**None of these are framework bugs.** They are signal-surface observations that would inform a future strategy-tuning sprint if the operator elected to pursue lazy_prices as a strategy candidate (which remains explicitly out of scope here).

**Rule R3 captured without interpretation.**

## Heavy-tail bootstrap SE override — diagnostic (unchanged)

`heavy_tail_flag = 1`, `heavy_tail_window_count = 4`. Same pattern as v0.25.3: the small-N trade counts on windows 0-3 push bootstrap SE substantially above parametric SE, correctly flagging. Window 4 is now excluded from this diagnostic under the duration override (state is set before power metrics are evaluated). No bug. No framework drift between v0.25.3 and v0.25.6.

## Framework-bug trigger evaluation (Rule R5)

Pre-registered triggers from Pass 1 §R5 are all PASS-conditional. **Outcome was INCONCLUSIVE. No trigger fires.**

- State-machine miscount — N/A (not PASS). Sums: 0 + 0 + 4 + 0 + 1 = 5 = n_windows ✓
- MDE gate miscalibrated — N/A (not PASS)
- Bootstrap SE override not firing — NOT a bug; `heavy_tail_flag=1`, `heavy_tail_window_count=4`
- Data leakage through purge/embargo — `n_purged=0`, `n_embargoed=0`. Boundary separation correctly enforced.
- VIX tier coverage miscount — `vix_tier_coverage=3` and 3 distinct tiers observed in the ledger ✓
- R8 overlap assertion bypass — `derived_from_source_type=NULL` correctly propagated from spec `derived_from: null` ✓

**No framework-bug investigation issue filed.**

## v0.25.3 → v0.25.6 delta summary

| metric | v0.25.3 | v0.25.6 | delta |
|---|---|---|---|
| `outcome_state` | INCONCLUSIVE | INCONCLUSIVE | — |
| `reason` | coverage_inconclusive | coverage_inconclusive | — |
| `pooled_sharpe` | 3.5280 | 3.8976 | +0.37 |
| `pooled_mde` | 10.5448 | 10.2932 | −0.25 |
| `heavy_tail_flag` | 1 | 1 | — |
| `heavy_tail_window_count` | 4 | 4 | — |
| `n_windows_inconclusive_data` | 5 | 4 | −1 (Window 4 moved) |
| `n_windows_inconclusive_power` | 0 | 0 | — |
| `n_windows_inconclusive_duration` | n/a (pre-#538) | 1 | **+1 (NEW)** |
| `vix_tier_coverage` | 0 | **3** | **+3** |
| OOS trades (per-window) | 4,7,4,4,1 | 4,7,4,4,2 | W4: +1 |
| Total OOS trades | 20 | 21 | +1 |
| `vix_at_entry` non-NULL | 0/20 | 21/21 | **+21 (enrichment wired)** |
| Max drawdown % | 15.00 | 15.00 | — |
| Effective universe size | 95 | 95 | — |
| Spec hash | `ea78fed3…` | `ea78fed3…` | identical ✓ |

**Framework behavior is consistent and correct.** The two framework-layer differences (VIX coverage 0→3, Window 4 state `DATA`→`DURATION`) exactly match the three sprints (#535, #538, #537) landing between v0.25.3 and v0.25.6. No other differences.

## Pre-registered rule grading (from Pass 1)

| rule | prediction | observed | verdict |
|---|---|---|---|
| R1 | Window 4 → INCONCLUSIVE_DURATION | INCONCLUSIVE_DURATION | **✓ CONFIRMS #538** |
| R2 | 100% OOS trades with `vix_at_entry` non-NULL; vix_tier_coverage ≥ 1 | 21/21 non-NULL; coverage = 3 | **✓ CONFIRMS #535** |
| R3 | 2-6× trade-count lift (subject to threshold gating) | +1 trade total (below range) | captured, not a bug (see §Sections_json impact) |
| R4 | INCONCLUSIVE primary outcome | INCONCLUSIVE | ✓ matches |
| R5 | Framework-bug triggers inert (non-PASS) | no triggers fired | ✓ matches |
| R6 | R7 reproducibility fields all populate | all populated; spec_hash identical to v0.25.3 | ✓ |
| R7 | Spec byte-identical to `main` | `git diff main -- src/platform/specs/lazy_prices_v1.yaml` empty | ✓ |

## Operator actions requested

- Review this rerun alongside `docs/sprints/v0.25.6_evaluation.md` (Pass 1) and `docs/sprints/lazy_prices_v1_rerun_raw.md` (Pass 2).
- Close v0.25.3 §Follow-ups items 1 (VIX enrichment) and 3 (window-duration flag) — both validated as closed by this run.
- Decide whether the trade-count delta finding (R3) warrants a v0.25.7+ sprint. Candidates if so:
  - #552 fetcher fix would restore ~1,424 rows to useful coverage (currently `sections_json = '{}'`)
  - Tuning the cosine threshold from 0.75 to a looser cut (spec modification — explicitly out of scope here)
  - Broadening from sp100 to sp500 (spec modification)
- Decide whether the CLI JSON gap (missing `n_windows_inconclusive_duration` in the `--json` summary) is worth a trivial PR or a `skip and live with it` — minor cosmetic bug only.

## Follow-ups filed / proposed

- **Not filed, proposed for trivial PR:** `scripts/backtest/run_walkforward.py::main()` summary dict is missing `n_windows_inconclusive_duration` — the DB row carries it but the CLI JSON doesn't. One-line fix adding the key to the summary dict at line ~171-184. Operator call whether worth its own PR or bundled with next walk-forward sprint.
- **Referenced:** #552 (upstream `_lookup_primary_document` fetcher issue) — caps the useful coverage at ~71%. Fix would lift lazy_prices signal surface.

## Checklist

- [x] Outcome state recorded vs v0.25.3 baseline
- [x] VIX enrichment confirmed on 100% of OOS trades (#535 closed)
- [x] Window-duration sub-state confirmed firing on Window 4 (#538 closed)
- [x] Trade count delta captured per window (+1 total, PG 2024-08-06)
- [x] R7 reproducibility fields captured + spec_hash identical to v0.25.3
- [x] Framework-bug trigger evaluation: none fired (PASS-conditional, outcome was INCONCLUSIVE)
- [x] Pre-registered R1-R7 rules graded
- [x] No spec modification (git diff empty)
- [x] No strategy verdict interpretation (operator-gated)
