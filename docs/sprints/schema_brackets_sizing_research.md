# Sprint D Pass 2 — multi-target brackets + regime-adaptive sizing research (#550)

Pass 2 verifies the five assumptions behind Pass 1 before code lands:

1. Incumbent usage counts (backward-compat evidence).
2. `KNOWN_REGIME_KEYS` ≡ `REGIME_THRESHOLDS.keys()` ≡ `classify_regime`
   return set (byte-for-byte match).
3. `classify_regime` has no eighth return key hiding.
4. `spec.raw` consumers do not break on the new optional blocks.
5. File-size budget after implementation stays ≤ 300 lines; test count
   floor stays clear.

## 1. Incumbent usage counts

### 1.1 Strategy specs on main

Grep results against `src/platform/specs/*.yaml`:

| Pattern | Occurrences | Files |
|---------|-------------|-------|
| `^  target:` (exit block, singular) | 2 | `lazy_prices_v1.yaml:50`, `post_audit_ruleset_v1.yaml:78` |
| `^  targets:` (exit block, plural) | 0 | — |
| `method:\s*fixed_pct_equity` | 2 | `lazy_prices_v1.yaml:58`, `post_audit_ruleset_v1.yaml:86` |
| `method:\s*regime_adaptive` | 0 | — |

The non-exit `target:` occurrences in `entry.signal[]` (lines
`lazy_prices_v1.yaml:30, 35`; `post_audit_ruleset_v1.yaml:58, 63`)
refer to 10-K / 10-Q item sections (`item_1a`, `item_7`) — a completely
different concept from bracket targets. They are string values inside
the `entry.signal[]` list and are not touched by any bracket validation.

**Backward-compat surface.** Two specs use the legacy shapes; zero use
the new shapes. The legacy shapes must continue to validate cleanly;
the new shapes are net-new and can be validated tightly.

### 1.2 No strategy spec uses the new keys yet

As expected for a schema-only sprint that ships ahead of its runtime
consumers (Sprints F, G). Pass 3 ships tests that declare the new
shapes in-line, not YAML fixtures — following Sprint C's precedent
(the Sprint C bands test fixture was an in-test dict, not a committed
YAML file).

## 2. Regime-key set verification

### 2.1 Runtime evidence

```
$ python -c "from src.ranking.ranker import REGIME_THRESHOLDS; print(sorted(REGIME_THRESHOLDS.keys()))"
['BEAR_EARLY', 'BEAR_ESTABLISHED', 'BULL_HIGH_VOL', 'BULL_LOW_VOL', 'CORRECTION', 'CRISIS', 'TRANSITION']
```

Seven keys. Identical to the Pass 1 §5.2 `KNOWN_REGIME_KEYS` set.

### 2.2 `classify_regime` returns (regime.py)

```
src/features/regime.py:223:        return "CRISIS"
src/features/regime.py:227:        return "BEAR_ESTABLISHED"
src/features/regime.py:231:        return "BEAR_EARLY"
src/features/regime.py:235:        return "CORRECTION"
src/features/regime.py:239:        return "TRANSITION"
src/features/regime.py:243:        return "BULL_HIGH_VOL"
src/features/regime.py:247:        return "BULL_LOW_VOL"
src/features/regime.py:249:    return "TRANSITION"
```

Eight `return` sites, seven distinct values. Line 249 is the fallback
(`return "TRANSITION"` after all cascading `if`s fall through) — same
key as line 239, not a new one.

**Conclusion.** No eighth regime key. The 7-element set is complete,
matching both `REGIME_THRESHOLDS.keys()` and `classify_regime`'s
codomain.

### 2.3 Schema ↔ runtime alignment

```
strategy_spec.KNOWN_REGIME_KEYS  ⊆ ⊇  REGIME_THRESHOLDS.keys()  ⊆ ⊇  classify_regime.returns
```

All three sets are equal. When Sprint F ports the ranker to read
`position_sizing.regimes` from the spec, the key lookup is direct — no
translation, no case conversion, no normalization.

## 3. `spec.raw` consumer audit

Grep pattern `spec\.raw|\.raw\[|\.raw\.get` across the source tree —
filtered to runtime code paths (docs, superpowers plans, and test
fixtures ignored since they're not load-bearing).

| # | File | Line | Access | Effect of new `exit.targets` / `position_sizing.regimes` |
|---|------|------|--------|--------------------------------------------------------|
| 1 | `src/scheduler/watch.py` | 762 | `spec.raw.get("shadow_cadence_seconds", 600)` | Unaffected — reads one specific key; new top-level/interior keys ignored. |
| 2 | `src/platform/backtest_engine.py` | 187 | `json.dumps(spec.raw, sort_keys=True, default=str)` | **Hash changes when spec declares the new shapes.** This is the *correct* behavior — the reproducibility hash must reflect any config that alters bracket placement or position sizing. Same as Sprint C's ruling for `ranking.bands`. |
| 3 | `src/platform/backtest_persist.py` | 56 | `strategy.raw.get("spec_version", 1)` | Unaffected — specific key. |
| 4 | `src/api/cloud_routes/platform.py` | 108 | `body["spec"] = spec.raw` | Pass-through — extra keys flow through to the JSON response; consumer (frontend) reads only the keys it knows about. |
| 5 | `scripts/backtest/run_walkforward.py` | 157, 167 | `strategy_spec_raw=spec.raw` | Pass-through to persistence. Extra keys ride along. |
| 6 | `scripts/backtest/lazy_prices_smoke_test.py` | 312, 315 | `_run_synthetic_variants(spec.raw, args.db_path)` + `_render_report(summaries, spec.raw, report_path)` | Pass-through. The synthetic variants probably read only entry/exit/universe — new keys are harmless. |

**Net finding.** Identical conclusion to Sprint C's audit: no consumer
breaks. The reproducibility hash captures the new keys, which is
desired (different brackets → different hash → different reproducibility
envelope).

### 3.1 `validate_spec` caller signature check

```
src/platform/strategy_spec.py:149     ok, errors = validate_spec(d)
tests/platform/test_strategy_spec.py:29, 38 + ...  # 7 call sites, all two-tuple unpacks
tests/platform/specs/test_schema_scoring_dsl.py     # 23 call sites, all two-tuple unpacks
```

Pass 1's §7 decision to keep the return shape `(ok, errors)` and
channel warnings through `logger.warning` means **zero call sites
require modification**. Pass 3 test module follows the same
two-tuple-unpack pattern.

### 3.2 Existing negative tests — non-regression check

`tests/platform/test_strategy_spec.py` carries three negative tests
that pass empty dicts for `exit: {}` and `position_sizing: {}`:

- `test_reject_spec_missing_strategy_id` (line 26) — `bad = {..., "exit": {}, "position_sizing": {}, ...}`
- `test_reject_spec_invalid_universe` (line 34) — same.
- `test_load_lazy_prices_yaml_valid` (line 16) — loads real YAML.

With the Pass 1 validator additions:

- `exit: {}` — has no `kind` key. `_validate_exit_brackets` checks
  `kind == "mechanical"` specifically before requiring targets. `None`
  is not `"mechanical"`, so no new error is appended. Existing
  "exit.kind must be one of [...]" error still fires from the
  pre-existing block. The `any("strategy_id" in e for e in errors)`
  / `any("universe" in e for e in errors)` assertions still hold —
  those tests only check for the presence of *some* specific error,
  not for the absence of others.
- `position_sizing: {}` — has no `method` key. `_validate_position_sizing`
  returns early on `method is None` (Pass 1 §8 sketch). No new error.
- Real YAML load — `lazy_prices_v1.yaml` has `exit.kind: mechanical`
  plus `exit.target` (singular) plus `exit.stop` (rich shape). My
  validator sees:
  - `kind == "mechanical"` + `has_target=True` + `has_targets=False` →
    XOR check passes.
  - Interior: `not has_targets: return` → no `exit.targets` entry
    validation, no `stop.atr_multiple` requirement.
  - `fixed_pct_equity` method → early return, no `regimes` check.

  Valid. Test `test_load_lazy_prices_yaml_valid` stays green.

## 4. File-size budget check

### 4.1 Current state

```
$ wc -l src/platform/strategy_spec.py
195 src/platform/strategy_spec.py
```

(Pass 1 cited 196 — the one-line delta is a trailing-newline counting
artifact. Authoritative count is 195.)

Budget: 300. Headroom: 105 lines.

### 4.2 Expected delta (Pass 3 implementation)

Pre-implementation estimate, conservatively padded:

| Addition | Estimated lines |
|----------|-----------------|
| `KNOWN_REGIME_KEYS` frozenset + `ALLOWED_SIZING_METHODS` set | 9 |
| `validate_spec` body additions (2 dispatch calls) | 4 |
| `_validate_exit_brackets` helper | ~55 |
| `_validate_position_sizing` helper | ~45 |
| Blank-line / docstring padding | ~6 |

**Total estimated:** ~119 new lines. 195 → ~314. **14 lines over
budget** in the worst case.

### 4.3 Mitigation plan

Three options, in preference order:

- **A: tighten the helpers.** Current sketch uses verbose inline
  `isinstance(..., bool)` double-guards at every numeric check. Can
  factor into a small `_is_positive_number(x)` / `_is_number_in_unit(x)`
  helper pair — saves ~8 lines across the four numeric checks, and
  clarifies intent.
- **B: combine the regime-entry error messages** by appending to a
  single-per-regime error list and flushing. Saves ~3 lines.
- **C: if A+B insufficient, extract the two helpers to a sibling
  `_validators.py` module** (underscore prefix preserves private API).
  Moves ~100 lines out of the main file; no public API change; no
  behavioral change.

Pass 3 will try A + B first. If post-implementation line count is
≤ 300, no further action. If > 300, apply C.

## 5. Test-count floor

### 5.1 Current count

CI guardrail (CLAUDE.md + `run_ci_locally.ps1`) requires ≥ 1500 tests
(wider than the CLAUDE.md quoted 1339 — `run_ci_locally.ps1` is the
stricter enforcer). No regression allowed.

### 5.2 Sprint D delta

Pass 1 §9 enumerates 29 tests in the new `test_schema_brackets_sizing.py`.
Additive only — no deletion of existing tests.

### 5.3 Effect on neighbours

The existing `tests/platform/test_strategy_spec.py` (9 tests, see §3.2)
and `tests/platform/specs/test_schema_scoring_dsl.py` (23 tests) stay
green per §3.2. No shared fixtures — `_base_spec()` helper is redefined
locally in each test module, following Sprint C's pattern.

`tests/platform/specs/test_post_audit_ruleset_v1.py` (7 tests) loads
the real YAML; covered by §3.2 non-regression analysis.

## 6. Risk register

| Risk | Severity | Mitigation |
|------|----------|------------|
| Existing spec `exit.stop: {method: atr_based, multiplier: 3.0}` (no `atr_multiple` key) gets rejected if validator fires on singular-`target` path | High if triggered | Pass 1 §4.4: `exit.stop.atr_multiple` required **only** when `exit.targets` (plural) is used. Legacy `exit.target` path leaves `exit.stop` untouched. Regression test: #15 `test_lazy_prices_v1_still_loads`. |
| Bool-is-int trap — `packet_worthy: 1` or `atr_multiple: True` passes type check | Medium | Explicit `isinstance(x, bool)` exclusion at every numeric check (per Sprint C precedent). Regression tests: #12 `test_exit_targets_atr_multiple_bool_rejects`, #26 `test_regime_adaptive_position_pct_bool_rejects`, #24 `test_regime_adaptive_packet_worthy_non_bool_rejects`. |
| `float('inf')` / `float('nan')` in `atr_multiple` or `position_pct` sneaks through | Low | Same as Sprint C §6 — out of scope; YAML loader is extremely unlikely to emit these; Sprint F/G port handles via runtime comparison. Noted for Sprint F/G. |
| `position_sizing.method` absent when `position_sizing` present | Low | Pass 1 §8 `_validate_position_sizing` early-returns on `method is None`. Consistent with current permissive treatment of `position_sizing` interior. If Sprint E wants to tighten this, it's a localized change. |
| Sprint F later picks a regime-key convention **other than** `KNOWN_REGIME_KEYS` | Low | Unlikely — Pass 1 §5.2 chose this set specifically because it matches the incumbent runtime lookup. Even if Sprint F diverges, the warn-not-reject policy means existing specs still load (just with noisy warnings). |
| `run_ci_locally.ps1` floor tightens between sprints | Low | Sprint D adds 29 tests (positive delta). Floor regression would require a *decrease* in total tests — Sprint D does not delete any. |

## 7. Sprint F / G preview — port shape

For the record, the downstream runtime consumers will look
approximately like:

```python
# Sprint F — src/ranking/ranker.py::_load_thresholds replacement
regimes_block = spec.raw.get("position_sizing", {}).get("regimes", {})
if regimes_block and regime_type in regimes_block:
    entry = regimes_block[regime_type]
    if not entry["packet_worthy"]:
        return None  # skip — regime disabled
    base["position_pct"] = entry["position_pct"]
    # packet_worthy threshold logic TBD at port time per Pass 1 §5.4

# Sprint G — src/packets/template.py::build_packet_from_features replacement
targets_block = spec.raw.get("exit", {}).get("targets", [])
stop_mult = spec.raw.get("exit", {}).get("stop", {}).get("atr_multiple", 2.0)
stop_price = price - stop_mult * atr
target_prices = {t["name"]: price + t["atr_multiple"] * atr for t in targets_block}
# "targets" display string built by joining target_prices in list order
```

Both ports are one-for-one with the declared shape; no translation
layer. Schema absent → runtime falls back to current hardcoded logic
(or — per sprint design — raises if a strategy spec is missing the
declaration once the port is the single source of truth).

## 8. Ready for Pass 3

All five Pass-2 verifications pass:

- ✅ Incumbent usage counts: 2 `exit.target` singular, 0 `exit.targets`
  plural, 2 `fixed_pct_equity`, 0 `regime_adaptive`. New shapes are
  net-new; legacy shapes untouched.
- ✅ `KNOWN_REGIME_KEYS` byte-equal to `REGIME_THRESHOLDS.keys()` and
  to `classify_regime` return-set.
- ✅ Zero `spec.raw` consumers break on new optional blocks;
  reproducibility hash-change is intentional.
- ✅ File-size budget achievable with A+B tightening; escalation to C
  (helper extraction) available if needed.
- ✅ Test count strictly additive (+29).

Proceed to Pass 3: implement the two helpers, write the 29-test module,
update CHANGELOG + MASTER, run `scripts/run_ci_locally.ps1` green.
