# Lazy Prices v1 — Walk-Forward Smoke Test (2026-04-19)

**SYNTHETIC FALLBACK.** This report was generated in a cloud
environment without access to the operator's local EDGAR
filing database. The three runs below exercise the walk-forward
framework state-machine against synthetic trade streams tuned
to reach each of the three outcome states (PASS, FAIL,
INCONCLUSIVE). Operator re-runs against real EDGAR data
locally after PR review.

Real-data expected outcome: **must NOT report PASS**. The forensic audit established that cosine-similarity signal alone is underpowered at the trade counts obtained on 2019-2024 data. A real-data PASS indicates a framework bug.

## R8(a) declaration

`derived_from: None`

Lazy Prices v1 is literature-derived from Cohen, Malloy, Nguyen
(2020) Journal of Finance. The null value is accepted by R8(a)
without triggering the R8(b) overlap assertion.

## INCONCLUSIVE (synthetic fallback)

- run_id: `b6fe34b9-4f1d-402f-94e1-00c9cd2c1031`
- outcome_state: **INCONCLUSIVE**
- reason: `coverage_inconclusive`
- pooled Sharpe: -6.1909
- pooled MDE: 10.8058
- heavy-tail windows: 4
- VIX tier coverage: 1
- window states: PASS=0 / FAIL=0 / INCONCLUSIVE_DATA=5 / INCONCLUSIVE_POWER=0

Per-window breakdown:

| Window | N trades | Sharpe | MDE | State |
|--------|----------|--------|-----|-------|
| 0 | 4 | 1.908 | 459.113 | INCONCLUSIVE_DATA |
| 1 | 4 | -16.373 | 163.709 | INCONCLUSIVE_DATA |
| 2 | 4 | -9.440 | 34.649 | INCONCLUSIVE_DATA |
| 3 | 4 | -3.738 | 75.580 | INCONCLUSIVE_DATA |
| 4 | 4 | 8.836 | 88.275 | INCONCLUSIVE_DATA |

## FAIL (synthetic fallback)

- run_id: `5b1306f2-231d-4136-a363-4628b2344992`
- outcome_state: **FAIL**
- reason: `criterion_4_drawdown`
- pooled Sharpe: -5.1109
- pooled MDE: 3.4648
- heavy-tail windows: 0
- VIX tier coverage: 3
- window states: PASS=4 / FAIL=0 / INCONCLUSIVE_DATA=0 / INCONCLUSIVE_POWER=1

Per-window breakdown:

| Window | N trades | Sharpe | MDE | State |
|--------|----------|--------|-----|-------|
| 0 | 20 | -69689166883265360.000 | 149281120504280064.000 | INCONCLUSIVE_POWER |
| 1 | 39 | 3.412 | 7.369 | PASS |
| 2 | 39 | 6.792 | 7.611 | PASS |
| 3 | 39 | 6.395 | 7.575 | PASS |
| 4 | 38 | 4.363 | 7.523 | PASS |

## PASS (synthetic fallback)

- run_id: `d4668510-3297-4185-89a5-4bef2f0002a3`
- outcome_state: **PASS**
- reason: `walkforward_pass`
- pooled Sharpe: 6.2309
- pooled MDE: 3.3284
- heavy-tail windows: 0
- VIX tier coverage: 2
- window states: PASS=5 / FAIL=0 / INCONCLUSIVE_DATA=0 / INCONCLUSIVE_POWER=0

Per-window breakdown:

| Window | N trades | Sharpe | MDE | State |
|--------|----------|--------|-----|-------|
| 0 | 39 | 5.926 | 7.555 | PASS |
| 1 | 39 | 5.855 | 7.529 | PASS |
| 2 | 39 | 5.933 | 7.535 | PASS |
| 3 | 39 | 3.348 | 7.398 | PASS |
| 4 | 38 | 10.820 | 8.198 | PASS |

## Framework verification

All three synthetic runs completed without R8ViolationError. `walkforward_results` now contains three rows with distinct `outcome_state` values; the `/api/walkforward/runs` endpoint surfaces them for the dashboard.
