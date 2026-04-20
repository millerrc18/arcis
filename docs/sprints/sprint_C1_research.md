# Sprint C.1 Pass 2 — Research

**Branch:** `feat/schema-c1-ranker-gaps`
**Issue:** #569
**Date:** 2026-04-20
**Builds on:** `docs/sprints/sprint_C1_evaluation.md` (Pass 1, commit `decfa42`)
**Prerequisites:** Operator resolutions to the 4 Pass 1 flags (received 2026-04-20).

-----

## Section 0 — Operator resolutions (lock-in)

The 4 Pass 1 open questions were resolved by the operator on 2026-04-20. Pass 2 locks them in as design constraints for Pass 3 implementation.

| # | Question | Resolution | Pass 1 section affected | Pass 2 work |
|---|---|---|---|---|
| 1 | Item 6 shape (band-grammar vs regime-keyed multiplier) | **Band-grammar + clamp** (Pass 1 proposal). **PLUS: add `KNOWN_REGIME_LABELS` frozenset (5-label, string-valued)** to Item 6 scope. Document alongside `KNOWN_REGIME_KEYS` that the two registries are intentionally separate — KEYS for threshold dispatch, LABELS for score adjustment. **+10 LOC accepted.** | §6 | Confirm enum contents from runtime source. See §1.5 below. |
| 2 | Item 9 scope (schema vs runtime edit vs defer) | **Option 9A: schema docstring note only, 5 LOC.** Do not touch `event_risk_score.py` or `MACRO_EVENT_TYPES`. | §9 | No runtime verification needed — resolution is schema-only. See §1.8. |
| 3 | Item 5 fallback semantics (accept gap vs add `normalize_on_missing`) | **Accept gap.** Do NOT add `normalize_on_missing`. Document as **Sprint F known divergence** in the Pass 1 eval doc. Sprint F will catch it via byte-identity fuzz and STOP → file issue at that time. | §5.5 | Confirm fallback is reachable from live call paths (so we know Sprint F will hit it). See §1.4. |
| 4 | `packet_worthy` legacy alias (keep vs hard-rename) | **Hard-rename. No legacy alias.** Pass 2 picks the new name by matching runtime variable naming. Suggested: `min_score`. | §1 | Pick new name from ranker source. See §1.1. |

**Updated budget: 218/400 LOC** added to `strategy_spec.py` (208 + 10 for `KNOWN_REGIME_LABELS`). Still under the 650-line guardrail.

**Pass 1 doc update:** Section 5.5 updated with the Sprint F known divergence note (bundled into this Pass 2 commit per user instruction).

-----

## Section 1 — Runtime verification per Pass 1 item

Empirical check of each item's YAML shape and registry contents against the actual runtime code on `origin/main` at `cb69485`.

### 1.1 Item 1 — `packet_worthy` rename target

**Source examined:** `src/ranking/ranker.py` (full file).

Naming usage inventory (all occurrences of `packet_worthy` in ranker.py):

| Location | Form | Role |
|---|---|---|
| ranker.py:18-24 (REGIME_THRESHOLDS values) | `"packet_worthy": 40` (dict key, int value) | In-memory threshold per regime |
| ranker.py:40 (bootcamp path) | `"packet_worthy": bootcamp_cfg.get("qualification_threshold", 40)` | Bootcamp dict key, int |
| ranker.py:51 (config read) | `ranking_cfg.get("packet_worthy_threshold", 70)` | **Config YAML key** — note: different name in config vs memory |
| ranker.py:62 (regime override) | `base["packet_worthy"] = regime_overrides["packet_worthy"]` | In-memory dict key |
| ranker.py:249 (threshold load) | `packet_threshold = thresholds["packet_worthy"]` | **Local variable** — `packet_threshold`, not `packet_worthy_threshold` |
| ranker.py:281 (qualification check) | `if score >= packet_threshold:` | Comparison value |
| ranker.py:282 (qualification label) | `qualification = "packet_worthy"` | String label, not threshold |
| ranker.py:286 | `qualification = "packet_worthy"` | Same |

**Observations:**

1. The name `packet_worthy` serves **two distinct roles** in ranker.py today:
   - **Threshold value** (int): in `REGIME_THRESHOLDS`, `_load_thresholds` output dict, and `thresholds["packet_worthy"]` reads. Semantic: the minimum score required to qualify.
   - **Qualification label** (string literal): the result assigned to `qualification` when a candidate meets the threshold, and the key in `get_top_candidates` output dict at ranker.py:328. Semantic: "this candidate qualifies as packet-worthy" (distinct from the threshold value).

2. Existing naming is **already inconsistent** across the codebase:
   - Config YAML key: `packet_worthy_threshold` (long form)
   - In-memory dict key: `packet_worthy` (short form, same word as the label — confusing)
   - Local variable: `packet_threshold` (yet a third form)

3. The schema validator's `_validate_position_sizing:279` assertion (`isinstance(rval.get("packet_worthy"), bool)`) was written against the short-form name with the wrong type. Renaming is a compound fix.

**Candidate names for the YAML field:**

| Candidate | Pros | Cons |
|---|---|---|
| **`min_score`** (user suggestion) | Concise; matches `if score >= X` usage pattern; contextually clear inside `regimes[KEY]`; disambiguates from the `"packet_worthy"` qualification label | Diverges from existing `packet_worthy_threshold` config key (but config key can be migrated separately in a future sprint if desired) |
| `packet_worthy_threshold` | Matches existing config key | Verbose; `threshold` suffix is redundant in context; preserves the naming-collision with the qualification label |
| `packet_threshold` | Matches existing local var; shorter than option 2 | Still contains `packet` word that ties to the `"packet_worthy"` label semantically |
| `qualification_threshold` | Matches existing bootcamp config key | Verbose; introduces a fourth naming form |

**Pass 2 recommendation: `min_score`.**

Rationale:
- The YAML field is a **new field introduced by Sprint C.1** (replacing the broken bool-typed `packet_worthy`). No backward compat constraint from existing specs (neither `lazy_prices_v1` nor `post_audit_ruleset_v1` declares this field — confirmed in §4).
- `min_score` reads naturally in context: `regimes.BULL_LOW_VOL.min_score: 40` → "minimum score in the BULL_LOW_VOL regime is 40."
- Aligns with the local variable `packet_threshold` semantically (both name "the threshold value") without inheriting the verbose `_threshold` suffix or the ambiguous `packet_worthy` name.
- The qualification label `"packet_worthy"` remains as a string literal elsewhere in ranker.py — untouched. No naming collision.
- **Sprint F will dispatch `spec.position_sizing.regimes[regime_key].min_score` → runtime comparison against ticker score.** Clean mapping.

Future sprint (not C.1) may want to rename the in-memory dict key `packet_worthy` → `min_score` in `_load_thresholds` output for consistency with the spec. That's a separate tech-debt item; Sprint C.1 scope stops at the YAML boundary.

### 1.2 Item 2 — `KNOWN_POST_SCAN_HELPERS` runtime names

**Source examined:** `src/features/enrichment.py` (full file).

Verification: `attach_post_scan_features` (enrichment.py:22-82) does NOT string-dispatch. It hardcodes two function imports:

```python
# enrichment.py:39-40 — Traffic Light
from src.features.traffic_light import compute_traffic_light
tl = compute_traffic_light(spy, vix=vix_value)

# enrichment.py:70-75 — Event Risk
from src.features.event_risk_score import attach_event_risk_scores
attach_event_risk_scores(features, **kwargs)
```

Feature dict writes that downstream code reads:
- `feat["traffic_light"]`, `feat["traffic_light_multiplier"]`, `feat["regime_label"]` (from traffic_light path)
- `feat["market_event_risk"]`, `feat["event_risk_score"]`, `feat["event_risk_components"]`, `feat["event_risk_multiplier"]` (from event_risk path)

**Confirmed canonical names for the registry:**

```python
KNOWN_POST_SCAN_HELPERS = frozenset({"traffic_light", "event_risk"})
```

These are **conceptual names** for the two function invocations. The runtime has no string-dispatch wiring yet (Sprint F's job). Pass 1 §2 shapes stand.

### 1.3 Item 3 + Item 4 — Band shape extensions (no runtime yet)

No runtime dispatch on `ranking.bands` exists yet (Sprint F's target). Pass 1 §3 and §4 YAML shapes stand as-designed. Pass 3 implements the validators without any corresponding runtime consumer this sprint.

### 1.4 Item 5 — sector_rs None fallback reachability

**Source examined:** `src/ranking/ranker.py:182-187, 223-300` plus the callers list from the module docstring at line 3.

Fallback trigger path (ranker.py:182-187):

```python
sector_rs_score = _as_float(features.get("_sector_rs_score"))
if sector_rs_score is not None:
    combined_rs = 0.6 * market_rs_score + 0.4 * sector_rs_score
else:
    combined_rs = market_rs_score  # FALLBACK: market-only (weight 1.0, not 0.6)
```

`_sector_rs_score` is set at ranker.py:259 — ONLY when ALL of:

1. `sector_etf_features` parameter is not None (line 253: `if sector_etf_features:`)
2. Ticker has a sector ETF mapping via `get_sector_etf(ticker)` (line 255)
3. ETF is in `sector_etf_features` dict (line 256)
4. `_compute_sector_rs` returns non-None (line 258 — returns None at ranker.py:112 if `sector_ohlcv` is None)

`rank_universe` signature (ranker.py:223-224): `sector_etf_features` is optional, defaults to `None`.

**Callers of `rank_universe`** (from docstring at ranker.py:3):
- `evaluation.backtester`
- `scheduler.premarket`
- `scheduler.watch`
- `services.recap_service`
- `services.scan_service`
- `services.watchlist_service`
- `training.historical_scanner`

**Reachability conclusions:**

- Any caller that does NOT pass `sector_etf_features` triggers the fallback for **every ticker** on that call. This is the default path when sector ETF data isn't pre-loaded.
- Any caller that DOES pass sector data but has a ticker without a sector-ETF mapping (e.g., newly-added tickers, non-standard symbols) triggers the fallback **for those specific tickers**.
- Any caller where `_compute_sector_rs` returns None because `sector_ohlcv` lookup is empty (e.g., during data-outage periods) triggers the fallback.

**Conclusion: the fallback is not just reachable — it is likely a common path** during normal operation. Sprint F's byte-identity fuzz will hit it on the first primary fixture date (2024-03-26) unless the golden fixture is generated with pre-loaded sector ETF data for ALL S&P 100 tickers. Even then, the 10-date fuzz (2024-01-16 through 2024-11-19) spans enough calendar time that at least one date will see a ticker with missing sector data.

**Per user resolution: Sprint F WILL observe byte-identity fuzz failure on the fallback path. That triggers the plan's STOP discipline → file issue for a C.2 (or similar) sprint that adds `normalize_on_missing` or equivalent fallback declaration.** Sprint C.1 deliberately defers this.

### 1.5 Item 6 — `KNOWN_REGIME_LABELS` enum

**Source examined:** `src/features/regime.py:161-170`.

Verified enum contents (single production point):

```python
# regime.py:161-170 — compute_market_regime() only write site for regime_label
is_uptrend = market_trend in ("strong_uptrend", "uptrend")
is_downtrend = market_trend in ("strong_downtrend", "downtrend")
is_volatile = volatility_regime in ("elevated", "extreme")

if is_uptrend and not is_volatile:
    regime_label = "calm_uptrend"
elif is_uptrend and is_volatile:
    regime_label = "volatile_uptrend"
elif is_downtrend and not is_volatile:
    regime_label = "calm_downtrend"
elif is_downtrend and is_volatile:
    regime_label = "volatile_downtrend"
else:
    regime_label = "transitional"
```

**Complete 5-label set (locked):**

```python
# strategy_spec.py (Sprint C.1 Item 6) — NEW
# KNOWN_REGIME_LABELS is INTENTIONALLY SEPARATE from KNOWN_REGIME_KEYS:
# - KNOWN_REGIME_KEYS  = 7-label set (BULL_LOW_VOL..CRISIS), used by
#                        position_sizing.regimes[] (threshold dispatch)
#                        via classify_regime() in regime.py:188-249.
# - KNOWN_REGIME_LABELS = 5-label set (calm_uptrend..transitional), used by
#                         ranking.adjustments compound conditions on
#                         `regime_label` metric, produced by
#                         compute_market_regime() in regime.py:161-170.
# Both are legitimate; both are used at runtime. Do not unify without
# coordinating with ranker port (#564 Sprint F).
KNOWN_REGIME_LABELS = frozenset({
    "calm_uptrend",
    "volatile_uptrend",
    "calm_downtrend",
    "volatile_downtrend",
    "transitional",
})
```

**Cross-reference verification** (from grep output):
- `tests/test_features_enrichment.py:58, 76` — test assertions on `regime_label` values match exactly (`volatile_uptrend`, `calm_downtrend`)
- `tests/test_mr_scan_service.py:87` — test fixture with `calm_uptrend`
- `regime.py:214, 238` — these are READS of the upstream-written value (in `classify_regime`), not new label producers

No other runtime source produces `regime_label` strings. The 5-label set is authoritative.

**Validator scope for KNOWN_REGIME_LABELS:**

Applies when a `conditions[i].metric == "regime_label"` (in `ranking.bands` Item 4 compound form or `ranking.adjustments` Item 6). Threshold string value must be in the 5-label set. Operator must be `==` or `!=` (other operators don't make sense on labels).

Symmetric validation for other categorical metrics (`trend_state`, `relative_strength_state`, `market_breadth_label`) is **out of C.1 scope** — user resolution is regime labels only. See §3.4 for why this is flagged but deferred.

### 1.6 Item 7 — `derived_metrics` supported operations

**Source examined:** `src/ranking/ranker.py:105-147` (`_compute_sector_rs`).

Ops required by incumbent:

- **`subtract`**: `excess[period] = ticker_return[period] - sector_return[period]` (lines 127-131). Called 3× for the three time periods.
- **`weighted_sum`**: `weighted_excess = 0.20 * excess["1m"] + 0.50 * excess["3m"] + 0.30 * excess["6m"]` (lines 133-137). Called 1×.

No other operations. `_compute_sector_rs`'s final threshold-banding (lines 140-147) is captured by `ranking.bands` with numeric ranges on the `weighted_sector_excess` derived metric name — does NOT require a third `range_band` operation (separation of concerns: derived_metrics emit scalars, bands score them).

**Locked: `subtract` + `weighted_sum` only.** Per user resolution 2026-04-20.

Future additions (NOT in C.1): if a future spec needs e.g. `divide`, `multiply`, `max`, `min`, or a conditional operation, open a separate sprint. Pass 1 §7 schema is extensible (adding a new op is ~5 LOC per op in `_validate_derived_metrics`).

### 1.7 Item 8 — `KNOWN_SCORING_METRICS` seed (full enumeration)

**Sources examined:** `engine.py` (full), `regime.py` (full), `ranker.py` (full).

#### 1.7.1 Complete feature pipeline inventory

All `feat[...]` write sites across the pipeline produce these distinct keys:

**From `compute_features` (engine.py:177-201) — 21 keys:**

`ticker`, `current_price`, `sma_50`, `sma_200`, `price_vs_sma50_pct`, `price_vs_sma200_pct`, `sma50_slope`, `sma200_slope`, `trend_state`, `rs_vs_spy_1m`, `rs_vs_spy_3m`, `rs_vs_spy_6m`, `relative_strength_state`, `pullback_depth_pct`, `atr_14`, `atr_pct`, `dist_to_sma20_pct`, `volume_ratio_20d`, `earnings_date`, `hold_overlaps_earnings`, `days_to_earnings`, `event_risk_level`

**From `compute_market_regime` (regime.py:172-185) — 12 keys:**

`market_trend`, `volatility_regime`, `vix_proxy`, `spy_rsi_14`, `spy_above_sma50`, `spy_above_sma200`, `spy_sma50_slope`, `spy_drawdown_from_high`, `spy_20d_return`, `market_breadth_pct`, `market_breadth_label`, `regime_label`

**From `_load_options_metrics` (engine.py:307-312) — 5 keys:**

`iv_rank`, `put_call_vol_ratio`, `put_call_oi_ratio`, `iv_skew`, `unusual_options_activity`

**From `compute_sector_context` (regime.py:297-303) — 4 keys:**

`sector`, `sector_rs_rank`, `sector_avg_score`, `sector_peer_count`

**From `_add_sector_features` (engine.py:354-364) — 4 keys (partially overlapping with above):**

`sector` (overridden), `sector_pullback_depth`, `sector_recovery_speed`, `sector_key_factors`

**From `_load_event_proximity` (engine.py:325-330) — 4 keys:**

`event_proximity_type`, `event_proximity_days`, `event_proximity_desc`, `events_within_3d`

**From earnings update (engine.py:246-251) — 4 keys (override initial null-set from compute_features):**

`earnings_date`, `hold_overlaps_earnings`, `days_to_earnings`, `event_risk_level`

**From setup_classifier (engine.py:272-283) — 3 keys:**

`setup_type`, `setup_confidence`, `setup_desk`

**Internal/derived at ranker stage:**

`_sector_rs_score` (ranker.py:259), `_score` (ranker.py:265)

**Total distinct feature pipeline surface: ~57 keys** (some duplicate across write paths).

#### 1.7.2 Scoring-relevant subset (C.1 seed set)

Metrics that actually participate in `_score_ticker` + `_regime_adjustment`:

| Metric | Type | Source | Used in |
|---|---|---|---|
| `trend_state` | categorical (5-val) | `_classify_trend` engine.py:57-68 | `_score_ticker:170-176` |
| `relative_strength_state` | categorical (5-val) | `_classify_relative_strength` engine.py:78-99 | `_score_ticker:179-180` |
| `pullback_depth_pct` | numeric | engine.py:162 | `_score_ticker:190-194` |
| `dist_to_sma20_pct` | numeric | engine.py:131 | `_score_ticker:197-199` |
| `volume_ratio_20d` | numeric | engine.py:175 | `_score_ticker:202-204` |
| `iv_rank` | numeric | `_load_options_metrics` engine.py:307 | `_score_ticker:207, 210, 212` |
| `put_call_vol_ratio` | numeric | `_load_options_metrics` engine.py:308 | `_score_ticker:208, 212` |
| `regime_label` | categorical (5-val) | `compute_market_regime` regime.py:162-170 | `_regime_adjustment:74` |
| `market_breadth_label` | categorical (3-val) | `compute_market_regime` regime.py:149-153 | `_regime_adjustment:75` |
| `spy_rsi_14` | numeric | `compute_market_regime` regime.py:176 | `_regime_adjustment:76, 94, 96` |

**10 metrics. Locked for Sprint C.1 seed:**

```python
KNOWN_SCORING_METRICS = frozenset({
    "trend_state",
    "relative_strength_state",
    "pullback_depth_pct",
    "dist_to_sma20_pct",
    "volume_ratio_20d",
    "iv_rank",
    "put_call_vol_ratio",
    "regime_label",
    "market_breadth_label",
    "spy_rsi_14",
})
```

At validation time, the effective known set becomes `KNOWN_SCORING_METRICS ∪ derived_metric_names_from_item_7`, per Pass 1 §8.4.

#### 1.7.3 Metrics present in feature pipeline but NOT in seed

47 keys exist in the feature pipeline that aren't scored today. A few notable ones that could plausibly be added in a future sprint:

| Metric | Type | Potential use |
|---|---|---|
| `atr_pct`, `atr_14` | numeric | Volatility-based sizing / stop distance bands |
| `price_vs_sma50_pct`, `price_vs_sma200_pct` | numeric | Trend depth bands beyond `trend_state` categorical |
| `market_trend`, `volatility_regime` | categorical | Alternative regime vocabulary |
| `vix_proxy` | numeric | Absolute volatility threshold bands |
| `spy_20d_return`, `spy_drawdown_from_high` | numeric | Market context bands |
| `sector_rs_rank` | categorical | Sector-relative position bands |
| `iv_skew`, `put_call_oi_ratio` | numeric | Additional options signals |
| `setup_type`, `setup_confidence` | categorical + numeric | Setup-classifier integration |
| `event_risk_score` | numeric | Pre-computed event-risk integer (0-10) — alternative to quarantine_categories approach |

**All intentionally deferred.** Adding any requires a new spec that uses the metric + registry expansion. Not Sprint C.1 territory.

### 1.8 Item 9 — Resolution lock-in

**User resolution: Option 9A only.** No code changes to `src/features/event_risk_score.py` or `MACRO_EVENT_TYPES`.

Docstring change to `strategy_spec.py:40-41`:

```python
# strategy_spec.py (Sprint C.1 Item 9) — updated comment above KNOWN_EVENT_RISK_CATEGORIES
# Union of sprint-prompt earnings categories + MACRO_EVENT_TYPES
# (event_risk_score.py, normalized) + KNOWN_EVENTS labels (known_events.py).
# CASING CONVENTION (Sprint C.1): all category names are lowercase with
# underscores. Runtime dispatch MUST lowercase event_type before matching
# against this set. Current runtime already emits lowercase via the
# `components` dict in event_risk_score.py (lines 201-207); MACRO_EVENT_TYPES
# uppercase is internal CSV/DB input-normalization only, invisible to specs.
```

Plus the Pass 3 test at Pass 1 §9.5 guards against future casing drift.

**No runtime changes.** Anti-goal preserved.

-----

## Section 2 — Runtime dependencies on bug behaviors

Verification that fixing #567 (`packet_worthy` type) and #568 (`KNOWN_POST_SCAN_HELPERS` contents) does not break existing runtime code.

### 2.1 #567 — `packet_worthy` type dependency

**Grep scope:** all `*.py` files.

All `packet_worthy` occurrences fall into 4 categories:

1. **Database column name** (`scan_metrics.packet_worthy`, integer count of packet-worthy candidates per scan run):
   - `scripts/weekly_review.py:97, 182, 190`
   - `src/schema/registry.py` (column definition)
   - Unrelated to `position_sizing.regimes[KEY].packet_worthy`.

2. **Qualification label** (string literal `"packet_worthy"`, used as dict key in rank_universe output):
   - `src/ranking/ranker.py:282, 286, 320, 322, 328` — label assignment + output dict key
   - `src/services/scan_service.py`, `src/evaluation/backtester.py`, and many others consume this dict key
   - **Not affected by the rename.** The rename changes only the YAML field name, not the qualification label.

3. **In-memory threshold dict key** (ranker.py: `thresholds["packet_worthy"]`):
   - `src/ranking/ranker.py:17-25, 40, 62, 249`
   - This is what the rename WOULD change if we extended to the in-memory dict. Sprint C.1 scope stops at the YAML boundary — in-memory dict key stays `packet_worthy` for this sprint. Future tech-debt sprint can align.

4. **Schema validator assertion** (the buggy path):
   - `src/platform/strategy_spec.py:279` — the sole site that treats `packet_worthy` as `bool`
   - **Only caller that would fail a rename with incorrect type:** `validate_spec` → `_from_dict` → `load_spec_from_yaml`. Currently only test fixtures exercise this path.

**Grep for tests asserting `packet_worthy: bool` or `packet_worthy: True/False`:**

Scanning test files for `packet_worthy` usage:
- `tests/test_backtester.py:68, 123` — uses `"packet_worthy": [...]` (qualification label dict key). Does NOT assert on `position_sizing.regimes[KEY].packet_worthy` type.
- No other test uses `packet_worthy` in a `position_sizing` spec context.

**Conclusion for #567: hard-rename `packet_worthy` → `min_score` in the YAML schema (field name + type) is safe for all known runtime code paths.** Only the schema validator itself changes. No production code depends on the bool-type bug behavior.

**Possible Sprint D/E test cleanups** (Pass 3 audits):
- `tests/platform/specs/test_schema_d*.py` (if exists) — Sprint D introduced the `regime_adaptive` sizing; any test asserting on the bool path must be updated.
- Same for any Sprint E test that touches `position_sizing.regimes`.

### 2.2 #568 — `KNOWN_POST_SCAN_HELPERS` contents + strict flip

**Grep scope:** `classifier`, `filter_duplicates`, `post_scan.chain`, `post_scan_helpers` across `*.py`.

All meaningful occurrences:

1. **Schema definition:** `src/platform/strategy_spec.py:39, 60` — the misleading frozenset + the `_LIST_BLOCKS` `strict=False` entry.

2. **Existing tests that use OLD names:**
   - `tests/platform/specs/test_schema_final_blocks.py:79` — `spec["post_scan"] = {"chain": ["classifier", "filter_duplicates"]}` with `ok, errors = validate_spec(spec); assert ok` (expects warn-only pass). **Will HARD FAIL after Sprint C.1 with strict=True + new frozenset contents** unless updated.
   - `tests/platform/specs/test_schema_final_blocks.py:184` — `spec["post_scan"] = {"chain": ["classifier"]}` with similar expectation. **Will HARD FAIL.**

3. **Unrelated `classifier` usage** (different semantic — neural network / ML classifier):
   - `src/features/setup_classifier.py` (the MODULE name)
   - `src/training/leakage_detector.py`, `src/training/audit/pass_c_leakage.py` (TF-IDF classifiers)
   - `llama.cpp/convert_hf_to_gguf.py` (external vendor code; out of scope)
   - All unrelated to `post_scan.chain`.

**Pass 3 action items for Item 2 implementation:**

- Update `tests/platform/specs/test_schema_final_blocks.py:79` and `:184` to use new names `["traffic_light", "event_risk"]`.
- Assertion messaging may change from "accepts with warning" to "accepts cleanly" under strict=True.
- Add a new rejection test: post_scan.chain with `["classifier"]` must now FAIL validation (regression guard for the strict flip).

**No runtime code depends on the old names being accepted.** Safe to flip.

-----

## Section 3 — Categorical-value validation scope decision

User resolution specifies `KNOWN_REGIME_LABELS` for `regime_label` metric only. Pass 2 enumerates the other categorical metrics and defers them explicitly.

### 3.1 Symmetric validation candidates (deferred)

| Metric | Producer | Distinct values |
|---|---|---|
| `trend_state` | `_classify_trend` engine.py:57-68 | `{strong_uptrend, uptrend, neutral, downtrend, strong_downtrend}` (5) |
| `relative_strength_state` | `_classify_relative_strength` engine.py:78-99 | `{strong_outperformer, outperformer, neutral, underperformer, strong_underperformer}` (5) |
| `market_breadth_label` | `compute_market_regime` regime.py:149-153 | `{healthy, narrowing, weak}` (3) |

Each of these could have its own `KNOWN_*_LABELS` frozenset and per-metric threshold validation. **Deliberately not in C.1 scope** per user resolution.

### 3.2 Deferral cost

- A spec declaring `ranking.bands` with `metric: trend_state, category: "strogn_uptrend"` (typo) will pass validation (string non-empty) but produce zero-score matches at runtime. Same silent-failure class as `KNOWN_SCORING_METRICS` protects against for the metric name itself.
- Sprint F or a future C.2 can add symmetric validation. Each additional registry is ~10 LOC (frozenset + validator hook in `_validate_band_condition`).

### 3.3 Recommendation

Flag for Sprint F or C.2:

> Consider adding `KNOWN_TREND_STATES`, `KNOWN_RS_STATES`, `KNOWN_MARKET_BREADTH_LABELS` frozensets with symmetric validation on `conditions[].threshold` when `metric` matches a categorical metric name. ~30 LOC total. Useful for typo detection at spec-authoring time.

**Not blocking Sprint F.** Sprint F can ship without this; typos in categorical thresholds manifest as zero-score bands, which byte-identity fuzz catches (differently-valued input → same score path as "no match").

-----

## Section 4 — Backward compat empirical verification

**Two production specs on main** (confirmed via `glob src/platform/specs/*.yaml`): `lazy_prices_v1.yaml` and `post_audit_ruleset_v1.yaml`. Both read in full during Pass 2.

### 4.1 `lazy_prices_v1.yaml` (72 lines)

Full structure mapped to C.1 items:

| C.1 item | Touches lazy_prices_v1? |
|---|---|
| 1 — `packet_worthy` → `min_score` | **No.** `position_sizing.method` is `fixed_pct_equity`; no `regimes` block. |
| 2 — `KNOWN_POST_SCAN_HELPERS` fix + strict=True | **No.** No `post_scan` block. |
| 3 — categorical bands | **No.** No `ranking` block. |
| 4 — compound AND bands | **No.** No `ranking` block. |
| 5 — weighted bands | **No.** No `ranking` block. |
| 6 — `ranking.adjustments` | **No.** No `ranking` block. |
| 7 — `ranking.derived_metrics` | **No.** No `ranking` block. |
| 8 — `KNOWN_SCORING_METRICS` | **No.** No `ranking.bands` to validate. |
| 9 — event-risk docstring | **No.** No `event_risk.quarantine_categories` block. Also uses `entry.event_exclusion.categories` (a different code path, not affected). |

**Verdict: zero impact. Loads unchanged post-C.1.**

### 4.2 `post_audit_ruleset_v1.yaml` (100 lines)

| C.1 item | Touches post_audit_ruleset_v1? |
|---|---|
| 1 — `packet_worthy` → `min_score` | **No.** `position_sizing.method` is `fixed_pct_equity`. |
| 2 — `KNOWN_POST_SCAN_HELPERS` fix + strict=True | **No.** No `post_scan` block. |
| 3-8 — ranking changes | **No.** No `ranking` block. |
| 9 — event-risk docstring | **No direct effect.** Spec uses `entry.event_exclusion.categories: [Trade Policy]`. "Trade Policy" is NOT in `KNOWN_EVENT_RISK_CATEGORIES` but `entry.event_exclusion` validator (strategy_spec.py:110-119) only checks list-of-strings, not ref-against-known-set. Passes unchanged. |

**Observation on `"Trade Policy"` category:** the spec uses the GICS sector-style capitalized string, while `KNOWN_EVENT_RISK_CATEGORIES` uses lowercase_with_underscores (`tariff_announcement`, `export_controls`, etc.). These are different namespaces — `entry.event_exclusion.categories` is a free-form list (for matching against `known_events.py` at runtime), `event_risk.quarantine_categories` is a registry-validated list. No conflict.

**Verdict: zero impact. Loads unchanged post-C.1.**

### 4.3 No other production specs

`glob src/platform/specs/*.yaml` returned exactly 2 files. Total production surface: 2 specs, both unaffected.

-----

## Section 5 — Pass 3 implementation handoff

### 5.1 Files to modify

- **`src/platform/strategy_spec.py`** — all 9 items. Estimated +218 LOC net (from 393 to ~611).
- **`tests/platform/specs/test_schema_c1_refinements.py`** — NEW file, ~25 tests (20 required + 5 bonus) per Pass 1 §11.2.
- **`tests/platform/specs/test_schema_final_blocks.py`** — 2 line updates (§2.2 above) plus potentially a new rejection test for strict post_scan.chain.

### 5.2 Commit plan

Pass 3 = single commit per user instruction:
- Title: `feat(#569): Pass 3 — Sprint C.1 schema refinement (9 items)`
- Atomic: validator changes + tests ship together (tests gate the validator behavior).
- Message body: per-item summary with LOC delta + test count.

### 5.3 Validation checklist (Pass 3)

Before Pass 3 commits:

1. `python -m pytest tests/platform/specs/` green (includes C.1 new tests + updated Sprint E tests).
2. `python -m pytest tests/` full suite: no regression from 1339 baseline per CLAUDE.md.
3. `wc -l src/platform/strategy_spec.py` ≤ 650.
4. `python -c "from src.platform.strategy_spec import load_spec; load_spec('lazy_prices_v1'); load_spec('post_audit_ruleset_v1')"` runs clean.
5. Grep confirms no lingering `packet_worthy: bool` assertions in the test tree.
6. `CHANGELOG.md` [Unreleased] updated per prompt's Documentation section.
7. `MASTER.md` #530 chain progress line updated (slot 6-a).
8. `SPRINT_FGH_PLAN.md` updated to reflect F/G/H shift to 7/8/9 numbering.

### 5.4 Exact implementation order (Pass 3 recommended)

Items can be implemented in any order, but this sequence minimizes merge-conflict risk within a single file:

1. **Item 9** (docstring note, 5 LOC) — smallest edit, lowest risk, zero logic change.
2. **Item 1** (`packet_worthy` → `min_score`, 6 LOC) — self-contained rename.
3. **Item 2** (`KNOWN_POST_SCAN_HELPERS` fix + strict flip, 2 LOC) — self-contained.
4. **Item 8** (`KNOWN_SCORING_METRICS` frozenset + signature refactor, ~18 LOC) — must land before Items 3/4/6 (which USE the set).
5. **Item 3** (categorical bands in `_validate_bands`, ~25 LOC).
6. **Item 4** (compound conditions + `_validate_band_condition`, ~45 LOC).
7. **Item 5** (weight + blend_group via `_validate_band_weights`, ~25 LOC).
8. **Item 6** (`ranking.adjustments` via `_validate_adjustments` reusing `_validate_bands`, ~25 LOC) — must land after Items 3, 4, 8 (reuses their grammar).
9. **Item 6 addendum** (`KNOWN_REGIME_LABELS` frozenset + validation hook in `_validate_band_condition`, ~10 LOC).
10. **Item 7** (`ranking.derived_metrics` with DAG check, ~55 LOC) — must land before final run of Item 8's metric-set union.

### 5.5 Post-Pass-3 gate

Push `feat/schema-c1-ranker-gaps` to origin after Pass 2 per user instruction. Operator reviews Pass 1 + Pass 2 docs + pushed branch state before Pass 3 starts.

-----

## Section 6 — Open items carried to Pass 3

**None.** All 4 Pass 1 flags resolved by operator 2026-04-20. All Pass 2 verification targets completed. All items have concrete YAML shapes, validator pseudocode, test plans, and LOC estimates.

Pass 3 implements the locked design. If Pass 3 surfaces any issue (e.g., a schema edge case, or a test fixture that needs more than the 2 lines called out in §2.2), Pass 3 STOPs per the plan's discipline and reports rather than scope-creeping.

-----

## Section 7 — What Pass 2 deliberately did not do

- **No code changes.** This is Pass 2 research; Pass 3 implements.
- **No new schema proposals.** Stayed within Pass 1's 9-item envelope plus the operator's `KNOWN_REGIME_LABELS` addition.
- **No test files created.** Pass 3 creates `tests/platform/specs/test_schema_c1_refinements.py`.
- **No categorical-value registries for non-regime metrics.** `KNOWN_TREND_STATES`, `KNOWN_RS_STATES`, `KNOWN_MARKET_BREADTH_LABELS` are out of scope per user resolution. Flagged for Sprint F or C.2 in §3.
- **No changes to `src/features/event_risk_score.py` or `MACRO_EVENT_TYPES`.** Anti-goal preserved per Option 9A.
- **No in-memory dict key renames in `ranker.py`.** The rename stops at the YAML boundary — `thresholds["packet_worthy"]` stays. In-memory rename is future tech-debt.
- **No Sprint F work.** Sprint F resumes on `feat/port-ranker-to-spec` (parked at `53dee07`) after C.1 merges + #570 (2024 OHLCV) resolves.
