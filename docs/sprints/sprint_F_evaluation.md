# Sprint F Pass 1 — Evaluation

## Scope

Sprint F ports the incumbent pullback ranker onto the existing strategy-spec
surface without changing legacy behavior when no spec is passed.

Live-repo drift from the archived prompt is material and must be preserved:

- Ranker scoring still lives in `src/ranking/ranker.py`.
- Core feature computation still lives in `src/features/engine.py`.
- Fundamental/news/macro/insider enrichment lives in `src/data_enrichment/enricher.py`.
- Post-scan `traffic_light` / `event_risk` dispatch now lives in
  `src/features/enrichment.py`, not `src/features/engine.py`.

Sprint F therefore treats the repo as authoritative and ports the live
boundaries rather than the archived prompt's older boundaries.

## 1. Ranker Constants Inventory

### 1.1 Threshold loading

`src/ranking/ranker.py:28-69`

- Bootcamp overrides:
  - `bootcamp.qualification_threshold`
  - `bootcamp.watchlist_threshold`
- Default thresholds:
  - `config.ranking.packet_worthy_threshold`
  - `config.ranking.watchlist_threshold`
- Regime-adaptive override table:
  - `REGIME_THRESHOLDS` at `src/ranking/ranker.py:17-25`

Sprint F does not port threshold loading to spec. The `rank_universe(...,
strategy=None)` signature is added for future Sprint H plumbing, but legacy
config-driven thresholding remains the source of truth in this sprint.

### 1.2 Regime adjustment

`src/ranking/ranker.py:72-102`

Hardcoded logic maps cleanly to `ranking.adjustments.bands` plus
`ranking.adjustments.clamp`.

Mapping:

| Runtime branch | Current line(s) | Spec path |
|---|---:|---|
| `regime_label == calm_uptrend && market_breadth_label == healthy -> +5` | 80-81 | `ranking.adjustments.bands[*].conditions[...]` |
| `regime_label == calm_uptrend && market_breadth_label == narrowing -> +2` | 82-83 | same |
| `regime_label == transitional -> -3` | 86-87 | same |
| `regime_label == calm_downtrend -> -5` | 88-89 | same |
| `regime_label == volatile_downtrend -> -10` | 90-91 | same |
| `spy_rsi_14 > 75 -> -3` | 94-95 | `ranking.adjustments.bands[*].range` |
| `spy_rsi_14 < 30 -> +3` | 96-97 | `ranking.adjustments.bands[*].range` |
| clamp to `[-10, 10]` | 102 | `ranking.adjustments.clamp` |

Notes:

- `volatile_uptrend -> +0` at `84-85` is an explicit no-op and does not need a
  band entry.
- Adjustment semantics are cumulative, then clamped.

### 1.3 Sector relative strength

`src/ranking/ranker.py:105-147`

Current implementation is a two-step process:

1. Compute `weighted_excess = 0.20 * excess_1m + 0.50 * excess_3m + 0.30 * excess_6m`
   at `133-137`.
2. Band that value to `25 / 15 / 5 / 0` at `140-147`.

Sprint F runtime port:

- Generic `ranking.derived_metrics` evaluation is implemented in the ranker.
- Live incumbent parity still depends on the legacy pre-score helper
  `_compute_sector_rs(...)` because current feature dicts do not expose raw
  `return_1m/3m/6m` fields from `compute_all_features(...)`.
- The incumbent-equivalent Sprint F synthetic spec therefore aliases the
  precomputed `_sector_rs_score` into a derived metric for scoring.

This is a live-repo drift from the archived prompt and must be documented, not
hand-waved.

### 1.4 Main scoring bands

`src/ranking/ranker.py:165-220`

Mapping:

| Runtime branch | Current line(s) | Spec path |
|---|---:|---|
| `trend_state == strong_uptrend -> +30` | 169-172 | `ranking.bands[*].category` |
| `trend_state == uptrend -> +20` | 173-174 | same |
| `trend_state == neutral -> +5` | 175-176 | same |
| market RS `strong_outperformer -> 25`, `outperformer -> 15` | 178-180 | categorical `ranking.bands` in a `blend_group` |
| sector RS contribution | 182-187 | numeric `ranking.bands` in same `blend_group` |
| pullback sweet spot `[-8, -3] -> +25` | 189-192 | numeric `ranking.bands` |
| pullback moderate `[-12, -8) -> +10` | 193-194 | numeric `ranking.bands`, order-sensitive |
| `dist_to_sma20_pct in [-5, -1] -> +10` | 196-199 | numeric `ranking.bands` |
| `volume_ratio_20d < 0.8 -> +15` | 201-204 | numeric `ranking.bands` with sentinel lower bound |
| `iv_rank < 25 -> +3` | 206-211 | numeric `ranking.bands` |
| `iv_rank > 75 && put_call_vol_ratio > 1.2 -> -3` | 212-213 | compound `ranking.bands[*].conditions` |
| final clamp to `[0, 100]` | 219-220 | runtime clamp after all spec scoring |

### 1.5 Blend-group semantics required for parity

The incumbent uses a 60/40 market/sector RS blend at `182-187`.

For byte identity, Sprint F must preserve three facts:

- band matching is first-match-wins per metric
- metrics with present values but no matching band still consume their
  declared group weight with a zero contribution
- metrics with unavailable values must not drag the whole group down

That last rule preserves the incumbent fallback at `185-186`:
when sector RS is unavailable, market RS receives the full effective weight.

## 2. Feature / Enrichment Inventory

### 2.1 Engine core

`src/features/engine.py:204-288`

Always-on shared loads:

- market regime: `221-226`
- options metrics: `228-229`
- event proximity: `231-232`
- sector profiles: `234-235`

Per-ticker branches:

- technical feature computation: `243`
- earnings lookup + overlap classification: `245-251`
- regime merge: `253-254`
- options merge: `256-258`
- event proximity merge: `260-261`
- sector conditioning: `263-264`
- setup classification: `271-283`

Sprint F live mapping:

- `enrichment.chain` can legitimately control the engine's sector conditioning,
  because `KNOWN_ENRICHERS` includes `sector` and `_add_sector_features(...)`
  lives here at `349-364`.
- `technicals` is represented by the function's core contract itself. The core
  technical feature calculation remains always-on in Sprint F because callers
  expect `compute_all_features(...)` to return a complete pullback feature dict.
- Options/event-proximity/earnings/setup remain legacy always-on in Sprint F.
  The current schema surface has no dedicated switches for them.

### 2.2 Data enrichment orchestrator

`src/data_enrichment/enricher.py:53-176`

Current branches:

- macro summary shared fetch: `81-88`
- fundamentals: `100-115`
- insiders: `117-136`
- news: `138-155`
- earnings signals: `157-167`

Live-repo drift vs schema registry:

- `KNOWN_ENRICHERS` at `src/platform/strategy_spec.py:49-55` is
  `{"technicals", "insider", "macro", "news", "sector"}`.
- The live enricher has no `fundamental` registry entry even though
  fundamentals are a real runtime branch.

Sprint F handling:

- `macro`, `insider`, and `news` are wired to the spec chain.
- `fundamental_summary` and `earnings_signals` remain legacy always-on to avoid
  inventing a schema alias in this sprint.
- This drift is documented and kept explicit.

### 2.3 Post-scan dispatch

`src/features/enrichment.py:22-82`

Current branches:

- `traffic_light`: `37-68`
- `event_risk`: `69-80`

These are the live consumers for:

- `post_scan.chain`
- `event_risk.quarantine_categories`

The archived Sprint F prompt placed this work inside `engine.py`. The live repo
moved it into `features/enrichment.py`, and Sprint F must wire the live helper.

## 3. Registry Alignment Check

### 3.1 Scoring metrics

`src/platform/_strategy_spec_ranking.py:38-42`

`KNOWN_SCORING_METRICS` covers the incumbent metrics used directly by
`_score_ticker(...)` and `_regime_adjustment(...)`.

Aligned:

- `trend_state`
- `relative_strength_state`
- `pullback_depth_pct`
- `dist_to_sma20_pct`
- `volume_ratio_20d`
- `iv_rank`
- `put_call_vol_ratio`
- `regime_label`
- `market_breadth_label`
- `spy_rsi_14`

Known live drift:

- `_sector_rs_score` is a live runtime field, not a validated top-level scoring
  metric. Sprint F uses a derived-metric alias in the synthetic incumbent spec.

### 3.2 Enricher / helper registries

`src/platform/strategy_spec.py:49-81`

Aligned:

- `KNOWN_POST_SCAN_HELPERS = {"traffic_light", "event_risk"}` matches
  `src/features/enrichment.py:37-80`.

Documented drift:

- `KNOWN_ENRICHERS` does not include `fundamental`, while the live orchestrator
  has a fundamentals branch at `src/data_enrichment/enricher.py:100-115`.

### 3.3 Event-risk categories

`src/platform/strategy_spec.py:61-69`

Live producer:

- `src/features/event_risk_score.py:190-320`

Current runtime can emit or infer:

- `fomc`
- `nfp`
- `cpi`
- `earnings_imminent`
- `earnings_elevated`

Other registry entries remain future-facing and are not yet emitted by the live
post-scan helper.

## 4. Fixture Plan

### 4.1 Location and format

- JSON fixtures live under `tests/platform/byte_identity/fixtures/`.
- Float serialization uses `repr()` round-trip via a sentinel object in the
  loader/dumper helper.

### 4.2 Generator

- Generator path: `scripts/platform/generate_sprint_f_fixtures.py`
- Shared helper path: `tests/platform/byte_identity/helpers.py`
- Synthetic incumbent spec id/path:
  - `strategy_id = "sprint_f_incumbent_v1"`
  - `spec_path = "synthetic://sprint_f_incumbent_v1"`

### 4.3 Dates

- Primary date: `2024-03-26`
- Fuzz dates:
  - `2024-01-16`
  - `2024-02-13`
  - `2024-03-26`
  - `2024-04-23`
  - `2024-05-21`
  - `2024-06-18`
  - `2024-07-16`
  - `2024-08-13`
  - `2024-09-10`
  - `2024-11-19`

### 4.4 Data source

- Cache root must be overridable because the clean Sprint F worktree does not
  include gitignored `data/simulation_cache/`.
- The validated canonical cache root is the original checkout:
  `C:/arcis/halcyon-lab/data/simulation_cache`.

### 4.5 Historical determinism

Fixture generation must patch the following live-time dependencies:

- `src.features.earnings.get_next_earnings_date` -> `None`
- `src.features.engine._load_options_metrics` -> `{}`
- `src.features.engine._load_event_proximity` -> reference-date-aware lookup

This keeps the fixture build offline and anchored to the requested as-of date.

## 5. Callsite Sweep

Current direct callers of the public signatures:

- `rank_universe(...)`
  - `src/evaluation/backtester.py`
  - `src/scheduler/premarket.py`
  - `src/scheduler/reports.py`
  - `src/scheduler/universe_scanner.py`
  - `src/services/recap_service.py`
  - `src/services/scan_service.py`
  - `src/services/watchlist_service.py`
- `compute_all_features(...)`
  - same broad scanner / backtester / service surface
- `enrich_features(...)`
  - `src/scheduler/reports.py`
  - `src/scheduler/universe_scanner.py`
  - `src/services/scan_service.py`

Sprint F adds optional `strategy` parameters only. No legacy caller is changed.

## 6. Test Plan

New files:

- `tests/platform/byte_identity/__init__.py`
- `tests/platform/byte_identity/conftest.py`
- `tests/platform/byte_identity/helpers.py`
- `tests/platform/byte_identity/test_sprint_F_ranker.py`
- `tests/platform/byte_identity/test_sprint_F_engine.py`

Existing suites that must stay green:

- `tests/test_ranking.py`
- `tests/test_features.py`
- `tests/test_features_enrichment.py`
- `tests/test_enrichment.py`
- `tests/platform/specs/test_schema_c1_refinements.py`
- `tests/platform/specs/test_schema_final_blocks.py`
- `tests/platform/test_find_candidates.py`

## 7. Watch List

Documented live-repo risks:

- `_sector_rs_score` is a runtime-only field and not a registry-listed scoring
  metric.
- `fundamental_summary` has no schema registry alias in `KNOWN_ENRICHERS`.
- Post-scan dispatch moved to `src/features/enrichment.py`; wiring the older
  `engine.py` boundary would be wrong on current `main`.
