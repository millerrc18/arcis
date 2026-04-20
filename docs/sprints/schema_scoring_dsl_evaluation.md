# Sprint C Pass 1 — scoring-DSL schema block evaluation (#549)

**Sprint:** feat/schema-scoring-dsl (third of 8 in #530 chain).
**Branch:** `claude/extend-scoring-dsl-MyYQl`.
**Target:** extend `src/platform/strategy_spec.py::validate_spec` to validate
an optional `ranking.bands` block so later sprints (F: ranker port) can
consume a declared scoring DSL instead of the hardcoded bands currently
living in `src/ranking/ranker.py::_score_ticker`.

This is a **schema-only** sprint. No runtime consumer — validation gates
malformed specs before they reach the ranker port in Sprint F.

## 1. Reference read — current `validate_spec` structure (strategy_spec.py:46–81)

| Block | Line(s) | Behavior |
|-------|---------|----------|
| Required keys | 48–50 | Loop over `REQUIRED_KEYS` tuple; append `"missing required key: {k}"` per miss. |
| `universe` shape | 51–58 | Type-check dict; `sector_filter` must be non-empty list of strings if present. |
| `entry.kind` | 59–64 | Must be in `ALLOWED_ENTRY_KINDS`. |
| `entry.event_exclusion` | 65–74 | Optional dict; `categories` must be non-empty list of strings. |
| `exit.kind` | 75–80 | Must be in `ALLOWED_EXIT_KINDS`. |
| Return | 81 | `(ok: bool, errors: list[str])`. |

**Observed pattern.** Validation is a **single flat function** with
sequential `if` blocks, each guarded with `if X in spec and isinstance(...)`.
No nested validator functions exist today. Errors are accumulated into a
single list; a warning channel does not exist in the return contract.

**File size.** 131 lines. Budget per sprint prompt: ≤250. Plenty of room.

## 2. Reference read — incumbent ranker bands (ranker.py:165–220)

The ranker's `_score_ticker` today hardcodes bands that match the sprint-C
shape exactly:

```python
# pullback_depth_pct bands
if -8 <= pullback <= -3:      score += 25
elif -12 <= pullback < -8:    score += 10

# dist_to_sma20_pct band
if -5 <= dist_sma20 <= -1:    score += 10

# volume_ratio_20d band
if vol_ratio < 0.8:           score += 15
```

**Shape confirmation.** The YAML grammar in the sprint prompt —
`{metric, range: [lo, hi], score}` — is a direct serialization of these
Python conditionals. The incumbent uses **closed intervals** (`<=` on both
sides) in most cases, with one mixed-closure (`< -8` on the second pullback
band to avoid double-count at -8 exactly). For schema purposes we treat
ranges uniformly as `[lower, upper]` with `lower < upper` and punt
inclusivity semantics to Sprint F's runtime port (both endpoints inclusive
is the sensible default; the sprint prompt's `[-8, -3]` / `[-12, -8]` pair
shows the caller expects Sprint F to resolve the -8 boundary as "first band
wins" or to tighten the ranges).

The sprint-F port therefore just needs to iterate `ranking.bands` and apply
each band if `range[0] <= metric_value <= range[1]` (plus a tie-break).

## 3. Decision — validation placement

**Decision: keep it flat, same function.** No nested validator module.

Rationale:
- Current validator is 36 lines of flat `if` blocks. Adding a bands block
  adds ~25 lines → 131 total function, still well under any split threshold.
- Inventing a `_validate_ranking(spec, errors, warnings)` sub-function now
  is premature abstraction — there's only one caller. If Sprint D (brackets)
  or Sprint E adds a second validator of comparable size, extract then.
- Keeps diff small and review-surface small — this is the most
  regression-sensitive sprint in the chain (backward compat is the main
  deliverable, not new features).

**Location inside `validate_spec`:** after the `exit.kind` block (line 80),
before the final `return`. `ranking` is an optional top-level key on par
with `llm_enhancement` — it is not nested inside `entry` or `exit`.

## 4. Decision — overlap-warning mechanism

Two options considered:

| Option | Pros | Cons |
|--------|------|------|
| **A: log via `logger.warning`** | Zero API change; existing callers don't touch warnings; matches `list_available_specs` "skipping malformed" style | Invisible to unit tests unless they use `caplog`; not embedded in spec metadata |
| **B: extend `validate_spec` return to `(ok, errors, warnings)`** | Explicit warning surface; testable without log capture | **Breaks every existing call site** (`_from_dict`, every test that unpacks `ok, errors = validate_spec(...)`) |

**Decision: A (log).** Backward compat is the top priority for this
sprint. The sprint prompt explicitly says "warn, don't reject" — it does
not require a structured warning channel. Tests assert via `caplog` (same
pattern used in `test_list_available_specs_warns_on_malformed_yaml`).

Log line format:
```
[PLATFORM] ranking.bands overlap: metric=<m> band#<i>[a,b] overlaps band#<j>[c,d]
```

Prefix `[PLATFORM]` matches existing convention in `list_available_specs`
(strategy_spec.py:128). Logger already configured at module top.

## 5. Decision — range comparison semantics for overlap detection

Given bands A=`[a_lo, a_hi]` and B=`[b_lo, b_hi]` (same metric), overlap iff
`a_lo <= b_hi AND b_lo <= a_hi` (standard closed-interval overlap). Touching
at a single point (e.g. `[-12, -8]` vs `[-8, -3]`) counts as overlap here —
the incumbent ranker uses a half-open workaround at -8, which *is* the kind
of ambiguity the warning is meant to surface. If the operator wants a clean
partition they tighten to `[-12, -8.01]` / `[-8, -3]`.

(This is the conservative choice; Sprint F can refine if the warning proves
too noisy.)

## 6. Implementation sketch

```python
# Added to validate_spec, after the exit.kind block:
if "ranking" in spec:
    ranking = spec["ranking"]
    if not isinstance(ranking, dict):
        errors.append("ranking must be a dict when present")
    elif "bands" in ranking:
        bands = ranking["bands"]
        if not isinstance(bands, list):
            errors.append("ranking.bands must be a list when present")
        else:
            _validate_bands(bands, errors)  # local helper below

# New module-level helper (not exported):
def _validate_bands(bands: list, errors: list[str]) -> None:
    parsed: list[tuple[str, float, float, int]] = []  # (metric, lo, hi, idx)
    for i, band in enumerate(bands):
        if not isinstance(band, dict):
            errors.append(f"ranking.bands[{i}] must be a dict")
            continue
        metric = band.get("metric")
        if not isinstance(metric, str) or not metric:
            errors.append(f"ranking.bands[{i}].metric must be a non-empty string")
            continue
        rng = band.get("range")
        if (not isinstance(rng, list) or len(rng) != 2
                or not all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in rng)):
            errors.append(
                f"ranking.bands[{i}].range must be a 2-element list of numerics"
            )
            continue
        lo, hi = rng
        if lo >= hi:
            errors.append(
                f"ranking.bands[{i}].range[0] must be < range[1] (got {lo} >= {hi})"
            )
            continue
        score = band.get("score")
        if not isinstance(score, (int, float)) or isinstance(score, bool):
            errors.append(
                f"ranking.bands[{i}].score must be numeric"
            )
            continue
        parsed.append((metric, float(lo), float(hi), i))

    # Overlap check (warn only)
    by_metric: dict[str, list[tuple[float, float, int]]] = {}
    for metric, lo, hi, idx in parsed:
        by_metric.setdefault(metric, []).append((lo, hi, idx))
    for metric, entries in by_metric.items():
        for a_idx in range(len(entries)):
            a_lo, a_hi, a_i = entries[a_idx]
            for b_idx in range(a_idx + 1, len(entries)):
                b_lo, b_hi, b_i = entries[b_idx]
                if a_lo <= b_hi and b_lo <= a_hi:
                    logger.warning(
                        "[PLATFORM] ranking.bands overlap: metric=%s "
                        "band#%d[%s,%s] overlaps band#%d[%s,%s]",
                        metric, a_i, a_lo, a_hi, b_i, b_lo, b_hi,
                    )
```

**Line delta estimate.** ~55 new lines (10 in `validate_spec` body + 45 in
`_validate_bands`). Total: 131 → ~186. Under the 250-line budget with 64
lines of headroom for Sprints D/E.

**`bool` filter note.** Python's `isinstance(True, int)` is `True`, so
numeric validation must exclude `bool` explicitly — otherwise a YAML `true`
in `range` or `score` passes typecheck. Cheap to add, easy to forget.

## 7. Test plan — `tests/platform/specs/test_schema_scoring_dsl.py`

| # | Name | Setup | Assertion |
|---|------|-------|-----------|
| 1 | `test_valid_bands_spec_loads` | Minimal valid spec + `ranking.bands` with two bands on different metrics. | `validate_spec → (True, [])`. |
| 2 | `test_bands_missing_metric_rejects` | Band dict omits `metric`. | `ok=False`; error mentions `metric`. |
| 3 | `test_bands_missing_range_rejects` | Band dict omits `range`. | `ok=False`; error mentions `range`. |
| 4 | `test_bands_range_lower_ge_upper_rejects` | `range: [5, 5]` (equal) and `range: [5, 3]` (inverted). | Both rejected with `< range[1]` error. |
| 5 | `test_bands_range_non_numeric_rejects` | `range: ["a", 3]`. | `ok=False`; range error. |
| 6 | `test_bands_score_non_numeric_rejects` | `score: "twenty-five"`. | `ok=False`; score error. |
| 7 | `test_bands_score_bool_rejects` | `score: True` (bool-is-int trap). | `ok=False`; score error. |
| 8 | `test_bands_overlapping_warns_not_rejects` | Two bands on same metric: `[-8,-3]` and `[-5,0]`. | `validate_spec → (True, [])`; `caplog` captures `[PLATFORM] ranking.bands overlap`. |
| 9 | `test_bands_multiple_per_metric_allowed` | Two non-overlapping bands on same metric: `[-12,-8]` and `[-3,0]`. | `(True, [])`; no warning. |
| 10 | `test_bands_float_score_allowed` | `score: 12.5`. | `(True, [])`. |
| 11 | `test_ranking_not_dict_rejects` | `ranking: "bands"` (string). | `ok=False`; "ranking must be a dict". |
| 12 | `test_ranking_bands_not_list_rejects` | `ranking: {bands: "foo"}`. | `ok=False`; "ranking.bands must be a list". |
| 13 | `test_bands_empty_list_allowed` | `ranking: {bands: []}`. | `(True, [])` — degenerate but well-formed. |
| 14 | `test_lazy_prices_still_loads` | Load `lazy_prices_v1.yaml` via `load_spec_from_yaml`. | Returns `StrategySpec`; no exception. |
| 15 | `test_post_audit_ruleset_still_loads` | Load `post_audit_ruleset_v1.yaml`. | Returns `StrategySpec`; no exception. |
| 16 | `test_ranking_weights_still_loads` | Spec with `ranking: {weights: {...}}` (hypothetical existing shape — no `bands` key). | `(True, [])` — unknown sub-keys under `ranking` are ignored. |

Fixtures: minimal spec dict builder — a `_base_spec()` helper in the test
module returning a dict with all `REQUIRED_KEYS`, so each test only has to
splice the `ranking` block in.

## 8. Guardrails check

- [x] No runtime consumption — validation only. `_from_dict` uses
      `validate_spec`'s return unchanged; `StrategySpec` dataclass is not
      modified; `.raw` already retains the full dict for Sprint F to read.
- [x] No modification to existing signal validation (`entry.signal`
      block — not touched).
- [x] No change to `entry.signal[]` shape.
- [x] File-size budget: 131 → ~186 lines. Under 250.
- [x] Backward compat: `lazy_prices_v1.yaml` and `post_audit_ruleset_v1.yaml`
      have no `ranking` key — new block is absent → no validation runs.
- [x] `ranking.weights` (a hypothetical alternate existing shape) is not
      rejected — only `ranking.bands` is validated; other sub-keys under
      `ranking` pass through unchecked. Confirmed no spec on main uses
      either `ranking.bands` or `ranking.weights` (grep `ranking:` on
      `src/platform/specs/*.yaml` returns zero).

## 9. Next

Pass 2 research:
1. Audit all existing specs on main for any `ranking` key usage (expect
   zero — already grep-confirmed but re-verify across `tests/**/*.yaml`
   and `configs/` if applicable).
2. Re-read `ranker.py::_score_ticker` bands (pullback, dist_to_sma20,
   volume_ratio) and tabulate the incumbent → DSL mapping to confirm the
   Sprint F port has a direct one-to-one target.
3. Identify spec consumers that read `spec.raw` directly — they must not
   break on a new `ranking.bands` key. Likely zero (raw is pass-through).
