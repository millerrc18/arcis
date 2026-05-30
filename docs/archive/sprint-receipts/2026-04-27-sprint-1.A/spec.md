# Sprint 1.A — T10 Survivorship Migration

## Goal

Backtests, simulations, training data, and leakage detection must use point-in-time SP100 universe (`pit.get_sp100_at(as_of)`) instead of today's SP100 universe (`get_sp100_universe()`). Per Sprint 0 TRIAGE.md T10, ~24 callers across `src/evaluation/`, `src/simulation/`, `src/training/`, and `src/training/audit/`. Survivorship bias currently overstates backtest edge.

## Pre-flight (Planner produces this BEFORE Developer dispatch)

A written report at `docs/audits/2026-04-27-sprint-1.A/pre-flight.md`:

1. Full grep of `get_sp100_universe()` callers (24 expected per Sprint 0 TRIAGE T10)
2. Per-caller table:
   - `file:line | role | as_of variable in scope | as_of value range | migration risk`
3. Verify `pit.get_sp100_at()` coverage adequate for caller `as_of` ranges (run `python -c "from src.universe.pit import get_data_range; print(get_data_range())"` or equivalent)
4. Identify import-graph dependencies between callers (parallelization map — domains aren't independent if `simulation/engine.py` imports from `evaluation/backtester.py` etc.)
5. Initial allowlist of live-runtime paths (each entry with rationale)
6. **STOP if pre-flight finds blockers** — operator decides before Developers dispatch

## Migration rule

- **LIVE-RUNTIME** (today's trading) → KEEP `get_sp100_universe()`
- **HISTORICAL / BACKTEST / TRAINING / AUDIT** → MIGRATE to `pit.get_sp100_at(<as_of>)`

## Per-site `as_of` decision (CRITICAL — heart of the migration)

For each migrated site, the Developer must:

1. Identify the date variable already in scope (`iter_date`, `bar_date`, `example.trade_date`, `start_date`, etc.)
2. Verify `pit.get_sp100_at(<that_date>)` doesn't raise on test fixtures (run the existing tests after the change)
3. If no obvious `as_of` in scope: STOP, file follow-up tracker `Sprint 1.A.X — thread <date_concept> through <function> signature`
4. Commit message MUST include: `as_of source: <variable> at <line>`

**This is NOT mechanical.** Wrong `as_of` (e.g., passing `date.today()`) recreates survivorship bias under PIT cover — correctness theater. The Planner's pre-flight report MUST identify the correct `as_of` per site OR mark it for follow-up.

## Failure mode contract

- `pit.get_sp100_at(as_of)` returns a non-empty set for all valid historical dates
- For dates BEFORE pit data coverage start, `pit` raises `UniverseDataMissing`
- Existing pit callers in `src/strategy/` (Stage-1 baseline) handle this — read their handler and mirror
- If migration target's `as_of` range exceeds pit coverage, file blocker tracker immediately

## Re-pin protocol for changed test numerics

After migration, backtest/simulation/training tests with pinned numerics WILL produce different values (because universe differs).

- **Discovery:** grep for `assert.*sharpe` `assert.*win_rate` `assert.*drawdown` `assert.*pnl` in `tests/`
- **Per-failed-test:** re-run, capture new value
- **Operator approval REQUIRED for any change >5%** (per Sprint 1.A spec gate). For changes ≤5%, agent updates with comment
- Update with comment: `# T10 re-pin: was X (survivorship-biased); now Y (PIT)`
- DO NOT silently update pinned numerics — every re-pin needs the comment

## Structural lint

Add `tests/test_pit_universe_discipline.py` (PR #747 pattern):

- AST-walk `src/` for `get_sp100_universe(` callers
- `_ALLOWLIST` seeded from pre-flight report (step 5)
- Each migration commit removes its file from `_ALLOWLIST`
- Lint passes only when migration is complete + only allowlist sites remain
- Each allowlist entry must have a rationale comment

## Out of scope

- **T22 methodology wiring** (Sprint 1.B)
- **`pit.py` refactor** (assume canonical)
- **PIT data backfill** (operator pre-flight verifies coverage)
- **Live-runtime callers** (KEEP, allowlist them)
- **Cohort 3 redesign** (1.C — explicitly waits for 1.A merge)

## Reference docs

- Sprint 0 TRIAGE.md T10 section (24-caller breakdown)
- `src/universe/pit.py` — canonical PIT implementation
- PR #747 (allowlist + structural lint test pattern)
- PR #735 / #739 / #750 (refactor patterns — orchestrator-namespace late binding for patch-compat)
- `docs/audits/known-pre-existing-failures.md` (CQ-07 — reference, don't rediscover)

## Strict-rigor receipts (per PR #749 Delivery Discipline)

- Worktree-isolated agents (SD-06) ✓
- Per-file commits (DR-05) ✓
- PR body regenerated from final git log (DR-06) ✓
- Pre-existing failures from canon doc (CQ-07) ✓
- `test_repo_structure.py` output disclosed (#731) ✓
- Sibling search per fix ✓
- Re-pin comments on every changed numeric assertion ✓
- Pre-flight report committed FIRST as a deliverable

## Operator approval gates (during execution)

1. **Pre-flight blocker findings** — STOP, await operator decision
2. **Re-pin >5% change per test** — flag for operator review
3. **New "thread date through signature" trackers** — file as separate Sprint 1.A.X items

## Coding-team skill notes

This is a feature wave. PM orchestrator dispatches Planner first (pre-flight is the Planner's primary deliverable), then parallel Developers per the Planner's decomposition (probably by-domain: `evaluation/`, `simulation/`, `training/`, `training/audit/`). QA Reviewer runs on every commit. Documentarian updates docs at end. Integrator does final regression sweep + canon doc update.
