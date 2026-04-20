# Sprint A Pass 2 — scheduled-kind wiring research findings (#494)

**Follows:** `docs/sprints/scheduled_kind_wiring_evaluation.md` (Pass 1, commit `c07f17d`).

Three research questions per sprint prompt:

1. Do any callers depend on the scheduled branch raising `NotImplementedError` / returning `[]` with a warning?
2. Which YAML specs on main declare `entry.kind: scheduled`?
3. Does `walkforward_runner` bypass `find_candidates_for_date` via `backtest_engine._run_scheduled`?

## 1. Caller dependency audit

### 1a. `NotImplementedError` for scheduled kind

```
$ grep -rn "NotImplementedError.*scheduled" src/ tests/
(no matches — current tree returns [] with warning, not raises)
```

All `NotImplementedError` references for scheduled-kind live in docs:

| File | Lines | Nature |
|------|-------|--------|
| `docs/sprints/incumbent_v1_yaml_evaluation.md` | 237 | Historical quote |
| `docs/sprints/incumbent_v1_yaml_research.md` | 36 | Historical quote |
| `docs/sprints/roadmap_completeness_research.md` | 31, 82, 87 | Historical quote |
| `frontend/src/pages/Roadmap.jsx` | 150 | Public roadmap description |

**None of these are runtime callers.** The docs freeze the state as of their
authorship; the roadmap entry is display text. Safe to change behavior.

### 1b. Warning-and-return-`[]` dependency

Only runtime caller of `find_candidates_for_date`:
`src/platform/shadow_harness.py:163–181`:

```python
def _find_candidates(self, as_of: datetime) -> list[dict]:
    from src.platform.signal_eval import find_candidates_for_date
    try:
        return find_candidates_for_date(self.spec, db_path=self.db_path, as_of=as_of)
    except Exception:
        logger.exception("[HARNESS %s] _find_candidates failed; tick continues with []", ...)
        return []
```

The harness:
- Tolerates `NotImplementedError` via the broad `except Exception` catch → degrades to 0 candidates (current behavior).
- Accepts any `list[dict]` return (including empty). No caller assumes `[]`.
- After this sprint, scheduled specs will receive real candidates through the normal path — matches the event_driven contract the harness was built around.

### 1c. Test-suite dependency

Two existing tests in `tests/platform/test_find_candidates.py` assert the
current stub behavior and must be updated (called out in Pass 1 §7):

| Test | Current assertion | New behavior expected |
|------|-------------------|------------------------|
| `test_find_candidates_scheduled_kind_returns_empty_or_raises` | `candidates == []` OR `NotImplementedError` | Emits one candidate per universe ticker on trigger-match day |
| `test_find_candidates_for_scheduled_spec_fires_warning` | warning containing "scheduled" or "not supported" | Retarget to python_plugin, OR delete |

No other tests hardcode the stub behavior:

```
$ grep -rn "find_candidates_for_date" tests/
tests/platform/test_find_candidates.py:14
tests/platform/test_find_candidates.py:68
tests/platform/test_find_candidates.py:88
tests/platform/test_find_candidates.py:116
tests/platform/test_find_candidates.py:149
tests/platform/test_find_candidates.py:177
```

All within the same file — scoped change.

`tests/platform/test_shadow_harness.py` uses `entry.kind: scheduled` in its
spec fixture (line 24) **but patches `_find_candidates` directly with
`return_value=fake_cands`** (lines 71, and again in other tests). The harness
test never hits `signal_eval.find_candidates_for_date` — orthogonal to this
sprint.

`tests/platform/rigor/test_walkforward.py` (line 27) uses scheduled specs
but exercises `run_backtest` via walkforward — see §3.

## 2. YAML spec inventory — scheduled specs on main

```
$ grep -rn "kind: scheduled" src/platform/specs/
(no matches)

$ grep -rn "kind: scheduled" src/
(no matches)
```

**Neither `lazy_prices_v1.yaml` nor `post_audit_ruleset_v1.yaml` declare
`entry.kind: scheduled`.** Both are `event_driven` (cosine similarity on
EDGAR filings). The only scheduled specs that exist today are:

- Test fixtures in `tests/platform/test_backtest_engine.py`, `test_shadow_harness.py`, `test_find_candidates.py`, `test_strategy_spec.py`, `test_walkforward.py`, `test_vix_enrichment.py` — all constructed in-memory via `StrategySpec(...)`.

**Conclusion:** this sprint does not activate any production strategy. It
unblocks specs that `#530` Sprint A chain will introduce (incumbent YAML
extraction, #523) and the broader v0.26.0 family, but no YAML on main
begins firing candidates as a side effect of the merge.

This is the intended posture: implement the capability first, then migrate
specs.

## 3. Walk-forward bypass confirmation

The sprint prompt states walk-forward bypasses `signal_eval` via
`backtest_engine._run_scheduled`. Verification:

```
$ grep -rn "find_candidates_for_date\|signal_eval" src/platform/rigor/
(no matches)
```

```
$ grep -rn "run_backtest\|_run_scheduled" src/platform/rigor/
src/platform/rigor/walkforward.py:23: from src.platform.backtest_engine import BacktestConfig, run_backtest
src/platform/rigor/walkforward.py:77:  train_result = run_backtest(train_cfg)
src/platform/rigor/walkforward.py:86:  test_result = run_backtest(test_cfg)
src/platform/rigor/trials.py:4:       scripts.run_backtest (records each trial on completion — Sprint 3+).
src/platform/rigor/walkforward_runner.py:4: Calls: src.platform.backtest_engine.run_backtest, ...
```

Dispatcher in `backtest_engine.run_backtest` (line 380–389):

```python
kind = spec.entry.get("kind")
if kind == "scheduled":
    trades = _run_scheduled(config)
elif kind == "event_driven":
    trades = _run_event_driven(config)
elif kind == "python_plugin":
    raise NotImplementedError("python_plugin entry kind not supported in MVP")
```

`_run_scheduled` is a pure historical-replay function that:
- iterates trading days,
- calls `_matches_scheduled_trigger(day, entry)` (shared helper from
  `signal_eval.py:31`, also used by the new live path — no behavior fork),
- loads OHLCV bars,
- builds `BacktestTrade` rows.

It does **not** reach `find_candidates_for_date`. The live scan path
(`shadow_harness → signal_eval.find_candidates_for_date`) and the backtest
path (`run_backtest → _run_scheduled`) are independent siblings. **Confirmed:
this sprint does not affect walk-forward runs.**

The one helper both branches will share after this sprint is
`_matches_scheduled_trigger`. That function is stateless, 5 lines, and
predates the sprint — no behavior change there.

## 4. Risk assessment

| Risk | Severity | Mitigation |
|------|----------|------------|
| Broken existing test: `test_find_candidates_scheduled_kind_returns_empty_or_raises` | medium | Update contract per Pass 1 §7 in same commit as the impl. |
| Broken existing test: `test_find_candidates_for_scheduled_spec_fires_warning` | low | Delete — the warning is removed. |
| `400-line file budget` exceeded | medium | Pass 1 decision: inline the scheduled_row dict into `_build_candidate` args; keep scheduled function ≤30 lines. |
| Harness silently emits candidates when operator expects the deferred-stub behavior | low (desirable) | New CHANGELOG entry + PR body call-out. |
| Shadow dedup breaks for scheduled strategies (strategy_id with unexpected characters) | low | `_load_open_tickers_for_desk` is reused verbatim; any bug would already affect event_driven. |
| Unknown universe alias for scheduled spec | low | `_resolve_universe` already warns + returns `[]`; scheduled returns `[]` for empty universe — same as event_driven. |
| Cosine-style signal arrives in a scheduled spec's `entry.signal` | accepted | v0.26.x sprint scope; for MVP, scheduled ignores `entry.signal`. Document explicitly in the code comment + CHANGELOG. |

## 5. Decision lock-in

- **Behavior:** on match day, emit one candidate per (resolved-universe ∩ sector_filter ∩ not-already-open) ticker; on non-match / empty universe / excluded-event day, return `[]`.
- **Signal filter:** ignored for scheduled (MVP). Future cron/interval DSL → separate sprint.
- **Dedup:** reuse `_load_open_tickers_for_desk`.
- **Metadata:** `{"trigger": "scheduled", "strategy_spec_hash": <12-char-hex>}` — `filing_*` keys omitted.
- **Signal strength:** constant 0.5 (neutral). Scheduled does not rank.
- **Error handling:** match event_driven (warn + `[]` on any degradation; no new exceptions).

Pass 3 proceeds with this decision lock.
