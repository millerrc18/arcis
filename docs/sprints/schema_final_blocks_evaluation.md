# Sprint E Pass 1 — hooks, enrichment, post-scan, event-risk, bootcamp schema (#551)

**Sprint:** feat/schema-final-blocks (fifth of 8 in #530 chain).
**Branch:** `feat/schema-final-blocks`.
**Target:** extend `src/platform/strategy_spec.py::validate_spec` with **five
additive optional blocks** — `hooks.attribution`, `enrichment.chain`,
`post_scan.chain`, `event_risk.quarantine_categories`, and `bootcamp`. Later
sprints (F: ranker port, G: exit port) will consume these. This sprint is
**schema-only** — no runtime.

Sprint D (brackets + regime-adaptive sizing) is merged on main (PR #561,
commits `56ba5ab` + `a1a0415` + `483edcd`). The current `strategy_spec.py`
is 298 lines with the Sprint-C `_validate_bands` helper and the Sprint-D
`_validate_exit_brackets` / `_validate_position_sizing` helpers already in
place. Budget per sprint prompt: `strategy_spec.py` stays under **400 lines**
after A + B + C + D + E combined — **~102 lines of headroom**.

Sprint E ships the final schema surface before runtime consumption begins
in Sprint F. After this sprint, `strategy_spec.py` covers every shape
needed for the incumbent pipeline port.

## 1. Reference read per block — registry source discovery

Pass 1's core task per the sprint prompt is **registry/reference source
identification**. This section documents each block's source of truth,
maturity, and validation viability.

### 1.1 Block 1 — `hooks.attribution`

**Sprint prompt shape:**
```yaml
hooks:
  attribution:
    - log_before_llm
    - log_after_llm
```

**Sprint prompt registry claim:** `src/ranking/attribution.py` —
**does not exist**. `src/ranking/` contains only `ranker.py` and
`__init__.py`. The actual attribution module lives at
**`src/attribution/logger.py`** (confirmed via `Glob` +
`grep "attribution"` — the `src/attribution/` package is the canonical
location; `src/platform/backtest_attribution.py` is the sibling
backtest-side module).

**Registered hooks in `src/attribution/logger.py`:**

| Line | Function | Purpose |
|------|----------|---------|
| 26 | `log_attribution_before_llm` | Phase 1 — log ranker-only bracket before LLM runs. Returns `attribution_id`. |
| 62 | `log_attribution_after_llm` | Phase 2 — update row with LLM action (`taken`/`rejected`/`parse_failed`/`conviction_none`). |

Two functions, stable since the attribution-resolver capability was
registered (capability registry entry `attribution_resolver`, v0.16.0,
line 314 of `logger.py`). The watch loop (`src/scheduler/watch.py`) is
the sole caller today.

**Short-name aliases in sprint prompt (`log_before_llm`, `log_after_llm`)**
do not literally exist in code. They are abbreviated spec-level aliases
for `log_attribution_before_llm` / `log_attribution_after_llm`. Sprint F
will bind the alias map at port time.

**Maturity: high.** Two hooks, stable, 2-year-old code, capability-registry
registered. A third hook has not been added since introduction.

### 1.2 Block 2 — `enrichment.chain`

**Sprint prompt shape:**
```yaml
enrichment:
  chain:
    - technicals
    - insider
    - macro
    - news
    - sector
```

**Sprint prompt registry claim:** `src/features/enrichment.py`. This file
**exists** (82 lines) but exports a **single function**
`attach_post_scan_features(features, *, config, spy, vix_value, db_path)`
— not a registry of named enrichers. Its internal sub-steps are:

1. `compute_traffic_light` (from `src.features.traffic_light`)
2. `attach_event_risk_scores` (from `src.features.event_risk_score`)

Only two steps. Neither is named `technicals`, `insider`, `macro`,
`news`, or `sector` — those are **conceptual categories spanning multiple
modules** (feature-engine for technicals, data_collection for
insider/news, FRED collector for macro, GICS mapping for sector). No
formal named-enricher registry exists today.

**Maturity: low.** No formal registry. Sprint prompt's 5 enricher names
are aspirational — the closest runtime analogue is the scan-service
pipeline orchestration, which calls modules by function-import, not by
name.

### 1.3 Block 3 — `post_scan.chain`

**Sprint prompt shape:**
```yaml
post_scan:
  chain:
    - classifier
    - filter_duplicates
```

**Sprint prompt registry claim:** "registered helpers" — location
unspecified. No file in the repo defines a post-scan helper registry.
`src/scheduler/handler_registry.py` exists (98 lines) but is a **generic
asyncio-event-dispatch mixin** (`HandlerRegistryMixin.on(event)` /
`_dispatch(event)`) for the watch loop — not a post-scan named-helper
registry.

Closest analogues: the post-scan orchestration in `src/services/scan_service.py`
and `src/scheduler/universe_scanner.py`, where ranking → dedup → packet
building is inlined rather than registry-driven.

**Maturity: none.** No registry exists. Sprint prompt's two names
(`classifier`, `filter_duplicates`) are aspirational.

### 1.4 Block 4 — `event_risk.quarantine_categories`

**Sprint prompt shape:**
```yaml
event_risk:
  quarantine_categories:
    - earnings_imminent
    - earnings_elevated
```

**Sprint prompt registry claim:** "`event_risk` module's known categories
(SD#33 earnings filter + v0.25.1 known_events categories)."

Two separate source files contribute category taxonomies today:

| Source | Categories | Stability |
|--------|-----------|-----------|
| `src/features/event_risk_score.py:25` | `MACRO_EVENT_TYPES = {"FOMC", "NFP", "CPI"}` | Stable since v0.21 / Sprint H1. |
| `src/features/event_risk_score.py:270-279` | Earnings proximity (implicit: "earnings within ≤10 calendar days" — no named category, just a boolean `earnings_forces_block`) | SD#33 / Sprint H1 — behavioral, not named. |
| `src/diagnostics/known_events.py:56-90+` | `KNOWN_EVENTS` label values — `TARIFF_PAUSE`, `TARIFF_ANNOUNCEMENT`, `SANCTIONS_INITIAL`, `SANCTIONS_ESCALATION`, `INDUSTRIAL_POLICY`, `EXPORT_CONTROLS`, `TRADE_DISRUPTION`, `TARIFF_ESCALATION`, `FOMC_DECISION`, … | Stable since v0.20.0 + v0.25.1 2019-2024 additions. Verified against primary sources. |

**Critical finding.** The sprint prompt's example (`earnings_imminent`,
`earnings_elevated`) does **not** match any existing category. The code
has a binary earnings-block (≤10 days) concept, not a three-tier
(imminent/elevated/normal) taxonomy. The prompt is proposing a **new**
category vocabulary.

**Maturity: fragmented.** MACRO_EVENT_TYPES is a stable 3-element set.
KNOWN_EVENTS has ~9 label values. Earnings has no named category.
Sprint prompt's names are net-new. Consolidation is a Sprint F+ task.

### 1.5 Block 5 — `bootcamp`

**Sprint prompt shape:**
```yaml
bootcamp:
  qualification_threshold: 55
  max_positions: 20
```

**Sprint prompt registry claim:** "known bootcamp parameters
(`qualification_threshold`, `max_positions`, `watchlist_threshold`,
`traffic_light_floor`)." Values type-checked per parameter (int for
thresholds, float 0-1 for floor).

**Source of truth:** `config/settings.example.yaml:435-457`. The
`bootcamp:` block has these documented keys:

| Key | Type | Range / semantics | Used by |
|-----|------|-------------------|---------|
| `enabled` | bool | true/false | Multiple; controls whether bootcamp is on. |
| `phase` | int | 1/2/3 | Lifecycle phase label. |
| `qualification_threshold` | int | 0-100 (ranker score) | Ranker packet-worthy override. |
| `watchlist_threshold` | int | 0-100 (ranker score) | Watchlist-include override. |
| `max_positions` | int | >0 | Risk governor override. |
| `traffic_light_floor` | float | 0.0-1.0 | Traffic light sizing floor (see `enrichment.py:45`). |
| `email_mode` | str enum | "full_stream"/"daily_summary"/"digest"/"silent" | Digest scheduler. |
| `max_packets_per_scan` | int | >0 | Scan-cycle cap. |
| `scan_interval_minutes` | int | >0 | Watch-loop cadence. |

The 4 sprint-prompt-required keys (`qualification_threshold`,
`watchlist_threshold`, `max_positions`, `traffic_light_floor`) **all
exist** in settings.example.yaml. They are also read by name in
multiple runtime sites:

- `src/features/enrichment.py:45` reads `bootcamp.traffic_light_floor`.
- Other bootcamp-consuming sites read the other 3 keys by name (Pass 2
  will enumerate).

**Maturity: high.** Real, documented, runtime-consumed config keys.

### 1.6 Summary table — registry maturity per block

| # | Block | Registry exists? | Stability | Proposed validation |
|---|-------|------------------|-----------|---------------------|
| 1 | `hooks.attribution` | Yes — `src/attribution/logger.py` (2 functions, 2-year-old) | High | **STRICT reject** |
| 2 | `enrichment.chain` | No formal registry; `enrichment.py` is 1 function | Low | **WARN on unknown** |
| 3 | `post_scan.chain` | No registry exists at all | None | **WARN on unknown** |
| 4 | `event_risk.quarantine_categories` | Fragmented — 2 modules + aspirational names | Low | **WARN on unknown** |
| 5 | `bootcamp` | Yes — `settings.example.yaml` + runtime readers | High | **STRICT reject** |

## 2. Decision — per-block validation policy

Sprint prompt default: **strict validation — unknown refs reject.** Prompt
explicitly permits: "Pass 1 may recommend warn-instead for one or more
blocks based on registry maturity — justify in doc."

### 2.1 Blocks 1 and 5 — STRICT rejection (retain prompt default)

**Block 1 `hooks.attribution`.** The 2 hooks are stable, tested,
capability-registry-registered, and 2 years old. A third hook has not
shipped since introduction. A typo in a spec (`log_before_Ilm` — capital-I
instead of `l`) would silently disable attribution logging for a
strategy — a **directly load-bearing** failure. Strict rejection catches
it at spec-load time. Future hooks can be added to the known set in one
line when Sprint F or later wires them.

**Block 5 `bootcamp`.** The 4 permitted keys map 1:1 to runtime-consumed
config keys read by name. A typo (`qualif_threshold: 55`) would silently
no-op the override — spec-author intent is lost without error. Strict
rejection protects the author.

### 2.2 Blocks 2, 3, 4 — WARN on unknown (permissive)

Justification per block:

**Block 2 `enrichment.chain`.** No named-enricher registry exists today.
The sprint prompt's 5 names (`technicals`, `insider`, `macro`, `news`,
`sector`) are aspirational — the runtime has no binding for them yet.
Strict rejection of unknown refs would force Pass 1 to either:
(a) reject all 5 prompt names (none are defined today → spec can't use
any), or (b) hardcode the 5 prompt names as the known set, creating a
definitional claim that's not grounded in code. Warning-on-unknown
allows the spec to declare intent now; Sprint F resolves the
enricher-name → function map at port time.

**Block 3 `post_scan.chain`.** Same reasoning, stronger. No registry
exists at all. Warning-on-unknown is the only viable policy until a
Sprint F+ PR lands the registry.

**Block 4 `event_risk.quarantine_categories`.** Registry is fragmented
across two modules with three different category conventions (macro
event types, KNOWN_EVENTS labels, implicit earnings proximity). The
sprint prompt's `earnings_imminent`/`earnings_elevated` names don't
match any existing convention. Forcing a strict enum now would either
reject the prompt's own example or codify a new 3-tier earnings
taxonomy that hasn't been ratified. Warn-on-unknown documents all
declared categories while leaving the consolidation for Sprint F+.

### 2.3 Ratio vs sprint-prompt default

**Two strict / three warn** — majority permissive, but justified per
block. Matches sprint prompt's escape valve. All three warn-blocks
include the sprint prompt's examples as seeds; no unknown-name warnings
fire for a spec using only the prompt's vocabulary.

## 3. Decision — per-block seed sets

Constants added to `strategy_spec.py` top-level section (near existing
`KNOWN_REGIME_KEYS` / `ALLOWED_SIZING_METHODS`):

```python
# Block 1 — strict. 2 registered attribution hooks (src/attribution/logger.py).
# Short-name aliases: sprint prompt uses log_before_llm / log_after_llm;
# Sprint F will bind to log_attribution_before_llm / log_attribution_after_llm.
KNOWN_ATTRIBUTION_HOOKS = frozenset({"log_before_llm", "log_after_llm"})

# Block 2 — warn. Seed from sprint prompt; registry aspirational.
KNOWN_ENRICHERS = frozenset({
    "technicals", "insider", "macro", "news", "sector",
})

# Block 3 — warn. Seed from sprint prompt; no registry exists today.
KNOWN_POST_SCAN_HELPERS = frozenset({"classifier", "filter_duplicates"})

# Block 4 — warn. Seed combines sprint prompt + MACRO_EVENT_TYPES +
# lowercased KNOWN_EVENTS labels. Registry consolidation deferred to Sprint F+.
KNOWN_EVENT_RISK_CATEGORIES = frozenset({
    # Earnings (sprint prompt; not defined in event_risk_score.py yet)
    "earnings_imminent", "earnings_elevated",
    # Macro event types (from event_risk_score.py:25, lowercased)
    "fomc", "nfp", "cpi",
    # known_events.py labels (lowercased)
    "tariff_pause", "tariff_announcement", "tariff_escalation",
    "sanctions_initial", "sanctions_escalation",
    "industrial_policy", "export_controls",
    "trade_disruption", "fomc_decision",
})

# Block 5 — strict. 4 keys from sprint prompt. All exist in
# config/settings.example.yaml:435-457.
KNOWN_BOOTCAMP_KEYS = frozenset({
    "qualification_threshold",
    "max_positions",
    "watchlist_threshold",
    "traffic_light_floor",
})
```

Rationale for case convention:

- Block 1 hooks and Block 5 bootcamp keys: **snake_case** — matches both
  sprint prompt and Python function-name conventions.
- Blocks 2, 3, 4: **lowercase snake_case** — matches sprint prompt's
  examples. Block 4 categories lowercase the KNOWN_EVENTS labels (which
  are UPPERCASE in source) to align with the sprint prompt's
  `earnings_imminent` style.

Case-fold on compare? **No.** Strict-case match per Sprint D precedent
(regime keys are uppercase, warning fires if lowercase given). Spec
author writes it exactly as the seed; typos produce warnings (or errors
in strict blocks).

## 4. Decision — validation placement

**Decision: keep one flat function — `validate_spec`.** Extract five
local helpers matching Sprint C/D's pattern:

- `_validate_attribution_hooks(hooks_block, errors)` — strict.
- `_validate_enrichment_chain(enrichment_block, errors)` — warn.
- `_validate_post_scan_chain(post_scan_block, errors)` — warn.
- `_validate_event_risk(event_risk_block, errors)` — warn.
- `_validate_bootcamp_overrides(bootcamp_block, errors)` — strict.

Placement order inside `validate_spec` (after Sprint D's additions):

1. Required keys (existing).
2. Universe (existing).
3. Entry (existing).
4. Exit + Sprint D brackets (existing).
5. Sprint D position_sizing (existing).
6. Sprint C ranking.bands (existing).
7. **New: `hooks` dispatch** → `_validate_attribution_hooks`.
8. **New: `enrichment` dispatch** → `_validate_enrichment_chain`.
9. **New: `post_scan` dispatch** → `_validate_post_scan_chain`.
10. **New: `event_risk` dispatch** → `_validate_event_risk`.
11. **New: `bootcamp` dispatch** → `_validate_bootcamp_overrides`.
12. Return.

## 5. Decision — shared helper for list-of-refs validation

Blocks 1, 2, 3, 4 all share the shape **"optional block containing an
optional list of string refs"**. To stay inside the 400-line budget,
factor the common validation into a single helper:

```python
def _validate_known_ref_list(
    items: list | None,
    known: frozenset[str],
    path: str,
    errors: list[str],
    *,
    strict: bool,
) -> None:
    """Validate an optional list of string refs against a known set.

    strict=True → unknown refs append to errors; validator rejects.
    strict=False → unknown refs emit logger.warning; validator passes.
    Both modes reject non-string / non-list shapes.
    """
    if items is None:
        return
    if not isinstance(items, list):
        errors.append(f"{path} must be a list when present")
        return
    if not items:
        errors.append(f"{path} must be a non-empty list when present")
        return
    for i, item in enumerate(items):
        if not isinstance(item, str) or not item:
            errors.append(f"{path}[{i}] must be a non-empty string")
            continue
        if item not in known:
            if strict:
                errors.append(
                    f"{path}[{i}] unknown ref {item!r} "
                    f"(known: {', '.join(sorted(known))})"
                )
            else:
                logger.warning(
                    "[PLATFORM] %s[%d]: unknown ref %r (known: %s)",
                    path, i, item, ", ".join(sorted(known)),
                )
```

Blocks 1/2/3/4 each become ~8-line dispatch helpers calling
`_validate_known_ref_list`. Saves ~40 lines vs inlining the pattern.
Line-delta estimate updated below.

## 6. Decision — error-message style

Match Sprint C/D patterns. Errors are prefixed with the JSON path to
the offending field:

- `hooks.attribution must be a list when present`
- `hooks.attribution[0] unknown ref 'log_before_Ilm' (known: log_after_llm, log_before_llm)`
- `enrichment.chain must be a non-empty list when present` (when `chain: []`)
- `post_scan.chain[0] must be a non-empty string`
- `event_risk.quarantine_categories must be a list when present`
- `bootcamp.qualification_threshold must be an int in [0, 100]`
- `bootcamp.traffic_light_floor must be a number in [0.0, 1.0]`
- `bootcamp.max_positions must be a positive int`
- `bootcamp: unknown keys {'foo', 'bar'} (allowed: max_positions, qualification_threshold, traffic_light_floor, watchlist_threshold)`

Warnings emitted via `logger.warning` (not returned), matching Sprint C
overlap + Sprint D regime-key patterns:

- `[PLATFORM] enrichment.chain[2]: unknown ref 'frog' (known: insider, macro, news, sector, technicals)`

## 7. Implementation sketch

```python
# strategy_spec.py — additions

KNOWN_ATTRIBUTION_HOOKS = frozenset({"log_before_llm", "log_after_llm"})
KNOWN_ENRICHERS = frozenset({
    "technicals", "insider", "macro", "news", "sector",
})
KNOWN_POST_SCAN_HELPERS = frozenset({"classifier", "filter_duplicates"})
KNOWN_EVENT_RISK_CATEGORIES = frozenset({
    "earnings_imminent", "earnings_elevated",
    "fomc", "nfp", "cpi",
    "tariff_pause", "tariff_announcement", "tariff_escalation",
    "sanctions_initial", "sanctions_escalation",
    "industrial_policy", "export_controls",
    "trade_disruption", "fomc_decision",
})
KNOWN_BOOTCAMP_KEYS = frozenset({
    "qualification_threshold", "max_positions",
    "watchlist_threshold", "traffic_light_floor",
})


# Dispatch (inside validate_spec, after sprint D position_sizing):
if "hooks" in spec and isinstance(spec["hooks"], dict):
    _validate_attribution_hooks(spec["hooks"], errors)
if "enrichment" in spec and isinstance(spec["enrichment"], dict):
    _validate_enrichment_chain(spec["enrichment"], errors)
if "post_scan" in spec and isinstance(spec["post_scan"], dict):
    _validate_post_scan_chain(spec["post_scan"], errors)
if "event_risk" in spec and isinstance(spec["event_risk"], dict):
    _validate_event_risk(spec["event_risk"], errors)
if "bootcamp" in spec and isinstance(spec["bootcamp"], dict):
    _validate_bootcamp_overrides(spec["bootcamp"], errors)


def _validate_known_ref_list(
    items, known, path, errors, *, strict,
):
    if items is None:
        return
    if not isinstance(items, list):
        errors.append(f"{path} must be a list when present")
        return
    if not items:
        errors.append(f"{path} must be a non-empty list when present")
        return
    for i, item in enumerate(items):
        if not isinstance(item, str) or not item:
            errors.append(f"{path}[{i}] must be a non-empty string")
            continue
        if item not in known:
            if strict:
                errors.append(
                    f"{path}[{i}] unknown ref {item!r} "
                    f"(known: {', '.join(sorted(known))})"
                )
            else:
                logger.warning(
                    "[PLATFORM] %s[%d]: unknown ref %r (known: %s)",
                    path, i, item, ", ".join(sorted(known)),
                )


def _validate_attribution_hooks(hooks_block, errors):
    _validate_known_ref_list(
        hooks_block.get("attribution"),
        KNOWN_ATTRIBUTION_HOOKS,
        "hooks.attribution", errors, strict=True,
    )


def _validate_enrichment_chain(block, errors):
    _validate_known_ref_list(
        block.get("chain"), KNOWN_ENRICHERS,
        "enrichment.chain", errors, strict=False,
    )


def _validate_post_scan_chain(block, errors):
    _validate_known_ref_list(
        block.get("chain"), KNOWN_POST_SCAN_HELPERS,
        "post_scan.chain", errors, strict=False,
    )


def _validate_event_risk(block, errors):
    _validate_known_ref_list(
        block.get("quarantine_categories"),
        KNOWN_EVENT_RISK_CATEGORIES,
        "event_risk.quarantine_categories", errors, strict=False,
    )


def _is_int_in_range(x, lo, hi):
    return (
        isinstance(x, int) and not isinstance(x, bool)
        and lo <= x <= hi
    )


def _validate_bootcamp_overrides(block, errors):
    unknown = set(block.keys()) - KNOWN_BOOTCAMP_KEYS
    if unknown:
        errors.append(
            f"bootcamp: unknown keys {sorted(unknown)!r} "
            f"(allowed: {sorted(KNOWN_BOOTCAMP_KEYS)})"
        )
    if "qualification_threshold" in block and not _is_int_in_range(
        block["qualification_threshold"], 0, 100,
    ):
        errors.append(
            "bootcamp.qualification_threshold must be an int in [0, 100]"
        )
    if "watchlist_threshold" in block and not _is_int_in_range(
        block["watchlist_threshold"], 0, 100,
    ):
        errors.append(
            "bootcamp.watchlist_threshold must be an int in [0, 100]"
        )
    if "max_positions" in block:
        mp = block["max_positions"]
        if not (isinstance(mp, int) and not isinstance(mp, bool) and mp > 0):
            errors.append("bootcamp.max_positions must be a positive int")
    if "traffic_light_floor" in block and not _is_unit_number(
        block["traffic_light_floor"],
    ):
        errors.append(
            "bootcamp.traffic_light_floor must be a number in [0.0, 1.0]"
        )
```

**`_is_unit_number` already exists** (strategy_spec.py:45) from Sprint D;
reused here for `traffic_light_floor`. No new utility needed.

## 8. File-size budget

### 8.1 Current state

```
$ wc -l src/platform/strategy_spec.py
298 src/platform/strategy_spec.py
```

Budget: 400. Headroom: 102 lines.

### 8.2 Expected delta (Pass 3)

| Addition | Estimated lines |
|----------|-----------------|
| 5 top-level frozenset constants (with docstrings) | ~22 |
| `validate_spec` body additions (5 dispatch lines) | ~10 |
| `_validate_known_ref_list` shared helper | ~25 |
| `_validate_attribution_hooks` — 1-line delegator | ~6 |
| `_validate_enrichment_chain` — 1-line delegator | ~6 |
| `_validate_post_scan_chain` — 1-line delegator | ~6 |
| `_validate_event_risk` — 1-line delegator | ~6 |
| `_is_int_in_range` utility | ~5 |
| `_validate_bootcamp_overrides` | ~28 |
| Blank-line / docstring padding | ~8 |

**Total estimated:** ~122 new lines. 298 → ~420. **20 lines over budget.**

### 8.3 Mitigation plan

Four options, in preference order:

- **A: Tighten `_validate_bootcamp_overrides`** using a data-driven
  per-key validator map:
  ```python
  _BOOTCAMP_RULES = (
      ("qualification_threshold",
       lambda v: _is_int_in_range(v, 0, 100),
       "must be an int in [0, 100]"),
      ("watchlist_threshold",
       lambda v: _is_int_in_range(v, 0, 100),
       "must be an int in [0, 100]"),
      ("max_positions",
       lambda v: isinstance(v, int) and not isinstance(v, bool) and v > 0,
       "must be a positive int"),
      ("traffic_light_floor",
       _is_unit_number,
       "must be a number in [0.0, 1.0]"),
  )
  ```
  Saves ~10 lines. Improves maintainability.

- **B: Inline 1-line delegators.** The four strict/warn dispatch
  helpers are each 6 lines with docstring. Compact to 3 lines each
  (one-liner body). Saves ~12 lines.

- **C: Fold dispatch into a single table-driven loop** inside
  `validate_spec`:
  ```python
  _LIST_BLOCKS = (
      ("hooks", "attribution", KNOWN_ATTRIBUTION_HOOKS, True),
      ("enrichment", "chain", KNOWN_ENRICHERS, False),
      ("post_scan", "chain", KNOWN_POST_SCAN_HELPERS, False),
      ("event_risk", "quarantine_categories",
       KNOWN_EVENT_RISK_CATEGORIES, False),
  )
  for outer, inner, known, strict in _LIST_BLOCKS:
      if outer in spec and isinstance(spec[outer], dict):
          _validate_known_ref_list(
              spec[outer].get(inner), known,
              f"{outer}.{inner}", errors, strict=strict,
          )
  ```
  Eliminates the 4 one-line delegator helpers entirely. Saves ~25
  lines. Costs one level of indirection but keeps the logic in the
  same file and readable.

- **D: Extract bootcamp helper to sibling `_validators.py`** if A+B+C
  insufficient (underscore prefix, no public API change). ~30 lines
  out of main file. Nuclear option.

**Pass 3 plan: apply A + B + C together.** Expected result 298 → ~378,
comfortably under 400. C is the decisive saver. If implementation
reveals tighter constraints, D is available.

## 9. Test plan — `tests/platform/specs/test_schema_final_blocks.py`

Sprint prompt requires **≥10 tests** (one valid + one rejection per
block) plus a combined-5-block test and backward-compat evidence.

Fixture — `_base_spec()` returning a minimal valid spec, identical
structure to Sprint C's and Sprint D's test module (copy the pattern,
not a shared fixture — Sprint C/D precedent is local fixture per module).

### 9.1 Block 1 — `hooks.attribution` (strict)

| # | Name | Setup | Assertion |
|---|------|-------|-----------|
| 1 | `test_hooks_attribution_valid_loads` | `spec["hooks"] = {"attribution": ["log_before_llm", "log_after_llm"]}`. | `ok=True, errors=[]`. |
| 2 | `test_hooks_attribution_unknown_ref_rejects` | `spec["hooks"] = {"attribution": ["log_before_llm", "frog"]}`. | `ok=False`; error contains `unknown ref 'frog'`. |

### 9.2 Block 2 — `enrichment.chain` (warn)

| # | Name | Setup | Assertion |
|---|------|-------|-----------|
| 3 | `test_enrichment_chain_valid_loads` | `spec["enrichment"] = {"chain": ["technicals", "insider"]}`. | `ok=True, errors=[]`; no warnings in caplog. |
| 4 | `test_enrichment_chain_unknown_ref_warns` | `spec["enrichment"] = {"chain": ["technicals", "frog"]}`. | `ok=True, errors=[]`; caplog warning mentions `frog` + `known:` list. |

### 9.3 Block 3 — `post_scan.chain` (warn)

| # | Name | Setup | Assertion |
|---|------|-------|-----------|
| 5 | `test_post_scan_chain_valid_loads` | `spec["post_scan"] = {"chain": ["classifier", "filter_duplicates"]}`. | `ok=True, errors=[]`. |
| 6 | `test_post_scan_chain_unknown_ref_warns` | `spec["post_scan"] = {"chain": ["frog"]}`. | `ok=True, errors=[]`; caplog warning. |

### 9.4 Block 4 — `event_risk.quarantine_categories` (warn)

| # | Name | Setup | Assertion |
|---|------|-------|-----------|
| 7 | `test_event_risk_valid_loads` | `spec["event_risk"] = {"quarantine_categories": ["earnings_imminent", "fomc"]}`. | `ok=True, errors=[]`. |
| 8 | `test_event_risk_unknown_category_warns` | `spec["event_risk"] = {"quarantine_categories": ["frog_moon_vol"]}`. | `ok=True, errors=[]`; caplog warning. |

### 9.5 Block 5 — `bootcamp` (strict)

| # | Name | Setup | Assertion |
|---|------|-------|-----------|
| 9 | `test_bootcamp_valid_loads` | `spec["bootcamp"] = {"qualification_threshold": 55, "max_positions": 20}`. | `ok=True, errors=[]`. |
| 10 | `test_bootcamp_unknown_key_rejects` | `spec["bootcamp"] = {"qualification_threshold": 55, "frog": 42}`. | `ok=False`; error lists `frog` + allowed keys. |
| 11 | `test_bootcamp_threshold_out_of_range_rejects` | `spec["bootcamp"] = {"qualification_threshold": 150}`. | `ok=False`; error `[0, 100]`. |
| 12 | `test_bootcamp_threshold_bool_rejects` | `spec["bootcamp"] = {"max_positions": True}`. | `ok=False`; error `positive int` (bool-is-int trap). |
| 13 | `test_bootcamp_traffic_light_floor_out_of_range_rejects` | `spec["bootcamp"] = {"traffic_light_floor": 1.5}`. | `ok=False`; `[0.0, 1.0]`. |
| 14 | `test_bootcamp_traffic_light_floor_valid` | `spec["bootcamp"] = {"traffic_light_floor": 0.5}`. | `ok=True, errors=[]`. |
| 15 | `test_bootcamp_watchlist_threshold_valid` | `spec["bootcamp"] = {"watchlist_threshold": 25}`. | `ok=True, errors=[]`. |

### 9.6 Combined and backward-compat

| # | Name | Setup | Assertion |
|---|------|-------|-----------|
| 16 | `test_all_five_blocks_combined_loads` | Valid setups for all 5 blocks simultaneously in one spec. | `ok=True, errors=[]`. |
| 17 | `test_lazy_prices_v1_still_loads` | `load_spec_from_yaml(specs/lazy_prices_v1.yaml)`. | Returns `StrategySpec`; no exception. |
| 18 | `test_post_audit_ruleset_v1_still_loads` | Same via post_audit_ruleset_v1. | Returns `StrategySpec`; no exception. |
| 19 | `test_none_of_five_blocks_present_still_loads` | `_base_spec()` with no hooks/enrichment/post_scan/event_risk/bootcamp keys. | `ok=True, errors=[]`. |
| 20 | `test_hooks_not_a_dict_ignored` | `spec["hooks"] = "not a dict"`. | `ok=True, errors=[]` (guard on outer `isinstance(spec["hooks"], dict)` skips). |

### 9.7 Edge cases

| # | Name | Setup | Assertion |
|---|------|-------|-----------|
| 21 | `test_hooks_attribution_empty_list_rejects` | `spec["hooks"] = {"attribution": []}`. | `ok=False`; `non-empty list`. |
| 22 | `test_hooks_attribution_not_a_list_rejects` | `spec["hooks"] = {"attribution": "log_before_llm"}` (string, not list). | `ok=False`; `must be a list`. |
| 23 | `test_enrichment_chain_entry_not_a_string_rejects` | `spec["enrichment"] = {"chain": [42]}`. | `ok=False`; `non-empty string`. |
| 24 | `test_bootcamp_not_a_dict_ignored` | `spec["bootcamp"] = "not a dict"`. | `ok=True, errors=[]`. |
| 25 | `test_all_five_block_outer_dicts_empty_pass` | Each of 5 blocks set to `{}` (no inner keys). | `ok=True, errors=[]` (inner keys absent → early return in each helper). |

**Total: 25 tests.** Exceeds the 10-test floor by 15. Sprint C shipped
16; Sprint D shipped 29. Sprint E at 25 is consistent.

### 9.8 Existing test non-regression check

| Test module | Expected effect |
|-------------|-----------------|
| `tests/platform/test_strategy_spec.py` (9 tests) | Unchanged. None of the 5 new blocks appear in the synthetic test fixtures. |
| `tests/platform/specs/test_schema_scoring_dsl.py` (16 tests) | Unchanged. `ranking.bands` logic is untouched. |
| `tests/platform/specs/test_schema_brackets_sizing.py` (29 tests) | Unchanged. `exit.targets` / `position_sizing.regimes` logic is untouched. |
| `tests/platform/specs/test_post_audit_ruleset_v1.py` (7 tests) | Loads real YAML; covered by #18 non-regression check. |

Test count floor: Sprint E adds 25 tests (strictly additive). CLAUDE.md
floor is 1339; `run_ci_locally.ps1` is the stricter enforcer. No
regression risk — Sprint E deletes no tests.

## 10. Guardrails check

- [x] **Schema-only.** No runtime consumption. `_from_dict` unchanged.
      `StrategySpec` dataclass unchanged — new blocks land in `.raw`.
- [x] **No new registries.** All seed sets are derived from existing
      sources (attribution/logger.py, settings.example.yaml,
      event_risk_score.py, known_events.py). Block 2/3 sprint-prompt
      seeds are aspirational but documented as such.
- [x] **Strict validation default.** Blocks 1, 5 strict. Blocks 2, 3, 4
      warn-instead — **justified per §2.2 on registry maturity** (sprint
      prompt escape clause).
- [x] **No changes to Sprint A-D blocks.** `ranking.bands`,
      `exit.targets`, `position_sizing.regimes`, `entry.kind`,
      `exit.kind` validators untouched.
- [x] **File-size budget: ≤400 lines.** Estimated 298 → ~378 with
      A+B+C mitigations. Pass 2 confirms exact number.
- [x] **Test count additive-only.** +25. No deletions.
- [x] **`validate_spec(spec) → (ok, errors)` return shape unchanged.**
      Warnings flow through `logger.warning` per Sprint C/D precedent.
- [x] **No CLAUDE.md-forbidden SQL.** strategy_spec.py has no SQL today
      and adds none.

## 11. Next — Pass 2 research queue

1. **Confirm attribution hook location** — re-verify
   `src/attribution/logger.py` is the canonical registry location (not
   `src/ranking/attribution.py` as sprint prompt says). Grep for any
   alternate attribution modules missed in Pass 1 discovery.

2. **Confirm bootcamp runtime consumers** — enumerate files that read
   `bootcamp.qualification_threshold`, `.watchlist_threshold`,
   `.max_positions`, `.traffic_light_floor` by name (Pass 1 confirmed
   only `.traffic_light_floor` at `enrichment.py:45`). The 4 keys must
   be load-bearing; if one is unused, reconsider strict policy.

3. **Re-verify that none of the 5 new top-level keys (`hooks`,
   `enrichment`, `post_scan`, `event_risk`, `bootcamp`) exist in
   `lazy_prices_v1.yaml` or `post_audit_ruleset_v1.yaml`.** If any
   collision, the backward-compat guarantee breaks.

4. **Re-verify that no Sprint A-D block key overlaps with the 5 new
   block names.** Sprint A added none; B added `python_plugin` exit/entry
   kinds (values, not top-level keys); C added `ranking.bands`
   (nested); D added `exit.targets` / `position_sizing.regimes`
   (nested). No top-level collision expected — but Pass 2 confirms.

5. **Audit `spec.raw` readers for the 5 new top-level keys** — confirm
   none break on the new pass-through. Expect identical finding to
   Sprint C/D: the reproducibility hash at `backtest_engine.py:187`
   captures the new keys, and pass-through consumers
   (`cloud_routes/platform.py`, `run_walkforward.py`,
   `lazy_prices_smoke_test.py`) ignore unknown keys.

6. **Line-count verification.** Confirm 298-line baseline and apply
   A+B+C mitigation plan post-implementation; if over 400 after
   implementation, escalate to option D.

7. **Test count floor re-check.** Confirm `run_ci_locally.ps1`
   baseline has not tightened between Sprint D merge and Sprint E
   branch.

After Pass 2 confirms, Pass 3 implements 5 helpers + `_validate_known_ref_list`
+ test module (25 tests), updates CHANGELOG and MASTER, runs
`scripts/run_ci_locally.ps1` to green.
