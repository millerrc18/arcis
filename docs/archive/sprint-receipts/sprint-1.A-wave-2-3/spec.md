# Sprint 1.A Wave 2 + Wave 3 — Spec

**Sprint ID:** sprint-1.A-wave-2-3
**Dispatched:** 2026-05-04
**Base SHA at dispatch:** 20ab3d8 (post-merge of #911, #916, #917, #918, #919)
**Gating:** Wave 1 (PRs #911, #916, #917) merged. Wave 2 unblocked.

## Wave 2 (parallel batch — two independent tasks)

### A.2 — Reduce one render_sync.py function below the 60-line guardrail

**Scope fence:** ONLY `src/sync/render_sync.py` + `tests/test_render_sync.py`.

Functions exceeding 60-line guardrail (per AST scan, end_lineno - lineno):

| Function | Lines | Over | Notes |
|---|---|---|---|
| `_resolve_sync_columns` | 64 | +4 | Smallest delta, recommended target |
| `_upsert_to_postgres` | 116 | +56 | Defer to later sprint |
| `_replace_latest_in_postgres` | 110 | +50 | Defer to later sprint |
| `pull_commands` | 121 | +61 | Defer to later sprint |
| `run_sync_cycle` | 130 | +70 | Defer to later sprint |

**Recommended target: `_resolve_sync_columns` (line 139, 64 lines).** Logic groups naturally into:
1. Registry-driven column filter (drop columns not in registry)
2. Postgres introspection (filter by live PG columns when introspection succeeds)
3. Conflict-col validation (raise if PG missing required ON CONFLICT targets)

Each becomes a private helper (similar shape to PR #916's RenderSyncThread split). Outer `_resolve_sync_columns` delegates to the three helpers.

**Test strategy:** Match PR #916's pattern — 10 unit tests in `TestRenderSyncThreadHelpers` covered the prior split. For this PR, add ≥6 unit tests covering each new helper's contract (registry filter, PG introspection success / fallback paths, conflict-col validation success / raise paths). Existing test suite must stay green (60/60+).

### B.2 — Wire `subtract_trading_days` into corpus generator

**Scope fence:** ONLY `scripts/generate_llm_corpus.py` + `tests/evaluation/test_corpus_generator.py` + `CHANGELOG.md`.

`subtract_trading_days(anchor, n)` was added in PR #911 (`src/scheduler/holidays.py`). Wire it into `scripts/generate_llm_corpus.py::_compute_features_for_window` (around line 204): replace the existing calendar-day buffer (`365` calendar days, currently `start_date - timedelta(days=365)`) with `subtract_trading_days(start_date, 200).isoformat()`.

The 200-trading-day target locks `slice_to_date`'s 200-row gate per pre-reg semantics — calendar-day arithmetic is a proxy that drifts with holiday count, while trading-day arithmetic is the binding contract.

**Test strategy:** regression test in `tests/evaluation/test_corpus_generator.py` that locks the fetch_start anchor against a hardcoded calendar date (mirroring `test_holidays.py::test_two_hundred_anchor` from PR #911 — `subtract_trading_days(date(2026, 5, 1), 200) == date(2025, 7, 16)`). The corpus test should call `_compute_features_for_window` with a known decision-point list and assert the fetch range starts at the trading-day-aware anchor.

## Wave 3 (gated on Wave 2 B.2 completion — sequential, single task)

### B.3 — Wire `subtract_trading_days` into backtester + regression test

**Scope fence:** ONLY `src/evaluation/backtester.py` + `tests/test_backtester.py` + `CHANGELOG.md`.

Same wiring as B.2, but at `src/evaluation/backtester.py:132` area (the 280-day buffer site identified in PR #911 review). Replace calendar-day arithmetic with `subtract_trading_days(start_date, 200).isoformat()`.

**Test strategy:** regression test in `tests/test_backtester.py` that locks the fetch anchor — same pattern as B.2's test, applied to the backtester call site.

## Cross-cutting constraints

- **CHANGELOG.md** — every PR adds an entry under `[Unreleased]` (per CLAUDE.md mandate)
- **Schema registry** — touch `src/schema/registry.py` only via registry helpers; if registry touched, run `python -m src.main validate-schema` and document output in PR body
- **test_schema.py end-to-end** — if registry touched, full `pytest tests/test_schema.py` (not subset) must run per rigor-reviewer rubric C2.2
- **Worktree isolation** — MANDATORY for parallel agents (PRs A.2 and B.2 dispatched simultaneously); per-agent `.claude/agent-scope.json` written before dispatch
- **Rigor reviewer auto-fire** — after each PR opens, `arcis:coding-rigor-reviewer` agent should run per PHASE 6.5 in commands/code.md. The agent file lives in plugin cache and may require operator session restart to be discoverable; manual rubric execution is acceptable as fallback

## Operator context (read-only — do NOT touch these)

- 7 modified + 7 untracked files in operator's main checkout (schema-refactor WIP). Worktree isolation handles this.
- Corpus generator process running at ~16K entries (PID 34720). B.2 wiring is a source change — takes effect on next `--resume`.
- Watch loop process running. Don't interrupt.

## Expected deliverables

Three PRs, in dispatch order:
1. **A.2 PR** (Wave 2 parallel batch): `fix(#85 follow-up): extract _resolve_sync_columns helpers to satisfy 60-line guardrail`
2. **B.2 PR** (Wave 2 parallel batch): `feat(#106 follow-up): wire subtract_trading_days into corpus_generator fetch anchor`
3. **B.3 PR** (Wave 3 sequential, after B.2 lands): `feat(#106 follow-up): wire subtract_trading_days into backtester fetch anchor + regression test`
