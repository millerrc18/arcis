# Attribution readout — bootcamp archive 2026-04-24

_Generated 2026-04-28. Read-only diagnostic. DB: `C:\arcis\data\archive\ai_research_desk_bootcamp_2026-04-24.sqlite3`._



## 1. Sample size & coverage

| metric | value |
| --- | --- |
| total_rows | 3052 |
| distinct_attribution_id | 3052 |
| resolved (outcome win/loss/timeout) | 2040 |
| pending (outcome='pending' or NULL) | 1012 |
| resolution_rate | 0.6684 |
| null_pnl_pct in resolved rows | 0 |
| resolution_version='v1_multiindex_bug' | 1 |
| resolution_version IS NULL | 1272 |
| null_conviction in llm_action='taken' | 0 |
| scan_timestamp earliest | 2026-04-06T09:33:32.844759-04:00 |
| scan_timestamp latest | 2026-04-24T16:13:34.193668-04:00 |

### llm_action distribution (raw)

| llm_action | n |
| --- | --- |
| rejected | 2690 |
| skip | 147 |
| taken | 130 |
| buy | 80 |
| pending | 5 |

## 2. Outcome breakdown by LLM action

_Filter: resolved (win/loss/timeout), pnl_pct present, not `v1_multiindex_bug`._

| llm_action | ranker_only_outcome | n | avg pnl_pct | min | max |
| --- | --- | --- | --- | --- | --- |
| buy | loss | 23 | -5.1578 | -6.7600 | -3.8300 |
| buy | timeout | 28 | -1.8654 | -4.3300 | 0.2600 |
| buy | win | 29 | 3.8793 | 2.4300 | 5.3600 |
| pending | win | 1 | 4.7000 | 4.7000 | 4.7000 |
| rejected | loss | 298 | -4.8940 | -13.9900 | -3.0700 |
| rejected | timeout | 905 | -0.7000 | -5.8700 | 5.4300 |
| rejected | win | 635 | 4.2483 | 2.4400 | 8.6500 |
| taken | loss | 13 | -4.8338 | -5.3700 | -3.3400 |
| taken | timeout | 67 | -0.4564 | -3.8000 | 5.3800 |
| taken | win | 40 | 4.1195 | 2.9700 | 6.7000 |

## 3. Conviction-banded analysis (LLM `taken` only)

_Filter: resolved + pnl_pct present + not `v1_multiindex_bug` + llm_action='taken'._

| band | n | ranker-only wins | avg ranker-only pnl_pct |
| --- | --- | --- | --- |
| null | 0 | 0 | — |
| 0-49 | 120 | 40 | 0.5947 |
| 50-69 | 0 | 0 | — |
| 70-84 | 0 | 0 | — |
| 85+ | 0 | 0 | — |

## 4. Selection alpha test

_Compare ranker_only_pnl_pct of llm_action='taken' vs 'rejected'._

| metric | value |
| --- | --- |
| n_taken | 120 |
| n_rejected | 1838 |
| mean_taken | 0.5947 |
| mean_rejected | 0.3296 |
| delta | 0.2651 |
| t_stat | 0.8527 |
| p_value | 0.3953 |
| test | Welch two-sample t-test (two-sided) |

Test: Welch's two-sample t-test (unequal variances), two-sided.
Interpretation guide (operator-side, NOT a verdict from this script):
p < 0.05 with positive `delta` indicates the LLM-taken trades had
statistically different ranker-only outcomes than the rejected
counterfactuals. The numbers are descriptive — drawing a conclusion
is the operator's call.

## 5. Time-stratified replication

Midpoint: `2026-04-15T12:53:33.519213-04:00`
- First half:  `[2026-04-06T09:33:32.844759-04:00, 2026-04-15T12:53:33.519213-04:00)`
- Second half: `[2026-04-15T12:53:33.519213-04:00, 2026-04-24T16:13:34.193668-04:00]`

| metric | first half | second half |
| --- | --- | --- |
| n_taken | 117 | 3 |
| n_rejected | 1542 | 296 |
| mean_taken | 0.5462 | 2.4833 |
| mean_rejected | 0.0624 | 1.7214 |
| delta | 0.4838 | 0.7619 |
| t_stat | 1.5265 | 0.4452 |
| p_value | 0.1292 | 0.6987 |
| test | Welch two-sample t-test (two-sided) | Welch two-sample t-test (two-sided) |

If the overall §4 result is driven by a single regime, one half will
carry the signal while the other is flat or reversed. Reporting the
two halves independently exposes that failure mode.



## Notes & caveats
- Numerical aggregates exclude `resolution_version='v1_multiindex_bug'` and rows with `ranker_only_pnl_pct IS NULL`.
- This archive (2026-04-24) predates the `quarantined` column added 2026-04-27 (audit-2026-04-27 §F-1, T1.05). No quarantine filter applied.
- `resolution_version IS NULL` rows are kept (legacy pre-tagging). Count surfaced in §1 as a data-quality flag.
- §4 / §5 use only `llm_action IN ('taken','rejected')`. Other values (`buy`, `skip`, `pending`) appear in §1/§2 but are excluded from the t-test by design.
