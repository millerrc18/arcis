# Sprint 1.A Wave 2+3 — Task Graph

**Status:** Plan approved by Planner agent + operator. **EXECUTION DEFERRED** per operator pause 2026-05-04.

## Resumption procedure

When ready to execute:

```
Skill: arcis:coding-team
Args: --plan docs/audits/sprint-1.A-wave-2-3/task-graph.json
```

The Planner phase is skipped; PM dispatches Developers in worktrees per the saved task graph.

## Plan snapshot at approval time

| | |
|---|---|
| Spec | `docs/audits/sprint-1.A-wave-2-3/spec.md` (commit `d183078`) |
| Task graph | `docs/audits/sprint-1.A-wave-2-3/task-graph.json` (this commit) |
| Sprint base | `sprint/sprint-1.A-wave-2-3/base` (cut from `origin/main` at `20ab3d8`) |
| Tasks | 4 (T-A2, T-B2, T-B3, T-DOCS) |
| Execution order | `[T-A2 ∥ T-B2]` → `[T-B3]` → `[T-DOCS]` |
| Test count target | 3692 (baseline 3682 + ≥10 new) |

## Tasks at a glance

- **T-A2** — render_sync.py refactor: extract 3 helpers from 64-line `_resolve_sync_columns`. ≥6 unit tests. **No CHANGELOG entry** (refactor, no behavior change).
- **T-B2** — wire `subtract_trading_days(start_date, 200)` into `generate_llm_corpus.py:222`. ≥2 tests. CHANGELOG.
- **T-B3** — same wiring on `backtester.py:136`. ≥2 tests. CHANGELOG. Gated on T-B2 (CHANGELOG conflict + reference impl).
- **T-DOCS** — documentation sweep (roadmap, dashboard roadmap, CLAUDE.md analytics section, stale Wave references). No tests. No CHANGELOG (docs-only).

## Why preserved as a committed artifact

PR provenance + resumption discipline. Months from now, anyone reading the sprint directory can answer "what was the plan at approval time?" without needing to recover the conversation. The Planner's task graph is the contract for what gets built — saving it under the sprint base branch (versioned, retrievable) means resumption skips re-planning and can dispatch Developers immediately.
