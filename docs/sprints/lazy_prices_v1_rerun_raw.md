# Pass 2 — v0.25.6 raw output capture (#547)

**Run timestamp:** 2026-04-20T11:21:53+00:00
**Invocation:** `python -m scripts.backtest.run_walkforward --strategy lazy_prices_v1 --json`
**Exit code:** 3 (INCONCLUSIVE)

No interpretation in this document. Raw capture only. Pass 3 (`docs/validation/...-rerun-2026-04-20.md`) grades against the pre-registered rules in Pass 1 (`docs/sprints/v0.25.6_evaluation.md`).

## CLI JSON summary (stdout)

```json
{
  "run_id": "7a8a96b6-3d3d-4cc3-9e6f-34573547cc72",
  "strategy_id": "lazy_prices_v1",
  "outcome_state": "INCONCLUSIVE",
  "reason": "coverage_inconclusive",
  "pooled_sharpe": 3.8975790681115847,
  "pooled_mde": 10.293153509676802,
  "n_windows_pass": 0,
  "n_windows_fail": 0,
  "n_windows_inconclusive_data": 4,
  "n_windows_inconclusive_power": 0,
  "heavy_tail_window_count": 4,
  "vix_tier_coverage": 3
}
```

**Observed gap:** the CLI JSON summary does **not** include `n_windows_inconclusive_duration` even though the field is populated in the persisted row. Minor CLI cosmetic bug; filed as follow-up.

## walkforward_results row (from DB)

| column | value |
|---|---|
| `run_id` | `7a8a96b6-3d3d-4cc3-9e6f-34573547cc72` |
| `strategy_id` | `lazy_prices_v1` |
| `spec_hash` | `ea78fed32a6ff7b3169e1657988392075677885280a22e800dfadd07c62b9e15` |
| `code_git_sha` | `638ef96912fa6338d88fd380b6d2328377a06d83` |
| `random_seed` | `42` |
| `outcome_state` | `INCONCLUSIVE` |
| `reason` | `coverage_inconclusive` |
| `pooled_sharpe` | `3.8975790681115847` |
| `pooled_mde` | `10.293153509676802` |
| `heavy_tail_flag` | `1` |
| `heavy_tail_window_count` | `4` |
| `n_windows` | `5` |
| `n_windows_pass` | `0` |
| `n_windows_fail` | `0` |
| `n_windows_inconclusive_data` | `4` |
| `n_windows_inconclusive_power` | `0` |
| `n_windows_inconclusive_duration` | **`1`** |
| `derived_from_source_type` | `NULL` (R8(a) literature-derived) |
| `derived_from_source_run_id` | `NULL` |
| `effective_universe_size` | `95` |
| `max_drawdown_pct` | `0.14996523012290414` |
| `vix_tier_coverage` | `3` |
| `created_at` | `2026-04-20T11:21:53.582831+00:00` |

States sum: 0 + 0 + 4 + 0 + 1 = 5 = n_windows ✓

## config_json (persisted, full)

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
  "min_window_duration_days": 365,
  "bootcamp_override": false,
  "windows": [
    {"train_start":"2017-01-01","train_end":"2018-12-31","test_start":"2019-01-01","test_end":"2020-03-31"},
    {"train_start":"2018-01-01","train_end":"2019-12-31","test_start":"2020-04-01","test_end":"2021-06-30"},
    {"train_start":"2019-01-01","train_end":"2020-12-31","test_start":"2021-07-01","test_end":"2022-09-30"},
    {"train_start":"2020-01-01","train_end":"2021-12-31","test_start":"2022-10-01","test_end":"2023-12-31"},
    {"train_start":"2021-01-01","train_end":"2022-12-31","test_start":"2024-01-01","test_end":"2024-09-30"}
  ]
}
```

## Per-window OOS breakdown

| win | n_oos | vix_at_entry non-NULL | vix_tiers observed | n_purged | n_embargoed |
|---|---|---|---|---|---|
| 0 | 4 | 4 | medium, high | 0 | 0 |
| 1 | 7 | 7 | medium, high | 0 | 0 |
| 2 | 4 | 4 | medium, high | 0 | 0 |
| 3 | 4 | 4 | medium, low | 0 | 0 |
| 4 | 2 | 2 | medium, high | 0 | 0 |

**Total OOS:** 21. **`vix_at_entry` non-NULL:** 21/21 (100.0%). **Distinct vix_tiers across all OOS:** 3 (low, medium, high).

## Per-trade OOS ledger (21 trades)

| win | ticker | entry_date | hold_d | pnl_pct | vix_tier | vix_at_entry | exit_reason | purged | embargoed |
|---|---|---|---|---|---|---|---|---|---|
| 0 | INTC | 2020-01-27 | 19 | −6.25% | medium | 18.23 | loss | 0 | 0 |
| 0 | LMT | 2020-02-10 | 10 | −5.00% | medium | 15.04 | loss | 0 | 0 |
| 0 | PM | 2020-02-10 | 13 | −5.79% | medium | 15.04 | loss | 0 | 0 |
| 0 | MCD | 2020-02-27 | 1 | −5.00% | high | 39.16 | loss | 0 | 0 |
| 1 | AAPL | 2020-11-02 | 21 | +13.00% | high | 37.13 | timeout | 0 | 0 |
| 1 | V | 2020-11-20 | 21 | −0.62% | medium | 23.70 | timeout | 0 | 0 |
| 1 | ADBE | 2021-01-19 | 21 | +5.90% | medium | 23.24 | timeout | 0 | 0 |
| 1 | INTC | 2021-01-25 | 21 | +12.76% | medium | 23.19 | timeout | 0 | 0 |
| 1 | HON | 2021-02-16 | 21 | +4.45% | medium | 21.46 | timeout | 0 | 0 |
| 1 | MCD | 2021-02-24 | 21 | +6.99% | medium | 21.34 | timeout | 0 | 0 |
| 1 | VZ | 2021-02-26 | 21 | +4.18% | high | 27.95 | timeout | 0 | 0 |
| 2 | COST | 2021-10-07 | 20 | +12.84% | medium | 19.54 | win | 0 | 0 |
| 2 | INTC | 2022-01-28 | 21 | −1.12% | high | 27.66 | timeout | 0 | 0 |
| 2 | NOW | 2022-02-04 | 21 | −7.46% | medium | 23.22 | timeout | 0 | 0 |
| 2 | MCD | 2022-02-25 | 5 | −5.10% | high | 27.59 | loss | 0 | 0 |
| 3 | INTC | 2023-01-30 | 21 | −7.51% | medium | 19.94 | timeout | 0 | 0 |
| 3 | MCD | 2023-02-27 | 21 | +4.68% | medium | 20.95 | timeout | 0 | 0 |
| 3 | MO | 2023-02-28 | 17 | −5.00% | medium | 20.70 | loss | 0 | 0 |
| 3 | V | 2023-11-16 | 21 | +3.93% | low | 14.32 | timeout | 0 | 0 |
| 4 | NKE | 2024-07-26 | 14 | +13.73% | medium | 16.39 | win | 0 | 0 |
| 4 | **PG** | 2024-08-06 | 21 | +4.51% | high | 27.71 | timeout | 0 | 0 |

**Bold:** new vs v0.25.3 baseline. 20 existing trades unchanged; 1 new trade (PG 2024-08-06) in Window 4.

## Delta vs v0.25.3 baseline

| | v0.25.3 (2026-04-19) | v0.25.6 (2026-04-20) |
|---|---|---|
| Per-window N_oos | 4, 7, 4, 4, **1** | 4, 7, 4, 4, **2** |
| Total OOS | 20 | 21 |
| OOS with `vix_at_entry` populated | 0 / 20 | 21 / 21 |
| `vix_tier_coverage` | 0 | 3 |
| Window 4 state | INCONCLUSIVE_DATA | **INCONCLUSIVE_DURATION** |
| `spec_hash` | `ea78fed3…` | `ea78fed3…` (identical) |
