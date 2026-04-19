# Post-Audit Ruleset v1 (Scoped) — Walk-Forward Validation (2026-04-19)

## Summary

**Outcome state:** **INCONCLUSIVE**
**Reason:** `coverage_inconclusive`
**Framework + filter verdict:** **VALIDATED.** Both schema extensions (`universe.sector_filter`, `entry.event_exclusion.categories`) correctly reduce the candidate stream end-to-end. Filter-bypass trigger did not fire. Outcome matches Pass 1 hypothesis.

This run exercises the two post-audit filter additions (Defensive sector hard-filter + Trade Policy event exclusion) layered on the lazy_prices_v1 signal substrate. It is the **first real-data run of a spec with `derived_from.source_type = forensic_audit_ruleset`**, i.e. the first R8(a)-non-null strategy to reach production-grade walk-forward framework.

Per the v0.25.3 precedent, this is **framework + schema validation, not strategy validation.** The forensic-audit ruleset is a candidate-selection filter, not a new strategy.

## R8 compliance

### R8(a) declaration

```yaml
derived_from:
  source_type: forensic_audit_ruleset
  source_run_id: april-2026-forensic-audit
  source_date_range:
    start: "2026-04-01"
    end: "2026-04-18"
# source_trade_ids intentionally omitted (Pass 2 §1 — key-absence accepted, null rejected)
```

Persisted to `walkforward_results`:
- `derived_from_source_type = forensic_audit_ruleset` ✓
- `derived_from_source_run_id = april-2026-forensic-audit` ✓

### R8(b) overlap assertion

Source date range `2026-04-01 → 2026-04-18` vs walk-forward OOS windows (2019-01-01 → 2024-09-30). Intersection = ∅. Overlap assertion trivially clears.

## R7 reproducibility fields

| Field | Value |
|---|---|
| `run_id` | `f266e097-0e19-4360-ac4a-ca1c388dda02` |
| `spec_hash` | `463853b503432ba2fc12277053f8fbf1eb15804bd2f9dbeff94df4f8e2fc8136` |
| `code_git_sha` | `6b88792717a3983f3c29776d80e9adf65ed11e50` |
| `random_seed` | `42` |
| `created_at` | `2026-04-19T22:22:13.146617+00:00` |

## Run-level metrics

| Metric | Value |
|---|---|
| Outcome state | INCONCLUSIVE |
| Reason | `coverage_inconclusive` |
| Pooled Sharpe | 1.0194 |
| Pooled MDE | 47.1966 |
| Heavy-tail flag | 0 |
| Heavy-tail window count | 0 |
| N windows | 5 |
| Windows PASS/FAIL/INC_DATA/INC_POWER | 0 / 0 / **5** / 0 |
| Effective universe size (mean OOS) | 95 tickers |
| Max drawdown (%) | 0.00 |
| VIX tier coverage | 0 (same enrichment gap as v0.25.3; non-blocking) |

## Per-window breakdown

Gate `min_trades_per_window = 10`. **No window meets the threshold.** All 5 → `INCONCLUSIVE_DATA`. Windows 1 and 4 had zero trades after filtering.

| Window | Test window | N OOS | Sharpe | MDE | Bootstrap SE | State |
|---|---|---|---|---|---|---|
| 0 | 2019-01-01 → 2020-03-31 | 1 | 0.000 | inf | inf | INCONCLUSIVE_DATA |
| 1 | 2020-04-01 → 2021-06-30 | **0** | — | — | — | INCONCLUSIVE_DATA |
| 2 | 2021-07-01 → 2022-09-30 | 1 | 0.000 | inf | inf | INCONCLUSIVE_DATA |
| 3 | 2022-10-01 → 2023-12-31 | 1 | 0.000 | inf | inf | INCONCLUSIVE_DATA |
| 4 | 2024-01-01 → 2024-09-30 | **0** | — | — | — | INCONCLUSIVE_DATA |

**Zero purged, zero embargoed.** Filter boundary-separation logic is wired but not stressed with only 3 total trades.

## Per-trade OOS ledger

3 trades — all Consumer Staples. No Utilities, no Health Care survived the joint filter (v0.25.3 baseline had none of those either; the filter preserves the 3 Defensive trades that already existed in baseline).

| Window | Ticker | GICS Sector | Entry | Hold (d) | PnL % | Exit |
|---|---|---|---|---|---|---|
| 0 | PM | Consumer Staples | 2020-02-10 | 13 | −5.79% | stop |
| 2 | COST | Consumer Staples | 2021-10-07 | 20 | +12.84% | timeout |
| 3 | MO | Consumer Staples | 2023-02-28 | 17 | −5.00% | stop |

Net: 1W / 2L (33% WR). Pooled Sharpe positive because COST's +12.8% dominates the 3-trade sum.

## Filter effect vs v0.25.3 baseline

| Metric | v0.25.3 baseline | v0.26.2-scoped | Δ |
|---|---|---|---|
| Total OOS trades | 20 | 3 | −85% |
| Defensive trades | 3 (PM/COST/MO) | 3 | no change |
| Non-Defensive trades | 17 | 0 | −100% |
| Trade Policy-date entries | 0 | 0 | no change (none in baseline either) |
| Outcome state | INCONCLUSIVE | INCONCLUSIVE | same |
| Reason | coverage_inconclusive | coverage_inconclusive | same |
| Pooled Sharpe | +3.528 | +1.019 | −71% (fewer trades, smaller gains) |
| Pooled MDE | 10.545 | 47.197 | 4.5× larger (expected as 1/√N grows) |
| Heavy-tail flag | 1 | 0 | baseline had small-N pathology; filtered stream is too small to stress heuristic |
| Heavy-tail window count | 4 | 0 | same reason |

**Interpretation:**
- Sector filter correctly removed 17 non-Defensive trades (−85%)
- Tariff exclusion removed 0 trades — none of the 3 surviving entry dates coincide with v0.25.1-backfilled Trade Policy dates (sanity-check: 2020-02-10 / 2021-10-07 / 2023-02-28 are clear)
- Framework outcome is correctly unchanged — same INCONCLUSIVE / coverage_inconclusive verdict
- Pooled MDE scales as expected for the reduced sample

## Framework-bug trigger evaluation

7 triggers pre-registered in Pass 1 (6 from v0.25.3 + new filter-bypass check). **None fired.**

| # | Trigger | Result |
|---|---|---|
| 1 | State-machine miscount | 0+0+5+0=5=n_windows ✓ |
| 2 | MDE gate miscalibrated | N/A (outcome INCONCLUSIVE; MDE=inf on N=1 windows as expected) |
| 3 | Bootstrap SE override not firing | Not triggered but correctly so — N=1 windows never reach the heavy-tail bootstrap code path; MDE=inf caps windows earlier in the state machine |
| 4 | Data leakage through purge/embargo | N/A; zero trades crossed a boundary |
| 5 | VIX tier coverage miscount | N/A; same upstream enrichment gap as v0.25.3 (filed as follow-up there, still applies here) |
| 6 | R8 overlap assertion bypass | N/A; source date range 2026-04-01/18 vs OOS 2019-2024 is trivially disjoint; firewall cleared |
| 7 | **Filter bypass (new for this sprint)** | post_audit=3 trades ≤ lazy_prices=20 trades ✓ |

**Framework-bug investigation NOT filed.**

## Secondary finding (known from v0.25.3, still present)

`vix_at_entry` and `vix_tier` are NULL on all 3 OOS trades → `vix_tier_coverage = 0`. Data-enrichment gap upstream; does not affect the INCONCLUSIVE verdict since the primary gate (`min_trades_per_window=10`) is already binding. Same follow-up as the v0.25.3 validation doc.

## Operator notes

- **Strategy verdict:** explicitly NOT INFERRED. Forensic-audit ruleset applied to 3 trades has no statistical power. The whole point of this sprint was schema validation, not strategy assessment. See `docs/validation/v0.26-cycle-summary.md`.
- **Morning-only filter (#540):** still pending. Gated on intraday OHLCV data layer. Once intraday data is available, a 3-filter variant can be tested; with only 3 base trades, intraday filtering is unlikely to change the outcome state.
- **Base coverage expansion:** the v0.25.3 validation doc already flagged `sections_json` coverage (1,518/5,393, 28%) as a limit on lazy_prices trade density. Widening section coverage upstream would also help this spec.

## Follow-ups

1. Widen `sections_json` coverage — would raise trade density across both lazy_prices and post_audit_ruleset_v1.
2. **VIX enrichment gap** — same as v0.25.3. `vix_at_entry` never populated at trade construction.
3. **Morning-only filter (#540)** — gate on intraday OHLCV.
4. **Point-in-time sector mapping** — current filter uses `SECTOR_MAP` (static current GICS). A ticker that changed sectors between 2019 and 2024 would be classified by 2026 membership. Out of scope for v0.26.2-scoped; flag if point-in-time sectors become relevant at higher trade counts.
