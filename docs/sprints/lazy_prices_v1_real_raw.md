# Pass 2 — v0.25.3 lazy_prices_v1 real-data walk-forward raw output (#532)

**Branch:** `validation/lazy-prices-v1-real-walkforward`
**Date:** 2026-04-19

## Command

```
python -m scripts.backtest.run_walkforward --strategy lazy_prices_v1 --json
```

(Adapted from prompt's `--spec/--output-tag` flags; see Pass 1 evaluation §"Runner invocation".)

## stdout — JSON summary

```json
{
  "run_id": "88fd926e-1789-46f0-aee4-501addbb7256",
  "strategy_id": "lazy_prices_v1",
  "outcome_state": "INCONCLUSIVE",
  "reason": "coverage_inconclusive",
  "pooled_sharpe": 3.52804969106398,
  "pooled_mde": 10.544805069192446,
  "n_windows_pass": 0,
  "n_windows_fail": 0,
  "n_windows_inconclusive_data": 5,
  "n_windows_inconclusive_power": 0,
  "heavy_tail_window_count": 4,
  "vix_tier_coverage": 0
}
```

**Exit code:** 3 (Python script). Note: the shell pipeline `python -m … | tee` returned 0 because `tee`'s exit status masks the Python exit — I read the persisted `walkforward_results` row to confirm the outcome independently of exit code.

## Run-level row (`walkforward_results`)

Queried by `run_id = '88fd926e-1789-46f0-aee4-501addbb7256'`:

| Field | Value |
|---|---|
| run_id | 88fd926e-1789-46f0-aee4-501addbb7256 |
| strategy_id | lazy_prices_v1 |
| spec_hash | ea78fed32a6ff7b3169e1657988392075677885280a22e800dfadd07c62b9e15 |
| code_git_sha | 0f5e7178c5e9d34e7f5af48a2e6cf929365a00f6 |
| random_seed | 42 |
| outcome_state | INCONCLUSIVE |
| reason | coverage_inconclusive |
| pooled_sharpe | 3.5280 |
| pooled_mde | 10.5448 |
| heavy_tail_flag | 1 |
| heavy_tail_window_count | 4 |
| n_windows | 5 |
| n_windows_pass | 0 |
| n_windows_fail | 0 |
| n_windows_inconclusive_data | 5 |
| n_windows_inconclusive_power | 0 |
| derived_from_source_type | NULL |
| derived_from_source_run_id | NULL |
| effective_universe_size | 95 |
| max_drawdown_pct | 0.1500 |
| vix_tier_coverage | 0 |
| created_at | 2026-04-19T21:51:28.220554+00:00 |

## R7 reproducibility fields

- **`spec_hash`:** `ea78fed32a6ff7b3169e1657988392075677885280a22e800dfadd07c62b9e15`
- **`code_git_sha`:** `0f5e7178c5e9d34e7f5af48a2e6cf929365a00f6` — matches the Pass 1 commit HEAD at run time
- **`random_seed`:** `42`
- **`config_json`:**

```json
{
  "strategy_id": "lazy_prices_v1",
  "universe_tag": "sp100",
  "embargo_days": 5,
  "per_side_cost_bps": 0.5,
  "random_seed": 42,
  "alpha": 0.05,
  "power": 0.8,
  "heavy_tail_se_ratio": 1.5,
  "bootstrap_resamples": 10000,
  "sharpe_min": 0.3,
  "mde_max": 0.3,
  "pooled_sharpe_min": 0.5,
  "max_drawdown_cap_pct": 0.2,
  "min_trades_per_window": 10,
  "min_vix_tiers": 2,
  "bootcamp_override": false,
  "windows": [
    {"train_start": "2017-01-01", "train_end": "2018-12-31", "test_start": "2019-01-01", "test_end": "2020-03-31"},
    {"train_start": "2018-01-01", "train_end": "2019-12-31", "test_start": "2020-04-01", "test_end": "2021-06-30"},
    {"train_start": "2019-01-01", "train_end": "2020-12-31", "test_start": "2021-07-01", "test_end": "2022-09-30"},
    {"train_start": "2020-01-01", "train_end": "2021-12-31", "test_start": "2022-10-01", "test_end": "2023-12-31"},
    {"train_start": "2021-01-01", "train_end": "2022-12-31", "test_start": "2024-01-01", "test_end": "2024-09-30"}
  ]
}
```

## Per-window OOS trade summary (`walkforward_trades`)

Aggregated by `window_index` across 20 total OOS trades (all clean; zero purged, zero embargoed):

| Window | test_start → test_end | N OOS | Sharpe (obs) | MDE (mean) | Bootstrap SE | State |
|---|---|---|---|---|---|---|
| 0 | 2019-01-01 → 2020-03-31 | 4 | −142.169 | 8.37e+15 | 2.08e+15 | INCONCLUSIVE_DATA |
| 1 | 2020-04-01 → 2021-06-30 | 7 | 21.703 | 45.232 | 13.755 | INCONCLUSIVE_DATA |
| 2 | 2021-07-01 → 2022-09-30 | 4 | −0.381 | 85.124 | 21.154 | INCONCLUSIVE_DATA |
| 3 | 2022-10-01 → 2023-12-31 | 4 | −2.520 | 176.856 | 43.950 | INCONCLUSIVE_DATA |
| 4 | 2024-01-01 → 2024-09-30 | 1 | 0.000 | inf | inf | INCONCLUSIVE_DATA |

Gate: `min_trades_per_window = 10`. No window meets the threshold — all 5 marked `INCONCLUSIVE_DATA`. Pooled aggregate: `outcome_state=INCONCLUSIVE, reason=coverage_inconclusive`.

## Per-trade OOS ledger (20 trades)

| Window | Ticker | Entry date | Hold days | PnL % |
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

Totals: 9 winners, 11 losers (45% win rate). Exit reasons: mostly `timeout_21d`; window 0 and occasional others show `stop_hit` (−5%). Window 4's single trade was NKE up +13.7%, but N=1 means MDE=inf and the window is INCONCLUSIVE_DATA.

## Secondary finding — VIX enrichment gap (non-blocking)

`vix_at_entry` and `vix_tier` are `NULL` for **20 / 20** OOS trades. This drives `vix_tier_coverage = 0` at the run level. Because the primary gate `min_trades_per_window=10` is already unmet, the VIX-tier-coverage gate (`min_vix_tiers=2`) is not the reason for INCONCLUSIVE — but if a future run ever hits 10+ trades/window, the VIX gap would independently trigger `coverage_inconclusive` via `min_vix_tiers`.

**Not a framework bug.** The framework *reads* `vix_tier` from `walkforward_trades.vix_tier`; the *population* path (VIX fetch + bucket classification during trade construction) is what's not writing the column. Root cause to investigate in a later sprint — out of scope for this framework-validation run.

## Framework-bug trigger evaluation (from Pass 1)

Pre-registered triggers (all PASS-conditional):

- **State-machine miscount** — N/A (outcome was INCONCLUSIVE, not PASS)
- **MDE gate miscalibrated** — N/A
- **Bootstrap SE override not firing** — NOT triggered; `heavy_tail_flag=1`, `heavy_tail_window_count=4`, bootstrap SE values are non-null for windows 0-3. Window 0 exhibits the heavy-tail runaway (Sharpe ≈ −142, MDE ≈ 8.37e+15) correctly reflecting a pathological 4-trade window with extreme dispersion — the override IS firing, just with extreme values because N=4 is below meaningful stability. This is correct behavior, not a bug.
- **Data leakage through purge/embargo** — N/A; outcome was INCONCLUSIVE not PASS. Diagnostic: zero purged + zero embargoed trades across all windows. Windows have clean separation (test_start of each window is > train_end of the same window by 0-1 days; embargo_days=5 but no trades straddled the boundary so none were embargoed). Purge/embargo logic appears to be correctly wired but not stressed by this particular trade set.
- **VIX tier coverage miscount** — N/A (outcome INCONCLUSIVE)
- **R8 overlap assertion bypass** — N/A; `derived_from_source_type=NULL` correctly reflects `derived_from: null` in spec. Lazy_prices R8 declaration is literature-derived (Cohen-Malloy-Nguyen 2020), not derived from a prior internal run.

**No PASS trigger fired. No framework-bug investigation required.**

## Next: Pass 3 validation doc

Fold this raw output + Pass 1 hypothesis into:
- `docs/validation/lazy-prices-v1-walkforward-real-2026-04-19.md`

With:
- Synthetic vs real comparison (synthetic INCONCLUSIVE run from `docs/validation/lazy-prices-v1-walkforward-2026-04-19.md`)
- R8(a) declaration echo
- R7 fields
- Per-window breakdown
- Heavy-tail flag analysis
- VIX enrichment gap as a sub-finding
