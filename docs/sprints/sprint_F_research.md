# Sprint F Pass 2 — Research

## Scope Check

Pass 2 re-verified the live repo after the clean worktree reset to `main`
(`90f5806`) and before the Sprint F runtime edits.

## 1. Line Verification

Pass 1 citations were re-checked against the clean worktree:

- `src/ranking/ranker.py`
  - `_regime_adjustment`: `72-102`
  - `_compute_sector_rs`: `105-147`
  - `_score_ticker`: `165-220`
  - `rank_universe`: `223-300`
- `src/features/engine.py`
  - `compute_all_features`: `204-288`
  - `_load_options_metrics`: `291-315`
  - `_load_event_proximity`: `318-330`
  - `_add_sector_features`: `349-364`
- `src/data_enrichment/enricher.py`
  - `enrich_features`: `53-176`
- `src/features/enrichment.py`
  - `attach_post_scan_features`: `22-82`
- `src/platform/strategy_spec.py`
  - `KNOWN_ENRICHERS`: `50`
  - `KNOWN_POST_SCAN_HELPERS`: `55`
  - `KNOWN_EVENT_RISK_CATEGORIES`: `61-69`

## 2. Callsite Sweep Findings

`rg` over `src tests scripts` confirmed the public call surface:

- `rank_universe(...)` callers assume only the existing return shape
  `{ticker, score, qualification, features}`.
- `compute_all_features(...)` callers assume a full feature dict and never pass
  optional arguments today.
- `enrich_features(...)` callers assume in-place enrichment of the existing
  feature dict and do not inspect any return-type-specific metadata.

Conclusion:

- Optional `strategy=None` parameters are safe.
- Changing default behavior is not safe.

## 3. Live-Repo Drift That Changes The Port Shape

### 3.1 Post-scan moved

The archived Sprint F prompt still says enrichment/event-risk dispatch lives in
`engine.py`.

On the live repo, that split is now:

- `src/data_enrichment/enricher.py`:
  fundamentals / insiders / macro / news / earnings-signals
- `src/features/enrichment.py`:
  `traffic_light` / `event_risk`

Therefore Sprint F must wire both live helpers and leave the archived boundary
behind.

### 3.2 Registry mismatch on fundamentals

`KNOWN_ENRICHERS` is:

```python
{"technicals", "insider", "macro", "news", "sector"}
```

but the live data-enrichment orchestrator has a fundamentals branch and no
`technicals` branch.

Decision:

- `macro`, `insider`, and `news` become spec-dispatchable now.
- `sector` is handled in `compute_all_features(...)`.
- `technicals` remains a documented always-on core contract of
  `compute_all_features(...)`.
- fundamentals remain always-on because inventing a new schema alias is out of
  scope for Sprint F.

### 3.3 Sector-RS data shape

`_compute_sector_rs(...)` still reads:

- ticker-side `return_1m/3m/6m`
- sector-side `return_1m/3m/6m`

but `compute_all_features(...)` does not populate the ticker-side absolute
return fields. Current production parity therefore still depends on the legacy
pre-score `_sector_rs_score` helper path when `sector_etf_features` are
available.

Decision:

- implement generic `derived_metrics` runtime support
- keep live incumbent parity via a derived alias over `_sector_rs_score` in the
  synthetic Sprint F incumbent spec

## 4. Fixture Tooling Feasibility

The generator is feasible against the local cache, with one important wrinkle:

- the clean worktree does not contain the gitignored simulation cache
- the canonical cache root exists in the original checkout:
  `C:/arcis/halcyon-lab/data/simulation_cache`

Confirmed local data facts from read-only probing:

- `104` full-year parquet files exist for `2023-01-01_2024-12-31`
- `SPY_2023-01-01_2024-12-31.parquet` exists with 501 rows
- `^VIX_2023-01-01_2024-12-31.parquet` exists with 501 rows

Primary-date feasibility check on `2024-03-26` (offline, using historical
patches) produced:

- `102` feature dicts
- `5` packet-worthy candidates
- top names: `COST`, `META`, `QCOM`, `AVGO`, `CRM`

This is enough to support deterministic byte-identity fixtures.

## 5. Float Round-Trip Contract

Sprint F fixture helpers use a JSON sentinel object:

```json
{"__float_repr__": "67.0"}
```

This keeps `repr()` exactness without relying on Python's default JSON float
writer. The loader restores with `float(...)`.

The contract is intentionally simple:

- dump: recursive `float -> {"__float_repr__": repr(x)}`
- load: recursive sentinel decode back to `float`
- hash: SHA-256 over sorted, separator-tight JSON

## 6. Runtime Decisions For The Port

### 6.1 Ranker band semantics

Decision:

- `ranking.bands` are evaluated first-match-wins per simple metric
- compound bands evaluate independently
- `ranking.adjustments.bands` accumulate all matches, then clamp

### 6.2 Blend-group parity rule

Decision:

- blend groups are evaluated at the metric level, not by summing every band
  entry's repeated weight
- if a metric value is present but no band matches, that metric contributes `0`
  while still consuming its declared weight
- if a metric value is unavailable, the remaining active metrics are
  reweighted back to the group's declared total

This preserves the incumbent sector-RS fallback without changing any legacy
no-spec path.

### 6.3 Enrichment dispatch rule

Decision:

- `compute_all_features(..., strategy=...)` only gates the live `sector`
  branch; technical core features stay always-on
- `enrich_features(..., strategy=...)` gates `macro`, `insider`, and `news`
  when a strategy chain is declared
- `attach_post_scan_features(..., strategy=...)` becomes the live consumer for
  `post_scan.chain` and `event_risk.quarantine_categories`

## 7. Baseline Verification

Clean-worktree baseline tests passed before the runtime edits:

```text
tests/test_ranking.py
tests/test_features_enrichment.py
tests/platform/specs/test_schema_c1_refinements.py
tests/platform/test_find_candidates.py
```

Result: `52 passed`

## 8. Remaining Known Risks

- Real validated specs still cannot name `_sector_rs_score` directly; Sprint F
  uses a synthetic incumbent spec for fixture evidence and leaves schema
  surface unchanged as required.
- `event_risk.quarantine_categories` is only partially observable from the live
  `event_risk_components` output; Sprint F can wire the categories the runtime
  actually emits today, but the full registry remains broader than the live
  producer.
- Branch push / remote reset is blocked in this environment because GitHub
  credentials are unavailable from the shell. Local implementation work is not
  blocked.
