# Sprint A Pass 1 — scheduled-kind `find_candidates_for_date` evaluation (#494)

**Sprint:** feat/scheduled-kind-wiring (first of 8 in #530 Sprint A chain).
**Branch:** `claude/scheduled-kind-find-candidates-KeLXe`.
**Target:** `src/platform/signal_eval.py` scheduled branch currently returns
`[]` with a warning (note: older docs/research notes reference an
`NotImplementedError` — that was the historical state; the current tree
returns `[]`. Either way the effect on callers is identical: scheduled specs
never resolve candidates through `ShadowHarness._find_candidates`.)

## 1. Reference read — `_find_candidates_event_driven` (signal_eval.py:210–258)

Reading the event-driven branch line-by-line so the scheduled branch can
reuse shape, error handling, and side-effects deliberately rather than by
coincidence.

| Step | Line(s) | Behavior |
|------|---------|----------|
| 1 | 223–226 | Read `entry.signal` (list), `entry.combinator` (default `all`), `filing_date_within_days` (default 5). |
| 2 | 227–230 | `_resolve_universe(spec.universe["tickers"])` — handles list/alias; empty → warn + `[]`. |
| 3 | 232 | `live_db = env("PLATFORM_EDGAR_DB", db_path)` — env override honored. |
| 4 | 233–235 | Query event table via `_query_event_rows_for_date`; `None` sentinel → `[]`. |
| 5 | 237–239 | `desk = f"research_{spec.strategy_id}"`; load open tickers (empty set on any DB miss — dedup is best-effort). |
| 6 | 239 | `_spec_hash(spec)` — 12-char SHA256 of id/entry/exit for metadata tagging. |
| 7 | 243–257 | Per row: skip if already open; parse `sections_json`; inject cosine scores; evaluate signal+combinator; compute signal strength; append `_build_candidate(...)` dict. |
| 8 | 258 | Return list; one dict per qualifying row. |

### Candidate dict shape (authoritative — `_build_candidate` 320–336)

```python
{
  "ticker": str,
  "as_of": ISO8601 str,         # as_of.isoformat()
  "shares": 1,                  # sizing is harness responsibility
  "price": 0.0,                 # harness fetches live price
  "signal_strength": float,     # [0,1] heuristic
  "metadata": {
    "filing_accession": str,    # event_driven only
    "filing_date": str,
    "form_type": str,
    "strategy_spec_hash": str,  # short hash
  },
}
```

For scheduled there is no filing; metadata will carry `trigger: "scheduled"`
(matches `backtest_engine._run_scheduled` metadata at line 296) plus the
`strategy_spec_hash`. `filing_accession`/`filing_date`/`form_type` are
event-driven-only keys and will be absent from the scheduled metadata (the
consuming harness reads `.get(...)` on all of them in `shadow_harness.py`, so
absence is safe — verified Pass 2).

## 2. Reference read — `backtest_engine._run_scheduled` (backtest_engine.py:271–300)

Scheduled lives in the backtest engine today:

1. Resolve `spec.universe.tickers`. **Known gap:** the backtest version
   short-circuits with `if not isinstance(tickers, list): return []` — it
   does NOT honor string aliases like `"sp100"`. The live path MUST go
   through `_resolve_universe` to match the event-driven contract.
2. For each ticker + each trading day in `[start_date, end_date]`:
   - Call `_matches_scheduled_trigger(day, entry_spec)` — already exists in
     `signal_eval.py` (line 31). Fires on `day_of_week` match or when key
     absent (always-fire).
   - Load OHLCV bar for that day (backtest-only; live flow gets price from
     the harness at order time → skip).
3. Append a trade per matching day.

For the **live** scheduled path, the analogue is: given a single `as_of`
datetime, determine whether the trigger fires today, and if so emit one
candidate per ticker in the resolved universe.

## 3. Decision — reuse vs. fork

**Decision: reuse, don't fork.**

The event-driven helpers that carry over unchanged:

- `_resolve_universe` — universe resolution (list or `"sp100"` alias).
- Sector filtering block (lines 133–135 in `_query_event_rows`): apply
  `spec.universe.sector_filter` via `SECTOR_MAP`.
- `_load_open_tickers_for_desk` — dedup against open shadow_trades.
- `_spec_hash` — metadata tagging.
- `_build_candidate` — shape producer, with event-specific `row` arg
  replaced by a minimal scheduled-row dict (trigger metadata only).
- `is_excluded_event_date` — the v0.26.2-scoped `entry.event_exclusion`
  check; applies identically once `as_of_iso` is resolved.

The event-driven helpers that do **not** apply:

- `_query_event_rows_for_date` — no event table to query for scheduled.
- `_inject_cosine_scores` + `_evaluate_event_signal` — scheduled specs use
  a different signal vocabulary (day-of-week triggers today; v0.26.x will
  add cron/interval, not cosine). MVP: no signal filter for scheduled —
  universe ∩ sector_filter ∩ trigger-fires ∩ not-already-open ∩
  not-excluded-event. This matches the sprint prompt's "empty-filter case
  returns full universe" requirement.

**Shared** helper extraction: none. The two branches are siblings, not a
template method pattern. Introducing a shared helper now would be
over-abstraction; three similar lines are fine.

## 4. Implementation sketch (scheduled branch)

```python
def _find_candidates_scheduled(spec, db_path, as_of) -> list[dict]:
    entry = spec.entry
    tickers = _resolve_universe(spec.universe.get("tickers", []))
    sector_filter = spec.universe.get("sector_filter")
    if sector_filter:
        from src.universe.sectors import SECTOR_MAP
        tickers = [t for t in tickers if SECTOR_MAP.get(t) in sector_filter]
    if not tickers:
        logger.warning(...); return []

    if not _matches_scheduled_trigger(as_of, entry):
        return []

    as_of_iso = as_of.isoformat()
    entry_iso = as_of.strftime("%Y-%m-%d")
    if is_excluded_event_date(entry_iso, entry):
        return []

    live_db = os.environ.get("PLATFORM_EDGAR_DB", db_path)
    desk = f"research_{spec.strategy_id}"
    open_tickers = _load_open_tickers_for_desk(desk, live_db)
    spec_hash = _spec_hash(spec)

    scheduled_row = {"trigger": "scheduled",
                     "accession_number": "",
                     "filing_date": None,
                     "form_type": None}
    candidates = []
    for t in tickers:
        if t in open_tickers:
            continue
        candidates.append(
            _build_candidate(t, as_of_iso, 0.5, scheduled_row, spec_hash)
        )
    return candidates
```

Wire into `find_candidates_for_date`: replace the `if kind == "scheduled"`
warning-and-return-`[]` block with `return _find_candidates_scheduled(...)`.

Signal-strength: constant 0.5 (neutral). Scheduled triggers don't express a
relative-strength signal today; harness sizing already treats this as a
tiebreaker. A cron/interval DSL in v0.26.x can refine later.

**Line budget:** ≈40 new lines (one new private function + 2-line branch
rewrite). signal_eval.py 370 → ~410. That pushes the 400-line cap. **Action:**
fold `scheduled_row` into `_build_candidate` call inline to trim; keep
function ≤30 lines. If still over, consider shrinking inline docstrings in
unrelated helpers (don't touch event-driven code).

## 5. Error-handling parity

- Unknown operator / bad spec → no new exception types. `_evaluate_event_signal`
  doesn't run for scheduled (no cosine conditions). The "unknown operator
  raises" regression guard test will use the event-driven path (existing
  behavior via `_evaluate_event_signal`) to verify nothing changed, or move
  to a sibling test that calls `_evaluate_event_signal` directly.
- DB errors (shadow_trades missing) — `_load_open_tickers_for_desk` already
  returns empty set on any `Exception`; reused verbatim.
- Empty universe — warn + `[]` (matches event_driven line 229).

## 6. Test plan — `tests/platform/test_signal_eval_scheduled.py`

Fixed historical date: **2023-11-06 (Monday)**. Matches `test_find_candidates.py`
fixture window and aligns with the existing scheduled-spec fixture at
`test_find_candidates.py:131–143`.

| # | Name | Setup | Assertion |
|---|------|-------|-----------|
| 1 | `test_scheduled_kind_resolves_candidates_for_fixed_date` | Spec: universe=`["AAPL","MSFT"]`, entry.kind=scheduled, day_of_week=Monday. `as_of = 2023-11-06`. | `len(candidates) == 2`; shape matches event_driven. |
| 2 | `test_scheduled_empty_filter_returns_full_universe` | Same spec, no `day_of_week` key. | All universe tickers become candidates. |
| 3 | `test_scheduled_sector_filter_applied` | Spec universe=`sp100`, `sector_filter: [Technology]`. | Returned tickers ⊆ SECTOR_MAP tech tickers. |
| 4 | `test_scheduled_event_exclusion_applied` | `as_of` patched to land on a KNOWN_EVENTS Trade Policy date; `entry.event_exclusion.categories=[Trade Policy]`. | `[]`. |
| 5 | `test_scheduled_day_of_week_mismatch` | spec day_of_week=Friday, as_of=Monday. | `[]`. |
| 6 | `test_scheduled_dedupes_open_positions` | Seed `shadow_trades` open for AAPL on desk `research_<id>`. | AAPL absent; MSFT present. |
| 7 | `test_scheduled_candidate_shape` | Inspect a candidate. | Keys: `ticker, as_of, shares, price, signal_strength, metadata`; metadata has `strategy_spec_hash` + `trigger: "scheduled"`. |
| 8 | `test_unknown_operator_regression_guard` | Event-driven spec with bogus operator. | Signal evaluates to False per `_evaluate_event_signal` (no exception). Confirms behavior unchanged. |
| 9 | `test_walkforward_scheduled_still_works` | Run `backtest_engine._run_scheduled` via a minimal cfg. | Trades emitted — confirms we didn't break the backtest path. |

Fixtures: reuse `_seeded_edgar_db` shape from test_find_candidates.py for
shadow_trades seeding; scheduled has no filings so the edgar_filings rows
are vestigial (safe).

## 7. Update to existing tests

`tests/platform/test_find_candidates.py::test_find_candidates_scheduled_kind_returns_empty_or_raises`
currently asserts `candidates == []` **or** `NotImplementedError`. With the
new impl, a Monday scheduled spec with universe=`["AAPL"]` will return one
candidate. The test must be updated to reflect the new contract:

- Rename to `test_find_candidates_scheduled_kind_returns_candidates` (or
  split into a "fires on match" + "empty when trigger misses" pair).
- Assert `len(candidates) == 1` + ticker=AAPL.
- Drop the NotImplementedError branch.

`test_find_candidates_for_scheduled_spec_fires_warning` — the warning is
gone; delete the test (or retarget it to python_plugin which still raises).

## 8. Guardrails check

- [x] No schema changes.
- [x] No changes to event_driven branch / scan_service.run_scan / backtest
      engine. Only `signal_eval.py` scheduled wiring + new tests + existing
      test updates.
- [x] No new exception types.
- [ ] Line budget: 370 → target ≤400. Tight — monitor at edit time.

## 9. Next

Pass 2 research: grep for callers that depend on the warning/return-`[]`
behavior; survey `src/platform/specs/*.yaml` for any `entry.kind: scheduled`
specs on main; confirm walkforward → `backtest_engine._run_scheduled` path
is untouched by this change.
