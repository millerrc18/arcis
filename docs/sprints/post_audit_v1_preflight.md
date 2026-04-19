# v0.26.2-preflight — Post-audit ruleset Pass 1 feasibility diagnostic

**Issue:** #533. **Sprint:** `preflight/post-audit-ruleset-feasibility`.
**Date:** 2026-04-19. **Type:** Pass 1 only — no implementation, no spec,
no schema changes.

**Mission.** Determine whether v0.26.2 (post-audit ruleset spec + walk-forward)
can proceed independently of #530, or whether the same schema gaps that
blocked v0.26.0's incumbent extraction also block v0.26.2.

## Outcome — **Path B (partial block, scoped sprint)**

v0.26.2 does **not** inherit the full #530 dependency chain. It is, however,
not feasible under the existing `lazy_prices_v1`-shaped schema either. The
three filters decompose into three disjoint new schema surfaces plus one
data-infrastructure gap that is **not** on #530's prerequisite list.

See §5 for the proposed scoped schema-extension sprint scope. Zero of
#530's Sprints A-H are strict prerequisites for v0.26.2; the one apparent
overlap (Sprint A / #494) is live-flow-only and does not affect the
walk-forward path (§3).

## 1. Schema fit

Against `src/platform/specs/lazy_prices_v1.yaml` (72 lines, the shape
`walk-forward` currently supports) and its validator
`src/platform/strategy_spec.py:24` (`ALLOWED_ENTRY_KINDS = {"scheduled",
"event_driven", "python_plugin"}`).

### 1.1 Morning-only entries (09:30-10:30 ET)

**Not expressible.** Two independent gaps:

- **Schema gap.** No `entry.time_filter`, `entry_window`,
  `intraday_window`, or `session_window` field exists in the lazy-prices
  schema or the validator's accepted keys. Evidence: full file read of
  `src/platform/specs/lazy_prices_v1.yaml:1-72` (zero time-of-day
  keywords), `src/platform/strategy_spec.py:24-29`. Hour-bucket
  infrastructure exists in `src/diagnostics/dimensions.py:138-148`
  (`entry_hour_bucket` returns `"09:30-10:30"`, `"10:30-12:00"`, etc.)
  but is post-hoc diagnostic only — not wired to entry decisions.

- **Data-infrastructure gap (new).** `src/platform/backtest_engine.py:266`
  `_run_scheduled` operates on **daily** OHLCV bars
  (`day_ts = pd.Timestamp(day_iso)`, `bar = df.loc[day_ts]`,
  `entry_price = bar["Close"]` at line 286-287). No intraday bars are
  loaded anywhere in the backtest path. A 09:30-10:30 window cannot be
  evaluated against daily bars regardless of schema shape.

Not on #530's list. This is a v0.26.2-specific gap. See §2 and §5 for the
consequence.

### 1.2 Defensive sector bias (XLP/XLU/XLV)

**Not expressible as-is; two sub-interpretations with different cost.**

- **Hard filter (restrict universe to Defensive sector tickers).**
  Schema gap only — `universe` today accepts a flat ticker list
  (`tickers: sp100` at `lazy_prices_v1.yaml:20`). No `universe.sector`,
  `universe.sector_filter`, or `universe.include_sectors` field exists.
  Runtime is cheap: `_run_scheduled` already iterates
  `spec.universe.get("tickers", [])` at `backtest_engine.py:268`, so a
  pre-resolved ticker list derived from `src/universe/sectors.py`
  (GICS→Defensive bucket via `src/diagnostics/dimensions.py:133-137`
  `SECTOR_MAP`) slots in without a runtime change.

- **Soft bias (score boost for Defensive names).** Requires a
  scoring/ranking DSL — the exact extension #530 calls out as
  "Sprint C: scoring-DSL block". This sub-interpretation DOES overlap
  with #530.

Filter 2 is **not on #530's list for the hard-filter interpretation**
and **overlaps #530 Sprint C for the soft-bias interpretation**.

### 1.3 Tariff-event exclusion

**Not expressible as schema, but runtime substrate is fully ready.**

- **Schema gap.** No `entry.exclusions`, `entry.date_filter`, or
  `entry.event_exclusions` field exists in the lazy-prices schema.
- **Runtime substrate (v0.25.1 backfill) is production-ready.**
  `src/diagnostics/known_events.py:302-319` defines
  `is_known_event(date_str: str, category: str | None = None) -> bool`
  with the exact signature the task asks for. `EVENT_CATEGORIES` at
  `known_events.py:96-114` maps the 4 tariff-family events
  (`TARIFF_PAUSE` 2019-10-11, `TARIFF_ANNOUNCEMENT` 2019-12-12,
  `TARIFF_ESCALATION` 2024-05-14, plus SANCTIONS/EXPORT_CONTROLS/
  INDUSTRIAL_POLICY/TRADE_DISRUPTION) to the `"Trade Policy"`
  category string. So `is_known_event("2024-05-14",
  category="Trade Policy")` → `True` today.
- **No callsite.** `src.platform.backtest_engine` and
  `src.platform.signal_eval` do not import `is_known_event` (grep:
  `src/diagnostics/known_events.py`, `src/diagnostics/analyses.py`
  are the only importers).

Not on #530's list. Schema extension + ~10-line wiring at the entry
candidate-loop in `backtest_engine._run_scheduled` (insert call before
`trade = _build_trade(...)` at line 289).

### 1.4 Per-filter summary table

| Filter | Existing schema field | #530 overlap | New gap |
|---|---|---|---|
| Morning-only (09:30-10:30) | None | None | Yes — schema (`entry.time_filter`) **and** data infra (intraday bars) |
| Defensive bias — hard filter | None (flat ticker list only) | None | Yes — schema (`universe.sector_filter` or pre-resolved ticker list convention) |
| Defensive bias — soft bias | None | **#530 Sprint C** (scoring-DSL) | Overlaps #530 |
| Tariff-event exclusion | None | None | Yes — schema (`entry.exclusions.known_events`); runtime substrate already shipped in v0.25.1 |

## 2. Overlap with #530

#530 (read 2026-04-19T21:35:21Z via `mcp__github__issue_read`) lists 7
prerequisites and suggests Sprints A-H. Cross-referenced:

- **Sprint A — close #494 (scheduled-kind live wiring).** NOT a v0.26.2
  prerequisite. #494 affects `src/platform/signal_eval.py:178-185`
  (live-flow `find_candidates_for_date`). Walk-forward runs through
  `scripts/backtest/run_walkforward.py:95` → `run_backtest()` →
  `backtest_engine._run_scheduled`, which is the "backtest_engine
  still works for backtests" path called out in the log warning at
  `signal_eval.py:180-184`. v0.26.2 is a walk-forward sprint;
  live-flow coverage is a separate, later concern. Marked independent.
- **Sprint B — close #493 (python_plugin wiring).** NOT a v0.26.2
  prerequisite. v0.26.2 targets `scheduled` or a new `daily_scan`
  kind, not `python_plugin`.
- **Sprint C — scoring-DSL block.** OVERLAPS only if Defensive bias is
  implemented as a soft bias. The scoped sprint in §5 picks the
  **hard-filter** interpretation to avoid this overlap.
- **Sprint D — multi-target brackets + regime-adaptive sizing.** NOT
  a v0.26.2 prerequisite. The post-audit ruleset Pass 1 prompt does
  not call out multi-target brackets or regime-adaptive sizing as
  filters; single `exit` block (as in `lazy_prices_v1.yaml:41-55`)
  is sufficient.
- **Sprints E, F, G, H — enrichment/post-scan/bootcamp/scan-pipeline
  port.** All specific to the incumbent's scan-service coupling. v0.26.2
  has no incumbent scan-service exposure; these are not prerequisites.

**Net overlap with #530:** one soft dependency on Sprint C (scoring-DSL)
**only if** Defensive bias is interpreted as a soft score boost. The
scoped sprint in §5 sidesteps this by specifying hard-filter semantics.

**New gaps not in #530:**
1. `entry.time_filter` schema + intraday OHLCV data layer (morning-only).
2. `universe.sector_filter` or a sector-resolved ticker-list convention
   (Defensive hard filter).
3. `entry.exclusions.known_events` schema + `is_known_event` wiring in
   `backtest_engine` (tariff exclusion). Runtime substrate exists.

## 3. Runtime path

`scripts/backtest/run_walkforward.py:75-100` (`_gather_window_trades`)
constructs `BacktestConfig` per window and calls
`src.platform.backtest_engine.run_backtest(cfg)`. `run_backtest` at
`backtest_engine.py:370-380` dispatches by `spec.entry["kind"]`:

- `kind == "scheduled"` → `_run_scheduled(cfg)` at line 266-295.
  **This is the path walk-forward uses.** Works today for daily-granular,
  unfiltered scheduled triggers.
- `kind == "event_driven"` → `_run_event_driven(cfg)` at line 298+.
- Other kinds → raises.

**The `signal_eval.py:180 NotImplementedError` (#494) is on the live-flow
code path, not the backtest path.** Walk-forward does not touch
`signal_eval.py` (grep of `scripts/backtest/run_walkforward.py` — no
import). v0.26.2 does **not** inherit #494.

**What IS missing in the backtest runtime for v0.26.2:**

1. `_run_scheduled` has no intraday dimension (`_iter_trading_days`
   returns daily dates; `df.loc[day_ts]` indexes into daily bars). A
   09:30-10:30 window cannot be applied without a new intraday
   `load_ohlcv_range` variant and an intraday bar store.
2. `_run_scheduled` does not consult `is_known_event` or any exclusion
   list. Tariff-exclusion wiring is additive and small but does not
   exist today.
3. `_run_scheduled` uses `spec.universe.get("tickers", [])` as a flat
   list; no sector resolution at `universe` load time. Either
   pre-resolve to Defensive tickers at spec-authoring time or add a
   `universe.sector_filter` hook.

**Is a new `daily_scan` kind required?** No. `scheduled` is already the
daily-scheduled-entry kind and is operable in `backtest_engine`. Adding
a `daily_scan` kind would duplicate `scheduled` and require
`ALLOWED_ENTRY_KINDS` expansion (`strategy_spec.py:24`) for no
functional benefit.

## 4. R8 declaration validity

The proposed declaration:

```yaml
derived_from:
  source_type: forensic_audit_ruleset
  source_run_id: "april-2026-forensic-audit"
  source_date_range:
    start: "2026-04-01"
    end: "2026-04-18"
  source_trade_ids: null
```

Evaluated against `src/platform/rigor/walkforward_firewall.py:81-136`
(`validate_derived_from`):

| Field | Rule | Verdict |
|---|---|---|
| `source_type: forensic_audit_ruleset` | Must be in `ALLOWED_SOURCE_TYPES = {forensic_audit_ruleset, bootcamp_backtest, shadow_trading_cohort, other}` (`walkforward_firewall.py:52-55`) | **Accepted** |
| `source_run_id: "april-2026-forensic-audit"` | Must match `^[A-Za-z0-9_.\-]+$` (`:57`) | **Accepted** (19 chars, hyphenated, alphanumeric) |
| `source_date_range: {start: "2026-04-01", end: "2026-04-18"}` | Both keys present, ISO `yyyy-mm-dd`, `start <= end` (`:111-127`) | **Accepted** |
| `source_trade_ids: null` | At `:129-135`: `if "source_trade_ids" in df: if not isinstance(sti, list) or not all(isinstance(x, str) for x in sti): raise R8ViolationError` | **Rejected** — `None` fails `isinstance(sti, list)` |

**R8(a) declaration is valid in 3 of 4 fields.** The `source_trade_ids:
null` clause fails the current validator because the key is present
(line 129 checks `"source_trade_ids" in df`) and its value is not a
list. Two resolutions, both cheap:

- **Spec convention (preferred, zero code change):** Omit the key
  entirely when no trade-id list is available. `source_trade_ids` is
  optional per `walkforward_firewall.py:128` ("source_trade_ids is
  optional but must be list[str] if present"). Omission is the
  already-supported "not present" signal.
- **Validator extension (~3 lines):** Accept `None` as equivalent to
  omission. Change `if not isinstance(sti, list)` to
  `if sti is not None and not isinstance(sti, list)`. Out-of-scope
  for this preflight.

**R8(b) overlap check.** `assert_no_overlap` at
`walkforward_firewall.py:143-162` compares `source_date_range` against
every OOS window. Given `source_date_range = 2026-04-01 → 2026-04-18`
and the v1 OOS windows ending `2024-09-30` (per CHANGELOG.md:44), zero
overlap is guaranteed — the forensic-audit period is ~18 months
**after** the last OOS window. No R8(b) concern.

**R8(d) bootcamp.** `ensure_bootcamp_off` at `:165-175` is orthogonal
to the declaration. Default `False`, no concern.

## 5. Proposed scope — scoped schema-extension sprint (Path B)

A single, small, schema-only sprint that unblocks v0.26.2-full:

**Sprint name:** `v0.26.2-pre — post-audit ruleset schema extensions`.
**Docs budget:** schema PR + `docs/sprints/post_audit_v1_extension.md`.
**Code surface:** `src/platform/strategy_spec.py`,
`src/platform/specs/post_audit_ruleset_v1.yaml` (new), and narrow hooks
in `src/platform/backtest_engine.py`.

### In-scope

1. **`universe.sector_filter` field** — accept
   `universe.sector_filter: defensive` (or equivalent) and resolve to a
   ticker list at spec-load time using `src/universe/sectors.py` +
   `src/diagnostics/dimensions.py:133-137` `SECTOR_MAP`. Or, simpler:
   author the spec with a pre-resolved Defensive ticker list and skip
   the schema extension entirely. Either works; the spec author picks.
2. **`entry.exclusions.known_events.categories` field** — schema
   addition in `strategy_spec.py` validator; runtime wiring: insert
   `if is_known_event(day_iso, category=c): continue` at
   `backtest_engine.py:~288` (after `day_iso = _iso(day)`, before
   `_build_trade`). ~10 lines including the import.
3. **R8(a) spec convention** — omit `source_trade_ids` key when no
   trade-id list is authored (instead of `null`). Document the
   convention in `post_audit_ruleset_v1.yaml` comments.

### Out-of-scope (defer)

1. **Morning-only entry window (Filter 1).** Requires intraday OHLCV
   data layer — a standalone data-infra sprint, not a schema sprint.
   Path-of-least-resistance recommendations for v0.26.2-full:
   - **Option P1 (proxy):** Replace 09:30-10:30 with "daily-open entry"
     as a proxy in v0.26.2-full; flag the approximation explicitly in
     the spec description and in the walk-forward run notes.
   - **Option P2 (defer filter):** Ship v0.26.2-full with only the
     sector + tariff filters; retire "morning-only" into a later
     sprint gated on intraday OHLCV.
   - **Option P3 (blocker):** File a new issue "intraday OHLCV data
     layer" and block v0.26.2-full on it. Expensive — historical
     intraday back to 2019 is a non-trivial data acquisition.
   Operator picks. Recommended default: **P2** — keeps v0.26.2 cheap
   and leaves morning-only as a follow-up.
2. **Soft-bias sector scoring.** Overlaps #530 Sprint C. Not
   implemented here. The hard-filter interpretation is sufficient for
   a fresh-spec ruleset.
3. **All other #530 items (Sprints A, B, D, E, F, G, H).** Not
   required for v0.26.2.

### Acceptance criteria for the scoped sprint

- `post_audit_ruleset_v1.yaml` loads under `load_spec` without
  validator errors.
- `backtest_engine.run_backtest(cfg)` with the new spec skips entries
  on dates where `is_known_event(date, category="Trade Policy") is
  True` (covered by a new unit test against the 4 tariff-family
  dates in `KNOWN_EVENTS`).
- `walkforward_firewall.validate_derived_from` accepts the
  forensic-audit `derived_from` block (omitting `source_trade_ids`).
- No change to `signal_eval.py` (live flow out of scope).

## Surprises

1. **R8(a) validator does not accept `null` for `source_trade_ids`.**
   The prompt's example declaration uses `source_trade_ids: null`,
   which the current validator (`walkforward_firewall.py:129-135`)
   rejects. Recommend spec convention of omitting the key rather than
   extending the validator in this sprint. Logged as an out-of-scope
   follow-up to harmonize null-vs-absent semantics if this pattern
   recurs.
2. **Walk-forward does not depend on #494.** #530's Sprint A frames
   #494 as a blocker for the incumbent YAML-ification. That framing
   is correct for *live-flow* incumbent extraction, but walk-forward
   uses `backtest_engine._run_scheduled` directly. v0.26.2's
   walk-forward path is insulated from the live-flow `NotImplementedError`
   at `signal_eval.py:180`. This narrows the dependency surface
   considerably and is the single biggest reason v0.26.2 can proceed
   independently of #530.
3. **Intraday OHLCV is a silent prerequisite for the morning-only
   filter.** Neither the post-audit ruleset prompt nor #533 flags
   that the 09:30-10:30 entry window requires intraday bars that the
   platform does not currently ingest. This is a material v0.26.2
   finding and is the primary reason the scoped sprint in §5 does
   not cover morning-only.

## References

- **Schema:** `src/platform/specs/lazy_prices_v1.yaml:1-72`,
  `src/platform/strategy_spec.py:24-65`.
- **Runtime:** `src/platform/backtest_engine.py:266-295`
  (`_run_scheduled`), `scripts/backtest/run_walkforward.py:75-100`
  (`_gather_window_trades`).
- **Live-flow (not on WF path):** `src/platform/signal_eval.py:175-190`
  (the #494 `NotImplementedError` site — backtest-engine-insulated).
- **R8 firewall:** `src/platform/rigor/walkforward_firewall.py:52-55`
  (`ALLOWED_SOURCE_TYPES`), `:81-136` (`validate_derived_from`),
  `:143-162` (`assert_no_overlap`).
- **Known events (v0.25.1):** `src/diagnostics/known_events.py:56-93`
  (`KNOWN_EVENTS`), `:96-114` (`EVENT_CATEGORIES`), `:302-319`
  (`is_known_event`). `CHANGELOG.md:39-59` (v0.25.1 release notes).
- **Issue #530:** 7 prerequisites + Sprints A-H (read
  2026-04-19T21:35:21Z).
- **Issue #533:** This preflight.

## Next step

File v0.26.2-pre scoped schema-extension sprint per §5. v0.26.2-full
(ruleset spec + walk-forward run) follows on v0.26.2-pre landing.
Close #533 with Path B outcome.
