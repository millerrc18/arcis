---
name: operate
description: Live-system incident response and change orchestration — triage symptoms via specialized agents, execute operator-confirmed mutations with safety-window enforcement, run named runbooks for known incidents. Composes the 13 Tier 1+2+3 tools and 4 investigator agents into one workflow.
---

# Operate

This skill provides the `/arcis:operate` command for live-system incident response and change orchestration on the halcyon-lab trading research desk.

## Approach: Verb-Dispatched State Machine

1. **PARSE** — Extract verb (`triage` | `act` | `status` | `runbook`) from POSITIONAL_INPUT[0]; parse verb-specific args
2. **SAFETY GATE** — For mutating verbs (`act`, mutating `runbook` steps), evaluate ET wall-clock vs `safety_windows.no_restart_overnight` (21:30–22:30 ET) BEFORE invoking any tool. Refuse without `--emergency`. This is the skill-layer ceiling; the tool-layer `@safety_window` decorator is the floor.
3. **TIER 3 PROBE** — For verbs that compose ContractCheck / GitArchaeology / DocConsistency, check tool availability via `python -m src.tools.<name> --help` (exit 0 = available). Warn + skip on absence (graceful degradation, gated on #107).
4. **DISPATCH** — Invoke tools via `python -m src.tools.<name> --json` and/or agents via `Agent(subagent_type: "<name>")`. Parse JSON envelopes and registered output tags (`<db_report>`, `<ci_report>`, `<git_report>`, `<live_report>`).
5. **COMPOSE** — When 2+ agents fire, merge findings into one operator-facing report using the OR-of-must-fix / AND-of-clear rule.
6. **CONFIRM** — For every mutation, `AskUserQuestion` with the proposed action + dry-run preview (where supported). Operator approval is required before passing `--confirm` to the tool layer.
7. **EXECUTE & VERIFY** — Execute the mutation, then run the per-action post-verification (e.g., `HealthProbe` after a restart).
8. **AUDIT** — Write a skill-level event to `data/logs/tool-execution.log` with `tool_name="arcis_operate.<verb>"` and a per-incident `session_id`. Per-tool events are inherited for free from the decorator stack.

## Agent Hierarchy

```
Operate Director (command orchestrator, opus)
├── live-monitor (opus, maxTurns:60)
│   — Live-system snapshot — NSSM state, heartbeat freshness, log tail, trading state. Always dispatched in triage.
├── db-investigator (opus, maxTurns:60)
│   — DB anomaly forensics — schema archaeology, row diffs, table ownership. Read-only. Dispatched on data symptoms.
├── ci-investigator (opus, maxTurns:60)
│   — pytest failure classification — flaky vs real, vacuous tests, mock drift. Dispatched on CI symptoms.
└── git-historian (opus, maxTurns:60)
    — Temporal git archaeology — who/when/why for a symbol or path. Read-only. Dispatched on regression symptoms.
```

The orchestrator does NOT have its own subagent file — it lives in `commands/operate.md` and dispatches the 4 #108 agents directly. None of the 4 agents are owned by this skill; they are inherited as read-only sensors.

## Key Properties

- **Skill-layer safety_window enforcement** — defense-in-depth: the skill refuses mutations inside 21:30–22:30 ET BEFORE invoking the tool, so the operator sees a clean refusal message rather than a subprocess exit-1 from the decorator stack
- **Mutation confirmation gate** — every `act` and every mutating `runbook` step requires `AskUserQuestion` approval; never auto-mutates
- **Graceful Tier 3 degradation** — verbs needing ContractCheck / GitArchaeology / DocConsistency emit `"tool not yet shipped, gated on #107 — skipping <step>"` warnings when the tool isn't installed; they do NOT crash
- **No out-of-scope deferral** — within an incident, the skill surfaces ALL discovered defects to the operator; it does not silently defer repairable issues to a "follow-up task"
- **Post-execution verification** — every `act` includes a verification step (e.g., after `restart-watchloop`, run `HealthProbe` to confirm the service came back)
- **Audit trail by inheritance + skill-layer summary** — per-tool events land in `data/logs/tool-execution.log` automatically; the skill also writes a verb-level event keyed by `session_id` for per-incident grepability
- **Operator decision authority** — the skill PROPOSES; the operator DECIDES. Every mutation is operator-approved.

## Verbs

| Verb | Behavior | Mutations | Agent dispatch |
|------|----------|-----------|----------------|
| `triage <symptom>` | Classify, dispatch agents, propose recommendation | No | live-monitor + selective {db,ci,git}-investigator |
| `act <action>` | Execute a confirmed mutation with verification | Yes | None |
| `status [service]` | Read-only health snapshot | No | None |
| `runbook <name>` | Execute a named codified flow | Per runbook | Per runbook |

## v1 Runbooks (5)

| Name | Symptom | File |
|------|---------|------|
| `watchloop-wedged` | ArcisWatchLoop unresponsive, heartbeat stale | `runbooks/watchloop-wedged.md` |
| `pg-tests-red` | pytest suite failing on Postgres-touching tests | `runbooks/pg-tests-red.md` |
| `training-failed` | Overnight training errored or produced no corpus | `runbooks/training-failed.md` |
| `gpu-degraded` | VRAM handoff failed / nvidia-smi anomaly | `runbooks/gpu-degraded.md` |
| `data-anomaly` | Row-count drift, orphan FK, missing collector tables | `runbooks/data-anomaly.md` |

## Arguments

| Flag | Purpose |
|------|---------|
| `<positional>[0]` | Verb (`triage` / `act` / `status` / `runbook`) — required |
| `<positional>[1...]` | Verb-specific args (symptom string / action name / service / runbook name) |
| `--emergency` | Bypass `safety_windows.no_restart_overnight` (still requires confirm) |
| `--dry-run` | For `act` and `runbook` verbs: stop before any mutation, just show the plan |
| `--service <name>` | Override the service target for `status` (default: all 3) |
| `--incident-id <id>` | Continue a prior incident (skips PARSE re-classification, replays session_id) |

## Out of scope

- Auto-execution of mutations without operator confirmation
- Trading strategy ideation / backtest — see `/arcis:strategy` (#110, future)
- Mutating any of the underlying Tier 1+2+3 tools or 4 #108 agents — frozen
