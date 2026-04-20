# Sprint C.1 Pass 1 — Evaluation

**Branch:** `feat/schema-c1-ranker-gaps`
**Issue:** #569
**Part of:** #530 chain — slot 6-a (F/G/H shift to 7/8/9)
**Date:** 2026-04-20
**Prerequisites:** Sprints A-E merged (origin/main at `cb69485`)
**Blocks:** #564 (Sprint F, parked at `53dee07` on `feat/port-ranker-to-spec`)

-----

## TL;DR

- **9 items designed** with exact YAML shapes, per-item test plans, and per-item LOC estimates.
- **3 required decisions made** (blend_group YES; derived ops = `subtract` + `weighted_sum`; `post_scan.chain` strict=True post-fix).
- **2 items flagged for operator resolution before Pass 2:**
  - **Item 6 shape disagreement.** Prompt example describes a regime-keyed multiplier table; actual `_regime_adjustment` (ranker.py:72-102) is a compound-band scorer with a `[-10, +10]` clamp using the 5-label `regime_label` (not the 7-label `KNOWN_REGIME_KEYS`). Pass 1 proposes reusing the band grammar (Items 3-5) + a `clamp` field. Flagged because this deviates from the prompt's YAML example.
  - **Item 9 anti-goal tension.** Scope directs an edit to `src/features/event_risk_score.py:25` (`MACRO_EVENT_TYPES`), but anti-goal forbids runtime changes. Verified that the "casing drift" is internal-only (CSV normalization layer) — runtime output is already lowercase matching the schema. Pass 1 proposes narrowing Item 9 to a schema docstring note. Flagged because this reduces the scope from the prompt's text.
- **Line budget: ~222 / 400 lines** added to `strategy_spec.py`. Well under budget.
- **Test count: ~22 tests** — meets the ~20 minimum in the prompt.
- **No 10th item surfaced.** No scope creep. Pass 1 stays within the 9-item prompt envelope.
- **No spec breakage expected** — `lazy_prices_v1.yaml` has no `ranking` block; `post_audit_ruleset_v1.yaml` doesn't declare `position_sizing.regimes`. Pass 2 will confirm this empirically.

### Decisions table

| # | Decision point | Choice | Rationale (brief) |
|---|---|---|---|
| 2 | `post_scan.chain` strict vs warn post-fix | **strict=True** | No current specs use `post_scan.chain`; flipping to strict now is zero-breakage and makes future drift hard-fail. Per prompt's operator vote. |
| 5 | `blend_group` tag for weighted bands | **YES, required** | Without explicit grouping, weight semantics are ambiguous (which bands sum?). `weight` alone is under-specified. See Section 5.4. |
| 7 | Supported operations in `derived_metrics` | **`subtract` + `weighted_sum` only** | Incumbent (`_compute_sector_rs`) needs exactly these two. Any other op is out of scope — prompt anti-goal forbids scope creep. |

### Flags for operator

| # | Item | Flag | Proposed resolution |
|---|---|---|---|
| 1 | Item 6 | Prompt example ≠ runtime shape | Use band grammar + clamp (Pass 1 proposal). Deviation from prompt's `{regime: {metric: multiplier}}` sketch. |
| 2 | Item 9 | Scope text directs runtime edit; anti-goal forbids | Narrow to schema docstring note. `MACRO_EVENT_TYPES` is an internal CSV-normalization layer; runtime output already matches schema. |

-----

## 1 — Item 1: `packet_worthy` type fix (closes #567)

### 1.1 Current state

`strategy_spec.py:279`:

```python
if not isinstance(rval.get("packet_worthy"), bool):
    errors.append(f"position_sizing.regimes[{rkey}].packet_worthy must be a bool")
```

`ranker.py:17-25`:

```python
REGIME_THRESHOLDS = {
    "BULL_LOW_VOL": {"packet_worthy": 40, "position_pct": 1.0},
    ...
}
```

Runtime stores `packet_worthy` as an `int` threshold (40-90). Schema rejects any int. See Pass 1 eval for Sprint F §1.11 for the full evidence chain.

### 1.2 Proposed schema shape

```yaml
position_sizing:
  method: regime_adaptive
  regimes:
    BULL_LOW_VOL:
      packet_worthy_threshold: 40       # NEW: int in [0, 100]
      position_pct: 1.0
    BULL_HIGH_VOL:
      packet_worthy_threshold: 50
      position_pct: 0.85
    # ...
```

**Field rename:** `packet_worthy` → `packet_worthy_threshold`. The old field `packet_worthy` becomes deprecated; for one release, if present, the validator emits a deprecation warning and silently accepts it as a synonym (only if an int; rejects bool).

### 1.3 Validator change

In `_validate_position_sizing` (currently line 251-284):

```python
# NEW (Item 1)
pw_val = rval.get("packet_worthy_threshold")
pw_legacy = rval.get("packet_worthy")
if pw_legacy is not None and pw_val is None:
    logger.warning(
        "[PLATFORM] position_sizing.regimes[%s].packet_worthy is deprecated; "
        "use packet_worthy_threshold (int 0-100)", rkey,
    )
    pw_val = pw_legacy
if not _is_int_0_100(pw_val):
    errors.append(
        f"position_sizing.regimes[{rkey}].packet_worthy_threshold "
        f"must be an int in [0, 100]"
    )
```

Reuses existing `_is_int_0_100` (strategy_spec.py:322-323) — no new helper.

### 1.4 Backward compat

- Specs on main do NOT declare `position_sizing.regimes[*].packet_worthy` — none of `lazy_prices_v1.yaml` or `post_audit_ruleset_v1.yaml` use `method: regime_adaptive`. Zero production breakage.
- Schema tests in `tests/platform/specs/test_regime_adaptive.py` (Sprint D) may assert bool — Pass 2 will audit and update to int.

### 1.5 Test plan (2 tests)

**Test 1.5a — valid int threshold:**

```python
def test_packet_worthy_threshold_accepts_int():
    spec = minimal_regime_adaptive_spec()
    spec["position_sizing"]["regimes"]["BULL_LOW_VOL"]["packet_worthy_threshold"] = 40
    ok, errors = validate_spec(spec)
    assert ok, errors
```

**Test 1.5b — reject bool (regression check for #567 fix):**

```python
def test_packet_worthy_threshold_rejects_bool():
    spec = minimal_regime_adaptive_spec()
    spec["position_sizing"]["regimes"]["BULL_LOW_VOL"]["packet_worthy_threshold"] = True
    ok, errors = validate_spec(spec)
    assert not ok
    assert any("packet_worthy_threshold" in e and "int" in e for e in errors)
```

**Test 1.5c (bonus) — deprecated alias still works, warns:**

```python
def test_packet_worthy_legacy_alias_works_with_warning(caplog):
    spec = minimal_regime_adaptive_spec()
    spec["position_sizing"]["regimes"]["BULL_LOW_VOL"]["packet_worthy"] = 40
    with caplog.at_level("WARNING"):
        ok, errors = validate_spec(spec)
    assert ok, errors
    assert "deprecated" in caplog.text
```

### 1.6 LOC estimate

~8 lines added to `strategy_spec.py`. No new helpers.

-----

## 2 — Item 2: `KNOWN_POST_SCAN_HELPERS` drift (closes #568)

### 2.1 Current state

`strategy_spec.py:39`:

```python
KNOWN_POST_SCAN_HELPERS = frozenset({"classifier", "filter_duplicates"})
```

`strategy_spec.py:60`:

```python
("post_scan", "chain", KNOWN_POST_SCAN_HELPERS, False),   # strict=False
```

### 2.2 Runtime reality (verified)

`src/features/enrichment.py::attach_post_scan_features` does NOT string-dispatch. It hardcodes two function imports:

```python
# enrichment.py:38-40
from src.features.traffic_light import compute_traffic_light
tl = compute_traffic_light(spy, vix=vix_value)

# enrichment.py:70-75
from src.features.event_risk_score import attach_event_risk_scores
kwargs = {"settings": config}
...
attach_event_risk_scores(features, **kwargs)
```

**No iteration over a chain list.** The names `traffic_light` and `event_risk` are conceptual labels for these two function calls, NOT dispatch strings that the runtime reads from `spec.post_scan.chain`. This is consistent with `KNOWN_ENRICHERS` (also no runtime dispatch — expected pre-Sprint F).

### 2.3 Proposed schema shape

```python
# strategy_spec.py:39 (Sprint C.1 Item 2)
KNOWN_POST_SCAN_HELPERS = frozenset({"traffic_light", "event_risk"})
```

```python
# strategy_spec.py:60 (Sprint C.1 Item 2 — strict flip)
("post_scan", "chain", KNOWN_POST_SCAN_HELPERS, True),   # strict=True
```

Example spec (forward-looking; no runtime dispatch yet):

```yaml
post_scan:
  chain:
    - traffic_light
    - event_risk
```

### 2.4 Strict=True decision

**Vote: YES, flip strict=True post-fix.**

Rationale:
- No existing spec on main declares `post_scan.chain` (verified via grep of `src/platform/specs/`). Strict flip is zero-breakage.
- Post-fix, the set is descriptive of runtime capability. Drift becomes hard-fail — any future contributor adding a third post-scan enricher must update the frozenset, which is how a registry should behave.
- `strict=False` existed because Sprint E deliberately didn't cross-reference runtime dispatch. With that coverage gap closed, the warn escape is no longer necessary.

### 2.5 Backward compat

- `lazy_prices_v1.yaml` — no `post_scan` block. Unaffected.
- `post_audit_ruleset_v1.yaml` — no `post_scan` block (verified in Pass 2 prep). Unaffected.
- Any new spec using the old names (`classifier`, `filter_duplicates`) would have failed anyway at runtime (no dispatch).

### 2.6 Test plan (2 tests)

**Test 2.6a — new names valid under strict:**

```python
def test_post_scan_chain_accepts_runtime_names():
    spec = minimal_spec()
    spec["post_scan"] = {"chain": ["traffic_light", "event_risk"]}
    ok, errors = validate_spec(spec)
    assert ok, errors
```

**Test 2.6b — old names rejected under strict=True:**

```python
def test_post_scan_chain_rejects_obsolete_names():
    spec = minimal_spec()
    spec["post_scan"] = {"chain": ["classifier"]}
    ok, errors = validate_spec(spec)
    assert not ok
    assert any("post_scan.chain" in e and "unknown ref" in e for e in errors)
```

### 2.7 LOC estimate

2 lines changed (one set contents, one tuple flag). No new validator code.

-----

## 3 — Item 3: Categorical bands

### 3.1 Current state

`_validate_bands` (strategy_spec.py:150-201) requires every band to have `range: [lo, hi]` of numerics. No way to express "score 30 if `trend_state == 'strong_uptrend'`".

### 3.2 Incumbent behavior to cover

Ranker `_score_ticker:169-176`:

```python
if trend == "strong_uptrend":
    score += 30
elif trend == "uptrend":
    score += 20
elif trend == "neutral":
    score += 5
```

And `_score_ticker:179-180`:

```python
market_rs_score = 25 if market_rs == "strong_outperformer" else 15 if market_rs == "outperformer" else 0
```

### 3.3 Proposed schema shape

```yaml
ranking:
  bands:
    - metric: trend_state
      category: strong_uptrend
      score: 30
    - metric: trend_state
      category: uptrend
      score: 20
    - metric: trend_state
      category: neutral
      score: 5
    - metric: relative_strength_state
      category: strong_outperformer
      score: 25
    - metric: relative_strength_state
      category: outperformer
      score: 15
```

**Rule:** each band entry has EXACTLY ONE of `range` (numeric pair) OR `category` (non-empty string). `range` + `category` in the same band is an error. Neither is an error. Both must be accompanied by `metric` + `score`.

### 3.4 Validator change

In `_validate_bands`:

```python
# NEW (Item 3) — after the `metric` check, before the range check
rng = band.get("range")
cat = band.get("category")
has_range = rng is not None
has_cat = cat is not None

if has_range and has_cat:
    errors.append(
        f"ranking.bands[{i}] specifies both 'range' and 'category' — mutually exclusive"
    )
    continue
if not has_range and not has_cat and not band.get("conditions"):  # conditions = Item 4
    errors.append(
        f"ranking.bands[{i}] must specify one of 'range', 'category', or 'conditions'"
    )
    continue

if has_cat:
    if not isinstance(cat, str) or not cat:
        errors.append(f"ranking.bands[{i}].category must be a non-empty string")
        continue
    # No overlap check needed for categoricals (distinct labels by definition)
    parsed_categorical.append((metric, cat, i))
elif has_range:
    # existing range validation path (unchanged)
    ...
```

### 3.5 Interaction with overlap check

The existing overlap check (strategy_spec.py:188-201) operates on numeric ranges only. Categorical bands are stored in a separate list (`parsed_categorical`) and checked for **duplicate (metric, category) pairs only** (not "overlap"). A second band with the same metric+category is an error.

```python
# NEW (Item 3)
seen_cat: dict[tuple[str, str], int] = {}
for metric, cat, idx in parsed_categorical:
    key = (metric, cat)
    if key in seen_cat:
        errors.append(
            f"ranking.bands[{idx}] duplicates metric={metric!r} category={cat!r} "
            f"from ranking.bands[{seen_cat[key]}]"
        )
    else:
        seen_cat[key] = idx
```

### 3.6 KNOWN_SCORING_METRICS interaction (Item 8)

`metric` validated against `KNOWN_SCORING_METRICS` on both range and categorical bands (Item 8 wires this). `trend_state` and `relative_strength_state` must be in the initial seed set.

### 3.7 Backward compat

- Specs on main with numeric-only bands: unchanged path.
- Specs on main with no `ranking.bands` block: unchanged path (block is optional).

### 3.8 Test plan (2 tests)

**Test 3.8a — valid categorical band:**

```python
def test_categorical_band_accepted():
    spec = minimal_spec_with_ranking()
    spec["ranking"]["bands"] = [
        {"metric": "trend_state", "category": "strong_uptrend", "score": 30},
    ]
    ok, errors = validate_spec(spec)
    assert ok, errors
```

**Test 3.8b — reject range + category in same band:**

```python
def test_categorical_and_range_mutually_exclusive():
    spec = minimal_spec_with_ranking()
    spec["ranking"]["bands"] = [
        {"metric": "pullback_depth_pct", "range": [-8, -3], "category": "foo", "score": 10},
    ]
    ok, errors = validate_spec(spec)
    assert not ok
    assert any("mutually exclusive" in e for e in errors)
```

**Test 3.8c (bonus) — reject duplicate categorical:**

```python
def test_categorical_band_rejects_duplicate_metric_category():
    spec = minimal_spec_with_ranking()
    spec["ranking"]["bands"] = [
        {"metric": "trend_state", "category": "strong_uptrend", "score": 30},
        {"metric": "trend_state", "category": "strong_uptrend", "score": 25},
    ]
    ok, errors = validate_spec(spec)
    assert not ok
    assert any("duplicates" in e for e in errors)
```

### 3.9 LOC estimate

~25 lines added.

-----

## 4 — Item 4: Compound AND bands

### 4.1 Current state

`_validate_bands` supports only single-metric bands. No way to express `iv_rank > 75 AND pc_vol > 1.2`.

### 4.2 Incumbent behavior to cover

Ranker `_score_ticker:206-213`:

```python
if iv_rank is not None:
    if iv_rank < 25:
        score += 3
    elif iv_rank > 75 and pc_vol and pc_vol > 1.2:
        score -= 3
```

The `iv_rank < 25` single-metric half-open needs Item 5's `operator` mechanism. The `iv_rank > 75 AND pc_vol > 1.2` compound is Item 4's target.

### 4.3 Proposed schema shape

```yaml
ranking:
  bands:
    # Compound AND: all conditions must hold
    - conditions:
        - metric: iv_rank
          operator: ">"
          threshold: 75
        - metric: put_call_vol_ratio
          operator: ">"
          threshold: 1.2
      score: -3
```

**Rule:** a band with `conditions` has NO top-level `metric`, `range`, or `category`. `conditions` is a non-empty list of `{metric, operator, threshold}` dicts. Semantics: implicit AND across all conditions (per prompt — "Compound AND bands"; `any_of`/OR deferred to a later sprint, out of scope).

**Operator enum:** `{">", ">=", "<", "<=", "==", "!="}`. When `operator` is `==` or `!=`, `threshold` may be string (for categorical metrics like `trend_state`) or numeric. For all other operators, `threshold` must be numeric.

### 4.4 Validator change

New helper function:

```python
# NEW (Item 4)
ALLOWED_BAND_OPERATORS = frozenset({">", ">=", "<", "<=", "==", "!="})
_EQUALITY_OPERATORS = frozenset({"==", "!="})

def _validate_band_condition(cond: Any, path: str, errors: list[str]) -> None:
    """Validate a single condition inside a compound band."""
    if not isinstance(cond, dict):
        errors.append(f"{path} must be a dict")
        return
    metric = cond.get("metric")
    if not isinstance(metric, str) or not metric:
        errors.append(f"{path}.metric must be a non-empty string")
    op = cond.get("operator")
    if op not in ALLOWED_BAND_OPERATORS:
        errors.append(
            f"{path}.operator must be one of {sorted(ALLOWED_BAND_OPERATORS)}, got {op!r}"
        )
    thr = cond.get("threshold")
    if op in _EQUALITY_OPERATORS:
        if not isinstance(thr, (int, float, str)) or isinstance(thr, bool):
            errors.append(f"{path}.threshold must be numeric or string for operator {op!r}")
    else:
        if not isinstance(thr, (int, float)) or isinstance(thr, bool):
            errors.append(f"{path}.threshold must be numeric for operator {op!r}")
```

In `_validate_bands`:

```python
# NEW (Item 4) — before the single-metric range/category path
conds = band.get("conditions")
if conds is not None:
    if band.get("metric") or band.get("range") or band.get("category"):
        errors.append(
            f"ranking.bands[{i}] with 'conditions' may not specify 'metric', 'range', or 'category'"
        )
        continue
    if not isinstance(conds, list) or not conds:
        errors.append(f"ranking.bands[{i}].conditions must be a non-empty list")
        continue
    for j, cond in enumerate(conds):
        _validate_band_condition(cond, f"ranking.bands[{i}].conditions[{j}]", errors)
    # score still required
    if not isinstance(band.get("score"), (int, float)) or isinstance(band.get("score"), bool):
        errors.append(f"ranking.bands[{i}].score must be numeric")
    continue   # skip single-metric validation below
```

### 4.5 Backward compat

All existing specs use single-metric bands (or no bands at all). Compound bands are net-new. No breakage.

### 4.6 Test plan (3 tests)

**Test 4.6a — valid compound band:**

```python
def test_compound_and_band_accepted():
    spec = minimal_spec_with_ranking()
    spec["ranking"]["bands"] = [{
        "conditions": [
            {"metric": "iv_rank", "operator": ">", "threshold": 75},
            {"metric": "put_call_vol_ratio", "operator": ">", "threshold": 1.2},
        ],
        "score": -3,
    }]
    ok, errors = validate_spec(spec)
    assert ok, errors
```

**Test 4.6b — reject unknown operator:**

```python
def test_compound_band_rejects_unknown_operator():
    spec = minimal_spec_with_ranking()
    spec["ranking"]["bands"] = [{
        "conditions": [{"metric": "iv_rank", "operator": "~~", "threshold": 75}],
        "score": 10,
    }]
    ok, errors = validate_spec(spec)
    assert not ok
    assert any("operator" in e for e in errors)
```

**Test 4.6c — reject mixing top-level metric with conditions:**

```python
def test_compound_band_rejects_mixed_shape():
    spec = minimal_spec_with_ranking()
    spec["ranking"]["bands"] = [{
        "metric": "iv_rank",
        "range": [0, 100],
        "conditions": [{"metric": "pc_vol", "operator": ">", "threshold": 1.2}],
        "score": 10,
    }]
    ok, errors = validate_spec(spec)
    assert not ok
    assert any("may not specify" in e for e in errors)
```

### 4.7 LOC estimate

~45 lines added (~15 for `_validate_band_condition` helper + ~30 for the `conditions` branch in `_validate_bands`).

-----

## 5 — Item 5: Weighted bands (with `blend_group`)

### 5.1 Current state

No `weight` or `blend_group` support. All bands contribute their raw `score` additively.

### 5.2 Incumbent behavior to cover

Ranker `_score_ticker:182-187`:

```python
sector_rs_score = _as_float(features.get("_sector_rs_score"))
if sector_rs_score is not None:
    combined_rs = 0.6 * market_rs_score + 0.4 * sector_rs_score
else:
    combined_rs = market_rs_score  # Fallback to market-only
score += combined_rs
```

`market_rs_score` is derived from categorical bands on `relative_strength_state` (Item 3 territory). `sector_rs_score` is derived from `_compute_sector_rs` (Item 7 territory). The 0.6/0.4 blend is Item 5.

### 5.3 Proposed schema shape

```yaml
ranking:
  bands:
    # Market RS bands (categorical — Item 3)
    - metric: relative_strength_state
      category: strong_outperformer
      score: 25
      weight: 0.6
      blend_group: rs_blend
    - metric: relative_strength_state
      category: outperformer
      score: 15
      weight: 0.6
      blend_group: rs_blend
    # Sector RS bands (numeric on derived metric — Item 7 produces sector_rs_score)
    - metric: sector_rs_score
      range: [20, 30]
      score: 25
      weight: 0.4
      blend_group: rs_blend
    - metric: sector_rs_score
      range: [10, 20]
      score: 15
      weight: 0.4
      blend_group: rs_blend
```

**Semantics:** bands with the same `blend_group` tag are summed with their weights, producing a single contribution to the total score. Bands without a `blend_group` are added raw (current behavior).

Within a blend_group:
- All bands MUST have a `weight` field.
- At most one band per ticker is active per metric (existing band-matching semantics).
- The blend computation is: `contribution = sum(weight_i * score_i for each matched band i)`.

### 5.4 blend_group decision

**YES, `blend_group` is required for weighted bands.**

Rationale considered during Pass 1:

- **Option A (weight alone, implicit grouping by metric-name pair):** brittle. If a spec declares three bands on `market_rs_score` plus two on `sector_rs_score`, the schema can't infer which pair to blend. Implicit grouping based on declaration order is worse.
- **Option B (weight alone, ALL weighted bands sum globally):** means `weight=0.5` on one band halves its contribution to the total, which has semantic value but doesn't express the "market + sector blend" case cleanly.
- **Option C (weight + blend_group, explicit tag):** **chosen.** Spec author explicitly tags related bands. Validator checks blend_group cohesion (below). Scales to N-way blends. No ambiguity.

### 5.5 Fallback semantics — RESOLVED (operator 2026-04-20)

Incumbent line 185 has a fallback: `if sector_rs is None: combined_rs = market_rs_score` (market gets weight 1.0 instead of 0.6).

Pure weighted blend can't express this cleanly. Options considered at Pass 1:
- **Defer to Item 7 (derived_metrics).** Define `combined_rs` as a derived metric with a conditional operation (`weighted_sum_or_fallback`), then band that single metric. But this adds a third operation to `derived_metrics`, which Pass 1 §7 decision closes at `subtract` + `weighted_sum` only.
- **Allow `normalize_on_missing: true` on blend_group.** When a band's `metric` is absent/None at runtime, renormalize remaining weights to sum to 1.0. Schema-side: optional boolean field on the first band in a blend_group, or a top-level `ranking.blends: {<group>: {normalize_on_missing: true}}` dict. Adds 5-10 LOC.
- **Accept semantic gap.** Document as a known Sprint F limitation; if walk-forward shows the gap matters, open Sprint C.2 for the renormalization feature.

**Resolution (operator, 2026-04-20): ACCEPT SEMANTIC GAP.**

Do NOT add `normalize_on_missing`. Do NOT extend `derived_metrics` operations. Sprint C.1 ships with the pure-weighted-blend schema; the fallback-when-None case remains Python-hardcoded in `ranker.py` (unchanged from today).

**Known Sprint F divergence:** when Sprint F ports the blend via spec-driven dispatch, the YAML path will NOT reproduce the Python fallback at ranker.py:185:

- **Python path (unchanged):** `if sector_rs is None: combined_rs = market_rs_score` — when `_sector_rs_score` is absent, market gets weight 1.0 fallback (full contribution).
- **Spec-driven path (Sprint F):** pure weighted sum regardless of None-ness. Either pre-populating `sector_rs_score = 0` (weight 0.4 applied to 0 → 0 contribution → market contributes only 0.6 × market_rs_score, which ≠ Python fallback of full market_rs_score) OR skipping the sector band entirely (same semantic issue — market stays at 0.6 weight, not 1.0).

**Expected Sprint F outcome:** byte-identity fuzz will FAIL on any date where at least one ticker lacks sector ETF data. Pass 2 §1.4 confirms the fallback is reachable — likely common across most callers of `rank_universe` (the `sector_etf_features` parameter defaults to `None`, so the fallback triggers for every ticker when the caller doesn't pre-load sector data).

Per the plan's STOP discipline (`SPRINT_FGH_PLAN.md` "If a sprint gets stuck"):

1. Sprint F STOPs on first fuzz failure attributable to this fallback.
2. Sprint F files a new issue describing the gap.
3. Operator decides: open Sprint C.2 (`normalize_on_missing` or equivalent) OR accept incumbent simplification (remove the fallback from Python and re-compute byte-identity against the simplified path).

This is the explicit plan. The known-divergence is documented here in Pass 1 so Sprint F can recognize it immediately when fuzz fails, rather than chasing it as a mystery bug.

### 5.6 Validator change

```python
# NEW (Item 5) — new helper
def _validate_band_weights(bands: list, errors: list[str]) -> None:
    """Validate weight + blend_group cohesion."""
    by_group: dict[str, list[tuple[int, float]]] = {}
    for i, band in enumerate(bands):
        if not isinstance(band, dict):
            continue
        w = band.get("weight")
        g = band.get("blend_group")
        if w is None and g is None:
            continue  # unweighted band, fine
        if w is None and g is not None:
            errors.append(f"ranking.bands[{i}] has blend_group without weight")
            continue
        if w is not None and g is None:
            errors.append(f"ranking.bands[{i}] has weight without blend_group")
            continue
        if not isinstance(w, (int, float)) or isinstance(w, bool) or not (0.0 <= w <= 1.0):
            errors.append(f"ranking.bands[{i}].weight must be a number in [0.0, 1.0]")
            continue
        if not isinstance(g, str) or not g:
            errors.append(f"ranking.bands[{i}].blend_group must be a non-empty string")
            continue
        by_group.setdefault(g, []).append((i, float(w)))

    # Weights within a group should typically sum to 1.0 (warn if not)
    for g, entries in by_group.items():
        total = sum(w for _, w in entries)
        if abs(total - 1.0) > 0.01:
            # Warn, not error — some blends are deliberately sub-unity
            logger.warning(
                "[PLATFORM] ranking.bands blend_group=%r weights sum to %.3f (not 1.0)",
                g, total,
            )
```

Call after existing band validation in `_validate_bands`.

### 5.7 Test plan (3 tests)

**Test 5.7a — valid weighted blend:**

```python
def test_weighted_band_blend_accepted():
    spec = minimal_spec_with_ranking()
    spec["ranking"]["bands"] = [
        {"metric": "market_rs_score", "range": [0, 100], "score": 25,
         "weight": 0.6, "blend_group": "rs_blend"},
        {"metric": "sector_rs_score", "range": [0, 100], "score": 25,
         "weight": 0.4, "blend_group": "rs_blend"},
    ]
    ok, errors = validate_spec(spec)
    assert ok, errors
```

**Test 5.7b — reject weight without blend_group:**

```python
def test_weight_requires_blend_group():
    spec = minimal_spec_with_ranking()
    spec["ranking"]["bands"] = [
        {"metric": "pullback_depth_pct", "range": [-8, -3], "score": 25, "weight": 0.5},
    ]
    ok, errors = validate_spec(spec)
    assert not ok
    assert any("blend_group" in e for e in errors)
```

**Test 5.7c — warn when weights sum != 1.0:**

```python
def test_blend_group_weights_warn_on_bad_sum(caplog):
    spec = minimal_spec_with_ranking()
    spec["ranking"]["bands"] = [
        {"metric": "a", "range": [0, 1], "score": 10, "weight": 0.3, "blend_group": "g"},
        {"metric": "b", "range": [0, 1], "score": 10, "weight": 0.3, "blend_group": "g"},
    ]
    with caplog.at_level("WARNING"):
        ok, _ = validate_spec(spec)
    assert ok
    assert "0.600" in caplog.text or "not 1.0" in caplog.text
```

### 5.8 LOC estimate

~25 lines added (new helper + call site).

-----

## 6 — Item 6: `ranking.adjustments` block (**FLAGGED**)

### 6.1 Prompt deviation

The prompt's example shape:

```yaml
ranking:
  adjustments:
    BULL_LOW_VOL:
      pullback_depth_pct: 1.2
      volume_ratio_20d: 1.0
    CORRECTION:
      pullback_depth_pct: 0.8
```

describes a **regime-keyed multiplier table**, with keys from `KNOWN_REGIME_KEYS` (7-label `BULL_LOW_VOL` set) and values mapping metric names to multipliers.

The actual incumbent `_regime_adjustment` (ranker.py:72-102) is structurally different:

```python
def _regime_adjustment(features: dict) -> float:
    regime = features.get("regime_label", "")             # 5-label set, NOT 7-label
    breadth = features.get("market_breadth_label", "")
    spy_rsi = features.get("spy_rsi_14", 50)
    adj = 0.0

    if regime == "calm_uptrend" and breadth == "healthy":
        adj += 5
    elif regime == "calm_uptrend" and breadth == "narrowing":
        adj += 2
    # ... 4 more compound conditions
    elif regime == "volatile_downtrend":
        adj -= 10

    if spy_rsi > 75:
        adj -= 3
    elif spy_rsi < 30:
        adj += 3

    return max(-10, min(10, adj))
```

Three key observations:

1. **The regime label set is the 5-label `regime_label`** (`calm_uptrend`, `volatile_uptrend`, `calm_downtrend`, `volatile_downtrend`, `transitional`), produced by `compute_market_regime()` in `regime.py:79-185`. This is a DIFFERENT set from `KNOWN_REGIME_KEYS` (7-label, used by `REGIME_THRESHOLDS`/`position_sizing.regimes`).
2. **The adjustment is a compound-band scorer**, not a multiplier. It adds/subtracts discrete points based on compound `(regime_label, market_breadth_label)` pairs plus numeric bands on `spy_rsi_14`. It does NOT multiply metrics.
3. **The output is clamped to `[-10, +10]`** and added to the base score.

The prompt's example doesn't describe `_regime_adjustment`. It describes something like "apply regime-specific multipliers to per-metric scores." That behavior doesn't exist in ranker.py today.

### 6.2 Proposed schema shape (Pass 1 recommendation)

**Recommendation: `ranking.adjustments` reuses the band grammar (Items 3/4/5) plus a `clamp` field.** No new regime-key registry; the regime labels are just categorical `threshold` values in compound conditions.

```yaml
ranking:
  adjustments:
    clamp: [-10, 10]
    bands:
      - conditions:
          - metric: regime_label
            operator: "=="
            threshold: calm_uptrend
          - metric: market_breadth_label
            operator: "=="
            threshold: healthy
        score: 5
      - conditions:
          - metric: regime_label
            operator: "=="
            threshold: calm_uptrend
          - metric: market_breadth_label
            operator: "=="
            threshold: narrowing
        score: 2
      # ... 4 more compound rules
      - conditions:
          - metric: regime_label
            operator: "=="
            threshold: volatile_downtrend
        score: -10
      - metric: spy_rsi_14
        range: [75.000001, 999]    # strict `>75` via a tight lower bound
        score: -3
      - metric: spy_rsi_14
        range: [-999, 29.999999]   # strict `<30`
        score: 3
```

(Or with Item 5's future `operator` mechanism the numeric bands could be cleaner, but strict intervals are ok here.)

Semantics:
- All matched `adjustments.bands` contribute (unlike `ranking.bands`, where bands are independent per metric); this matches `_regime_adjustment`'s cumulative `adj +=` pattern.
- The sum of all matched adjustments is clamped to `clamp: [lo, hi]` before being added to the total score.
- `clamp` is optional; default is no clamp.

### 6.3 Validator change

New function (reuses `_validate_bands` for the `bands` list):

```python
# NEW (Item 6)
def _validate_adjustments(adj_block: dict, errors: list[str]) -> None:
    clamp = adj_block.get("clamp")
    if clamp is not None:
        if (
            not isinstance(clamp, list)
            or len(clamp) != 2
            or not all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in clamp)
            or clamp[0] >= clamp[1]
        ):
            errors.append(
                "ranking.adjustments.clamp must be a 2-element list of numerics with lo < hi"
            )
    bands = adj_block.get("bands")
    if bands is None:
        errors.append("ranking.adjustments.bands is required")
        return
    if not isinstance(bands, list):
        errors.append("ranking.adjustments.bands must be a list")
        return
    _validate_bands(bands, errors)   # REUSE — bands grammar is identical
```

Call from top-level `validate_spec`:

```python
# NEW (Item 6) — after the existing ranking block handling
if "ranking" in spec and isinstance(spec["ranking"], dict):
    if "adjustments" in spec["ranking"]:
        adj = spec["ranking"]["adjustments"]
        if not isinstance(adj, dict):
            errors.append("ranking.adjustments must be a dict when present")
        else:
            _validate_adjustments(adj, errors)
```

### 6.4 Backward compat

- `ranking.adjustments` is net-new. Specs that don't declare it are unchanged.

### 6.5 Operator flag

**Deviation from prompt example.** Pass 1 proposes the band-grammar-based shape (matches runtime) rather than the regime-keyed multiplier shape (matches prompt example but not runtime). If the operator intends the multiplier shape, Item 6 would need a different validator and would not cover `_regime_adjustment`.

**Recommendation: confirm the band-grammar shape. Ship the prompt example as a future extension if the multiplier pattern appears in some spec in the future.**

### 6.6 Test plan (2 tests)

**Test 6.6a — valid adjustments block:**

```python
def test_adjustments_block_with_bands_and_clamp():
    spec = minimal_spec_with_ranking()
    spec["ranking"]["adjustments"] = {
        "clamp": [-10, 10],
        "bands": [
            {"conditions": [
                {"metric": "regime_label", "operator": "==", "threshold": "calm_uptrend"},
                {"metric": "market_breadth_label", "operator": "==", "threshold": "healthy"},
            ], "score": 5},
        ],
    }
    ok, errors = validate_spec(spec)
    assert ok, errors
```

**Test 6.6b — reject bad clamp:**

```python
def test_adjustments_clamp_must_be_lo_lt_hi():
    spec = minimal_spec_with_ranking()
    spec["ranking"]["adjustments"] = {"clamp": [10, -10], "bands": [
        {"metric": "spy_rsi_14", "range": [0, 100], "score": 0}
    ]}
    ok, errors = validate_spec(spec)
    assert not ok
    assert any("clamp" in e for e in errors)
```

### 6.7 LOC estimate

~25 lines added (helper function + top-level integration).

-----

## 7 — Item 7: `ranking.derived_metrics` block

### 7.1 Current state

No `derived_metrics` block. `_compute_sector_rs` is a hardcoded Python function.

### 7.2 Incumbent behavior to cover (ranker.py:105-147)

```python
excess["1m"] = ticker_return_1m - sector_return_1m
excess["3m"] = ticker_return_3m - sector_return_3m
excess["6m"] = ticker_return_6m - sector_return_6m

weighted_excess = 0.20 * excess["1m"] + 0.50 * excess["3m"] + 0.30 * excess["6m"]

# Then band weighted_excess to 0/5/15/25 via thresholds
```

### 7.3 Supported operations decision

Enumerate from the incumbent:
- `subtract(a, b)` → `a - b`. Needed 3× for excess returns.
- `weighted_sum(inputs: dict[str, float])` → `sum(weight * value for name, weight in inputs.items())`. Needed 1×.

**Decision: `subtract` + `weighted_sum` only.** No `divide`, `multiply`, `sum_unweighted`, `max`, `min`. If a future spec needs a new op, open a separate sprint — don't scope-creep C.1.

The threshold-banding step (weighted_excess → 0/5/15/25) is NOT a derived_metrics operation — it uses `ranking.bands` with numeric ranges on the `weighted_sector_excess` metric name. Separation of concerns: `derived_metrics` produces scalars; `bands` scores them.

### 7.4 Proposed schema shape

```yaml
ranking:
  derived_metrics:
    sector_excess_1m:
      operation: subtract
      inputs: [rs_vs_spy_1m, sector_rs_vs_spy_1m]
    sector_excess_3m:
      operation: subtract
      inputs: [rs_vs_spy_3m, sector_rs_vs_spy_3m]
    sector_excess_6m:
      operation: subtract
      inputs: [rs_vs_spy_6m, sector_rs_vs_spy_6m]
    weighted_sector_excess:
      operation: weighted_sum
      inputs:
        sector_excess_1m: 0.20
        sector_excess_3m: 0.50
        sector_excess_6m: 0.30
  bands:
    - metric: weighted_sector_excess
      range: [5.0, 999]
      score: 25
    - metric: weighted_sector_excess
      range: [2.0, 5.0]
      score: 15
    - metric: weighted_sector_excess
      range: [-2.0, 2.0]
      score: 5
    - metric: weighted_sector_excess
      range: [-999, -2.0]
      score: 0
```

**Schema rules:**
- `derived_metrics` is a dict of `name → {operation, inputs}`.
- `operation` must be one of `{"subtract", "weighted_sum"}` (strict enum).
- For `subtract`: `inputs` is a list of exactly 2 metric names (result = inputs[0] - inputs[1]).
- For `weighted_sum`: `inputs` is a dict of `metric_name → weight` (result = sum of weight × metric).
- Metric name references (both in `inputs` and as derived output names) must resolve against `KNOWN_SCORING_METRICS` (Item 8) at validation time — treating derived names as pre-added to the set.
- **No cycles.** A derived metric cannot reference itself or reference another metric that references back. Validator must DAG-check.

### 7.5 Validator change

```python
# NEW (Item 7)
ALLOWED_DERIVED_OPS = frozenset({"subtract", "weighted_sum"})

def _validate_derived_metrics(dm_block: dict, errors: list[str]) -> set[str]:
    """Validate derived_metrics block. Returns the set of derived metric names
    for downstream use in KNOWN_SCORING_METRICS validation."""
    if not isinstance(dm_block, dict):
        errors.append("ranking.derived_metrics must be a dict when present")
        return set()
    derived_names: set[str] = set()
    specs_by_name: dict[str, dict] = {}
    for name, entry in dm_block.items():
        if not isinstance(name, str) or not name:
            errors.append(f"ranking.derived_metrics keys must be non-empty strings")
            continue
        if not isinstance(entry, dict):
            errors.append(f"ranking.derived_metrics[{name}] must be a dict")
            continue
        op = entry.get("operation")
        if op not in ALLOWED_DERIVED_OPS:
            errors.append(
                f"ranking.derived_metrics[{name}].operation must be one of "
                f"{sorted(ALLOWED_DERIVED_OPS)}, got {op!r}"
            )
            continue
        inputs = entry.get("inputs")
        if op == "subtract":
            if not isinstance(inputs, list) or len(inputs) != 2 or not all(isinstance(x, str) and x for x in inputs):
                errors.append(
                    f"ranking.derived_metrics[{name}].inputs must be a list of 2 non-empty strings for 'subtract'"
                )
                continue
        elif op == "weighted_sum":
            if not isinstance(inputs, dict) or not inputs:
                errors.append(
                    f"ranking.derived_metrics[{name}].inputs must be a non-empty dict for 'weighted_sum'"
                )
                continue
            for k, w in inputs.items():
                if not isinstance(k, str) or not k:
                    errors.append(f"ranking.derived_metrics[{name}].inputs keys must be non-empty strings")
                    continue
                if not isinstance(w, (int, float)) or isinstance(w, bool):
                    errors.append(f"ranking.derived_metrics[{name}].inputs[{k}] weight must be numeric")
        derived_names.add(name)
        specs_by_name[name] = entry

    # DAG check: no metric may reference itself (direct or transitive)
    def _refs(entry: dict) -> list[str]:
        inp = entry.get("inputs")
        if isinstance(inp, list):
            return [x for x in inp if isinstance(x, str)]
        if isinstance(inp, dict):
            return [k for k in inp.keys() if isinstance(k, str)]
        return []

    def _has_cycle(start: str) -> bool:
        stack = [start]
        visited: set[str] = set()
        while stack:
            node = stack.pop()
            if node == start and visited:
                return True
            if node in visited:
                continue
            visited.add(node)
            if node in specs_by_name:
                stack.extend(_refs(specs_by_name[node]))
        return False

    for name in specs_by_name:
        if name in _refs(specs_by_name[name]):
            errors.append(f"ranking.derived_metrics[{name}] references itself")
        elif _has_cycle(name):
            errors.append(f"ranking.derived_metrics[{name}] participates in a cycle")

    return derived_names
```

Call from `validate_spec` and thread `derived_names` into `_validate_bands` so derived metrics are treated as valid `metric` values.

### 7.6 Backward compat

- Net-new block. No existing spec uses it.

### 7.7 Test plan (3 tests)

**Test 7.7a — valid derived_metrics block:**

```python
def test_derived_metrics_subtract_and_weighted_sum():
    spec = minimal_spec_with_ranking()
    spec["ranking"]["derived_metrics"] = {
        "sector_excess_1m": {"operation": "subtract",
                              "inputs": ["rs_vs_spy_1m", "sector_rs_1m"]},
        "weighted_excess": {"operation": "weighted_sum",
                             "inputs": {"sector_excess_1m": 0.2, "sector_excess_3m": 0.5}},
    }
    ok, errors = validate_spec(spec)
    assert ok, errors
```

**Test 7.7b — reject unknown operation:**

```python
def test_derived_metrics_rejects_unknown_op():
    spec = minimal_spec_with_ranking()
    spec["ranking"]["derived_metrics"] = {
        "x": {"operation": "multiply", "inputs": ["a", "b"]},
    }
    ok, errors = validate_spec(spec)
    assert not ok
    assert any("operation" in e for e in errors)
```

**Test 7.7c — reject circular dependency:**

```python
def test_derived_metrics_rejects_cycle():
    spec = minimal_spec_with_ranking()
    spec["ranking"]["derived_metrics"] = {
        "a": {"operation": "subtract", "inputs": ["b", "x"]},
        "b": {"operation": "subtract", "inputs": ["a", "y"]},
    }
    ok, errors = validate_spec(spec)
    assert not ok
    assert any("cycle" in e for e in errors)
```

### 7.8 LOC estimate

~55 lines added.

-----

## 8 — Item 8: `KNOWN_SCORING_METRICS` registry

### 8.1 Current state

No `KNOWN_SCORING_METRICS` frozenset. `ranking.bands[].metric` is validated only as "non-empty string". Typos produce zero-score bands silently at dispatch time.

### 8.2 Seed contents

Derived from the minimum set of metrics referenced in incumbent scoring (`_score_ticker`, `_regime_adjustment`):

```python
# NEW (Item 8) — strategy_spec.py
KNOWN_SCORING_METRICS = frozenset({
    # From _score_ticker (ranker.py:165-220)
    "trend_state",
    "relative_strength_state",
    "pullback_depth_pct",
    "dist_to_sma20_pct",
    "volume_ratio_20d",
    "iv_rank",
    "put_call_vol_ratio",
    # From _regime_adjustment (ranker.py:72-102)
    "regime_label",
    "market_breadth_label",
    "spy_rsi_14",
})
```

All 10 metrics verified to be produced by:
- `compute_features` in `engine.py:102-201` (7 of them)
- `compute_market_regime` in `regime.py:79-185` (3 of them)

### 8.3 Dispatch: where names are validated

- `ranking.bands[].metric` → validate against `KNOWN_SCORING_METRICS ∪ derived_names`
- `ranking.bands[].conditions[].metric` (Item 4) → same
- `ranking.adjustments.bands[].metric` and `.conditions[].metric` (Item 6) → same
- `ranking.derived_metrics[].inputs` (list or dict keys, Item 7) → same

Strict=True for all: typos hard-fail.

### 8.4 Validator change

```python
# NEW (Item 8) — in _validate_bands and _validate_band_condition, after metric coercion
# (pass known_metrics as a parameter from validate_spec)
if metric not in known_metrics:
    errors.append(
        f"{path}.metric {metric!r} not in KNOWN_SCORING_METRICS "
        f"(known: {', '.join(sorted(known_metrics))})"
    )
```

Refactor `_validate_bands` signature to accept `known_metrics: frozenset[str]`. Build the runtime set as `KNOWN_SCORING_METRICS | derived_names_from_item_7` in `validate_spec`.

### 8.5 Backward compat

- Specs that use `ranking.bands` on metrics in the seed set: unchanged.
- Specs that use `ranking.bands` on a metric NOT in the seed set: previously accepted silently, now rejected. **This is by design — the fix hardens typo detection.** Pass 2 must audit existing specs.
- `lazy_prices_v1.yaml` has no `ranking.bands` block — unaffected.
- `post_audit_ruleset_v1.yaml` — to be audited in Pass 2.

### 8.6 Test plan (2 tests)

**Test 8.6a — valid known metric:**

```python
def test_known_scoring_metric_accepted():
    spec = minimal_spec_with_ranking()
    spec["ranking"]["bands"] = [
        {"metric": "trend_state", "category": "strong_uptrend", "score": 30},
    ]
    ok, errors = validate_spec(spec)
    assert ok, errors
```

**Test 8.6b — reject unknown metric:**

```python
def test_unknown_scoring_metric_rejected():
    spec = minimal_spec_with_ranking()
    spec["ranking"]["bands"] = [
        {"metric": "made_up_metric", "range": [0, 1], "score": 10},
    ]
    ok, errors = validate_spec(spec)
    assert not ok
    assert any("KNOWN_SCORING_METRICS" in e or "not in" in e for e in errors)
```

**Test 8.6c (bonus) — derived metric added to known set implicitly:**

```python
def test_derived_metric_becomes_valid_band_metric():
    spec = minimal_spec_with_ranking()
    spec["ranking"]["derived_metrics"] = {
        "custom": {"operation": "subtract", "inputs": ["trend_state", "trend_state"]},
    }
    spec["ranking"]["bands"] = [
        {"metric": "custom", "range": [0, 1], "score": 10},
    ]
    ok, errors = validate_spec(spec)
    assert ok, errors
```

### 8.7 LOC estimate

~18 lines added (frozenset definition + validation call + signature refactor).

-----

## 9 — Item 9: Event-risk casing (**FLAGGED**)

### 9.1 Actual state (verified)

The prompt describes "inconsistent casing" across `KNOWN_EVENT_RISK_CATEGORIES` and `MACRO_EVENT_TYPES`. Verification of the 20-entry frozenset at `strategy_spec.py:42-50`:

```python
KNOWN_EVENT_RISK_CATEGORIES = frozenset({
    "earnings_imminent", "earnings_elevated",    # lowercase_with_underscores
    "fomc", "nfp", "cpi",                         # lowercase
    "cpi_print", "export_controls", "fomc_decision", "industrial_policy",
    "nfp_friday", "opex_monthly", "opex_weekly", "ppi_print",
    "quarter_end_rebalance", "sanctions_initial", "sanctions_escalation",
    "tariff_pause", "tariff_announcement", "tariff_escalation",
    "trade_disruption",
})
```

**All 20 entries are already consistent: lowercase with underscores.** There is NO casing inconsistency in the frozenset.

The runtime `MACRO_EVENT_TYPES = {"FOMC", "NFP", "CPI"}` at `src/features/event_risk_score.py:25` is uppercase, but:
- It is matched only against CSV/DB `event_type` column values that are `.upper()` normalized at lines 63 and 112. So `MACRO_EVENT_TYPES` is an internal input-normalization layer.
- The user-facing output `components` dict uses lowercase keys: `{"fomc": 0, "nfp": 0, "cpi": 0, ...}` at lines 201-207.
- The lowercase output matches `KNOWN_EVENT_RISK_CATEGORIES`'s lowercase entries.

**There is no dispatch mismatch that affects specs today.** The uppercase `MACRO_EVENT_TYPES` is an implementation detail of the CSV/DB reader, invisible to specs and users.

### 9.2 Operator flag

The prompt scope says:

> **Item 9: Event-risk casing normalization** — Pick one convention (lowercase with underscores is the most common in the set), normalize the frozenset, and update any test fixtures using the old casing.

And the prompt anti-goals say:

> No changes to ranker, features, or executor — Sprint F resumes those after C.1 merges.

`MACRO_EVENT_TYPES` is in `src/features/event_risk_score.py` — a file the anti-goal forbids modifying. Also, since the frozenset is already consistent, there's no normalization work needed at the schema layer.

### 9.3 Proposed resolution options

**Option 9A (recommended): narrow Item 9 to a schema docstring note.**

```python
# strategy_spec.py:40-41 (updated)
# Union of sprint-prompt earnings categories + MACRO_EVENT_TYPES
# (event_risk_score.py, ALL NORMALIZED TO lowercase_with_underscores — see
# Sprint C.1 Item 9) + KNOWN_EVENTS labels (known_events.py).
# Runtime dispatch MUST lowercase event_type before matching against this set.
# Current runtime emits lowercase via event_risk_score.py `components` dict
# (lines 201-207); internal MACRO_EVENT_TYPES uppercase is input-normalization only.
```

LOC: ~5 lines of comment/docstring. No code change to `src/features/`.

**Option 9B: add Item 9 to anti-goal exception.**

Change `MACRO_EVENT_TYPES` to lowercase. This requires updating lines 25, 63, 64, 95, 104, 113, 213, 215, 217 in `event_risk_score.py` — a cascading change across `_load_fallback_events`, `_fetch_macro_events`, and `compute_market_event_risk`. ~15 lines touched. Crosses into "feature" territory prohibited by anti-goals. Would require operator exception.

**Option 9C: drop Item 9 from C.1, defer to Sprint F.**

Sprint F's dispatch layer will need to handle case normalization anyway when wiring `spec.event_risk.quarantine_categories` to runtime event matching. The work belongs where the dispatch lives.

**Pass 1 recommendation: Option 9A.** Narrows Item 9 to a docstring note, stays within C.1's schema-only charter, documents the convention explicitly for future maintainers. Flags the fact that the prompt's Item 9 scope is larger than schema-only work can accommodate.

### 9.4 Backward compat

Option 9A: zero impact — docstring only.
Option 9B: runtime behavior unchanged (all match via `.upper()` normalization); internal constants rename only.
Option 9C: zero impact now; impact when Sprint F dispatches.

### 9.5 Test plan (1 test for Option 9A)

```python
def test_known_event_risk_categories_consistent_casing():
    """Guard against future additions that break the lowercase_with_underscores convention."""
    from src.platform.strategy_spec import KNOWN_EVENT_RISK_CATEGORIES
    for cat in KNOWN_EVENT_RISK_CATEGORIES:
        assert cat == cat.lower(), f"{cat!r} breaks lowercase convention"
        assert " " not in cat, f"{cat!r} contains space (use underscore)"
```

### 9.6 LOC estimate

Option 9A: ~5 lines (comment/docstring). Option 9B: ~15 lines. Option 9C: 0 lines.

-----

## 10 — Line budget confirmation

| Item | LOC estimate |
|---|---|
| 1 — packet_worthy type | 8 |
| 2 — POST_SCAN drift + strict | 2 |
| 3 — categorical bands | 25 |
| 4 — compound AND bands | 45 |
| 5 — weighted bands | 25 |
| 6 — ranking.adjustments | 25 |
| 7 — ranking.derived_metrics | 55 |
| 8 — KNOWN_SCORING_METRICS | 18 |
| 9 — event-risk docstring (Option 9A) | 5 |
| **Total** | **208** |

Current `strategy_spec.py`: 393 lines (measured 2026-04-20). Post-C.1: ~601 lines. Under the 650-line guardrail by ~49 lines.

**Budget OK.** If Option 9B is chosen for Item 9, add ~15 to the total (still under 650).

-----

## 11 — Aggregate test strategy

### 11.1 Test file

**New:** `tests/platform/specs/test_schema_c1_refinements.py`

### 11.2 Test count

| Item | Required tests | Bonus | Total |
|---|---|---|---|
| 1 | 2 | 1 | 3 |
| 2 | 2 | 0 | 2 |
| 3 | 2 | 1 | 3 |
| 4 | 3 | 0 | 3 |
| 5 | 3 | 0 | 3 |
| 6 | 2 | 0 | 2 |
| 7 | 3 | 0 | 3 |
| 8 | 2 | 1 | 3 |
| 9 | 1 | 0 | 1 |
| Backward compat | — | — | 2 |
| **Total** | **20** | **3** | **25** |

Backward compat tests (new):

```python
def test_lazy_prices_v1_still_loads():
    spec = load_spec("lazy_prices_v1")
    assert spec.strategy_id == "lazy_prices_v1"

def test_post_audit_ruleset_v1_still_loads():
    spec = load_spec("post_audit_ruleset_v1")
    assert spec.strategy_id == "post_audit_ruleset_v1"
```

### 11.3 Test fixtures

Helpers added to the test file:
- `minimal_spec()` — minimum-valid spec (currently duplicated across Sprint C/D/E tests; may extract to a shared helper module in Pass 2)
- `minimal_spec_with_ranking()` — minimal valid + `ranking: {}` block
- `minimal_regime_adaptive_spec()` — minimal valid + `position_sizing: {method: regime_adaptive, regimes: {...}}`

### 11.4 Existing test updates

To check during Pass 2:
- `tests/platform/specs/test_schema_final_blocks.py` (266 lines, Sprint E) — may have tests asserting `post_scan.chain` is warn-only. Flip expectations to strict=True.
- Any test that asserts `packet_worthy: bool` — update to `packet_worthy_threshold: int`.

-----

## 12 — Pass 2 handoff — what Pass 2 must verify

1. **Backward compat empirical check.** Load `lazy_prices_v1.yaml` and `post_audit_ruleset_v1.yaml` through `validate_spec`. Confirm both pass post-C.1 changes. Document full spec contents cross-referenced against C.1's 9 items.
2. **Audit existing tests.** Enumerate every test in `tests/platform/specs/` that could conflict with C.1 changes. Propose updates.
3. **Item 6 shape final decision.** Operator confirms band-grammar shape (Pass 1 proposal) vs regime-multiplier shape (prompt example). Pass 2 updates Item 6 design accordingly.
4. **Item 9 scope final decision.** Operator picks Option 9A (docstring) / 9B (runtime edit, anti-goal exception) / 9C (defer to Sprint F).
5. **Fallback semantics for Item 5.** Operator decides: accept semantic gap (Pass 1 recommendation) or add `normalize_on_missing` field (+10 LOC, adds to total).
6. **KNOWN_SCORING_METRICS seed completeness.** Verify the 10-entry seed covers every metric named in Sprint F's `sprint_F_evaluation.md` §6. Extend if needed.
7. **No-runtime-binding restatement.** Confirm C.1 adds no code in `src/ranking/`, `src/features/`, or `src/services/`. Only `src/platform/strategy_spec.py` + test files.

-----

## 13 — What Pass 1 deliberately did not do

- **No code changes to `strategy_spec.py`, `ranker.py`, or any other source file.** Only designed.
- **No spec files created or modified.**
- **No test files created.** Only test cases proposed per item.
- **No commits to runtime.** This is Pass 1 — the doc is the deliverable; Pass 2 follows; Pass 3 implements.
- **No scope creep.** Pass 1 stayed within the 9-item prompt envelope; surfaced flags rather than expanding scope unilaterally.
- **No schema pre-flight against actual specs.** Pass 2 runs `lazy_prices_v1` and `post_audit_ruleset_v1` through the proposed validators empirically.
- **Did not extend Item 9 to change `MACRO_EVENT_TYPES`.** Narrow interpretation flagged for operator; Option 9A proposed.
- **Did not invent a regime-keyed multiplier schema for Item 6.** Pass 1 proposed the band-grammar shape that matches runtime; flagged the prompt deviation for operator.

-----

## 14 — Open questions for operator before Pass 2 starts

1. **Item 6 shape:** band-grammar + clamp (matches runtime) or regime-keyed multiplier (matches prompt example)? Pass 1 proposes the former.
2. **Item 9 scope:** Option 9A (docstring, schema-only), 9B (runtime edit, anti-goal exception), or 9C (defer to Sprint F)? Pass 1 proposes 9A.
3. **Item 5 fallback:** accept semantic gap (Pass 1 recommendation) or add `normalize_on_missing` field to `blend_group` (+10 LOC)?
4. **`packet_worthy` legacy alias:** keep deprecation path (Pass 1 proposal, 3-line alias handling) or hard-rename (2 fewer LOC, 1 less test)?

Pass 2 blocks on these four decisions.
