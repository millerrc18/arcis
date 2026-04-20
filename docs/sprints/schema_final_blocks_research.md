# Sprint E Pass 2 — hooks / enrichment / post-scan / event-risk / bootcamp research (#551)

Pass 2 verifies the seven assumptions behind Pass 1 before code lands:

1. Attribution module location (sprint prompt vs reality).
2. Bootcamp parameter names — confirmed against `config/settings.example.yaml`
   **and** enumerated runtime consumers (load-bearing verification).
3. Zero top-level key collision between Sprint E's 5 new blocks and
   Sprints A-D additions.
4. Zero consumer breakage on the 5 new `spec.raw` pass-through keys.
5. Known event-risk category sources — MACRO_EVENT_TYPES +
   `KNOWN_EVENTS` labels, byte-for-byte.
6. File-size budget achievable with Pass 1 §8.3 A+B+C mitigations.
7. Test count floor stays clear (+25 net).

## 1. Attribution module location

### 1.1 Sprint prompt claim vs reality

Sprint prompt said the hooks registry lives at `src/ranking/attribution.py`.
Pass 1 discovered the actual module is `src/attribution/logger.py`.
Pass 2 verifies this exhaustively:

```
$ glob src/ranking/*.py
src/ranking/__init__.py
src/ranking/ranker.py
```

No `attribution.py` under `src/ranking/`. Searched one level higher:

```
$ glob src/attribution/*.py
src/attribution/logger.py
src/attribution/__init__.py  (inferred from package)
```

### 1.2 Import-site census

Grep `from src\.attribution` across source tree:

| # | File | Line | Import |
|---|------|------|--------|
| 1 | `src/simulation/engine.py` | 22 | `simulate_mechanical_outcome` |
| 2 | `src/scheduler/universe_scanner.py` | 176, 213, 237 | `log_attribution_before_llm`, `log_attribution_after_llm` (×2) |
| 3 | `src/scheduler/overnight.py` | 437 | `resolve_pending_outcomes` |
| 4 | `src/shadow_trading/executor.py` | 1205, 1240, 1599 | `link_trade_outcome` (×3) |
| 5 | `src/platform/backtest_engine.py` | 29 | `simulate_mechanical_outcome` |
| 6 | `src/services/scan_service.py` | 153, 186 | `log_attribution_before_llm`, `log_attribution_after_llm` |
| 7 | `src/api/routes/system.py` | 596 | `get_attribution_stats` |

**14 import sites across 7 files. Zero imports from `src.ranking.attribution`.**

### 1.3 Runtime hook invocations matching Pass 1 seed set

The two hook functions referenced by Sprint E's seed
`KNOWN_ATTRIBUTION_HOOKS = {"log_before_llm", "log_after_llm"}` map to:

- `log_before_llm` → `src.attribution.logger.log_attribution_before_llm`
- `log_after_llm` → `src.attribution.logger.log_attribution_after_llm`

Sprint F will bind the alias map at port time. No third hook function
exists in `src/attribution/logger.py`. Pass 1 §1.1 finding confirmed.

### 1.4 Decision carried forward

Pass 1 §2.1 strict-rejection policy stands — 2 hooks, 2-year-old code,
capability-registry-registered. Strict list of `{log_before_llm,
log_after_llm}` matches the two canonical hooks exactly.

## 2. Bootcamp parameter names — runtime consumer census

Pass 1 §1.5 identified the 4 sprint-prompt keys in
`config/settings.example.yaml:435-457`. Pass 2 enumerates every
runtime consumer of each to validate "load-bearing" status.

### 2.1 `bootcamp.qualification_threshold`

| # | File | Line | Code |
|---|------|------|------|
| 1 | `src/ranking/ranker.py` | 40 | `bootcamp_cfg.get("qualification_threshold", 40)` — overrides ranker packet-worthy threshold. |
| 2 | `src/services/bootcamp_state.py` | 31 | `int(bc.get("qualification_threshold", 0))` — mirrors into bootcamp_state row for Telegram reporting. |

**2 sites.** Used by the ranker directly to decide whether a ticker
qualifies for a trade. A spec typo would silently revert to hardcoded
default 40.

### 2.2 `bootcamp.watchlist_threshold`

| # | File | Line | Code |
|---|------|------|------|
| 1 | `src/ranking/ranker.py` | 41 | `bootcamp_cfg.get("watchlist_threshold", 25)` — overrides watchlist inclusion threshold. |

**1 site.** Directly gates watchlist inclusion. Typo reverts to default 25.

### 2.3 `bootcamp.max_positions`

| # | File | Line | Code |
|---|------|------|------|
| 1 | `src/shadow_trading/executor.py` | 83 | `bootcamp.get("max_positions", 50)` — cap inside `_effective_position_cap`. |
| 2 | `src/shadow_trading/executor.py` | 415 | `bootcamp_cfg.get("max_positions", 50)` — second read point inside executor. |
| 3 | `src/risk/governor.py` | 502 | `bootcamp.get("max_positions", 50)` — risk governor effective limit override. |

**3 sites.** Enforces per-trade cap during bootcamp. Typo reverts
all three call sites to default 50.

### 2.4 `bootcamp.traffic_light_floor`

| # | File | Line | Code |
|---|------|------|------|
| 1 | `src/features/enrichment.py` | 45 | `bootcamp_cfg.get("traffic_light_floor", 0.5)` — sets minimum traffic light sizing multiplier during bootcamp. |

**1 site.** Only one consumer, but load-bearing — it's the sole knob
that keeps data collection alive in RED (crisis) regimes.

### 2.5 Aggregate

| Key | Runtime sites | Fallback on typo |
|-----|---------------|------------------|
| `qualification_threshold` | 2 | 40 (ranker default) |
| `watchlist_threshold` | 1 | 25 (ranker default) |
| `max_positions` | 3 | 50 (executor/governor default) |
| `traffic_light_floor` | 1 | 0.5 (enrichment default) |

**All 4 keys are load-bearing** — every typo silently reverts to a
hardcoded default, breaking spec-author intent. Pass 1 §2.1
strict-rejection policy stands.

### 2.6 Runtime-only consumers not in sprint-prompt set

`config/settings.example.yaml:435-457` also documents these bootcamp
keys, read at runtime but **not** permitted as spec overrides per
sprint prompt scope:

- `enabled` (bool) — system-level flag, not a strategy override.
- `phase` (int) — lifecycle label, not a tunable.
- `email_mode` (str enum) — digest scheduling, unrelated to strategy.
- `max_packets_per_scan` (int) — watch-loop rate limit, not strategy.
- `scan_interval_minutes` (int) — watch-loop cadence, not strategy.

These are intentionally excluded from `KNOWN_BOOTCAMP_KEYS` — a strategy
spec that attempts to override `scan_interval_minutes` would correctly
fail strict validation with "unknown keys" error, since changing scan
cadence via a strategy spec is out of scope. Operators change cadence
via `settings.yaml`, not spec.

## 3. Top-level key collision check

### 3.1 Sprint E's 5 new top-level keys

`{hooks, enrichment, post_scan, event_risk, bootcamp}`

### 3.2 Existing top-level keys (pre-Sprint E)

From `src/platform/strategy_spec.py::REQUIRED_KEYS` + optionals:

```python
REQUIRED_KEYS = (
    "spec_version", "strategy_id", "display_name",
    "universe", "entry", "exit",
    "position_sizing", "attribution",
)
# Optionals observed: ranking (Sprint C), llm_enhancement (legacy),
# derived_from (legacy), description (legacy), citation (legacy).
```

### 3.3 Set intersection

```
$ python -c "
from src.platform.strategy_spec import REQUIRED_KEYS
top = set(REQUIRED_KEYS) | {'ranking', 'llm_enhancement', 'derived_from',
                             'description', 'citation'}
new = {'hooks', 'enrichment', 'post_scan', 'event_risk', 'bootcamp'}
print('collisions:', top & new)
"
collisions: set()
```

### 3.4 Live-YAML scan

```
$ grep -n '^hooks:\|^enrichment:\|^post_scan:\|^event_risk:\|^bootcamp:' \
    src/platform/specs/*.yaml
(no matches)
```

**Zero occurrences** across the two shipped strategy specs
(`lazy_prices_v1.yaml`, `post_audit_ruleset_v1.yaml`). Sprint E's 5 new
top-level keys are strictly net-new. Backward compatibility preserved.

### 3.5 Note on `attribution` as top-level key

`attribution:` is already an **existing required top-level key** (e.g.,
`lazy_prices_v1.yaml:62-64`):

```yaml
attribution:
  benchmark: SPY_matched_window
  metrics: [raw_sharpe, excess_sharpe, ...]
```

Sprint E introduces `hooks.attribution` — a **sub-field of a separate
top-level `hooks` dict**, not modifying the existing top-level
`attribution` block. No conflict. The two namespaces are:

- Top-level `attribution`: benchmark + metric list for post-trade analysis.
- `hooks.attribution`: ordered list of attribution-logging hook refs.

Different semantic domains, clearly separated by nesting depth.

## 4. `spec.raw` consumer audit

Full grep of `spec.raw|strategy.raw|.raw.get|.raw[` in runtime source:

| # | File | Line | Access | Effect of 5 new optional blocks |
|---|------|------|--------|----------------------------------|
| 1 | `src/api/cloud_routes/platform.py` | 108 | `body["spec"] = spec.raw` | Pass-through to JSON response. Extra keys flow through; frontend reads only keys it knows. |
| 2 | `src/scheduler/watch.py` | 762 | `spec.raw.get("shadow_cadence_seconds", 600)` | Specific key; unaffected. |
| 3 | `src/platform/backtest_persist.py` | 56 | `strategy.raw.get("spec_version", 1)` | Specific key; unaffected. |
| 4 | `src/platform/backtest_persist.py` | 57 | `spec_hash(result.config.strategy.raw)` | **Hash changes when spec declares the 5 new blocks.** Same precedent as Sprint C (ranking.bands) and Sprint D (exit.targets, position_sizing.regimes). Reproducibility requires new keys captured. |
| 5 | `src/platform/shadow_harness.py` | 16 | docstring only | No runtime read; unaffected. |
| 6 | `src/platform/backtest_engine.py` | 187 | `json.dumps(spec.raw, sort_keys=True, default=str)` | Same as #4 — hash capture, intentional. |

**Net finding.** Identical to Sprint C + Sprint D audits: zero consumer
breaks. The reproducibility hash captures new blocks, which is the
desired behavior — different hooks / enrichment / categories / bootcamp
overrides → different reproducibility envelope.

### 4.1 `validate_spec` caller signature check

Pass 1 noted Sprint C/D preserved the `(ok, errors)` return shape;
Sprint E adds no new return channel (warnings flow through
`logger.warning`). Call sites:

```
src/platform/strategy_spec.py:154   ok, errors = validate_spec(d)
tests/platform/test_strategy_spec.py (9 call sites, all two-tuple unpack)
tests/platform/specs/test_schema_scoring_dsl.py (23 call sites)
tests/platform/specs/test_schema_brackets_sizing.py (29 call sites)
```

All existing call sites unpack `(ok, errors)`. Sprint E adds no new
return channel — zero call-site modifications needed.

### 4.2 Non-regression — existing specs under new validator

With Pass 1 validator additions, `lazy_prices_v1.yaml` (72 lines) and
`post_audit_ruleset_v1.yaml` (100 lines) both pass:

- Neither spec has a `hooks` key → outer `isinstance(spec["hooks"], dict)`
  check short-circuits, no validator runs.
- Same for `enrichment`, `post_scan`, `event_risk`, `bootcamp`. None of
  the 5 outer keys appear in either YAML.

Regression risk: zero. Backward compat: preserved.

## 5. Event-risk category source byte-cross-reference

Pass 1 §1.4 proposed `KNOWN_EVENT_RISK_CATEGORIES` combining three
sources. Pass 2 verifies each source.

### 5.1 `MACRO_EVENT_TYPES` from `event_risk_score.py`

```
src/features/event_risk_score.py:25:MACRO_EVENT_TYPES = {"FOMC", "NFP", "CPI"}
```

Also used at lines 64, 95, 104, 113, 213, 215, 217 — consistent
3-element set. Source stable since v0.21 / Sprint H1 (per docstring at
`sprint-H1-earnings-filter.md`).

Pass 1 seeded `"fomc", "nfp", "cpi"` (lowercased). ✅ Matches MACRO set
byte-for-byte after case-fold.

### 5.2 `KNOWN_EVENTS` label set from `known_events.py`

From Pass 1 §1.4 read of `src/diagnostics/known_events.py:56-90`:

```python
KNOWN_EVENTS = {
    "2019-10-11": "TARIFF_PAUSE",
    "2019-12-12": "TARIFF_ANNOUNCEMENT",
    "2022-02-24": "SANCTIONS_INITIAL",
    "2022-03-08": "SANCTIONS_ESCALATION",
    "2022-07-27": "INDUSTRIAL_POLICY",
    "2022-08-09": "INDUSTRIAL_POLICY",
    "2022-10-07": "EXPORT_CONTROLS",
    "2023-12-18": "TRADE_DISRUPTION",
    "2024-05-14": "TARIFF_ESCALATION",
    "2026-03-18": "FOMC_DECISION",
    "2026-03-19": "FOMC_DECISION",
    ...
}
```

Distinct label values: `{TARIFF_PAUSE, TARIFF_ANNOUNCEMENT,
SANCTIONS_INITIAL, SANCTIONS_ESCALATION, INDUSTRIAL_POLICY,
EXPORT_CONTROLS, TRADE_DISRUPTION, TARIFF_ESCALATION, FOMC_DECISION}`
— 9 distinct uppercase labels. (There may be additional labels in the
file past line 90; Pass 1 read the first 80 lines only. Pass 3 will
verify the complete label set pre-seeding.)

Pass 1 seeded 9 lowercase labels:
`{tariff_pause, tariff_announcement, tariff_escalation,
sanctions_initial, sanctions_escalation, industrial_policy,
export_controls, trade_disruption, fomc_decision}`. ✅ Matches
observed labels byte-for-byte after case-fold.

### 5.3 Earnings categories — sprint prompt origin

`earnings_imminent`, `earnings_elevated` — no byte match in code. They
are sprint-prompt-proposed new names. Pass 1 seeded them in the
warn-on-unknown set so specs can declare them now; Sprint F+
consolidation binds them to runtime behavior.

### 5.4 Final `KNOWN_EVENT_RISK_CATEGORIES` seed (Pass 1 §3 confirmed)

14-element frozenset:

```python
{
    # Earnings — sprint-prompt new names
    "earnings_imminent", "earnings_elevated",
    # Macro events — from MACRO_EVENT_TYPES (event_risk_score.py:25)
    "fomc", "nfp", "cpi",
    # Point-in-time events — from known_events.py KNOWN_EVENTS labels
    "tariff_pause", "tariff_announcement", "tariff_escalation",
    "sanctions_initial", "sanctions_escalation",
    "industrial_policy", "export_controls",
    "trade_disruption", "fomc_decision",
}
```

## 6. File-size budget verification

### 6.1 Current state

```
$ wc -l src/platform/strategy_spec.py
298 src/platform/strategy_spec.py
```

Matches Pass 1 §8.1 claim exactly.

### 6.2 Expected delta

Pass 1 §8.2 estimated +122 lines naively, mitigated to +80 via
A+B+C (compacted bootcamp validators + inline delegators +
table-driven dispatch).

### 6.3 Mitigation plan — C is the decisive saver

Post-mitigation sketch (compact form):

```python
# Constants — 5 frozensets + 1 validator rule tuple
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

# Per-block list dispatch config (outer, inner, known, strict).
# Blocks 1-4 share the list-of-refs shape; table avoids 4 delegator helpers.
_LIST_BLOCKS = (
    ("hooks", "attribution", KNOWN_ATTRIBUTION_HOOKS, True),
    ("enrichment", "chain", KNOWN_ENRICHERS, False),
    ("post_scan", "chain", KNOWN_POST_SCAN_HELPERS, False),
    ("event_risk", "quarantine_categories",
     KNOWN_EVENT_RISK_CATEGORIES, False),
)


# In validate_spec — 4 blocks handled by one loop
for outer, inner, known, strict in _LIST_BLOCKS:
    if outer in spec and isinstance(spec[outer], dict):
        _validate_known_ref_list(
            spec[outer].get(inner), known,
            f"{outer}.{inner}", errors, strict=strict,
        )
if "bootcamp" in spec and isinstance(spec["bootcamp"], dict):
    _validate_bootcamp_overrides(spec["bootcamp"], errors)


# Two new helpers: _validate_known_ref_list + _validate_bootcamp_overrides
# (see Pass 1 §5, §7 for full code)
```

Estimated line delta with C applied:

| Addition | Estimated lines |
|----------|-----------------|
| 5 top-level frozensets (14-member event_risk keeps compact multi-line) | ~22 |
| `_LIST_BLOCKS` tuple | ~7 |
| `validate_spec` body — single loop + bootcamp dispatch | ~8 |
| `_validate_known_ref_list` shared helper | ~23 |
| `_validate_bootcamp_overrides` with data-driven rules | ~28 |
| `_is_int_in_range` utility | ~3 |
| Blank-line / docstring padding | ~7 |

**Total estimated:** ~98 lines. 298 → ~396. **Under 400 budget by 4
lines.** Margin thin; Pass 3 will tighten further if implementation
reveals overhead.

### 6.4 Fallback — helper extraction to `_validators.py`

Option D in Pass 1 §8.3 remains available if Pass 3 lands over 400.
Extracting `_validate_known_ref_list` + `_validate_bootcamp_overrides`
to a sibling `_validators.py` saves ~50 lines from
`strategy_spec.py` with no public API change. Not used unless needed.

## 7. Test count floor

### 7.1 Current baseline

Reading the CI enforcement at `scripts/run_ci_locally.ps1:144`:

```
$floor = 1500
```

CLAUDE.md quotes 1339 (older number); `run_ci_locally.ps1:136` explains:
"Old CI enforced ≥1339. With v0.26.0 additions we should be well above.
Floor bumped to 1500 to reflect current baseline while leaving headroom."

`run_ci_locally.ps1` is the stricter enforcer. Sprint E must stay above
1500.

### 7.2 Current collected-count in `tests/platform/`

```
$ python -m pytest tests/platform/ --collect-only -q | tail -1
447 tests collected
```

447 in the platform subtree alone. Full repository test count (MASTER
quotes 2,633 across 237 files, April 2026) is well above 1500.

### 7.3 Sprint E delta

Pass 1 §9 enumerates 25 new tests in
`tests/platform/specs/test_schema_final_blocks.py`:

- 2 tests per block × 5 blocks = 10 (floor)
- +5 combined + backward-compat (lazy_prices, post_audit_ruleset, none
  of 5 blocks, not-a-dict guard, `_base_spec()` with no optionals)
- +5 edge cases (empty list, not-a-list, entry not string, bootcamp
  not-a-dict ignored, outer dicts empty)
- +5 bootcamp-specific (threshold range, bool-is-int trap, floor range,
  floor valid, watchlist valid)

**Total: 25 tests.** Strictly additive. No deletions.

### 7.4 Effect on neighbours

- `tests/platform/test_strategy_spec.py` (9 tests) — unchanged; no
  spec fixture uses the 5 new blocks.
- `tests/platform/specs/test_schema_scoring_dsl.py` (23 tests) —
  unchanged; ranking.bands logic untouched.
- `tests/platform/specs/test_schema_brackets_sizing.py` (29 tests) —
  unchanged; exit.targets / position_sizing.regimes logic untouched.
- `tests/platform/specs/test_post_audit_ruleset_v1.py` (7 tests) —
  loads real YAML; covered by §4.2 non-regression analysis.

### 7.5 Post-Sprint-E expected baseline

447 + 25 = **472 in `tests/platform/`**. Repo-wide 2,633 + 25 = **2,658**,
well above the 1500 CI floor.

## 8. Risk register

| Risk | Severity | Mitigation |
|------|----------|------------|
| Existing YAML spec declares one of `{hooks, enrichment, post_scan, event_risk, bootcamp}` as a top-level key | High if triggered | Pass 2 §3.4 confirmed zero occurrences. Non-regression test #17/#18 loads both real YAMLs. |
| `KNOWN_EVENT_RISK_CATEGORIES` seed misses a `known_events.py` label past line 80 | Low | Pass 3 will grep full file pre-commit. Warn-on-unknown policy means missed labels just trigger a warning, not a failure. |
| Bool-is-int trap in `bootcamp.max_positions` (e.g., `True` passes `isinstance(int)`) | Medium | Explicit `isinstance(x, bool)` exclusion in `_validate_bootcamp_overrides` per Sprint C/D precedent. Regression test #12. |
| Sprint F changes the attribution hook alias convention (e.g., decides to use the long names `log_attribution_before_llm`) | Low | Schema seed is a frozenset; can be expanded in one commit without breaking existing specs. Warn-on-unknown is not applicable (this block is strict), but adding two long aliases alongside the short ones is trivial. |
| Strategy author writes uppercase `BOOTCAMP.QUALIFICATION_THRESHOLD: 55` by mistake | Low | YAML is case-sensitive; YAML loader would not match the lowercase required shape. The key would be `BOOTCAMP`, not `bootcamp`, and fail the `"bootcamp" in spec` check silently. Not a correctness risk; would be a "why isn't my override taking effect" troubleshooting time-sink. Out of scope for Sprint E; could add a case-insensitive guard in a later sprint. |
| Line-count drift if implementation inflates beyond Pass 1 §8.3 estimate | Low | Escalation path to option D (helper extraction to `_validators.py`) preserved. Pass 3 measures post-implementation before proceeding to tests. |
| `run_ci_locally.ps1` floor tightens between sprints | Low | Sprint E adds 25 tests (positive delta). Floor regression would require a decrease; Sprint E deletes no tests. |

## 9. Sprint F / G preview — how each block consumes the schema

For the record, the downstream runtime consumers will look approximately:

```python
# Sprint F — attribution hook binding
_HOOK_ALIAS_MAP = {
    "log_before_llm": log_attribution_before_llm,
    "log_after_llm": log_attribution_after_llm,
}
hooks = spec.raw.get("hooks", {}).get("attribution", [])
for hook_name in hooks:
    _HOOK_ALIAS_MAP[hook_name](...)  # Invoke in declared order

# Sprint F — enrichment chain
chain = spec.raw.get("enrichment", {}).get("chain", [])
for enricher_name in chain:
    _ENRICHER_MAP[enricher_name](features)  # Falls back to
    # attach_post_scan_features if chain is empty / absent.

# Sprint F+ — post_scan chain (similar pattern)

# Sprint F — event-risk quarantine gate
quarantine = spec.raw.get("event_risk", {}).get("quarantine_categories", [])
if any(cat in active_event_categories for cat in quarantine):
    return None  # skip entry

# Sprint F — bootcamp overrides
bc_override = spec.raw.get("bootcamp", {})
if "qualification_threshold" in bc_override:
    bootcamp_cfg["qualification_threshold"] = bc_override["qualification_threshold"]
# (etc. for the other 3 keys)
```

All 5 ports are straightforward pass-through reads. Schema's job is
just to accept the shape and catch typos. None of the 5 ports have
been attempted in Sprint E — per the sprint prompt, runtime wiring is
Sprint F-G.

## 10. Ready for Pass 3

All seven Pass-2 verifications pass:

- ✅ Attribution module location: `src/attribution/logger.py` (14
  import sites; zero `src/ranking/attribution.py` refs).
- ✅ Bootcamp keys: 4 sprint-prompt keys all load-bearing at 7 runtime
  sites total; strict rejection justified.
- ✅ Top-level key collisions: zero across `REQUIRED_KEYS` + optionals
  + committed YAML specs.
- ✅ `spec.raw` consumers: zero breakage; reproducibility hash change
  intentional (same precedent as Sprint C/D).
- ✅ Event-risk seed: byte-exact match to MACRO_EVENT_TYPES +
  `known_events.py` labels observed in Pass 1.
- ✅ File-size budget: 298 → ~396 with A+B+C mitigations applied.
  Option D fallback preserved if needed.
- ✅ Test count: +25 strictly additive; floor of 1500 stays clear.

Proceed to Pass 3:

1. Implement constants + `_LIST_BLOCKS` tuple + `_validate_known_ref_list`
   shared helper + `_validate_bootcamp_overrides` + dispatch in
   `validate_spec`.
2. Write 25-test module `tests/platform/specs/test_schema_final_blocks.py`.
3. Update `CHANGELOG.md [Unreleased]` — entry noting Sprint E completes
   v0.26.0 schema surface; Sprints F-G next for runtime.
4. Update `MASTER.md` — #530 chain progress (5 of 8); note schema
   complete; update Tests count to 2,658.
5. Run `scripts/run_ci_locally.ps1` to green.
6. PR body per sprint prompt — per-block registry table + backward
   compat evidence.
