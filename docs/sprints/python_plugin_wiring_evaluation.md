# Sprint B Pass 1 — `python_plugin` find_candidates_for_date evaluation (#493 / #548)

**Sprint:** feat/python-plugin-wiring (2 of 8 in #530 chain).
**Branch:** `claude/scheduled-kind-find-candidates-KeLXe` (stacked on Sprint A's
commits `c07f17d`, `943a8db`, `0d45ca0`).
**Target:** `src/platform/signal_eval.py` python_plugin branch currently raises
`NotImplementedError("python_plugin find_candidates_for_date is Task 2 (issue #474)")`
at the dispatcher in `find_candidates_for_date` (post-Sprint A ref: lines 191–194).

## 1. Sprint A shape read — `_find_candidates_scheduled` (signal_eval.py:249–283)

Reading Sprint A line-by-line so the python_plugin branch mirrors it deliberately:

| Step | Sprint A line(s) | Behavior |
|------|------------------|----------|
| 1 | 258–259 | `_resolve_universe(spec.universe["tickers"])` — shared universe resolution (list or `"sp100"` alias). |
| 2 | 260–263 | Apply `spec.universe.sector_filter` via `SECTOR_MAP` (v0.26.2-scoped). |
| 3 | 264–266 | Empty universe → warn + `[]`. |
| 4 | 267–268 | Kind-specific trigger check (scheduled: `_matches_scheduled_trigger`). |
| 5 | 269–271 | `is_excluded_event_date(as_of_iso, entry)` (v0.26.2-scoped). |
| 6 | 273 | `live_db = env("PLATFORM_EDGAR_DB", db_path)`. |
| 7 | 274–275 | `desk = f"research_{spec.strategy_id}"` + `_load_open_tickers_for_desk(desk, live_db)`. |
| 8 | 276–277 | `spec_hash = _spec_hash(spec)`; `as_of_iso = as_of.isoformat()`. |
| 9 | 278–283 | Build candidate dict via `_build_candidate` per qualifying ticker. |

The python_plugin branch will reuse steps 1–3, 5–9 verbatim. Step 4 (trigger
check) is replaced by the plugin dispatch itself — the plugin's `find_candidates`
method returns exactly the tickers it wants to trade, so there's no separate
"does the trigger fire?" gate.

## 2. Plugin registry interface read

From `src/platform/plugin_registry.py`:

```python
_PLUGINS: dict[str, type[StrategyPlugin]] = {}

def get_plugin(strategy_id: str) -> Optional[StrategyPlugin]:
    cls = _PLUGINS.get(strategy_id)
    return cls() if cls else None
```

- Keyed by plugin's self-declared `strategy_id()`.
- `get_plugin(id)` returns a **fresh instance per call** (the registry stores
  classes; calls instantiate). Non-cached — cheap dataclasses, acceptable.
- Returns `None` on miss (not raise).

From `src/platform/strategy_plugin.py`:

```python
@abstractmethod
def find_candidates(
    self, as_of: str, universe: list[str], context: dict,
) -> list[Candidate]: ...

@dataclass
class Candidate:
    ticker: str
    as_of: str
    signal_direction: str         # 'long' | 'short'
    signal_strength: float
    metadata: dict = field(default_factory=dict)
```

**Interface deltas from the sprint prompt:**

- Sprint prompt: `find_candidates(date: str, universe: list[str]) -> list[CandidateDict]`
- Actual: `find_candidates(as_of: str, universe: list[str], context: dict) -> list[Candidate]` (dataclass, not dict)

The prompt's `date` param is `as_of`; the prompt omits `context`; and the return
is a `Candidate` dataclass (not a dict). The wiring must translate `Candidate`
objects → the signal_eval dict shape that `shadow_harness._open_position`
already consumes (verified at `shadow_harness.py:230–257` via `.get("shares",1)`,
`.get("price",0.0)`, `.get("metadata",{})`).

**Translation:**

| Plugin `Candidate` field | Signal_eval dict field |
|--------------------------|------------------------|
| `ticker` | `ticker` |
| `as_of` | `as_of` |
| `signal_strength` | `signal_strength` |
| `metadata` (plugin-supplied) | `metadata` (augmented with `strategy_spec_hash`, `trigger: "python_plugin"`, `signal_direction`) |
| `signal_direction` | → metadata key (harness doesn't read direction from top-level; short support is a separate sprint) |
| — | `shares = 1` (harness sizing responsibility) |
| — | `price = 0.0` (live lookup at order time) |

## 3. Decision: which spec field carries the plugin name?

The sprint prompt suggests `spec.entry.plugin_ref` but asks Pass 2 to verify.
Pass 2 grep finds **zero references** to `plugin_ref`, `plugin_name`, or
`entry.plugin` anywhere in the repo — no existing convention to honor.

Options considered:

| Option | Lookup key | Pros | Cons |
|--------|-----------|------|------|
| A | `spec.strategy_id` | Plugin self-identifies by strategy_id; YAML + Python share one id. Matches `plugin_registry` design exactly. | No way for a YAML spec to reference a plugin registered under a different id. |
| B | `spec.entry.plugin_ref` | Explicit decoupling; multiple YAML specs can share a plugin; clearer to readers. | New schema field (sprint prohibits schema changes); adds indirection for no current use case. |
| C | `entry.plugin_ref` override, fallback to `spec.strategy_id` | Flexibility without requiring the field. | Two-path logic in a branch the prompt says to keep small. |

**Decision: Option C — `entry.plugin_ref` optional, fallback to `spec.strategy_id`.**

Rationale:
- Zero impact on the only production path (YAML + Python share strategy_id).
- `entry.plugin_ref` is a plain-dict lookup on `spec.entry`, NOT a schema change
  (no validator edit in `strategy_spec.py`; it's an optional key the
  dispatcher reads, same pattern as `entry.signal` / `entry.event_filter`).
- Sprint prompt explicitly says "verify in Pass 2" — the flexibility is the
  conservative choice.
- Test matrix covers both lookup paths.

## 4. Decision: caching / lazy init

The registry returns a **fresh instance per `get_plugin` call**
(`cls()` at registry line 38). Two considerations:

1. Live scan hits `find_candidates_for_date` once per tick — not hot. No caching
   needed.
2. Plugins may hold expensive state (ML models, embeddings). A future sprint
   can add instance caching in `plugin_registry.py` if profiling shows cost.
   Out of scope here.

**Decision: use `get_plugin(name)` verbatim, no caching in signal_eval.** The
new branch calls once per live tick, allocates the plugin instance once per
tick, discards it — matches Sprint A simplicity.

## 5. Error-path design

Sprint A's error contract:
- Bad universe / empty universe / trigger miss / excluded day → `[]`.
- Unknown `entry.kind` → `ValueError`.
- DB failures (shadow_trades missing) → degrade to empty dedup set (no raise).

Sprint B additions:

| Condition | Behavior | Error type |
|-----------|----------|------------|
| `entry.plugin_ref` missing AND `spec.strategy_id` missing | Can't happen (StrategySpec requires `strategy_id`). | — |
| Plugin not in registry | Raise. | `KeyError` with `plugin_ref=<name>` + helpful "did you forget to `@register_plugin`?" hint. |
| Plugin's `find_candidates` raises | Bubble — wrap with plugin name context. | Re-raise `RuntimeError` from the original exception (chained via `from e`). |
| Plugin returns non-list | Raise. | `TypeError`. |
| Plugin returns list of non-`Candidate` items | Raise. | `TypeError` per item. |

Why these error types, not custom classes? Sprint prompt: "Match Sprint A's
error handling pattern — don't invent new exception types." Sprint A used
`ValueError` for unknown kind and plain `warnings` for expected degradations.
The python_plugin branch uses built-ins (`KeyError`, `RuntimeError`, `TypeError`)
for three cleanly distinguishable misuse cases. No new classes.

Harness tolerance: `shadow_harness._find_candidates` (line 176) wraps in a
broad `except Exception` that logs + continues with `[]`. All three raises
above are caught — tick doesn't die.

## 6. Implementation sketch

```python
def _find_candidates_python_plugin(spec, db_path, as_of) -> list[dict]:
    """python_plugin-kind candidate generation at a single as_of date (#493).

    Dispatches to the registered StrategyPlugin whose id is
    spec.entry.get("plugin_ref") or spec.strategy_id. Translates the plugin's
    Candidate dataclass objects into the dict shape shadow_harness expects,
    applies universe / sector_filter / dedup / event_exclusion like the
    scheduled and event_driven paths.
    """
    from src.platform.plugin_registry import get_plugin

    entry = spec.entry
    tickers = _resolve_universe(spec.universe.get("tickers", []))
    sector_filter = spec.universe.get("sector_filter")
    if sector_filter:
        from src.universe.sectors import SECTOR_MAP
        tickers = [t for t in tickers if SECTOR_MAP.get(t) in sector_filter]
    if not tickers:
        logger.warning("[SIGNAL_EVAL] empty universe for %s; returning []", spec.strategy_id)
        return []

    entry_iso = as_of.strftime("%Y-%m-%d")
    if is_excluded_event_date(entry_iso, entry):
        return []

    plugin_ref = entry.get("plugin_ref") or spec.strategy_id
    plugin = get_plugin(plugin_ref)
    if plugin is None:
        raise KeyError(
            f"python_plugin find_candidates_for_date: no plugin registered "
            f"for plugin_ref={plugin_ref!r}. Did you import the module "
            f"that declares @register_plugin?"
        )

    live_db = os.environ.get("PLATFORM_EDGAR_DB", db_path)
    context = {"db_path": live_db, "strategy_id": spec.strategy_id}
    as_of_iso = as_of.isoformat()
    try:
        raw = plugin.find_candidates(as_of_iso, tickers, context)
    except Exception as exc:
        raise RuntimeError(
            f"plugin {plugin_ref!r} find_candidates raised: {exc}"
        ) from exc

    if not isinstance(raw, list):
        raise TypeError(
            f"plugin {plugin_ref!r} must return list, got {type(raw).__name__}"
        )

    desk = f"research_{spec.strategy_id}"
    open_tickers = _load_open_tickers_for_desk(desk, live_db)
    spec_hash = _spec_hash(spec)
    out: list[dict] = []
    for c in raw:
        if not isinstance(c, Candidate):
            raise TypeError(
                f"plugin {plugin_ref!r} returned {type(c).__name__}; "
                f"expected Candidate"
            )
        if c.ticker in open_tickers:
            continue
        meta = dict(c.metadata or {})
        meta.update({
            "strategy_spec_hash": spec_hash,
            "trigger": "python_plugin",
            "signal_direction": c.signal_direction,
            "plugin_ref": plugin_ref,
        })
        out.append({
            "ticker": c.ticker,
            "as_of": as_of_iso,
            "shares": 1,
            "price": 0.0,
            "signal_strength": c.signal_strength,
            "metadata": meta,
        })
    return out
```

Wire into dispatcher: replace the `NotImplementedError` raise at lines 191–194
with `return _find_candidates_python_plugin(spec, db_path, as_of)`.

**Line budget:** ~55 new lines + dispatcher change. 399 → ~454. Over the
450 budget by ~4 lines. **Action:** compress docstring to 2 lines; inline
the plugin-kind import at top of module to free a line; remove redundant
`plugin is None` error-message padding. Target ≤ 449.

## 7. Test plan — `tests/platform/test_signal_eval_python_plugin.py`

Fixed historical date: **2023-11-06 (Monday)** — reuses Sprint A's anchor.
`clean_registry` autouse fixture borrowed from `test_strategy_plugin.py`.

| # | Name | Setup | Assertion |
|---|------|-------|-----------|
| 1 | `test_python_plugin_dispatches_to_registered_plugin` | Register MockPlugin (`strategy_id=pp_v1`); spec.strategy_id=`pp_v1`; universe=`["AAPL","MSFT"]`. | `len(candidates) == 2` (plugin returns one per ticker); metadata.trigger==`python_plugin`. |
| 2 | `test_python_plugin_honors_entry_plugin_ref_override` | Register `actual_plugin`; spec.strategy_id=`wrapper_id`, entry.plugin_ref=`actual_plugin`. | Plugin is called; candidates returned. |
| 3 | `test_python_plugin_missing_plugin_raises_keyerror` | No registration; kind=`python_plugin`. | `KeyError` matching `plugin_ref`. |
| 4 | `test_python_plugin_raising_bubbles_with_context` | Plugin whose `find_candidates` raises `ValueError("boom")`. | `RuntimeError` chained; plugin name in str. |
| 5 | `test_python_plugin_non_list_return_raises_typeerror` | Plugin returns `"wat"`. | `TypeError` matching `"expected list"`. |
| 6 | `test_python_plugin_wrong_item_type_raises_typeerror` | Plugin returns `[{"ticker":"AAPL"}]` (dict, not Candidate). | `TypeError` with item type. |
| 7 | `test_python_plugin_candidate_shape_matches_contract` | Mock plugin returns 1 candidate. | Dict has keys `ticker, as_of, shares, price, signal_strength, metadata`; metadata has `strategy_spec_hash, trigger, signal_direction, plugin_ref`. |
| 8 | `test_python_plugin_dedupes_open_positions` | Seed open shadow_trade for `AAPL` desk=`research_pp_v1`; plugin returns AAPL + MSFT. | Only MSFT emitted. |
| 9 | `test_python_plugin_sector_filter_applied` | Spec sector_filter=`["Technology"]`; plugin ignores universe arg; return tickers. | Plugin's universe arg is already sector-filtered (universe passed in == filtered tickers). |
| 10 | `test_python_plugin_event_exclusion_applied` | Mock `is_excluded_event_date` → True. | `[]`. |
| 11 | `test_python_plugin_empty_universe_returns_empty` | universe=`[]`. | `[]`; plugin NOT called (verify via mock call-count=0). |
| 12 | `test_walkforward_path_still_raises_for_python_plugin` | Confirm `backtest_engine.run_backtest` still raises `NotImplementedError` for python_plugin kind (out of sprint scope — historical replay is not wired). | `NotImplementedError` preserved. |

## 8. Guardrails checklist

- [x] No schema changes. `entry.plugin_ref` is an optional dict key the dispatcher
      reads; `strategy_spec.py` validator not modified (see Pass 2 verify).
- [x] No plugin registry changes. signal_eval is a read-only consumer of
      `get_plugin`.
- [x] No changes to scheduled / event_driven branches.
- [x] No new exception types — use built-ins.
- [x] Backtest_engine `_run_python_plugin` (which doesn't exist) is out of scope;
      `run_backtest` still raises `NotImplementedError` for python_plugin kind.
- [ ] Line budget: target ≤ 450 (current impl sketch: 454 → needs ~4 lines
      compressed at edit time).

## 9. Next

Pass 2: verify `plugin_registry.get_plugin` signature and return type (done
inline here but Pass 2 will also grep for `plugin_ref` in tests/docs, confirm
no YAML spec on main declares `entry.kind: python_plugin`, confirm walk-forward
path is preserved).
