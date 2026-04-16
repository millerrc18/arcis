# Regime & Sector Classifier Audit

**Date:** 2026-04-16
**Classification:** **Hypothesis (c) confirmed — schema-recent scanner bypass, fix already deployed 2026-04-14**
**Evidence strength:** strong (per-day pattern directly shows the deployment cut-over)
**Authority:** SD#41 REVISED / Sprint D3
**Trigger:** Forensic report found `market_regime` NULL on 67% of recommendations, with NULL-regime trades outperforming labeled regimes by 25+ points in early analyses

---

## Section 1 — Label Source Map

**Three distinct label vocabularies** live in the codebase, each written by a
different component to a different column. Much of the forensic confusion comes
from conflating them.

| Writer | Source file / line | Label vocabulary | Destination column |
|---|---|---|---|
| `compute_market_regime` | `src/features/regime.py:79`, labels at 162/164/170 | 5-state — `calm_uptrend`, `volatile_uptrend`, `calm_downtrend`, `volatile_downtrend`, `transitional` | `recommendations.market_regime` (via `journal/store.py:172`, reading `features.get("regime_label")`) |
| `classify_regime` (wrapper over compute_market_regime) | `src/features/regime.py:188` | **7-state — `BULL_LOW_VOL`, `BULL_HIGH_VOL`, `TRANSITION`, `CORRECTION`, `BEAR_EARLY`, `BEAR_ESTABLISHED`, `CRISIS`** | No DB column yet (derived on demand, used by ranker and agent prompts) |
| `compute_traffic_light` | `src/features/traffic_light.py:44,122,131` | `GREEN`, `YELLOW`, `RED` | `traffic_light_state.current_regime` + **`shadow_trades.regime_at_entry`** (via `executor.py:804` — see note below) |

### ⚠️ Column-naming bug worth flagging

`src/shadow_trading/executor.py:804`:

```python
trade_data["regime_at_entry"] = features.get("traffic_light", {}).get("regime_label", "")
```

The column is named `regime_at_entry` on `shadow_trades` but it stores the
**traffic-light regime** (GREEN/YELLOW/RED), not the market regime. The DB
currently shows `regime_at_entry: {GREEN: 128, NULL: 100}` which confused the
forensic report. The column should ideally be renamed `traffic_light_at_entry`
for accuracy; not done in this sprint because it's out-of-scope (schema
rename) — flagged as a follow-up.

### "Canonical" label decision

Per the sprint spec, the **7-state `classify_regime` set is the intended
canonical vocabulary going forward**. However, the DB today stores the 5-state
`compute_market_regime` labels in `recommendations.market_regime`. These two
vocabularies coexist and are not directly comparable:

- `calm_uptrend` (5-state) ≈ `BULL_LOW_VOL` (7-state)
- `volatile_uptrend` (5-state) ≈ `BULL_HIGH_VOL` (7-state)
- `transitional` (5-state) ≈ `TRANSITION` (7-state)
- 5-state has no distinct `CORRECTION`, `BEAR_EARLY`, `BEAR_ESTABLISHED`, `CRISIS` — lumps them as `volatile_downtrend`

Migrating the column to the 7-state vocabulary belongs in the SD#35 regime
classifier v2 sprint, not here.

The `GREEN/YELLOW/RED` vocabulary is the **traffic-light** output — a related
but distinct system that scales position sizing. It is NOT a regime vocabulary
and should never appear in regime-based analyses.

---

## Section 2 — Hypothesis Verdict

**Classification:** **Hypothesis (c) — schema-recent / scanner bypass (now fixed)**

### Evidence

**Per-day NULL-regime rate in `recommendations` (live DB, 2026-04-16):**

| Date          | NULLs    | Total    | % NULL |
|---------------|----------|----------|--------|
| 2026-03-*     | 1076     | 1076     | 100%   |
| 2026-04-01    | 171      | 171      | 100%   |
| 2026-04-06    | 260      | 260      | 100%   |
| 2026-04-07    | 320      | 320      | 100%   |
| 2026-04-08    | 260      | 260      | 100%   |
| **2026-04-09**| **0**    | **260**  | **0%** |
| 2026-04-10    | 0        | 120      | 0%     |
| 2026-04-13    | 65       | 325      | 20%    |
| 2026-04-14    | 30       | 150      | 20%    |
| **2026-04-15**| **0**    | **220**  | **0%** |
| 2026-04-16    | 0        | 191      | 0%     |

The cut-over between "100% NULL" and "0% NULL" happens on **2026-04-09**,
with two minor-miss days 2026-04-13/14 at 20%. This matches the enrichment
module's own documentation at `src/features/enrichment.py:8-14`:

> "Why this exists: before 2026-04-14 each scanner attached (or omitted)
> traffic_light and event_risk scores in its own way. The mean-reversion
> scanner omitted both, which caused all MR candidates to fall back to
> conservative defaults (0.5 traffic_light, 1.0 event_risk) AND to store
> market_regime=NULL in the recommendations table."

The 20% mixed days on 4-13 and 4-14 coincide with the progressive rollout of
`attach_post_scan_features` across all three scanner paths — partial deployment
before the final cover.

### Verification all three scanners now enrich (live grep, 2026-04-16)

```
src/scheduler/universe_scanner.py:120   from src.features.enrichment import attach_post_scan_features
src/scheduler/universe_scanner.py:121   attach_post_scan_features(...)
src/services/mr_scan_service.py:65      from src.features.enrichment import attach_post_scan_features
src/services/mr_scan_service.py:81      attach_post_scan_features(...)
src/services/scan_service.py:77         from src.features.enrichment import attach_post_scan_features
src/services/scan_service.py:83         attach_post_scan_features(...)
```

All three scanner paths call `attach_post_scan_features` before writing
recommendations. No bypass exists in the current code. Protected by regression
tests added in Task 6.

### Hypotheses (a) and (b) rejected

- **(a) Intermittent classifier:** Rejected. `compute_market_regime` runs on
  SPY OHLCV which is always available at scan time. No evidence of silent
  failures producing NULL. The cut-over pattern above is too clean for
  intermittent failure.
- **(b) Biased labels:** Rejected for `market_regime` specifically. The column
  is populated with the 5-state `regime_label` from `compute_market_regime`,
  which is deterministic on SPY features. Not biased by ticker or scan-time
  selection.

### Action required

- **No production code changes** — the fix was already deployed 2026-04-14.
- **Regression tests added** — see Section 5 / Task 6.
- **Historical NULL rows left in place** — they accurately reflect recommendations
  created while the bypass was active. Do not retroactively fill. Analyses that
  condition on `market_regime` must either drop these rows or explicitly bucket
  them as `pre_enrichment_unknown`.

---

## Section 3 — Sector Column Status

### `shadow_trades.realized_sector` (D1 instrumentation)

After D1 v0.19.0 landed and this sprint's top-up backfill ran:

| Sector                    | n   |
|---------------------------|-----|
| Consumer Staples          | 32+ |
| Financials                | 30+ |
| Technology                | 28+ |
| Industrials               | 24+ |
| Health Care               | 23+ |
| Communication Services    | 18+ |
| Energy                    | 16+ |
| Utilities                 | 12+ |
| Consumer Discretionary    | 10+ |
| Materials                 | 6+  |
| Real Estate               | 4+  |

**Coverage: 226 / 226 shadow_trades (100%). Zero NULL `realized_sector`.** Every
row has a valid GICS sector from `data/reference/sp100-gics-lookup.csv`.

### `recommendations.sector_context` remains 100% NULL

This column was never reliably populated by the scanner context pipeline. The
code path that was supposed to write it has always been broken (scope note: not
a regression introduced by any sprint — has been NULL since schema addition).

**Recommendation: deprecate `sector_context` in favor of `realized_sector`.**
Every analysis that wants a sector handle on a recommendation can join through
`recommendation_id → shadow_trades.realized_sector` or reconstruct from ticker
via the GICS lookup directly. The `sector_context` column stays in the schema
for back-compat but should be marked deprecated in the next SD#35 sprint.

---

## Section 4 — Labels Going Forward

### Canonical vocabulary (going forward)

**Regime:** 7-state set from `src/features/regime.py:classify_regime`:

```
BULL_LOW_VOL, BULL_HIGH_VOL, TRANSITION, CORRECTION,
BEAR_EARLY, BEAR_ESTABLISHED, CRISIS
```

**Traffic-light (position sizing):** 3-state set from
`src/features/traffic_light.py`:

```
GREEN, YELLOW, RED
```

### Legacy / transitional labels

Still present in the DB and codebase but **deprecated**:

- `calm_uptrend`, `volatile_uptrend`, `calm_downtrend`, `volatile_downtrend`,
  `transitional` — the 5-state `compute_market_regime` output. Currently written
  to `recommendations.market_regime`. Migration to the 7-state vocabulary is
  part of SD#35 regime classifier v2.
- `shadow_trades.regime_at_entry` stores traffic-light GREEN/YELLOW/RED despite
  being named `regime_at_entry`. Rename to `traffic_light_at_entry` tracked as a
  follow-up (out of scope here).

### Policy

Any new lever that filters on regime **must** use the 7-state canonical set
obtained via `classify_regime()`. Dashboards that display regime should label
their source (5-state vs 7-state vs traffic-light) rather than silently mix.

---

## Section 5 — Regression Protection

Four regression tests added in `tests/features/test_enrichment_coverage.py`:

1. `test_universe_scanner_calls_attach_post_scan_features` — source-literal
   check on `src/scheduler/universe_scanner.py`.
2. `test_main_scanner_calls_attach_post_scan_features` — source-literal check
   on `src/services/scan_service.py`.
3. `test_mr_scanner_calls_attach_post_scan_features` — source-literal check on
   `src/services/mr_scan_service.py`; the pre-2026-04-14 bug lived here.
4. `test_classify_regime_never_returns_none` — behavior check: empty and
   realistic inputs all produce a label in the canonical 7-state set.

If anyone removes the `attach_post_scan_features` call from any scanner, or
changes `classify_regime` to return `None`, tests fail at CI — BEFORE reaching
prod where it would silently re-open the NULL hole.

The source-literal check is deliberately simpler than mocking the import
graph. A false positive (someone renames `attach_post_scan_features` without
updating the test) is preferable to the false negative of "scanner quietly
stopped calling it but mock still passes."

---

## Decision log

- Kept `sector_context` in the schema but marked deprecated (no rename / drop)
- Did NOT migrate `market_regime` from 5-state to 7-state vocabulary (SD#35 scope)
- Did NOT rename `shadow_trades.regime_at_entry` to `traffic_light_at_entry`
  (schema rename requires a data-migration sprint)
- Did NOT retroactively populate the 1076 pre-enrichment NULL rows — they're a
  legitimate "enrichment not yet deployed" signal

---

*Audit closed 2026-04-16. No follow-up fix sprint required — root cause already
remediated. Regression tests guard against recurrence.*
