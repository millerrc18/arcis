# Sprint 1.A Wave 2+3 — Task Graph (planning artifact)

**Status:** Plan approved by Planner agent, EXECUTION DEFERRED per operator (2026-05-04).

**Resumption:** When ready to execute, re-invoke `arcis:coding-team` with `--plan docs/audits/sprint-1.A-wave-2-3/task-graph.json`. The Planner phase will be skipped; the Developer dispatch begins immediately.

**Snapshot of approval state:**
- Spec at `docs/audits/sprint-1.A-wave-2-3/spec.md` (commit `d183078`)
- Task graph at `docs/audits/sprint-1.A-wave-2-3/task-graph.json` (this commit)
- Sprint base SHA: `20ab3d8` (origin/main HEAD at time of planning)
- 3 tasks: T-A2 (medium), T-B2 (low), T-B3 (medium)
- Execution order: `[T-A2, T-B2]` parallel → `[T-B3]` sequential

**Why the plan is preserved as-committed:**
The Planner's task graph is the contract for what gets built. Saving it on the sprint base branch (versioned, retrievable) means:
1. Resumption months later doesn't require re-planning
2. PR provenance traces back to a specific approved plan, not "whatever the agent decided in the moment"
3. Operator can review the saved plan independently of the live conversation
