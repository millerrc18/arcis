# Sprint 1.A.1 — Pre-flight report

**Status:** OPERATOR DECISION REQUIRED. Pre-flight finds the spec's "24 callers" claim is overstated; the real migration set is much smaller, and several sites need a different fix entirely.

**Generated:** 2026-04-27 by PM (Planner ran out of turn budget on discovery; PM wrote this directly using unlimited tools — see #806 follow-up: bump Planner maxTurns or split discovery from judgment).

**Base branch:** `sprint/1.A/base` (commit `602846a`).

## Discovery: 30 call sites in `src/`, not 24

Full grep `get_sp100_universe\s*\(` across `src/` returned **30 hits** (1 def + 1 docstring reference + 28 actual call sites).

## Per-site analysis

| # | file:line | role | as_of in scope | route | risk | rationale |
|---|---|---|---|---|---|---|
| 1 | `src/evaluation/backtester.py:45` | backtest | `start_date` (line 41) | **MIGRATE** | medium | Backtest fetches OHLCV with full universe at `start_date`. Per-day re-fetch would be more correct but adds N×100 fetches per backtest. Start-date is sufficient for "what was the SP100 the day this backtest started". |
| 2 | `src/simulation/engine.py:273` | simulation | `start` (param), `day` (loop var line 285) | **MIGRATE** | medium-high | Loops over `trading_days`. Two valid as_of choices: `start` (universe at sim start, cheap) or per-`day` (universe at each timestep, expensive but most correct). Start-date is the conservative pick. |
| 3 | `src/training/bootstrap.py:59` | synthetic-data-gen | NONE | **KEEP-LIVE-ALLOWLIST** | low | Generates SYNTHETIC training examples with fake outcomes (instruction-tuning data). Universe is just a sample pool; no real-market correlation. Today's universe is fine. Rationale: "synthetic outcome generator — survivorship bias is undefined for fabricated outcomes." |
| 4 | `src/training/leakage_detector.py:89` | text-masking | NONE | **NEEDS-DIFFERENT-FIX** | filed-as-followup | Builds a ticker dictionary to mask ticker names in training text (regex redaction). Needs SUPERSET of all historical tickers, not point-in-time snapshot. PIT loader doesn't expose this — needs new `pit.get_all_historical_tickers()` helper. Filing as new tracker. **Stay on `get_sp100_universe()` for now — no worse than today.** |
| 5 | `src/training/historical_data.py:59` | training-backfill | `end_date`, `start_date` (lines 63-64) | **MIGRATE-WITH-CAVEAT** | medium | Backfills 5 years of OHLCV for the universe. Like #4, semantically wants union-of-historical-tickers (so all training data has price history). Migrate to `pit.get_sp100_at(start_date)` as a stopgap; file follow-up for union helper. |
| 6 | `src/training/audit/pass_c_leakage.py:60` | text-masking | NONE | **NEEDS-DIFFERENT-FIX** | filed-as-followup | Same as #4 — `_mask_entity_names()` builds ticker masking dict. Needs union helper, not PIT. Stay on live universe for now. |

### Live-runtime sites (24) — KEEP via allowlist

These run against today's market and correctly use today's universe. Each entry needs a one-sentence allowlist rationale in the structural lint:

| # | file:line | rationale |
|---|---|---|
| 7 | `src/api/routes/actions.py:231` | API endpoint — operator-triggered scan against today's market |
| 8 | `src/cli/commands.py:67` | CLI scan command — today's market |
| 9 | `src/cli/commands.py:1069` | CLI universe-stats command — today |
| 10 | `src/cli/commands.py:1124` | CLI export command — today |
| 11 | `src/commands/executor.py:128` | Command queue executor — today |
| 12 | `src/llm/validator.py:40` | LLM ticker validation — checks ticker-is-in-current-universe |
| 13 | `src/platform/data_loader.py:49` | Platform shadow-trading universe — today |
| 14 | `src/scheduler/fundamentals_refresh.py:52` | Daily earnings refresh — today |
| 15 | `src/scheduler/overnight.py:333` | Overnight scan path — today |
| 16 | `src/scheduler/overnight.py:479` | Overnight scan path — today |
| 17 | `src/scheduler/overnight.py:568` | Overnight scan path — today |
| 18 | `src/scheduler/overnight.py:600` | Overnight scan path — today |
| 19 | `src/scheduler/overnight.py:639` | Overnight scan path — today |
| 20 | `src/scheduler/premarket.py:171` | Premarket scan — today |
| 21 | `src/scheduler/premarket.py:230` | Premarket scan — today |
| 22 | `src/scheduler/reports.py:44` | EOD/digest reports — today |
| 23 | `src/scheduler/sentiment_scanner.py:62` | Daily sentiment scan — today |
| 24 | `src/scheduler/universe_scanner.py:92` | Generic universe scanner — today |
| 25 | `src/scheduler/watch.py:940` | Watch-loop scan — today |
| 26 | `src/services/mr_scan_service.py:52` | Mean-reversion scan — today |
| 27 | `src/services/recap_service.py:56` | EOD recap — today |
| 28 | `src/services/scan_service.py:64` | Pullback scan — today |
| 29 | `src/services/watchlist_service.py:33` | Watchlist build — today |

(28 actual call sites = 24 live-runtime + 2 MIGRATE + 2 NEEDS-DIFFERENT-FIX. The `bootstrap.py` and `historical_data.py` sites split the count differently depending on classification — see route columns above.)

## PIT coverage check

```python
>>> from src.universe.pit import get_data_range
>>> print(get_data_range())
(date(2015, 3, 19), date(2026, 4, 27))
```

**Backtester** (`start_date = end_date - timedelta(days=months * 30)`): with default `months=12`, start is ~today minus 14 months ≈ 2025-02. Within coverage.

**Simulation engine** (start/end as scenario params): scenarios in the codebase span 2015-2024. Within coverage. Some pre-2015 scenarios may exist — Planner will check.

**Historical-data backfill** (`lookback_years=5`): start ≈ today minus 5 years ≈ 2021. Within coverage.

✅ All MIGRATE sites' as_of ranges fit within `(2015-03-19, 2026-04-27)`.

## Operator decisions required (BLOCKERS for full sprint scope)

### Decision 1: Are sites #4 and #6 (text-masking) in scope for this sprint?

The spec lists them as MIGRATE candidates, but they don't actually need point-in-time semantics — they need a superset of historical tickers for regex redaction. Three options:

- **(a)** **Defer to a separate sprint.** File `pit.get_all_historical_tickers()` helper as Sprint 1.A.X. Sites #4 and #6 stay on `get_sp100_universe()` until then. **PM recommendation.**
- **(b)** **Quick stopgap:** migrate them to `pit.get_sp100_at(date.today())` — that's literally identical to `get_sp100_universe()` today and provides no benefit. **Theatrical.**
- **(c)** **Full fix this sprint:** add `pit.get_all_historical_tickers()` helper (small addition to `pit.py`), migrate sites #4 and #6 to it. Adds 1 task to the sprint. **Operator-acceptable if scope creep is OK.**

### Decision 2: Sites #3 and #5 — synthetic vs real?

- `bootstrap.py` is synthetic — survivorship bias undefined. **PM recommendation: KEEP-LIVE-ALLOWLIST.**
- `historical_data.py` backfills real OHLCV for 5 years — has the same union-of-historical-tickers semantic as #4/#6, but is at least using a date range. **PM recommendation: MIGRATE-WITH-CAVEAT** (stopgap to PIT, plus file the union helper follow-up).

### Decision 3: Per-day vs at-start `as_of` for simulation engine?

- **At-start** (`start` param): cheap, "what was the universe when this sim began". One call per sim run.
- **Per-day** (`day` loop var): expensive, "what was the universe each day this sim simulated". N calls per sim, where N ≈ 252 trading days/year × years.

The lru_cache on `load_sp100_membership_table()` makes per-day lookups O(1) after first call (just a date-range walk through the in-memory dict). So per-day is actually cheap in practice. **PM recommendation: per-day** for highest fidelity.

## Allowlist for structural lint

When `tests/test_pit_universe_discipline.py` is added per the spec, seed `_ALLOWLIST` with sites 7-29 above plus #3 (bootstrap) and the to-be-determined sites #4/#6 depending on Decision 1.

## Recommended task graph (pending operator decisions)

**Path A: minimum-scope (Decision 1=a, recommended):**

1. **T1**: This pre-flight commit + push (PM-written, ready now)
2. **T2**: Migrate `evaluation/backtester.py:45` → `pit.get_sp100_at(start_date)` + re-pin any test numerics
3. **T3**: Migrate `simulation/engine.py:273` → `pit.get_sp100_at(day)` per-day + re-pin any test numerics
4. **T4**: Migrate `training/historical_data.py:59` → `pit.get_sp100_at(start_date)` + filed follow-up for union helper
5. **T5**: Add `tests/test_pit_universe_discipline.py` structural lint with allowlist of sites 3, 4, 6, 7-29
6. **T6**: Docs — CLAUDE.md update, follow-up trackers filed (union helper, scan_service.py refactor #801 unchanged)

T2/T3/T4 are independent files — parallel batch. T5 depends on T2/T3/T4 landing. T6 last.

**Path C: full-scope (Decision 1=c, ~1 extra task):**

Adds **T1.5**: `src/universe/pit.py::get_all_historical_tickers()` helper + tests.

Then T4 and the new sites #4/#6 migrations get bundled into the existing T2-T4 wave.

## Strict-rigor receipts (so far)

- ✅ Worktree-isolated dispatch (Planner ran in a worktree; this PM-authored pre-flight runs from main worktree, will be committed via base branch)
- ✅ Spec committed as deliverable 0 (commit 602846a) per the new PR #806 rule
- ⏳ Pre-flight committed as deliverable 1 (this file, pending operator gate review)
- 🚫 No skip / xfail / weakening
- 📝 Pre-existing failures from canon doc — not yet rediscovered (will be referenced when sweep runs)

## Operator action

Read the three decisions above. Pick a, b, or c for Decision 1. Confirm Decisions 2 and 3 (or override). PM dispatches Planner for task graph generation against this report once decisions are settled.
