# Sprint D Pass 1 — multi-target brackets + regime-adaptive sizing schema (#550)

**Sprint:** feat/schema-brackets-sizing (fourth of 8 in #530 chain).
**Branch:** `feat/schema-brackets-sizing`.
**Target:** extend `src/platform/strategy_spec.py::validate_spec` with two
additive blocks — an alternative `exit.targets[]` list-form shape (alongside
the existing singular `exit.target`) and a `position_sizing.method:
regime_adaptive` option (alongside the existing `fixed_pct_equity`). Later
sprints (F: ranker port, G: exit port) will consume these. This sprint is
**schema-only** — no runtime.

Sprint C (scoring-DSL `ranking.bands`) is merged on main (commit `7093d19`,
PR #560); the current `strategy_spec.py` is 196 lines with the `_validate_bands`
helper already in place. Budget per sprint prompt: `strategy_spec.py` stays
under **300 lines** after C + D combined — ~104 lines of headroom.

## 1. Reference read — existing `exit` + `position_sizing` shapes

### 1.1 `lazy_prices_v1.yaml` + `post_audit_ruleset_v1.yaml` (both specs on main)

```yaml
exit:
  kind: mechanical
  timeout_days: 21
  stop:
    method: atr_based
    atr_period: 14
    multiplier: 3.0
    floor_pct: 0.05
    cap_pct: 0.12
  target:                       # ← singular, rich shape
    method: atr_based
    atr_period: 14
    multiplier: 6.0
    floor_pct: 0.10
    cap_pct: 0.25

position_sizing:
  method: fixed_pct_equity      # ← existing shape
  pct: 0.15
  max_concurrent: 5
```

Both strategy specs on main use this shape. Grep confirmation:

- `grep "method:\s*fixed_pct_equity" src/platform/specs/*.yaml` → 2 hits
  (lazy_prices, post_audit).
- `grep "^\s+target:" src/platform/specs/*.yaml` → 2 hits (both are the
  singular `exit.target` block — the other `target:` occurrences are inside
  `entry.signal[]` referencing 10-K item sections, not bracket targets).
- `grep "^\s+targets:" src/platform/specs/*.yaml` → 0 hits. Plural form is
  **net-new**.

### 1.2 Existing `validate_spec` treatment

From Sprint C's state (strategy_spec.py:75–81):

```python
if "exit" in spec and isinstance(spec["exit"], dict):
    kind = spec["exit"].get("kind")
    if kind not in ALLOWED_EXIT_KINDS:
        errors.append(...)
```

Only `exit.kind` is validated. The interior (`exit.stop`, `exit.target`,
`exit.timeout_days`) is **unvalidated** and flows through unexamined via
`spec.raw`. Likewise `position_sizing` is listed as a `REQUIRED_KEYS` entry
but its interior (`method`, `pct`, `max_concurrent`) is also unvalidated.

**This is the crucial backward-compat lever.** The existing interior shapes
are not tested by the validator today. The new validation can therefore
restrict itself to the *new* keys (`exit.targets[]`, `regime_adaptive`
block) without accidentally tightening or rejecting the legacy shapes.

## 2. Reference read — incumbent multi-target brackets (`packets/template.py`)

The live scan pipeline computes two targets deterministically
(`packets/template.py:71–76`):

```python
stop_price = price - stop_distance    # stop_distance = 2 * atr (or price * 0.03 fallback)
target_1 = price + 1.5 * atr
target_2 = price + 3.0 * atr
targets = f"${target_1:.2f} / ${target_2:.2f}"
```

Two targets per position, each an ATR multiple of entry price. Render
layer at `template.py:190` folds them into a single human-readable
"targets" string — but the underlying numbers are two distinct levels
(1.5·ATR and 3·ATR). This is exactly the shape the sprint prompt's
`exit.targets[]` DSL serializes.

The simulation engine (`simulation/engine.py:89–93`) uses a
**VIX-regime-adaptive** single-target bracket table — that diverges from
the live pipeline and is out of scope for this sprint (the "incumbent" per
the #523 blocker inventory is the live pipeline, not the sim engine).

**Conclusion.** The incumbent has two targets at `1.5·ATR` and `3·ATR`.
The Sprint-F/G port target is:

```yaml
exit:
  targets:
    - name: target_1
      atr_multiple: 1.5
    - name: target_2
      atr_multiple: 3.0
  stop:
    atr_multiple: 2.0
```

No spec on main declares this shape yet — it's the future state the
schema must accept.

## 3. Reference read — incumbent regime + sizing (`ranker.py`, `regime.py`)

### 3.1 `REGIME_THRESHOLDS` (ranker.py:17–25)

```python
REGIME_THRESHOLDS = {
    "BULL_LOW_VOL":     {"packet_worthy": 40, "position_pct": 1.0},
    "BULL_HIGH_VOL":    {"packet_worthy": 50, "position_pct": 0.85},
    "TRANSITION":       {"packet_worthy": 60, "position_pct": 0.70},
    "CORRECTION":       {"packet_worthy": 65, "position_pct": 0.60},
    "BEAR_EARLY":       {"packet_worthy": 75, "position_pct": 0.40},
    "BEAR_ESTABLISHED": {"packet_worthy": 80, "position_pct": 0.30},
    "CRISIS":           {"packet_worthy": 90, "position_pct": 0.20},
}
```

Seven keys. `packet_worthy` is a ranker-score threshold (0–100 scale);
`position_pct` is a sizing multiplier (0.0–1.0). No `packet_worthy: false`
concept here — every regime is tradeable, just with different thresholds
and haircuts.

Activated from `ranker.py:56–67` when `config["regime_adaptive"]["enabled"]
== True`. Regime label comes from `classify_regime(sample_feat)`
(regime.py:188–249), which returns one of the seven uppercase keys.

### 3.2 Relationship to the Sprint-D schema

The sprint prompt's example uses a different shape:

```yaml
regimes:
  bull: {packet_worthy: true, position_pct: 0.05}
  cautious: {packet_worthy: true, position_pct: 0.03}
  bear: {packet_worthy: false, position_pct: 0.0}
```

Two meaningful differences vs incumbent:

- **`packet_worthy` is a bool in the prompt, a numeric threshold in
  incumbent.** The prompt's bool ("is this regime allowed to trade at
  all?") is a simpler runtime concept: if false, skip new entries. The
  incumbent's numeric threshold is a finer knob. These are **compatible
  at the schema level** — a bool is a different field and different
  semantics from a numeric threshold. The schema can accept the bool
  without interfering with the incumbent table (Sprint F resolves the
  semantic reconciliation).

- **`position_pct` range diverges.** The prompt uses 0.05 / 0.03 / 0.0
  (fraction of equity per trade — matches `fixed_pct_equity.pct`), while
  the incumbent `REGIME_THRESHOLDS.position_pct` uses 1.0 / 0.85 / ...
  (a **multiplier** applied to the base risk). Both are floats in
  [0.0, 1.0], so the schema doesn't need to distinguish — but this is a
  **semantic flag** worth noting for Sprint F: the spec-author
  declaration (prompt shape) reads as "position_pct = absolute size
  fraction"; the incumbent table is "position_pct = relative
  multiplier". Sprint F must pick a convention and document it at port
  time. Schema's job is just to accept the number.

### 3.3 Regime label namespaces on main

There are **three** regime-label namespaces in the codebase:

| Namespace | Source | Keys |
|-----------|--------|------|
| **5-label descriptive** | `compute_market_regime` (regime.py:79–185) | `calm_uptrend`, `volatile_uptrend`, `calm_downtrend`, `volatile_downtrend`, `transitional` |
| **7-label categorical** | `classify_regime` (regime.py:188–249) | `BULL_LOW_VOL`, `BULL_HIGH_VOL`, `TRANSITION`, `CORRECTION`, `BEAR_EARLY`, `BEAR_ESTABLISHED`, `CRISIS` |
| **Prompt's abstract set** | sprint prompt only | `bull`, `cautious`, `bear`, `strong_bull`, `volatile`, `recovery`, `unknown` |

The first two are live. The third appears only in the sprint prompt as
illustration and does not match any live consumer.

## 4. Decision — `exit.target` XOR `exit.targets` enforcement

### 4.1 Scope of enforcement

**Decision: enforce XOR only when `exit.kind == "mechanical"`. Do not
enforce when `exit.kind == "python_plugin"`.**

Rationale:

- `python_plugin` exit kind means the plugin owns bracket logic end-to-end
  (per `ALLOWED_EXIT_KINDS` + the Sprint B python_plugin wiring). The
  spec author may legitimately omit both `target` and `targets` —
  brackets live in Python, not YAML.
- `mechanical` exit kind needs the bracket levels in YAML — some
  declaration of targets is mandatory. Exactly one is required so the
  runtime does not have to pick when both are present.

### 4.2 Semantics

| Case | `exit.target` | `exit.targets` | `exit.kind` | Validator |
|------|---------------|----------------|-------------|-----------|
| A | present | absent | `mechanical` | pass (legacy happy path) |
| B | absent | present | `mechanical` | pass (new happy path) |
| C | present | present | `mechanical` | **reject** (`exit.target` and `exit.targets` are mutually exclusive) |
| D | absent | absent | `mechanical` | **reject** (`exit` requires one of `target` or `targets`) |
| E | any | any | `python_plugin` | pass (plugin owns brackets) |
| F | absent | absent | `python_plugin` | pass |

Error messages (for C and D):

```
exit: 'target' and 'targets' are mutually exclusive — specify one
exit: mechanical kind requires one of 'target' or 'targets'
```

### 4.3 Interior validation of the new `exit.targets[]` list

Validate the new shape tightly (it is net-new — no backward-compat risk):

- `exit.targets` must be a non-empty list.
- Each entry is a dict with:
  - `name`: non-empty string.
  - `atr_multiple`: numeric (int or float, not bool), strictly `> 0`.
- `name` values must be unique across the list.

Interior validation of `exit.target` (singular, legacy): **unchanged —
none.** The existing specs already pass the current un-validated block
and we must not start rejecting them. Sprint prompt guardrail: "No
changes to `exit.target` or `fixed_pct_equity` shapes."

### 4.4 `exit.stop.atr_multiple` when `exit.targets` is used

Sprint prompt requirement: "`stop.atr_multiple` required if `exit.targets`
used (existing `exit.stop_atr_multiple` shape preserved for `exit.target`)."

Interpretation: when the spec uses the new plural `exit.targets`, it
should also declare stop distance in the matching flat shape
(`exit.stop: {atr_multiple: <float>}`). When it uses the legacy
`exit.target`, leave `exit.stop` unchecked — same pass-through as today.

Validator decision:

- If `exit.targets` present AND `exit.kind == "mechanical"`: require
  `exit.stop` to be a dict containing a numeric `atr_multiple > 0`.
- If `exit.target` present (legacy): do not validate `exit.stop`
  interior. Existing rich shape (`method: atr_based`, `multiplier`, ...)
  passes through as before.

## 5. Decision — regime key enum

### 5.1 Enum source candidates

| Option | Source | Notes |
|--------|--------|-------|
| A | Sprint prompt's abstract set — `{bull, cautious, bear, strong_bull, volatile, recovery, unknown}` | Does not match any live consumer. 7 elements. |
| B | Incumbent `classify_regime` 7-label set — `{BULL_LOW_VOL, BULL_HIGH_VOL, TRANSITION, CORRECTION, BEAR_EARLY, BEAR_ESTABLISHED, CRISIS}` | Matches `REGIME_THRESHOLDS` keys exactly. 7 elements. Sprint F port consumes this set. |
| C | Union of A + B (case-insensitive) | 14 distinct keys. Permissive but encodes neither side's convention. |
| D | Config-driven — validator takes allowed set as a function argument | Pushes the list to settings.yaml. Too flexible for a schema-only sprint. |

### 5.2 Decision: **Option B — incumbent 7-label categorical set.**

```python
KNOWN_REGIME_KEYS = frozenset({
    "BULL_LOW_VOL",
    "BULL_HIGH_VOL",
    "TRANSITION",
    "CORRECTION",
    "BEAR_EARLY",
    "BEAR_ESTABLISHED",
    "CRISIS",
})
```

Rationale:

- The downstream consumer (Sprint F — ranker port) already uses these
  exact keys as the `REGIME_THRESHOLDS` lookup. Using the schema's
  allowed set identical to the runtime's lookup keys means *zero*
  translation when porting; any other choice introduces a mapping
  layer.
- The sprint prompt's example set is illustrative — the prompt itself
  says "warn on unknown keys, don't reject", implying the set is not
  load-bearing. Warning, not rejection, means a spec that uses the
  prompt's names still loads; it just logs a warning line per unknown
  key at load time.
- A case-insensitive match (Option C) silently absorbs typos — if a spec
  author writes `bull_low_vol` (lowercase), it would be accepted without
  the authors noticing the case convention. Warn-on-unknown (per prompt)
  with a strict 7-key set catches this at the warning stage and the
  operator can fix.
- Config-driven (Option D) is over-engineering for Sprint D's remit.
  Can add later if a second regime classifier ships.

### 5.3 Warn-on-unknown, don't reject

Per sprint prompt. Implemented the same way as Sprint C's bands-overlap
warning — via `logger.warning`, not the return signature. Preserves
`validate_spec(spec) → (ok, errors)` backward compat. Tests assert via
`caplog`.

Log line format:

```
[PLATFORM] position_sizing.regimes: unknown regime key <key> (known: BEAR_EARLY, BEAR_ESTABLISHED, BULL_HIGH_VOL, BULL_LOW_VOL, CORRECTION, CRISIS, TRANSITION)
```

One warning per unknown key per spec load. `known:` list is sorted for
deterministic log output (helpful for test assertions).

### 5.4 Interior validation of a regime entry

- `packet_worthy`: must be present; must be a bool. Rejecting numerics
  here (incumbent threshold style) is a **deliberate scope limitation**
  — the sprint prompt's shape is bool-only; numeric thresholds would be
  a separate schema addition and would conflict with the bool/numeric
  overloading described in §3.2. Sprint F port will map the bool to
  "override `packet_worthy_threshold` with 0 if true else 999" or
  equivalent; the schema doesn't need to know.
- `position_pct`: must be present; must be numeric (int or float, not
  bool); must satisfy `0.0 <= position_pct <= 1.0`.

## 6. Decision — validation placement

**Decision: keep one flat function — `validate_spec`.** Extract two local
helpers (`_validate_exit_brackets`, `_validate_position_sizing`) to keep
the function body readable without promoting them to a module
(matches Sprint C's `_validate_bands` pattern).

Placement order inside `validate_spec`:

1. Required keys (existing).
2. Universe (existing).
3. Entry (existing).
4. Exit kind (existing) → **immediately after: call `_validate_exit_brackets`
   if `exit` is a dict** (adds target/targets/stop checks).
5. Ranking bands (Sprint C).
6. **New: call `_validate_position_sizing`** after ranking bands.
7. Return.

Line-delta estimate (per §9):

- `validate_spec` body additions: ~10 lines.
- `_validate_exit_brackets` helper: ~45 lines.
- `_validate_position_sizing` helper: ~40 lines.
- `KNOWN_REGIME_KEYS` constant: ~10 lines.
- **Total: ~105 new lines.** Current 196 → estimated 301.

This **exceeds the 300-line budget by 1 line.** Mitigation: the helper
implementations can be tightened (combine adjacent checks, drop a couple
of blank lines). A realistic target is 295–298 lines post-D. Pass 2
confirms the exact number after implementation; if tight, the helpers
move to a sibling `_validators.py` file (no public API change — both are
underscore-prefixed). Preferred: keep in-file and tighten.

## 7. Decision — error-message style

Match Sprint C's existing pattern. Errors are prefixed with the JSON path
to the offending field:

- `exit: 'target' and 'targets' are mutually exclusive — specify one`
- `exit: mechanical kind requires one of 'target' or 'targets'`
- `exit.targets must be a non-empty list when present`
- `exit.targets[0] must be a dict`
- `exit.targets[0].name must be a non-empty string`
- `exit.targets[0].atr_multiple must be a positive number`
- `exit.targets[0].name duplicates exit.targets[1].name`
- `exit.stop.atr_multiple must be a positive number (required when exit.targets is used)`
- `position_sizing.method must be one of ['fixed_pct_equity', 'regime_adaptive']`
- `position_sizing.regimes must be a non-empty dict when method == regime_adaptive`
- `position_sizing.regimes[bull].packet_worthy must be a bool`
- `position_sizing.regimes[bull].position_pct must be a number in [0.0, 1.0]`

## 8. Implementation sketch

```python
# strategy_spec.py — additions

KNOWN_REGIME_KEYS = frozenset({
    "BULL_LOW_VOL", "BULL_HIGH_VOL", "TRANSITION", "CORRECTION",
    "BEAR_EARLY", "BEAR_ESTABLISHED", "CRISIS",
})

ALLOWED_SIZING_METHODS = {"fixed_pct_equity", "regime_adaptive"}


def validate_spec(spec: dict) -> tuple[bool, list[str]]:
    errors: list[str] = []
    # ... existing REQUIRED_KEYS / universe / entry / exit.kind checks ...

    if "exit" in spec and isinstance(spec["exit"], dict):
        kind = spec["exit"].get("kind")
        if kind not in ALLOWED_EXIT_KINDS:
            errors.append(...)
        _validate_exit_brackets(spec["exit"], errors)  # ← NEW

    # ... existing ranking.bands check ...

    if "position_sizing" in spec and isinstance(spec["position_sizing"], dict):
        _validate_position_sizing(spec["position_sizing"], errors)  # ← NEW

    return (len(errors) == 0, errors)


def _validate_exit_brackets(exit_block: dict, errors: list[str]) -> None:
    kind = exit_block.get("kind")
    has_target = "target" in exit_block
    has_targets = "targets" in exit_block

    if kind == "mechanical":
        if has_target and has_targets:
            errors.append("exit: 'target' and 'targets' are mutually exclusive — specify one")
            return
        if not has_target and not has_targets:
            errors.append("exit: mechanical kind requires one of 'target' or 'targets'")
            return

    if not has_targets:
        return  # legacy singular exit.target — no interior checks

    targets = exit_block["targets"]
    if not isinstance(targets, list) or not targets:
        errors.append("exit.targets must be a non-empty list when present")
        return

    seen_names: dict[str, int] = {}
    for i, entry in enumerate(targets):
        if not isinstance(entry, dict):
            errors.append(f"exit.targets[{i}] must be a dict")
            continue
        name = entry.get("name")
        if not isinstance(name, str) or not name:
            errors.append(f"exit.targets[{i}].name must be a non-empty string")
        elif name in seen_names:
            errors.append(
                f"exit.targets[{i}].name duplicates exit.targets[{seen_names[name]}].name"
            )
        else:
            seen_names[name] = i
        mult = entry.get("atr_multiple")
        if not isinstance(mult, (int, float)) or isinstance(mult, bool) or mult <= 0:
            errors.append(f"exit.targets[{i}].atr_multiple must be a positive number")

    # stop.atr_multiple required when using plural targets[]
    stop = exit_block.get("stop")
    if not isinstance(stop, dict):
        errors.append(
            "exit.stop must be a dict with 'atr_multiple' when exit.targets is used"
        )
        return
    stop_mult = stop.get("atr_multiple")
    if not isinstance(stop_mult, (int, float)) or isinstance(stop_mult, bool) or stop_mult <= 0:
        errors.append(
            "exit.stop.atr_multiple must be a positive number (required when exit.targets is used)"
        )


def _validate_position_sizing(sizing: dict, errors: list[str]) -> None:
    method = sizing.get("method")
    if method is None:
        return  # required-keys check already flagged absence of position_sizing itself;
                # a missing method here is a soft absence we do not escalate.
    if method not in ALLOWED_SIZING_METHODS:
        errors.append(
            f"position_sizing.method must be one of {sorted(ALLOWED_SIZING_METHODS)}, got {method!r}"
        )
        return
    if method != "regime_adaptive":
        return  # fixed_pct_equity passes through — existing shape unvalidated (backward compat)

    regimes = sizing.get("regimes")
    if not isinstance(regimes, dict) or not regimes:
        errors.append(
            "position_sizing.regimes must be a non-empty dict when method == 'regime_adaptive'"
        )
        return
    for rkey, rval in regimes.items():
        if rkey not in KNOWN_REGIME_KEYS:
            logger.warning(
                "[PLATFORM] position_sizing.regimes: unknown regime key %r (known: %s)",
                rkey, ", ".join(sorted(KNOWN_REGIME_KEYS)),
            )
        if not isinstance(rval, dict):
            errors.append(f"position_sizing.regimes[{rkey}] must be a dict")
            continue
        pw = rval.get("packet_worthy")
        if not isinstance(pw, bool):
            errors.append(
                f"position_sizing.regimes[{rkey}].packet_worthy must be a bool"
            )
        pp = rval.get("position_pct")
        if (
            not isinstance(pp, (int, float))
            or isinstance(pp, bool)
            or not (0.0 <= pp <= 1.0)
        ):
            errors.append(
                f"position_sizing.regimes[{rkey}].position_pct must be a number in [0.0, 1.0]"
            )
```

## 9. Test plan — `tests/platform/specs/test_schema_brackets_sizing.py`

Fixture: a `_base_spec()` helper returning a minimal valid spec
(identical to the Sprint C test module's helper). Each test splices the
`exit` / `position_sizing` blocks it wants to exercise.

### Block 1 — multi-target brackets

| # | Name | Setup | Assertion |
|---|------|-------|-----------|
| 1 | `test_exit_targets_list_form_loads` | Valid `exit.targets` list with 2 entries + `exit.stop: {atr_multiple: 2.0}`. | `ok=True, errors=[]`. |
| 2 | `test_exit_target_singular_still_loads` | Legacy `exit.target: {method: atr_based, multiplier: 6.0, ...}` + `exit.stop: {method: atr_based, multiplier: 3.0}`. | `ok=True, errors=[]` (no interior validation of singular). |
| 3 | `test_exit_both_target_and_targets_rejects` | Both `exit.target` and `exit.targets` present with `kind: mechanical`. | `ok=False`; error contains `mutually exclusive`. |
| 4 | `test_exit_neither_target_nor_targets_rejects` | `exit.kind: mechanical` with neither. | `ok=False`; error contains `requires one of`. |
| 5 | `test_exit_python_plugin_allows_neither` | `exit.kind: python_plugin` with no `target`/`targets`. | `ok=True, errors=[]`. |
| 6 | `test_exit_targets_empty_list_rejects` | `exit.targets: []`. | `ok=False`; `non-empty list`. |
| 7 | `test_exit_targets_entry_missing_name_rejects` | `exit.targets: [{atr_multiple: 1.5}]`. | `ok=False`; `name`. |
| 8 | `test_exit_targets_entry_missing_atr_multiple_rejects` | `exit.targets: [{name: 't1'}]`. | `ok=False`; `atr_multiple`. |
| 9 | `test_exit_targets_duplicate_names_rejects` | `exit.targets: [{name: t1, ...}, {name: t1, ...}]`. | `ok=False`; `duplicates`. |
| 10 | `test_exit_targets_atr_multiple_zero_rejects` | `atr_multiple: 0.0`. | `ok=False`; `positive number`. |
| 11 | `test_exit_targets_atr_multiple_negative_rejects` | `atr_multiple: -1.5`. | `ok=False`; `positive number`. |
| 12 | `test_exit_targets_atr_multiple_bool_rejects` | `atr_multiple: True`. | `ok=False`; `positive number` (bool-is-int trap). |
| 13 | `test_exit_targets_requires_stop_atr_multiple` | `exit.targets` valid, but `exit.stop: {method: atr_based, multiplier: 3.0}` (legacy rich shape, no `atr_multiple`). | `ok=False`; error mentions `atr_multiple`. |
| 14 | `test_exit_targets_stop_atr_multiple_zero_rejects` | `exit.stop: {atr_multiple: 0}`. | `ok=False`; `positive number`. |
| 15 | `test_lazy_prices_v1_still_loads` | `load_spec_from_yaml(specs/lazy_prices_v1.yaml)`. | Returns `StrategySpec`; no exception. |
| 16 | `test_post_audit_ruleset_v1_still_loads` | Same via post_audit_ruleset_v1. | Returns `StrategySpec`; no exception. |

### Block 2 — regime-adaptive sizing

| # | Name | Setup | Assertion |
|---|------|-------|-----------|
| 17 | `test_regime_adaptive_valid_spec_loads` | `position_sizing: {method: regime_adaptive, regimes: {BULL_LOW_VOL: {packet_worthy: true, position_pct: 0.05}, CRISIS: {packet_worthy: false, position_pct: 0.0}}}`. | `ok=True, errors=[]`. |
| 18 | `test_fixed_pct_equity_still_loads` | Existing `{method: fixed_pct_equity, pct: 0.15, max_concurrent: 5}`. | `ok=True, errors=[]` (interior unvalidated). |
| 19 | `test_unknown_method_rejects` | `{method: frog_sizing}`. | `ok=False`; error lists allowed methods. |
| 20 | `test_regime_adaptive_missing_regimes_rejects` | `{method: regime_adaptive}` (no `regimes` key). | `ok=False`; `non-empty dict`. |
| 21 | `test_regime_adaptive_empty_regimes_rejects` | `{method: regime_adaptive, regimes: {}}`. | `ok=False`; `non-empty dict`. |
| 22 | `test_regime_adaptive_regime_missing_packet_worthy_rejects` | A regime entry omits `packet_worthy`. | `ok=False`; `packet_worthy`. |
| 23 | `test_regime_adaptive_regime_missing_position_pct_rejects` | A regime entry omits `position_pct`. | `ok=False`; `position_pct`. |
| 24 | `test_regime_adaptive_packet_worthy_non_bool_rejects` | `packet_worthy: 0.5`. | `ok=False`; `bool`. |
| 25 | `test_regime_adaptive_position_pct_out_of_range_rejects` | `position_pct: 1.5`. | `ok=False`; `[0.0, 1.0]`. |
| 26 | `test_regime_adaptive_position_pct_bool_rejects` | `position_pct: True`. | `ok=False` (bool-is-int trap). |
| 27 | `test_regime_adaptive_unknown_key_warns_not_rejects` | `regimes: {BULL_LOW_VOL: {...}, FROG_MOON_VOL: {...}}`. | `ok=True, errors=[]`; `caplog` captures warning with `FROG_MOON_VOL` + `known:` list. |
| 28 | `test_regime_adaptive_all_known_keys_no_warning` | All 7 `KNOWN_REGIME_KEYS` present, each with valid entry. | `ok=True, errors=[]`; `caplog` has no warnings. |
| 29 | `test_regime_adaptive_regime_entry_not_dict_rejects` | `regimes: {BULL_LOW_VOL: "not a dict"}`. | `ok=False`; `must be a dict`. |

**Total: 29 tests.** Fits the Sprint C pattern (16 tests). Test count
floor (1500 per `run_ci_locally.ps1`) stays comfortably clear.

## 10. Guardrails check

- [x] No runtime consumption — validation only. `_from_dict` still
      returns a `StrategySpec`; no dataclass changes.
- [x] No changes to `exit.target` (singular) interior validation — the
      legacy rich shape is not inspected (preserves §1.2 status quo).
- [x] No changes to `fixed_pct_equity` interior validation — the
      existing `pct`/`max_concurrent` shape passes through as today.
- [x] No modification to Sprint C's scoring-DSL block — `_validate_bands`
      and its call site are untouched.
- [x] File-size budget: current 196, estimated post-D 295–298, under
      300 after tightening. Verified in Pass 2.
- [x] No new top-level `StrategySpec` dataclass fields — `.raw` retains
      the new blocks for downstream consumers.
- [x] `validate_spec(spec) → (ok, errors)` return shape unchanged —
      warnings flow through `logger.warning` like Sprint C's overlap
      check.
- [x] No new CLAUDE.md-forbidden SQL — `strategy_spec.py` has no SQL
      today and adds none.

## 11. Next — Pass 2 research queue

1. Verify incumbent usage counts (backward-compat evidence for PR body):
   - `exit.target` (singular) occurrences in `src/platform/specs/*.yaml` — expect 2.
   - `exit.targets` (plural) occurrences — expect 0.
   - `position_sizing.method: fixed_pct_equity` occurrences — expect 2.
   - `position_sizing.method: regime_adaptive` occurrences — expect 0.

2. Confirm `REGIME_THRESHOLDS` keys (ranker.py) match the proposed
   `KNOWN_REGIME_KEYS` set byte-for-byte.

3. Re-audit `classify_regime` return values — confirm no eighth key
   slipped in since Pass 1 was drafted (grep for `return "..."` inside
   `regime.py::classify_regime`).

4. Audit `spec.raw` readers for the new `exit.targets` and
   `position_sizing.regimes` keys — confirm none break on the new
   additions (expect zero — only pass-through consumers). Specifically
   check `backtest_engine.py` hash + `cloud_routes/platform.py`
   pass-through.

5. Line-count `strategy_spec.py` after implementation to confirm the
   ≤300 budget (or tighten helpers / move to sibling module if over).

6. Count tests in `tests/platform/` before and after — confirm the
   incremental 29 fits the floor.

After Pass 2 confirms, Pass 3 implements the two helpers + test module,
updates CHANGELOG and MASTER, runs `scripts/run_ci_locally.ps1` to green.
