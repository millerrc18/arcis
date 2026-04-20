# Sprint B Pass 2 — `python_plugin` wiring research (#493 / #548)

**Follows:** `docs/sprints/python_plugin_wiring_evaluation.md` (Pass 1, commit `a93f223`).

Three questions per sprint prompt:

1. Verify `plugin_registry.py` interface — confirm `get_plugin` exists and shape.
2. Verify existing specs don't declare `python_plugin` kind (should be zero).
3. Confirm walk-forward runner doesn't dispatch through this path.

## 1. Plugin registry interface verification

```
$ grep -n "get_plugin\|register_plugin" src/platform/plugin_registry.py
14:from src.platform.strategy_plugin import StrategyPlugin
16:_PLUGINS: dict[str, type[StrategyPlugin]] = {}
19:def register_plugin(cls: type[StrategyPlugin]) -> type[StrategyPlugin]:
34:def get_plugin(strategy_id: str) -> Optional[StrategyPlugin]:
37:    cls = _PLUGINS.get(strategy_id)
38:    return cls() if cls else None
```

Signature confirmed:

```python
def get_plugin(strategy_id: str) -> Optional[StrategyPlugin]:
    """Return an instance of the registered plugin for this strategy_id,
    or None if no plugin is registered (e.g. for YAML-only strategies)."""
```

- **Input:** plugin's self-declared `strategy_id` string.
- **Return:** fresh plugin instance (via `cls()`) or `None`. **Not cached.**
- **No raise path** — missing registrations return `None`. Caller must handle.

`StrategyPlugin.find_candidates` signature (verified at `strategy_plugin.py:55`):

```python
def find_candidates(
    self, as_of: str, universe: list[str], context: dict,
) -> list[Candidate]: ...
```

**Important interface deltas from sprint prompt** (carried forward from Pass 1 §2):

| Prompt | Actual |
|--------|--------|
| `find_candidates(date, universe)` | `find_candidates(as_of, universe, context)` |
| returns `list[CandidateDict]` | returns `list[Candidate]` (dataclass) |

The implementation (Pass 3) translates `Candidate` → the dict shape
`shadow_harness._open_position` consumes (`.get("shares", 1)`, `.get("price", 0.0)`,
`.get("metadata", {})` — verified at `shadow_harness.py:220–257`).

`register_plugin` and `_clear_registry_for_tests` are also exposed. The
latter is the fixture hook the new tests will use to avoid cross-test
pollution (pattern already established in `test_strategy_plugin.py:13–17`).

## 2. YAML spec inventory — python_plugin specs on main

```
$ grep -rn '"kind":\s*"python_plugin"\|kind: python_plugin' src/ config/
(no matches outside docs)

$ grep -rn 'kind:\s*python_plugin' src/platform/specs/
(no matches)
```

The two YAML specs on main:

- `src/platform/specs/lazy_prices_v1.yaml` → `entry.kind: event_driven`
- `src/platform/specs/post_audit_ruleset_v1.yaml` → `entry.kind: event_driven`

**No YAML spec declares `entry.kind: python_plugin`.** The kind is listed in
`ALLOWED_ENTRY_KINDS` at `strategy_spec.py:24` (the validator accepts it)
but no one has registered a plugin or written a matching YAML yet. This
sprint is pure capability wiring — merge does not activate any production
strategy.

Similarly, `@register_plugin` appears nowhere in `src/` — only in tests and
docs. Zero registered plugins on main. Fresh-state wiring.

## 3. `plugin_ref` field inventory

```
$ grep -rn "plugin_ref\|plugin_name\|entry\.plugin" src/ tests/ config/
(no matches)
```

**Zero references to `plugin_ref` anywhere.** The field is new to this
sprint. Pass 1 Option C (optional `entry.plugin_ref`, fallback to
`spec.strategy_id`) is confirmed non-colliding:

- No spec declares it today.
- No validator checks it.
- Adding it as an **optional dict key read by the dispatcher** costs zero
  schema changes. `strategy_spec.REQUIRED_KEYS` untouched;
  `ALLOWED_ENTRY_KINDS` untouched; no new `entry.plugin_ref` validation
  needed in `validate_spec`.

This satisfies the sprint guardrail "No schema changes — Sprint C starts that."

## 4. Walk-forward path confirmation

```
$ grep -n "python_plugin" src/platform/backtest_engine.py
386:    elif kind == "python_plugin":
387:        raise NotImplementedError("python_plugin entry kind not supported in MVP")
```

`backtest_engine.run_backtest` still raises for `python_plugin` kind —
**this sprint does not change that**. Historical replay for plugin
strategies requires OHLCV iteration + per-day `plugin.find_candidates`
calls, which is a separate Sprint-C-or-later task.

Walk-forward runner path:

```
$ grep -rn "run_backtest\|find_candidates_for_date\|python_plugin" \
      src/platform/rigor/
src/platform/rigor/walkforward.py:23: from src.platform.backtest_engine import BacktestConfig, run_backtest
src/platform/rigor/walkforward.py:77: train_result = run_backtest(train_cfg)
src/platform/rigor/walkforward.py:86: test_result = run_backtest(test_cfg)
```

- Walk-forward routes `python_plugin` → `run_backtest` → `NotImplementedError`
  (unchanged before and after this sprint).
- Walk-forward does **not** call `signal_eval.find_candidates_for_date`
  (confirmed again — same finding as Sprint A Pass 2 §3).

Pass 1 Test #12 (`test_walkforward_path_still_raises_for_python_plugin`)
codifies this: walk-forward behavior is identical pre- and post-merge.

## 5. Caller audit — who calls `find_candidates_for_date`?

```
$ grep -rn "find_candidates_for_date" src/ tests/
src/platform/signal_eval.py:168:def find_candidates_for_date(
src/platform/signal_eval.py:191:    if kind == "python_plugin":  # currently raises
src/platform/shadow_harness.py:171: from src.platform.signal_eval import find_candidates_for_date
src/platform/shadow_harness.py:173: return find_candidates_for_date(...)
tests/platform/test_find_candidates.py:14:from src.platform.signal_eval import find_candidates_for_date
tests/platform/test_signal_eval_scheduled.py:*: (Sprint A tests)
```

Only one runtime caller: `ShadowHarness._find_candidates`, wrapped in a
broad `except Exception` at `shadow_harness.py:176`. All three Sprint B
error paths (`KeyError`, `RuntimeError`, `TypeError`) are caught → tick
continues with 0 candidates, just like Sprint A degradations.

No test asserts the current `NotImplementedError` for python_plugin outside
Sprint A's scheduled test file — Sprint A Pass 2 already audited this.

## 6. Risk assessment

| Risk | Severity | Mitigation |
|------|----------|------------|
| `spec.strategy_id` collides with a plugin's `strategy_id()` when caller wants a YAML-only strategy | low | `get_plugin(id)` returns `None` when nothing registered — raises only on python_plugin kind which is gated by `entry.kind` check. Non-python_plugin specs never enter this branch. |
| Plugin holds expensive state (ML model load on every tick) | accepted | No caching in signal_eval per Pass 1 §4. A future sprint can memoize `get_plugin` calls in `plugin_registry.py`. Profiling-driven. |
| Candidate metadata clobber: plugin puts `strategy_spec_hash` in metadata; wrapper overwrites | accepted | Wrapper adds keys AFTER `dict(c.metadata or {})`, so `update()` wins. Plugins that want to override must set keys not in the wrapper's reserved set (`strategy_spec_hash`, `trigger`, `signal_direction`, `plugin_ref`). Document in Pass 3 impl docstring. |
| `Candidate.signal_direction == 'short'` silently drops to long in harness | accepted | Harness short support is a separate sprint. Direction is stashed in metadata so no information is lost; the harness will start reading it when short support lands. |
| Plugin raises a PluginException that we wrap with `RuntimeError` — loses original type | accepted | `raise RuntimeError(...) from exc` preserves original in `__cause__`; debuggability preserved. Users who catch specific plugin exceptions are rare (plugins are trust-boundary code, not third-party). |
| File budget 450 exceeded | medium | Pass 1 estimated 454 lines. Edit-time compression targets the `_find_candidates_python_plugin` docstring and inline the `from src.platform.plugin_registry import get_plugin` at module top if needed. |

## 7. Decision lock-in

- **Lookup key:** `entry.get("plugin_ref") or spec.strategy_id`.
- **Registry call:** `get_plugin(plugin_ref)`; `None` → `KeyError` with hint.
- **Plugin call:** `plugin.find_candidates(as_of_iso, tickers, context)` where
  `context = {"db_path": live_db, "strategy_id": spec.strategy_id}`.
- **Translation:** `Candidate` → dict per Pass 1 §2 table; wrapper adds
  `strategy_spec_hash`, `trigger: "python_plugin"`, `signal_direction`,
  `plugin_ref` to metadata (update-after-copy ordering).
- **Error handling:** `KeyError` (missing), `RuntimeError` (plugin raised,
  chained via `from`), `TypeError` (wrong return shape). No new classes.
- **Harness tolerance:** broad `except Exception` in
  `shadow_harness._find_candidates` catches all three.
- **Backtest path:** untouched. `run_backtest` still raises for python_plugin.
- **Walk-forward path:** untouched (routes through backtest).
- **Schema:** untouched. `entry.plugin_ref` is an optional dict key, not a
  validated field.

Pass 3 proceeds with this decision lock.
