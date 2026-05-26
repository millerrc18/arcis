# Arcis #109 — `arcis:operate` Skill Design Specification

**Target version:** v0.36.6X (re-baselined at impl time, current main: v0.36.64)
**PR target:** dual-Opus QA — operator-experience capstone
**Status:** Spec + plan, ready for `/arcis:code --spec ... --plan ...`

---

## 0. Summary & Operator Workflow

`arcis:operate` is the operator's single live-system surface. At 3 AM, when the trading-research desk has a problem, the operator types ONE thing — `/arcis:operate triage <symptom>` — and the skill orchestrates a 13-tool + 4-agent decision tree, surfaces a structured recommendation, and (with operator confirmation) executes the remediation. Mutations honor the `safety_windows` policy at the skill layer (defense-in-depth on top of the tool-layer `@safety_window` decorator). Every step is audit-logged.

**The four verbs:**

1. `/arcis:operate triage <symptom>` — classify the incident, dispatch the right agent(s) (live-monitor + selectively db-investigator / ci-investigator / git-historian), merge findings, propose a remediation. **NO MUTATIONS.**
2. `/arcis:operate act <action> [args]` — execute a specific operational mutation (e.g., `restart-watchloop`, `post-pr-summary 1234`) with operator confirmation + safety-window check + audit log + post-execution verification.
3. `/arcis:operate status [service]` — read-only health snapshot composing `ProcessManager.status` + `HealthProbe` + `TradingState`. No agent dispatch.
4. `/arcis:operate runbook <name> [--dry-run]` — execute one of 5 named v1 flows: `watchloop-wedged`, `pg-tests-red`, `training-failed`, `gpu-degraded`, `data-anomaly`. Each runbook is a codified `triage → diagnose → confirm → act → verify` sequence stored as markdown.

This skill is the **capstone** of the infra-tooling track: it converts every prior investment (Tier 1+2+3 tools per #105/#106/#107, 4 specialized agents per #108, central config per #104) into a single workflow the operator invokes without remembering which sub-component to call first.

**Why state-machine (not freeform):** Live-system actions are high-stakes. The state machine forces explicit phase transitions, AskUserQuestion checkpoints at mutation gates, and audit-log writes at known boundaries. The freeform `arcis:research` precedent works for read-only investigation; the high-stakes precedents (`design`, `code`) both use state machines, and `operate` joins that camp.

**Why this is genuinely first-in-class:**

- First skill that performs live-system mutations (not just file/git mutations like `design`/`code`).
- First skill to enforce `safety_windows` at the skill layer (in addition to tool layer).
- First skill to compose 4 specialized agent output tags (`<db_report>`, `<ci_report>`, `<git_report>`, `<live_report>`) into a single operator-facing report.
- First skill to use a runbook convention (greenfield per FA15 — no existing precedent).

---

## 1. File Structure

| Path | Purpose | Est. lines |
|------|---------|------------|
| `.claude/plugins/arcis/skills/operate/SKILL.md` | Descriptor — user-facing surface for skill listing / discovery | 90 |
| `.claude/plugins/arcis/commands/operate.md` | Orchestrator — slash-command executable. Routes to `/arcis:operate <verb>` per FA12. Parses verb + dispatches. | 480 |
| `.claude/plugins/arcis/skills/operate/runbooks/watchloop-wedged.md` | Runbook — NSSM service unresponsive / heartbeat stale | 130 |
| `.claude/plugins/arcis/skills/operate/runbooks/pg-tests-red.md` | Runbook — pytest suite failing on Postgres-touching tests | 130 |
| `.claude/plugins/arcis/skills/operate/runbooks/training-failed.md` | Runbook — overnight training run errored or produced no corpus | 130 |
| `.claude/plugins/arcis/skills/operate/runbooks/gpu-degraded.md` | Runbook — VRAM handoff failure / nvidia-smi anomaly | 130 |
| `.claude/plugins/arcis/skills/operate/runbooks/data-anomaly.md` | Runbook — table-level data anomaly (row count drift, orphan FK, missing collector tables) | 130 |
| `.claude/plugins/arcis/skills/operate/references/action-authorization-matrix.md` | Reference — every `act` action's auth class (auto / confirm / emergency-only). Single source of truth referenced from `commands/operate.md`. | 60 |
| `.claude/plugins/arcis/skills/operate/references/error-envelopes.md` | Reference — error envelope shapes the operator sees for each failure class | 60 |
| `CHANGELOG.md` (modified) | Add v0.36.6X entry — "Skill: `/arcis:operate` ships with 4 verbs + 5 runbooks" | (~3 lines added) |

**Note on layout:** Runbooks live at `skills/operate/runbooks/<name>.md` (per requirements §Must — operator-confirmed path). References live at `skills/operate/references/`, joining `coding-team/references/` and `research-team/references/` in adopting a `references/` subdir convention (single-source precedent at spec time was `coding-team/references/`; `research-team` has its own references subtree; `design-team` and `marketpulse` have no `references/` subdir). The orchestrator `commands/operate.md` references both subtrees by relative path (per the FA4 precedent of `commands/code.md` line 225 referencing `skills/coding-team/references/anti-fallacy-playbook.md`).

**Total surface:** 10 new files + 1 modified file (CHANGELOG). All markdown. No Python.

---

## 2. SKILL.md Descriptor

**FULL VERBATIM CONTENT** of `.claude/plugins/arcis/skills/operate/SKILL.md`:

```markdown
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
```

---

## 3. commands/operate.md Orchestrator

**FULL VERBATIM CONTENT** of `.claude/plugins/arcis/commands/operate.md` (the executable orchestrator the LLM reads at slash-command invocation):

```markdown
---
name: operate
description: "Live-system incident response and change orchestration — triage symptoms, execute operator-confirmed mutations, run named runbooks. Composes 13 tools + 4 investigator agents."
---

# Operate — Live-System Director

You are the Director of the ARCIS Operate skill. The operator invokes you at 3 AM during an incident. Your job: classify the symptom, dispatch the right agents, surface a structured recommendation, and execute operator-confirmed remediation while honoring `safety_windows`. You do NOT diagnose with your own reasoning when an investigator agent exists for the domain — you dispatch the agent and synthesize its findings.

## NO OUT-OF-SCOPE DEFERRAL

Within an incident, you must surface ALL discovered defects to the operator. If triage finds 3 issues, your recommendation lists all 3 — never "we'll handle the other 2 later." If you find a defect in adjacent code while diagnosing the primary symptom (e.g., a sibling-line anti-pattern, a swallowed exception, a vacuous test), surface it as a numbered finding alongside the primary. The operator decides what to act on now vs. queue. You do not silently defer.

**This is the operator's explicit standard** (memory: `feedback_complete_efforts_no_deferral`). Honor it verbatim in every triage, every runbook, every act post-verify.

## ARGUMENT PARSING

Parse the user's input for these flags:

| Flag | Variable | Default |
|------|----------|---------|
| `--emergency` | `EMERGENCY` | false |
| `--dry-run` | `DRY_RUN` | false |
| `--service <name>` | `SERVICE_OVERRIDE` | null |
| `--incident-id <id>` | `INCIDENT_ID` | null (auto-generated below) |

Then split the remaining tokens (everything before/between/after flags) as `POSITIONAL_INPUT[]`.

- `POSITIONAL_INPUT[0]` is the **VERB** — required. One of: `triage` | `act` | `status` | `runbook`.
- `POSITIONAL_INPUT[1...]` is verb-specific (see per-verb tables below).

If `INCIDENT_ID` is null, generate it now (DA6 fix — second-resolution collisions resolved via random suffix; secrets is cross-platform — no openssl dependency on Windows):

```bash
INCIDENT_ID="$(date -u '+incident-%Y-%m-%dT%H-%M-%SZ')-$(python -c "import secrets; print(secrets.token_hex(3))")"
```

Result shape: `incident-2026-05-25T13-15-00Z-9c3f1a` (6-hex-char suffix). Store as `INCIDENT_ID` and use it as the `session_id` for every audit-log write in this invocation.

**If `--incident-id` flag is supplied:**

1. Regex-validate the value: `^incident-\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}Z-[0-9a-f]{6}$`. On mismatch → ERROR envelope (§10.1-style) `unknown incident-id format: '<received>'. Expected: incident-YYYY-MM-DDTHH-MM-SSZ-XXXXXX`. STOP.
2. If the id matches an existing audit event in last 1 hour (grep `tool-execution.log` for any line with `session_id=<id>` and `timestamp` within 1h): AskUserQuestion: `"An incident with id <id> already has audit events in the last hour. Continuing will merge new events into that incident's stream. Continue?"` — options: `"Yes — merge streams"`, `"Cancel — pick a new incident-id"`. If "Cancel", STOP.
3. Otherwise, use as-is.

### Verb-unknown handling

If `POSITIONAL_INPUT[0]` is missing or not in {`triage`, `act`, `status`, `runbook`}:

1. Print:
   ```
   ERROR — unknown verb: "<received>". Expected one of: triage, act, status, runbook.
   Usage:
     /arcis:operate triage "<symptom>"           — investigate (no mutations)
     /arcis:operate act <action> [args]          — execute mutation with confirm
     /arcis:operate status [service]             — read-only health snapshot
     /arcis:operate runbook <name> [--dry-run]   — run a named flow
   ```
2. STOP. Do NOT proceed to any phase. Do NOT write to audit log (no incident).

### Tier 3 availability probe (one-time, cached for this invocation)

Before any phase that may compose Tier 3 tools, run:

```bash
for tool in contractcheck gitarchaeology docconsistency; do
  python -m src.tools.$tool --help 2>/dev/null 1>/dev/null && echo "$tool=available" || echo "$tool=missing"
done
```

Store results as `TIER3_AVAILABLE[<name>]` map. Verbs that compose a Tier 3 tool branch to:

```
"Tool <name> not yet shipped, gated on #107 — skipping <step>. Surfacing partial findings only."
```

Then continue with available tools. Do NOT crash. Do NOT abort the verb.

---

## PHASE 0: COMMON PREAMBLE (all verbs)

Every verb runs these 3 steps first.

### Step 0.1 — Capture ET wall-clock

```bash
NOW_ET=$(python -c "import os, datetime; from zoneinfo import ZoneInfo; o=os.environ.get('ARCIS_NOW_ET_OVERRIDE'); now=datetime.datetime.fromisoformat(o) if o else datetime.datetime.now(ZoneInfo('America/New_York')); print(now.strftime('%Y-%m-%d %H:%M %Z'))")
```

Store as `NOW_ET` (e.g., "2026-05-25 22:15 EDT"). Use this string in any audit-prelude bracket events ONLY.

**IMPORTANT (DA1):** The Python one-liner honors the `ARCIS_NOW_ET_OVERRIDE` env var (per FA9 `_safety.py:218` test seam) so spec §12 item 3 (`ARCIS_NOW_ET_OVERRIDE=...` verification) is actually exercised. The shell `TZ='America/New_York' date` form was rejected because it ignores the override env var.

**This Step-0.1 capture is for audit-prelude bracket events ONLY.** The safety bounds check (SAFETY WINDOW GATE below) MUST re-run the same Python one-liner at gate entry — do not reuse Step 0.1's stale capture. A long-running act started at 21:28 may finish triage and arrive at the gate at 21:31 ET; the gate must see 21:31 (fresh), not 21:28 (stale).

### Step 0.2 — Verify working directory

```bash
cd "$(git rev-parse --show-toplevel)" 2>&1 || cd "$WORKTREE_PATH"
pwd
```

The skill must run from the repo root (or a designated worktree). If neither resolves, refuse:

```
ERROR — cannot resolve repo root via git rev-parse. Pass --incident-id and rerun from a known repo path.
```

### Step 0.3 — Write incident-start audit event

Skip if `VERB == status` (status is read-only; no incident audit needed).

```bash
python -c "
from src.tools._execution_log import write_event
write_event(
  tool_name='arcis_operate.${VERB}.start',
  params={'positional': $POSITIONAL_INPUT_JSON, 'flags': {'emergency': $EMERGENCY, 'dry_run': $DRY_RUN}},
  result='success',
  duration_ms=0,
  session_id='$INCIDENT_ID',
)
"
```

Failure of this write is non-blocking. Log a warning to operator output, continue.

---

## SAFETY WINDOW GATE (shared by `act` and mutating `runbook` steps)

This gate runs before any tool invocation that mutates state.

### Evaluation

**Re-capture NOW_ET at gate entry (DA1 fix).** Step 0.1's capture is for audit-prelude bracket events ONLY; the safety bounds check uses a fresh capture, because the gate may fire many seconds (or minutes) after Step 0.1 in a long-running act or runbook:

```bash
NOW_ET_GATE=$(python -c "import os, datetime; from zoneinfo import ZoneInfo; o=os.environ.get('ARCIS_NOW_ET_OVERRIDE'); now=datetime.datetime.fromisoformat(o) if o else datetime.datetime.now(ZoneInfo('America/New_York')); print(now.strftime('%Y-%m-%d %H:%M %Z'))")
```

Extract the `HH:MM` substring from `NOW_ET_GATE`. Compare:

- If `21:30 <= HH:MM < 22:30` (inclusive start, exclusive end — matches `_in_window` in `src/tools/_safety.py:239-255`) → **IN WINDOW**.
- Otherwise → **OUT OF WINDOW**.

(All in-window / out-of-window prose below uses `NOW_ET_GATE` — the fresh capture — not the stale Step 0.1 `NOW_ET`.)

### In-window behavior

If IN WINDOW and `EMERGENCY = false`:

1. Print verbatim (substituting `$NOW_ET_GATE` for `Current ET`):
   ```
   REFUSE — safety_windows.no_restart_overnight active.
     Current ET: $NOW_ET_GATE
     Window: 21:30–22:30 (no_restart_overnight)
     Reason: mid-cycle restart forces a redundant overnight re-launch (memory: feedback_no_restart_during_overnight_window)

   Options:
     1. Wait until 22:30 ET and re-run the same command.
     2. Re-run with --emergency if this is a genuine emergency. You will be asked to confirm.

   No mutation attempted. No audit event for mutation written.
   ```
2. Write `arcis_operate.<verb>.safety_window_refused` audit event.
3. STOP. Do NOT invoke any tool. Do NOT prompt operator (the refusal IS the answer).

If IN WINDOW and `EMERGENCY = true`:

1. AskUserQuestion (BLOCKING):

   > You are bypassing safety_windows.no_restart_overnight (21:30–22:30 ET).
   > Current ET: $NOW_ET_GATE. The window exists because mid-cycle restart forces a redundant overnight re-launch from scratch (incident 2026-05-18 v0.36.22 deploy).
   > Action to execute: $PROPOSED_ACTION
   > Proceed with emergency override?

   Options:
   - "No — wait until 22:30 ET" — STOP, return to caller, write `arcis_operate.<verb>.emergency_denied` audit event.
   - "Yes — emergency override" — proceed to verb-specific phase, set `EMERGENCY_OVERRIDE_CONFIRMED = true` in audit params.

2. On "Yes": continue to verb body. The tool-layer will see `--emergency` and bypass its decorator block — the audit trail will record `params.emergency = true`.

### Out-of-window behavior

OUT OF WINDOW: proceed directly to verb-specific phase. No prose required.

---

## VERB: triage

**Usage:** `/arcis:operate triage "<symptom>"`

Triage is **read-only**. It dispatches agents, composes findings, proposes a recommendation. It does NOT mutate. AskUserQuestion budget: ≤3 per incident.

### Phase T1 — Symptom classification

`POSITIONAL_INPUT[1...]` joined by spaces is the `SYMPTOM` string.

Classify the symptom using keyword heuristics:

| Keyword in $SYMPTOM (case-insensitive) | Domain | Always dispatch | Conditionally dispatch |
|---|---|---|---|
| `watchloop`, `nssm`, `wedged`, `unresponsive`, `service` | live | live-monitor | — |
| `trades`, `recommendation`, `shadow`, `orphan`, `position`, `alpaca` | data | live-monitor | db-investigator |
| `pytest`, `tests`, `red`, `flaky`, `ci`, `workflow` | ci | live-monitor (skip if pure-CI) | ci-investigator |
| `training`, `corpus`, `gguf`, `vram`, `ollama`, `gpu`, `cuda` | training | live-monitor | db-investigator (if corpus), git-historian (if regression) |
| `regression`, `started failing`, `worked before`, `bisect` | git | live-monitor | git-historian |
| (no keyword match) | unclear | — | — (go to AskUserQuestion below) |

**Default:** always dispatch `live-monitor` unless the symptom is unambiguously pure-CI (e.g., "PR 1234 tests are flaky" with no live-system context).

### Phase T2 — Operator confirmation of agent slate (AskUserQuestion #1 of 3)

Show the operator the dispatch plan:

> Symptom: "$SYMPTOM"
> Classified domain: $DOMAIN
> Proposed agent dispatch: $DISPATCH_LIST (e.g., "live-monitor + db-investigator")
> Proceed?

Options:
- "Approve — dispatch the slate" — continue to T3
- "Modify — add or remove an agent" — interactive sub-prompt (use AskUserQuestion with `multi_select=true` listing all 4 agents)
- "Cancel — abort triage" — STOP, write `arcis_operate.triage.cancelled` audit event

**AskUserQuestion budget clarification (DA4 fix):** The ≤3-per-triage budget is for **MANDATORY checkpoints** (T2 dispatch confirm, optional T6 recommendation, optional unclear-symptom disambig). **Conditional operator-initiated subprompts** (the T2 modify-subprompt, the T6 "show me the runbook first" subprompt) are **unbounded but operator-initiated** — they only fire if the operator selected the option that demands them. Worst-case mandatory count: T2 disambig (1, if unclear) + T2 dispatch confirm (2) + T6 recommendation (3) = 3, within budget. The T2 modify-subprompt fires only if operator picked "Modify"; the T6 "show runbook" fires only if operator picked that option — both are sub-flows of an already-counted checkpoint, not new mandatory checkpoints.

If symptom was **unclear** (no keyword match), use AskUserQuestion to disambiguate FIRST:

> Symptom "$SYMPTOM" does not match a known domain. Which area is closest?
> Options:
> - "Live system / service"
> - "Data / database"
> - "Tests / CI"
> - "Training / GPU"
> - "Regression / git history"
> - "I'm not sure — start with live-monitor only"

Then re-derive `DISPATCH_LIST` and ask T2 above.

### Phase T3 — Parallel dispatch

Dispatch all agents in the slate IN PARALLEL (single message with multiple `Agent(...)` blocks — per FA2 code.md PHASE 3 EXECUTE pattern, lines 184-194).

**For each agent in $DISPATCH_LIST:**

```
Agent(
  subagent_type: "<agent-name>",
  prompt: <inject DYNAMIC CONTEXT below>
)
```

**DYNAMIC CONTEXT for live-monitor:**
```
## DYNAMIC CONTEXT

**MANDATE:** Snapshot the live system in service of triaging symptom: "{SYMPTOM}". Classify each finding by severity.
**FOCUS_SERVICES:** {classified focus or "ArcisWatchLoop,ArcisOllamaWatchdog,ArcisDashboard"}
**INCLUDE_TRADING_STATE:** {true if symptom mentions trades/positions/recommendations, else false}
**INCLUDE_CI_CONTEXT:** {true if symptom mentions tests/ci, else false}
**WORKTREE_PATH:** {pwd from Step 0.2}
```

**DYNAMIC CONTEXT for db-investigator:**
```
## DYNAMIC CONTEXT

**MANDATE:** Investigate DB-side correlate(s) of symptom: "{SYMPTOM}". Read-only.
**INVESTIGATION_MODE:** surface
**INITIAL_HYPOTHESIS:** {Director's best guess based on symptom keywords}
**FOCUS_TABLES:** {extracted from symptom — e.g., "shadow_trades,recommendations" if symptom mentions trades}
**WORKTREE_PATH:** {pwd from Step 0.2}
```

**DYNAMIC CONTEXT for ci-investigator:**
```
## DYNAMIC CONTEXT

**MANDATE:** Classify pytest failure(s) related to symptom: "{SYMPTOM}".
**RUN_ID:** {extracted from symptom if "PR 1234" or run-id mentioned; else "latest"}
**RUN_IDS:** {N/A unless symptom names ≥2 runs}
**TARGET_PR:** null (triage does NOT post; that is `/arcis:operate act post-pr-summary`)
**POST_SUMMARY:** false
**WORKTREE_PATH:** {pwd from Step 0.2}
```

**DYNAMIC CONTEXT for git-historian:**
```
## DYNAMIC CONTEXT

**MANDATE:** Identify regression introduction window / bisect for symptom: "{SYMPTOM}".
**TARGET_SYMBOL:** {extracted from symptom — e.g., "reconcile_live_trades" if mentioned}
**VERSION_RANGE:** {extracted if "between v0.36.50 and v0.36.55" pattern matched; else "last 30d"}
**PATH_FILTER:** {extracted if symptom names a file; else null}
**WORKTREE_PATH:** {pwd from Step 0.2}
```

**Maximum wait per agent:** 5 minutes default. If an agent dispatch fails (Agent tool returns error, or no `<*_report>` tag in output), treat that agent as a SOURCE FAILURE — proceed with remaining agents, surface the failure in the final report as a numbered finding.

**TOTAL_WALL_CLOCK_BUDGET = 6 min for the parallel batch (DA5 fix).** If the parallel dispatch as a whole exceeds 6 min wall-clock, mark any agent that has not yet returned as `source: agent_timeout` (severity=anomaly, type=agent_timeout, evidence="agent did not return within 6min batch budget") and proceed to T3.5 with whatever returned. The slow-agent does NOT dominate end-to-end latency.

### Phase T4 — Compose findings

Parse the registered output tags from each agent:

- `<live_report>` per `live-monitor.md:102-145`: `snapshot_timestamp`, `service_state[]`, `correlations[]`, `coverage_assessment`
  - **Field-name discipline (FB2):** the registered live-monitor schema uses `service_state[]` (not `services[]`) and per-service `composite_verdict` ∈ `{healthy, degraded, unhealthy, unknown}` (not `verdict`, and there is NO `wedged` enum value). See `.claude/plugins/arcis/agents/live-monitor.md:106` (`service_state` field) and `:113` (`composite_verdict` enum). The "watchloop is wedged" triage condition is **derived**, not read directly: `wedged ≡ composite_verdict = "unhealthy" AND any(c.type == "heartbeat_stale" for c in correlations)`. Runbook decision points compose this mapping rather than reading a literal `wedged` value.
- `<db_report>` per `db-investigator.md:109`: `findings[]`, `coverage_assessment`
- `<ci_report>` per `ci-investigator.md:138`: `failures[]`, `classifications[]`, `coverage_assessment`
- `<git_report>` per `git-historian.md:99`: `findings[]`, `bisect_result`, `coverage_assessment`

**Composition algorithm** (per FA13 — reviewer-aggregation pattern from `code.md:240-307`):

1. Collect all findings/correlations/failures into a single list, tagging each with its source agent.
2. **Severity rollup:**
   - If ANY finding has `severity = "must_fix"` → incident severity = `critical`
   - Else if ANY finding has `severity = "anomaly"` → incident severity = `degraded`
   - Else if ALL findings have `severity = "informational"` or no findings → incident severity = `clear`
3. **Dedup criteria:** two findings are duplicates if they share `(table_or_symbol, defect_type)` — e.g., live-monitor noting "ArcisWatchLoop heartbeat stale" and db-investigator noting "watchloop_heartbeat row not updated in 30min" merge into ONE finding. Preserve both source references in `evidence_sources[]`.
4. **Ordering:** sort by severity (must_fix > anomaly > informational), then by `confidence` desc, then by agent name (live > db > ci > git for tie-break — live is the snapshot, so it comes first).
5. **Recommendation synthesis:** for each top-3 finding, propose:
   - The matching runbook (if a v1 runbook matches the domain — see runbook frontmatter `symptom-matchers:` per §4)
   - OR a specific `/arcis:operate act <action>` invocation
   - OR "no automated remediation available — investigate manually"

### Phase T4.5 — Re-verify primary symptom (DA5 fix)

Between T4 (compose findings) and T5 (report), the orchestrator runs a 10-second targeted re-check matching the primary symptom. This guards against composing recommendations on a stale snapshot when the system self-recovered during agent execution.

**Re-check selection (heuristic, derived from primary symptom classification at T1):**

- Primary symptom domain = `live` (watchloop/nssm/wedged) → re-run `python -m src.tools.healthprobe --service ArcisWatchLoop --json` (1-2s, cheap)
- Primary symptom domain = `data` (trades/recommendations/orphan) → re-run a targeted query via `python -m src.tools.dbquery --select "<the same diagnostic query that surfaced the primary db finding>" --json`
- Primary symptom domain = `ci` (pytest/tests) → re-fetch the gh run status: `gh run view <RUN_ID> --json status,conclusion`
- Primary symptom domain = `training` → re-run `python -m src.tools.tradingstate --json` + check the latest trainer log line via `python -m src.tools.logtail --service trainer --json --lines 1`
- Primary symptom domain = `git` (regression) → skip re-check (git symptoms don't self-resolve)
- Primary symptom domain = `unclear` → skip re-check (no specific signal to re-test)

**Time-box:** 10 seconds for the re-check call. If it doesn't return in 10s, skip (proceed to T5 with un-rechecked snapshot — log `re_check_skipped_timeout` in the T7 completion event params).

**Downgrade rule:**

- If the re-check shows the primary symptom **no longer reproduces** (e.g., heartbeat is now fresh, the missing rows now exist, the gh run is now `success`) → DOWNGRADE the incident `severity` to `monitor` (a fifth severity value, between `degraded` and `clear`). REPLACE the T6 AskUserQuestion prompt with: `"The primary symptom appears to have self-resolved during triage (re-check at $RECHECK_TS shows $RECHECK_EVIDENCE). Investigate root cause anyway, or close the incident?"` — options: `"Investigate root cause via /arcis:operate triage 'root cause of $SYMPTOM transient'"`, `"Close — no action"`.
- If the re-check shows the symptom **still present** → proceed to T5 unchanged (recommendation stands).
- If the re-check returns ERROR envelope → proceed to T5 unchanged + add a finding `[anomaly] re-check failed: $ERROR_MESSAGE` (the operator sees the re-check attempt didn't get a clean signal).

Write `arcis_operate.triage.recheck_result` audit event with `params = {recheck_evidence, downgrade_applied: bool, recheck_skipped: bool}`.

### Phase T5 — Operator-facing report (DA4 fix — ALL findings shown)

Print to operator. **ALL findings shown; first 5 in detail; remaining as one-line summary each.** This is the no-out-of-scope-deferral discipline applied at presentation time — no silent drop of findings 6 through N:

```
INCIDENT $INCIDENT_ID — TRIAGE COMPLETE
Symptom: $SYMPTOM
Severity: $SEVERITY (critical | degraded | clear)
Captured: $NOW_ET
Agents dispatched: $DISPATCH_LIST
Agents succeeded: $SUCCESS_LIST
Agents failed (source failure): $FAILED_LIST

FINDINGS ($N total — first 5 in detail; remaining $N-5 as one-line summary each):

1. [$SEVERITY] $TITLE
   Source: $AGENT_NAMES
   Evidence: $TRUNCATED_EVIDENCE  (≤200 chars + " [truncated]" if longer)
   Confidence: $CONFIDENCE
   Recommendation: $REC

2. ...

(items 1-5 in full detail above)

ADDITIONAL FINDINGS (one-line each, ordered same):
  6. [$SEVERITY/$CONFIDENCE] $TITLE — $SOURCE — rec: $REC
  7. [$SEVERITY/$CONFIDENCE] $TITLE — $SOURCE — rec: $REC
  ...
  N. [$SEVERITY/$CONFIDENCE] $TITLE — $SOURCE — rec: $REC

(Per §13 #3 + §12 item 10: NO out-of-scope deferral. ALL $N findings appear; only the detail tier differs.)

PROPOSED NEXT ACTIONS:
  A. /arcis:operate runbook $RUNBOOK_NAME    (matches top finding; suggested)
  B. /arcis:operate act $ACTION_NAME         (specific mutation; needs your confirm)
  C. Continue investigation manually          (no automated remediation)
```

### Phase T6 — Recommendation approval (AskUserQuestion #2 of 3 — optional)

If `SEVERITY = clear`: STOP. No further action. Write `arcis_operate.triage.clear` audit event.

If `SEVERITY != clear` AND a top-1 recommendation maps to a runbook or act:

> Triage produced a remediation recommendation. What's next?

**Options (DA4 fix — neutral order, default to information-gathering not action):**
- "Show me the runbook first" — Read the runbook file, print it inline, then re-ask the same question (DEFAULT — information-gathering, no action)
- "Yes — invoke $RUNBOOK_NAME / $ACTION" — set `CHAIN_VERB = runbook|act`, `CHAIN_ARG = <name>`, fall through to that verb's phases (passing the same `$INCIDENT_ID`)
- "No — I'll act manually" — STOP, write `arcis_operate.triage.completed_no_chain` audit event

Rationale: a 3 AM operator may reflexively pick the first option. Putting "Show me the runbook first" first biases toward read-before-mutate, not action-first.

Triage ends here. No mutations executed by triage itself.

### Phase T7 — Audit completion

Write `arcis_operate.triage.completed` event with:

```python
params={
  "symptom": SYMPTOM,
  "domain": DOMAIN,
  "dispatch_list": DISPATCH_LIST,
  "severity": SEVERITY,
  "finding_count": N,
  "chained_to": CHAIN_VERB or None,
}
```

---

## VERB: act

**Usage:** `/arcis:operate act <action> [action-specific args]`

Act executes a single specific mutation. Goes through Safety Window Gate, AskUserQuestion confirm, tool invocation, post-execution verification. AskUserQuestion budget: ≤2 per act (one for the action itself, one for emergency override if needed).

### Phase A1 — Resolve action

`POSITIONAL_INPUT[1]` is the `ACTION_NAME`. `POSITIONAL_INPUT[2...]` are action-specific args.

Look up the action in the **Action Authorization Matrix** (see §7 — `references/action-authorization-matrix.md`). If not found:

```
ERROR — unknown action: "$ACTION_NAME". Known actions: $KNOWN_LIST. See references/action-authorization-matrix.md.
```

STOP. Write `arcis_operate.act.unknown_action` audit event.

### Phase A2 — Action plan (dry-run preview)

Generate the planned invocation (the `python -m src.tools.<name> ...` command line) but DO NOT execute it. This is the dry-run preview shown in the confirm prompt.

For mutating tools that support an explicit dry-run flag (e.g., ProcessManager — without `--confirm` it returns a `DryRunResult` per FA8 `__main__.py:50-51`), invoke the dry-run version now and capture the JSON envelope. The `would_do` field is shown to the operator.

For mutating tools without dry-run support, render the planned command line verbatim ("would execute: `python -m src.tools.processmanager restart ArcisWatchLoop --confirm --json`") without invoking.

### Phase A3 — Safety Window Gate

Per the shared **SAFETY WINDOW GATE** section above.

If the action's row in the Action Authorization Matrix has `auth_class = auto-approved`, SKIP the safety gate (auto-approved actions are read-only adjacents like `status-snapshot`).

### Phase A4 — Confirmation (AskUserQuestion #1 of 2)

> Action: $ACTION_NAME
> Auth class: $AUTH_CLASS
> Planned command: $PLANNED_CMD
> Dry-run preview: $DRY_RUN_PREVIEW (or "no dry-run available for this tool")
> Post-execution verification: $VERIFY_STEP (e.g., "HealthProbe will run after restart to confirm service came back")
> Approve?

Options:
- "Approve — execute" — continue to A5
- "Cancel" — STOP, write `arcis_operate.act.cancelled` audit event
- "Show me the safety/audit context" — print the relevant memory references (e.g., `feedback_no_restart_during_overnight_window`, `feedback_hotfix_deploy_two_layer_staleness`), then re-ask

**After operator approves (DA8):** write `arcis_operate.act.<action>.confirmed` event with `prompt_hash` (SHA-256 of the prompt prose shown above) and `option_text` (verbatim string operator selected, e.g., `"Approve — execute"`) BEFORE proceeding to A5. See §9 Layer 2 schema for the event params shape.

### Phase A4.1 — Confirm-inheritance contract (DA2 fix)

A runbook step's `ask` MAY satisfy the inner `act`'s A4 confirm ONLY IF ALL FIVE of the following hold (otherwise A4 fires fresh inside `act`):

(i) The ask's prose names the exact `act <action>` identifier verbatim (e.g., `"act restart-watchloop"` or `"act restart-ollama-watchdog"`).
(ii) The ask's prose shows the exact CLI invocation (e.g., `"python -m src.tools.processmanager restart ArcisWatchLoop --confirm --json"`) — same string the Action Authorization Matrix's `CLI invocation` column would produce.
(iii) The ask's prose shows the `verify_step` from the Action Authorization Matrix for that action (e.g., `"python -m src.tools.healthprobe --service ArcisWatchLoop --json"`).
(iv) ONE of the AskUserQuestion options is exactly `"Approve <action>"` matching the auth-matrix verbiage (e.g., `"Approve — restart now"` is acceptable; `"OK"`, `"Yes"`, `"Continue"` are NOT — they fail contract requirement (iv) because the option label must name the action).
(v) The option labeled `Approve <action>` carries a `verified=true` bit that propagates to the inner `act`. The orchestrator sets `RUNBOOK_CONFIRM_VERIFIED = true` after the runbook's `ask` step completes with the matching option AND requirements (i)-(iv) above are all satisfied.

**On contract success (all 5 met):** A4 inherits — write `arcis_operate.act.<action>.confirmed` event with `prompt_hash` set to the runbook ask's prompt-prose hash, `option_text` set to the runbook ask's selected option, and `inherited_from_runbook=true` in params. A4's AskUserQuestion is SKIPPED.

**On contract failure (any of i-v missing):** A4 fires fresh — orchestrator writes a `arcis_operate.runbook.<name>.confirm_contract_failed_at_step_<N>` audit event noting which requirement failed (`failed_requirement: "(iv)_option_label_did_not_match_action"`), then the inner act re-prompts via standard A4 flow. The operator may see two confirms (the runbook ask + a4) — that is the safe fallback when the runbook author's prose did not satisfy the contract.

### Phase A5 — Execute

If `DRY_RUN = true` (flag set on the verb): STOP HERE. Print the planned command + preview. Write `arcis_operate.act.dry_run` audit event. Do NOT invoke the tool.

### Phase A5.1 — Re-capture preview before execute (DA10 fix)

System state can change between operator-approval at A4 and the actual `--confirm` execute. To prevent "approved X, executed Y" surprises:

1. BEFORE invoking the tool with `--confirm`, re-run the same dry-run command that produced the A2 preview (e.g., `python -m src.tools.processmanager restart ArcisWatchLoop --json` without `--confirm`).
2. Capture the fresh `would_do` text and observed state snapshot.
3. DIFF against the A2 preview captured at Phase A2:
   - **If `would_do` text differs OR observed state changed** → fresh AskUserQuestion (counts as an extra confirm — exceeds the ≤2 budget in this case; see §0):
     > System state changed since you approved.
     > A2 preview: $A2_PREVIEW
     > Current preview: $A5_PREVIEW
     > Diff: $DIFF
     > Re-approve with the new preview?
     Options:
     - "Yes — re-approve with new preview" — proceed to actual execute below
     - "Cancel" — STOP, write `arcis_operate.act.cancelled_state_changed` audit event
   - **If diff is null (no change)** → proceed silently to actual execute below (no extra prompt).

The A4 confirm prompt prose MUST also state explicitly: `"preview captured at $A2_DRY_RUN_TS; if state changes before execute, the actual action may differ."` — so the operator knows the re-capture may fire.

Then, invoke the tool via Bash:

```bash
python -m src.tools.<name> <verb> <args> --confirm [--emergency if EMERGENCY_OVERRIDE_CONFIRMED] --json
```

Parse the JSON envelope per FA8:

- `{"service": "...", "restarted": true, "verified": true, "elapsed_s": ..., ...}` (success — verb-specific shape)
- `{"error": {"type": "...", "message": "...", "tool": "..."}}` (failure)

On error envelope: surface verbatim, write `arcis_operate.act.tool_error` audit event with `params.error = error_envelope`. Do NOT retry automatically.

### Phase A6 — Post-execution verification

Run the action's verification step (defined in the Action Authorization Matrix `verify_step` column).

Example for `restart-watchloop`:

```bash
python -m src.tools.healthprobe --service ArcisWatchLoop --json
```

Parse the result. If verification PASSES → success path. If verification FAILS → escalate path.

**Two-layer staleness check** (memory: `feedback_hotfix_deploy_two_layer_staleness`): for restart actions, the post-verify must ALSO check that any dependent stale state has been refreshed. For `restart-watchloop` specifically: if the action followed a code change to auditor/governor, AND there's a stale `audit_reports` row older than 36h, the verify step must also trigger an auditor re-run (this is a verify-time check, not a separate mutation). Surface as a finding if detected; do NOT auto-trigger.

### Phase A7 — Operator-facing report + audit completion

```
ACT $ACTION_NAME — $RESULT (success | tool_error | verify_failed)
Incident: $INCIDENT_ID
Executed: $NOW_ET
Elapsed: $ELAPSED_S
Verify: $VERIFY_RESULT
$EVIDENCE
```

Write `arcis_operate.act.<action>.completed` audit event.

---

## VERB: status

**Usage:** `/arcis:operate status [service]`

Status is **read-only**. No agent dispatch. No mutations. No confirms.

### Phase S1 — Compose snapshot

> **Per-service status calls (FB4):** `processmanager` takes a single service per call (`processmanager/__main__.py:42`). The S1 phase issues a status call **per service** (3 calls when `SERVICE_OVERRIDE` is unset, 1 call when set), parallel with healthprobe + tradingstate.

Run the tools IN PARALLEL (single message, multiple Bash blocks):

```bash
# processmanager: per-service (no $SERVICE_OVERRIDE → all three; else just the override)
python -m src.tools.processmanager status ArcisWatchLoop --json        # if !SERVICE_OVERRIDE || SERVICE_OVERRIDE=ArcisWatchLoop
python -m src.tools.processmanager status ArcisOllamaWatchdog --json   # if !SERVICE_OVERRIDE || SERVICE_OVERRIDE=ArcisOllamaWatchdog
python -m src.tools.processmanager status ArcisDashboard --json        # if !SERVICE_OVERRIDE || SERVICE_OVERRIDE=ArcisDashboard

# parallel:
python -m src.tools.healthprobe ${SERVICE_OVERRIDE:+--service $SERVICE_OVERRIDE} --json
python -m src.tools.tradingstate --json
```

Parse each JSON envelope. Aggregate the 1-3 `processmanager status` envelopes into a virtual `{services: [...]}` map for the §S2 operator-facing template. On any tool returning ERROR envelope: include the error envelope in the report (don't fail the verb — it's a snapshot, partial is fine).

### Phase S2 — Operator-facing report

```
STATUS SNAPSHOT — $NOW_ET

NSSM Services:
  ArcisWatchLoop:      $STATE  (PID $PID, started $START_TS)
  ArcisOllamaWatchdog: $STATE  (PID $PID, started $START_TS)
  ArcisDashboard:      $STATE  (PID $PID, started $START_TS)

Health probes:
  watch_loop_heartbeat: $AGE (threshold $THRESHOLD — $PASS_FAIL)
  ollama_heartbeat:     $AGE ($PASS_FAIL)
  db_connect:           $LATENCY_MS ms ($PASS_FAIL)
  gpu_visible:          $YES_NO

Trading state:
  Open positions: $N
  Pending recommendations: $N
  Last broker poll: $TS
  Drawdown (peak-relative): $PCT

(Partial snapshot if any subprobe ERROR'd — errors listed below.)
$ERRORS
```

Status is the operator's "first thing I run when something feels off". MUST be fast (target <30s) and never block. If any subprobe times out at 60s, treat as ERROR.

### Phase S3 — No audit write

Status is read-only and inherits per-tool audit events automatically. No skill-level audit event.

---

## VERB: runbook

**Usage:** `/arcis:operate runbook <name> [--dry-run]`

Runbook executes a named codified flow. v1 ships with 5 runbooks (see §5 for the full content of each). Runbook execution is structured as a sequence of steps — each step is either a tool invocation, an agent dispatch, an AskUserQuestion checkpoint, or an inner-act call. Mutating steps go through the Safety Window Gate + confirm path identical to `act`.

### Phase R1 — Resolve runbook

`POSITIONAL_INPUT[1]` is `RUNBOOK_NAME`. Resolve to file path:

```
.claude/plugins/arcis/skills/operate/runbooks/<RUNBOOK_NAME>.md
```

If file does not exist:

```
ERROR — unknown runbook: "$RUNBOOK_NAME". Known runbooks: watchloop-wedged, pg-tests-red, training-failed, gpu-degraded, data-anomaly.
```

STOP. Write `arcis_operate.runbook.unknown` audit event.

### Phase R2 — Read runbook

**Validator gate (DA7 fix):** before parsing frontmatter, the orchestrator runs the §4 Runbook validation gate. If `data/cache/runbooks/<name>.validated` is missing OR the runbook file's content-hash has drifted from the cached hash → re-run the 5-check validator. If validation fails → REFUSE with the §10-class envelope from §4. If frontmatter is malformed (validator check (a)) → REFUSE with the §10-class envelope (do NOT attempt frontmatter parse downstream — it would crash). On validator PASS → continue with frontmatter parse below.

Read the runbook file. Parse the frontmatter (per §4 schema):

```yaml
---
name: <name>
verb: runbook
symptom-matchers:
  - <regex or keyword>
required-tools:
  - <tool name>
required-agents:
  - <agent name>
expected-duration: <e.g., 5-10 min>
mutations: <true|false>
---
```

If `required-tools` references a Tier 3 tool that's `TIER3_AVAILABLE[<name>] = missing`:

- If the runbook can degrade gracefully (per its prose), warn and skip that step.
- If the runbook strictly requires the missing tool, refuse:

```
REFUSE — runbook $RUNBOOK_NAME requires $MISSING_TOOL, which is not yet shipped (gated on #107).
Use /arcis:operate triage instead, or wait for #107 to land.
```

### Phase R3 — Execute steps

Parse the runbook body's `## Steps` section. Each step is one of:

- **`tool <name> <args>`** — Bash invocation of `python -m src.tools.<name> --json <args>`. Parse envelope. On ERROR: surface to operator, ask "continue/abort".
- **`agent <name>`** — Agent dispatch. DYNAMIC CONTEXT specified inline in the runbook.
- **`ask <question>`** — AskUserQuestion checkpoint.
- **`act <action>`** — call the `act` verb internally. Inherits Safety Window Gate + confirm. Inherits `$INCIDENT_ID`.
- **`verify <command>`** — post-execution verification, fail-on-error.

For each step in order:

1. Print the step number and description.
2. Execute per the step kind.
3. On success → continue to next step.
4. On error or AskUserQuestion-cancel → print the runbook's escalation prose (per `## Escalation` section), write `arcis_operate.runbook.<name>.escalated_at_step_<N>` audit event, STOP.

### Mid-runbook abandonment recovery (DA9 fix)

If an AskUserQuestion is **cancelled** OR a step **times out** AFTER a mutating step has executed but BEFORE its corresponding `verify` step has completed (mutating step N has finished, but step N+1 verify has not yet returned a clean pass), the orchestrator MUST NOT just STOP — the system is in an unknown-verified state:

(a) **Attempt the post-mutation verify step on a best-effort basis** (time-boxed to 60 seconds). Execute the verify command from step N+1; capture pass/fail/timeout. Do not require operator interaction — this is automated recovery.

(b) **Write `arcis_operate.runbook.<name>.abandoned_after_mutation` event** with params: `{"last_mutation": "<step N description>", "verify_result": "pass" | "fail" | "attempted_but_timed_out", "step": N+1, "abandonment_cause": "operator_cancel" | "timeout"}`.

(c) **On next `/arcis:operate status` or `/arcis:operate runbook <same-name>` invocation:** the orchestrator greps the audit log for any `arcis_operate.runbook.*.abandoned_after_mutation` event in the last 24h. If found, prompt: `"Previous runbook <name> (incident <prior-id>) abandoned after mutation step <N>; auto-verify result was <verify_result>. Verify status before continuing?"` — options: `"Yes — run /arcis:operate status before continuing"`, `"Continue anyway"`, `"Cancel"`.

This recovery applies to ALL runbooks where any step in the body is kind=`act` or kind=`tool` against a mutating tool (i.e., `mutations: true` runbooks). For `mutations: false` runbooks, abandonment recovery is a no-op (nothing mutated, nothing to verify).

### Phase R4 — Verify completion

After all steps complete, run the runbook's `## Success criteria` block (verify command). If it passes, the runbook succeeded.

### Phase R5 — Operator-facing report + audit

```
RUNBOOK $RUNBOOK_NAME — $RESULT (completed | escalated | aborted)
Incident: $INCIDENT_ID
Steps: $N_COMPLETE of $N_TOTAL
Elapsed: $ELAPSED_TOTAL
$SUCCESS_OR_FAILURE_EVIDENCE
```

Write `arcis_operate.runbook.<name>.completed` event with full step trace.

---

## ACTION AUTHORIZATION MATRIX

The full reference is at `.claude/plugins/arcis/skills/operate/references/action-authorization-matrix.md`. The orchestrator's responsibility:

1. **At Phase A1** — look up the action; if not found, ERROR.
2. **At Phase A3** — read the `auth_class` column; if `auto-approved`, skip Safety Gate.
3. **At Phase A4** — print the `verify_step` column to the operator in the confirm prompt.

### Inline summary (full table in §7):

| Action | Auth class | Verify step |
|---|---|---|
| `status-snapshot` | auto-approved | (no verify — read-only) |
| `restart-watchloop` | confirm + safety_window | `healthprobe --service ArcisWatchLoop` |
| `restart-ollama-watchdog` | confirm + safety_window | `healthprobe --service ArcisOllamaWatchdog` |
| `restart-dashboard` | confirm + safety_window | `healthprobe --service ArcisDashboard` |
| `post-pr-summary <pr>` | confirm | `prcomments --pr <pr> --tail 1` (verify post landed) |
| `verify-nvidia-smi` | confirm | (re-run nvidia-smi after; verify [N/A] absence) |
| `force-broker-poll` | confirm + safety_window | `tradingstate --json` (verify positions refreshed) |
| `regenerate-stale-audit` | confirm | `dbquery --select "SELECT max(generated_at) FROM audit_reports"` |

`emergency-only-in-window` is a marker applied to `confirm + safety_window` actions when the operator passes `--emergency`. See Safety Window Gate above.

---

## ERROR ENVELOPES (operator-facing)

Every error class has a defined operator-facing shape. See `references/error-envelopes.md` (§10) for full examples. Quick reference:

- **Verb-unknown** → see ARGUMENT PARSING section above.
- **Tier 3 unavailable** → warn + skip; never crash.
- **Safety window block** → REFUSE prose with override options.
- **Agent dispatch failure** → surface as numbered finding in composed report; proceed with remaining agents.
- **Tool JSON ERROR envelope** → surface `error.message` verbatim; recommend `/arcis:operate triage` to investigate.
- **Operator denial at confirm** → STOP, audit event, no mutation.
- **Runbook step timeout** → escalate per runbook's `## Escalation` section.

---

## AUDIT TRAIL CONVENTIONS

Every verb writes events to `data/logs/tool-execution.log` (the canonical log per FA10). The conventions:

- `tool_name = "arcis_operate.<verb>"` for high-level events (e.g., `arcis_operate.triage.start`, `arcis_operate.act.restart-watchloop.completed`)
- `session_id = $INCIDENT_ID` (the timestamp-based id from Step 0.0)
- `params` contains the sanitized inputs + outputs

Per-tool events from the underlying `python -m src.tools.<name>` calls are inherited automatically via the decorator stack — each underlying invocation writes its own event with its own tool_name + same session_id (the session_id propagation is via the orchestrator passing `session_id=$INCIDENT_ID` to the tool's CLI, OR by sharing the env var `ARCIS_SESSION_ID` which the `_execution_log.write_event` function picks up when present).

**IMPORTANT: session_id propagation in v1.** The orchestrator runs the tool subprocess with `ARCIS_SESSION_ID=$INCIDENT_ID python -m src.tools.<name> --json ...`. The tool's CLI envelope (`_cli_envelope.run_cli`) does not currently read this env var into the `write_event` call. **The skill must compensate by writing its own bracketing event** (`arcis_operate.<verb>.start` + `arcis_operate.<verb>.completed`) so the operator can grep by `session_id` and reconstruct the timeline from the bracket events alone if needed.

If desired post-v1, a one-line patch to `_cli_envelope.run_cli` would propagate `ARCIS_SESSION_ID` automatically. **Flag this in §14 as an Open Question for the implementing PM.**

---

## END OF ORCHESTRATOR
```

---

## 4. Runbook Convention

**Greenfield per FA15** — no existing runbook precedent in the codebase. The architect defines the convention:

### Frontmatter schema

```yaml
---
name: <kebab-case-name>           # must match filename
verb: runbook                      # always "runbook" (anchors that this is operate's runbook)
symptom-matchers:                  # array of strings or regexes the triage verb matches against
  - "watchloop wedged"
  - "heartbeat stale"
  - "ArcisWatchLoop unresponsive"
required-tools:                    # tool names — orchestrator checks availability before running
  - processmanager
  - healthprobe
  - logtail
required-agents:                   # agent names — orchestrator dispatches per step
  - live-monitor
expected-duration: 5-10 min        # human-readable estimate for operator planning
mutations: true                    # boolean — flag for "this runbook performs mutations" to trip Safety Gate per-step
risk-level: medium                 # low | medium | high — determines confirm gate strictness
references:                        # supporting memory/spec citations, for context surface
  - feedback_no_restart_during_overnight_window
  - reference_watch_loop_management
confirm-inheritance:               # OPTIONAL — declares which `ask` steps INTEND to satisfy a downstream `act`'s A4 confirm (DA2)
  - step: 2                        # the ask step number
    satisfies_act_step: 3          # the act step that should inherit A4 from this ask
    target_action: restart-watchloop  # the action whose A4 this satisfies
---
```

### Confirm-inheritance contract (DA2 — operator-authored runbook safety)

The `confirm-inheritance:` frontmatter field is OPTIONAL but RECOMMENDED for any runbook that chains `ask <question>` directly into `act <action>`. The orchestrator uses this field as an intent-declaration: "step <N> ask is intended to satisfy step <M> act's A4 confirm." At runtime, the orchestrator enforces the FIVE-point contract from §3.A4.1 — even if the runbook author declares inheritance, the contract checks (i)-(v) determine whether it actually inherits. If contract fails, A4 fires fresh regardless of the frontmatter declaration. The frontmatter field is documentation + intent; the contract is the enforcer.

The 5-point contract verbatim (mirror of §3.A4.1):

(i) The ask's prose names the exact `act <action>` identifier.
(ii) The ask's prose shows the exact CLI invocation.
(iii) The ask's prose shows the `verify_step` from the auth matrix.
(iv) ONE AskUserQuestion option is exactly `Approve <action>` matching the auth-matrix verbiage.
(v) The Approve option carries `verified=true` propagating to the inner act.

Runbook authors authoring a new mutating runbook are STRONGLY ENCOURAGED to:
1. Include the `confirm-inheritance:` frontmatter declaring intent.
2. Author the ask step prose to satisfy all 5 contract requirements (use spec §5.1 Step 2 as the template).
3. Test via the spec §12 ask-then-act chain verification item.

### Body structure (required sections, in order)

1. **`## When to use`** — 1-3 sentences describing the operator-facing trigger
2. **`## Prerequisites`** — what must be true to attempt this runbook (e.g., "operator has terminal access", "git working tree clean — runbook does not modify code")
3. **`## Steps`** — ordered list, each item one of the 5 step kinds:

   - `Step N — tool <name> <args>` — Bash subprocess
   - `Step N — agent <name>` — Agent dispatch, with inline DYNAMIC CONTEXT
   - `Step N — ask <question-id>` — AskUserQuestion checkpoint with options
   - `Step N — act <action>` — recursive call into the act verb (inherits Safety Gate)
   - `Step N — verify <command>` — post-step verification, fail-on-error

   Each step block has the shape:
   ```
   ### Step N — <kind> <name>
   
   **Purpose:** <1 sentence>
   **Invocation:** <verbatim command or Agent block>
   **Expected output:** <JSON shape or natural-language>
   **Decision point:** <if-then for each outcome>
   **On failure:** <recover or escalate path>
   ```

4. **`## Success criteria`** — verify command + expected JSON shape that confirms the runbook achieved its goal
5. **`## Rollback`** — if any step mutated state, what's the rollback procedure
6. **`## Escalation`** — if the runbook can't complete, what the operator should do next (e.g., "page the on-call human", "open an issue at #109", "fall back to manual triage")

### Symptom-matchers semantics

The triage verb's classifier (Phase T1) consults the runbook frontmatters as a secondary signal. If a symptom string matches a runbook's `symptom-matchers`, the triage Phase T6 recommendation defaults to "execute that runbook." Matches are: case-insensitive substring match for plain strings, full-regex for strings starting with `/`.

### Runbook validation gate (DA7 fix)

BEFORE first use of any runbook in a given invocation, the orchestrator runs a Bash subprocess validator. The validator performs FIVE checks:

(a) **Frontmatter schema lint** — required keys present (`name`, `verb`, `symptom-matchers`, `required-tools`, `required-agents`, `expected-duration`, `mutations`, `risk-level`); each key's value matches its declared type (`mutations` is bool, `risk-level` ∈ {low, medium, high}, `symptom-matchers` is list-of-strings, etc.).
(b) **Required-tools resolve to real modules** — every value in `required-tools[]` corresponds to a `src/tools/<value>/` directory in the repo (Glob check). A typo (`capabilityregistryquery` vs the correct `capabilityregistry`) fails here.
(c) **Symptom-matcher catch-all detection** — if a symptom-matcher (plain string or regex) matches > 50% of the orchestrator's test-symptom corpus (a small set of 8-10 hand-crafted symptoms covering each domain), the matcher is too broad → REJECT.
(d) **Cyclic runbook references** — build a `runbook → runbook` dependency graph from any `## Steps` body line that mentions `runbook <name>`; reject cycles.
(e) **Step kind enumeration** — every numbered step's `<kind>` MUST be in {`tool`, `agent`, `ask`, `act`, `verify`}. Other kinds → REJECT.

**Validator caching:** validation result is cached at `data/cache/runbooks/<name>.validated` with shape `{"validated_at": <ISO-ts>, "content_hash": "<sha256 of runbook file>", "result": "pass" | {"failed_check": "(b)", "message": "..."}}`. On subsequent invocations, the orchestrator reads the cache file; if `content_hash` matches the runbook file's current hash, the cache is valid (re-validation skipped). If the runbook file has been edited since cache (hash mismatch), re-validate.

**On validation failure:** Phase R2 REFUSES the runbook with a §10-class envelope:

```
REFUSE — runbook $RUNBOOK_NAME failed validation check $FAILED_CHECK.
  Detail: $FAILED_DETAIL
  Action: fix the runbook file at $RUNBOOK_PATH and re-run.

No incident audit event written (runbook never executed).
```

The orchestrator runs the validator at Phase R2 BEFORE parsing the frontmatter for required-tools/agents. Validator failure short-circuits Phase R2.

**Implementing PM note:** the validator itself is a ~50-line Python script that the implementing PM authors (out of T3-T7 runbook scope; included in T8 references work). For v1, ship as `src/tools/_runbook_validator.py` (single-purpose, not a CLI tool — invoked via `python -c "from src.tools._runbook_validator import validate; validate('runbooks/<name>.md')"`).

### Required-tools / required-agents semantics

- `required-tools[]` — every named tool must be available (Tier 3 check passes) for the runbook to execute. If any is missing AND graceful degradation is documented in the body, warn+skip the affected step. If missing AND no degradation path, REFUSE the runbook.

  **Module-name vs conceptual-name discipline (FB1):** `required-tools[]` values are **Python module names** (e.g., `capabilityregistry`, `processmanager`, `dbquery`, `logtail`), NOT conceptual capability names like "CapabilityRegistryQuery." The CLI invocation is literally `python -m src.tools.<value>` (see `src/tools/capabilityregistry/__main__.py:1` — module path is `capabilityregistry`; conceptual descriptor "CapabilityRegistryQuery" appears only in prose/SKILL.md descriptions, never in invocation paths or `required-tools[]`). The orchestrator's Tier 3 availability probe (§3 line ~208) and per-runbook availability check both expand `<value>` directly into `python -m src.tools.<value> --help`; a conceptual name there fails with `ModuleNotFoundError`.

- `required-agents[]` — every named agent must exist (file present at `.claude/plugins/arcis/agents/<name>.md`). The orchestrator verifies via Glob before Phase R3.

### Step-list shape (worked example)

```markdown
### Step 1 — agent live-monitor

**Purpose:** Establish that ArcisWatchLoop is actually wedged (heartbeat stale + process status).

**Invocation:**
```
Agent(
  subagent_type: "live-monitor",
  prompt: <inject DYNAMIC CONTEXT>
)
```

**DYNAMIC CONTEXT:**
```
## DYNAMIC CONTEXT

**MANDATE:** Determine whether the ArcisWatchLoop service is wedged. Cross-correlate the NSSM process state, heartbeat file freshness, and recent log output to produce a snapshot verdict.
**FOCUS_SERVICES:** ArcisWatchLoop
**INCLUDE_TRADING_STATE:** false
**INCLUDE_CI_CONTEXT:** false
**WORKTREE_PATH:** {pwd}
```

**Expected output:** `<live_report>` tag with `service_state[0].composite_verdict ∈ {healthy, degraded, unhealthy, unknown}` plus `correlations[]` entries that may include `type = "heartbeat_stale"`.

**Decision point** (derived "wedged" condition per FB2 mapping):
- `composite_verdict = "unhealthy" AND any(c.type == "heartbeat_stale" for c in correlations)` → **wedged-equivalent** → proceed to Step 2
- `composite_verdict = "healthy"` → STOP, runbook does not apply
- `composite_verdict = "degraded"` (without `heartbeat_stale` correlation) → AskUserQuestion: "ArcisWatchLoop is degraded but not stale-heartbeat. Investigate cause or treat as wedged?"
- `composite_verdict = "unknown"` → AskUserQuestion to operator: "Live-monitor could not classify. Proceed assuming wedged?"

**On failure:** If agent dispatch fails (no `<live_report>` returned), AskUserQuestion: "live-monitor failed — fall back to manual nssm status check?" Manual fallback: `Bash: sc query ArcisWatchLoop`
```

This template is used by all 5 v1 runbooks below.

---

## 5. The 5 v1 Runbooks (FULL VERBATIM CONTENT)

### 5.1 — `runbooks/watchloop-wedged.md`

```markdown
---
name: watchloop-wedged
verb: runbook
symptom-matchers:
  - "watchloop wedged"
  - "ArcisWatchLoop unresponsive"
  - "heartbeat stale"
  - "watch loop not running"
  - "watch loop frozen"
required-tools:
  - processmanager
  - healthprobe
  - logtail
required-agents:
  - live-monitor
expected-duration: 5-10 min
mutations: true
risk-level: medium
references:
  - feedback_no_restart_during_overnight_window
  - reference_watch_loop_management
  - reference_scm_dependency_wedge
---

# Runbook — watchloop-wedged

## When to use

The ArcisWatchLoop NSSM service appears unresponsive: the heartbeat file under `paths.watchdog_heartbeat` is older than the configured threshold, OR `sc query ArcisWatchLoop` returns RUNNING but no recent log activity, OR the operator observes that scheduled tasks (broker poll, drawdown recompute) have not advanced.

## Prerequisites

- Operator has terminal access to the host (NSSM operations require admin elevation on Windows; the underlying `processmanager` tool handles this internally).
- Current ET is outside the `safety_windows.no_restart_overnight` window (21:30–22:30) — OR operator is invoking with `--emergency` and prepared to accept the redundant overnight re-launch cost (per `feedback_no_restart_during_overnight_window`).

## Steps

### Step 1 — agent live-monitor

**Purpose:** Confirm the wedged state before any restart. Avoid restarting a healthy service.

**Invocation:**
```
Agent(
  subagent_type: "live-monitor",
  prompt: <inject DYNAMIC CONTEXT>
)
```

**DYNAMIC CONTEXT:**
```
## DYNAMIC CONTEXT

**MANDATE:** Determine whether the ArcisWatchLoop service is wedged. Cross-correlate the NSSM process state, heartbeat file freshness, and recent log output to produce a snapshot verdict.
**FOCUS_SERVICES:** ArcisWatchLoop
**INCLUDE_TRADING_STATE:** false
**INCLUDE_CI_CONTEXT:** false
**WORKTREE_PATH:** {pwd}
```

**Expected output:** `<live_report>` with `service_state[0].name = "ArcisWatchLoop"`, `service_state[0].composite_verdict ∈ {healthy, degraded, unhealthy, unknown}`, plus correlation findings (`correlations[*].type` may include `heartbeat_stale`) on heartbeat age + log tail.

> **Schema discipline (FB2):** the registered live-monitor schema (see `.claude/plugins/arcis/agents/live-monitor.md:106-113`) does NOT include a `wedged` enum value. The "wedged" decision is derived: `wedged ≡ composite_verdict = "unhealthy" AND any(c.type == "heartbeat_stale" for c in correlations)`.

**Decision point:**
- `composite_verdict = "unhealthy" AND any(c.type == "heartbeat_stale" for c in correlations)` (**wedged-equivalent**) → continue to Step 2
- `composite_verdict = "healthy"` → STOP. Runbook does not apply. Print: "ArcisWatchLoop is healthy — no restart needed. Investigate why the operator thought it was wedged (stale dashboard? clock drift?)."
- `composite_verdict = "degraded"` (no `heartbeat_stale` correlation) OR `composite_verdict = "unhealthy"` without `heartbeat_stale` → `ask continue-degraded`:
  > live-monitor reports composite_verdict={VAL} without a heartbeat_stale correlation. Proceed with restart anyway (treat as wedged)?
  - "Yes — proceed to Step 2"
  - "No — abort runbook"
- `composite_verdict = "unknown"` → `ask continue-unknown`:
  > live-monitor classified as unknown. Proceed assuming wedged?
  - "Yes — proceed to Step 2"
  - "No — abort runbook"

**On failure:** Agent dispatch returns no `<live_report>` → AskUserQuestion fallback:
> live-monitor failed to return a report. Fall back to manual `sc query` check?
- "Yes — Bash: `sc query ArcisWatchLoop`"
- "No — abort"

### Step 2 — ask confirm-restart

**Purpose:** Operator approval gate before any service mutation. This is the Safety Window Gate + Auth confirm rolled into one (per the `act restart-watchloop` Auth Matrix row).

**Invocation:** AskUserQuestion (BLOCKING).

> live-monitor confirms ArcisWatchLoop is wedged (heartbeat age $AGE; last log $LAST_LOG).
> Current ET: $NOW_ET.
> Proposed action: `python -m src.tools.processmanager restart ArcisWatchLoop --confirm --json`
> Verify step after restart: `python -m src.tools.healthprobe --service ArcisWatchLoop --json`
> Proceed?

Options:
- "Approve — restart now" — continue to Step 3
- "Cancel — abort runbook" — STOP, audit event `arcis_operate.runbook.watchloop-wedged.cancelled_at_step_2`

If in safety window AND `EMERGENCY = false`: this step is REFUSED per the Safety Window Gate; show the override prompt.

### Step 3 — act restart-watchloop

**Purpose:** Restart the wedged service via the canonical NSSM-managed path. **NEVER** call `python -m src.main startup` directly (memory: `reference_watch_loop_management`).

**Invocation:** `/arcis:operate act restart-watchloop` (inherits this runbook's `$INCIDENT_ID` for audit-trail continuity).

Under the hood: `python -m src.tools.processmanager restart ArcisWatchLoop --confirm --json` (per FA8 — the CLI shape).

**Expected output (JSON envelope):**
```json
{"service": "ArcisWatchLoop", "restarted": true, "verified": true, "elapsed_s": 8.2, "log_evidence": "...", "state": "RUNNING"}
```

**Decision point:**
- `restarted = true && verified = true` → continue to Step 4
- `restarted = true && verified = false` → continue to Step 4 anyway, but flag verification failure
- ERROR envelope (e.g., NSSM dependency wedge per `reference_scm_dependency_wedge`) → escalate

**On failure:** If error envelope indicates NSSM SCM dependency wedge (look for `error.message` containing "1068" or "1075"), surface the manual recovery from `reference_scm_dependency_wedge`:
> SCM appears wedged. Manual recovery: `nssm dump ArcisWatchLoop` → save config → `sc delete ArcisWatchLoop` → reinstall via `nssm install`. Need operator hands-on intervention. Runbook escalates.

### Step 4 — verify healthprobe

**Purpose:** Confirm the service came back. Two-layer staleness check (memory: `feedback_hotfix_deploy_two_layer_staleness`).

**Invocation:**
```bash
python -m src.tools.healthprobe --service ArcisWatchLoop --json
```

**Expected output:**
```json
{"service": "ArcisWatchLoop", "state": "RUNNING", "heartbeat_age_s": 12, "passed": true}
```

**Decision point:**
- `passed = true && heartbeat_age_s < 60` → continue to Step 5 (clean success)
- `passed = true && heartbeat_age_s >= 60` → continue to Step 5 BUT print warning: "Service running but heartbeat still stale — may need 60s grace period; re-run /arcis:operate status in 2 min to confirm."
- `passed = false` → escalate per `## Escalation`

### Step 5 — verify trading-state

**Purpose:** Confirm the watch loop is making actual progress (not just running but stuck on a different wedge).

**Invocation:**
```bash
python -m src.tools.tradingstate --json
```

**Expected output:** Look at `last_broker_poll_ts`. Should be within 5 min of `$NOW_ET`.

**Decision point:**
- `last_broker_poll_ts` within 5 min of now → SUCCESS. Runbook complete.
- `last_broker_poll_ts` older than 5 min AND `state = STARTING` → wait 2 min, re-run this step.
- `last_broker_poll_ts` older than 5 min AND `state = RUNNING` → ESCALATE: service is running but watch cycle not progressing. Possibly a code-level wedge, not a process wedge.

## Success criteria

```bash
# All three must be true:
python -m src.tools.healthprobe --service ArcisWatchLoop --json | jq '.passed' # → true
python -m src.tools.tradingstate --json | jq '.last_broker_poll_age_s < 300'    # → true (poll within 5min)
TZ='America/New_York' date '+%H:%M'                                              # outside 21:30-22:30 window
```

## Rollback

Restart is non-destructive — the underlying state (DB, files, positions) is unchanged. If the restart made things WORSE (unlikely but possible), the rollback is: do nothing additional. The service was already wedged; a failed restart leaves it wedged. Operator escalation pathway is to inspect logs and consider hand-restarting via `nssm restart ArcisWatchLoop` directly.

## Abandonment recovery (DA9)

If the operator cancels or the AskUserQuestion at Step 2 times out AFTER Step 3 (`act restart-watchloop`) has executed but BEFORE Step 4 (verify healthprobe) completes — i.e., the restart fired but verification didn't:

1. Orchestrator MUST attempt Step 4 (`healthprobe --service ArcisWatchLoop --json`) on a best-effort basis, time-boxed to 60 seconds.
2. Capture the verify result (`pass` / `fail` / `attempted_but_timed_out`).
3. Write `arcis_operate.runbook.watchloop-wedged.abandoned_after_mutation` event with `last_mutation="Step 3 restart-watchloop"`, `verify_result=<captured>`, `step=4`.
4. On next `/arcis:operate status` invocation in the next 24h, the orchestrator will prompt the operator to re-verify before continuing (per §3 Phase R3 abandonment recovery sub-section).

## Escalation

If the runbook escalates from any step:

1. Capture the current state via `/arcis:operate status` (the snapshot survives the runbook failure).
2. Surface the captured findings + the runbook step trace to the operator.
3. Suggest:
   - If SCM wedge: follow `reference_scm_dependency_wedge` manually (~13 min).
   - If heartbeat stale but service running: code-level wedge — investigate `src/scheduler/watch.py` recent changes via `/arcis:operate triage "watch loop running but not progressing"` (will dispatch git-historian).
   - If verification persistently fails: page operator out-of-band.
```

### 5.2 — `runbooks/pg-tests-red.md`

```markdown
---
name: pg-tests-red
verb: runbook
symptom-matchers:
  - "pg tests red"
  - "postgres tests failing"
  - "pytest pg failures"
  - "pg-tests.yml failing"
  - "Postgres CI red"
required-tools:
  - ciinvestigate
  - dbquery
  - logtail
  - prcomments
required-agents:
  - ci-investigator
  - db-investigator
expected-duration: 10-20 min
mutations: false  # diagnostic-only; resulting fixes are handed to operator
risk-level: low
references:
  - feedback_vacuous_test_pattern
  - feedback_review_sibling_search
---

# Runbook — pg-tests-red

## When to use

The `pg-tests.yml` CI workflow (or any PG-touching pytest job) is showing failures. The operator wants to know:
1. Which tests failed.
2. Whether each is flaky / vacuous / real regression.
3. Whether the failure is correlated with DB-side state (e.g., a table got dropped, a row diff between local and CI).
4. What the fix-now path is.

## Prerequisites

- A PR number OR a CI run ID. If neither is supplied, the runbook will prompt for one.
- gh CLI authenticated (the underlying tools assume this).

## Steps

### Step 1 — ask which-run

**Purpose:** Identify the CI run to investigate. Avoid scope creep (do not auto-scan all recent runs — that's git-historian's job for a different runbook).

**Invocation:** AskUserQuestion if `RUNBOOK_ARG[1]` (CI run id or PR number) was not provided.

> Which CI run should this runbook investigate?
> Provide one of:
> - PR number (e.g., "1234")
> - GitHub Actions run ID (e.g., "14123456789")
> - "latest" — use most recent pg-tests.yml run

Options:
- "PR number: <input>" — set TARGET_PR
- "Run ID: <input>" — set TARGET_RUN_ID
- "Latest" — fetch latest pg-tests run via `gh run list --workflow pg-tests.yml --limit 1`
- "Cancel"

### Step 2 — agent ci-investigator

**Purpose:** Classify each pytest failure. Distinguish real regression from flaky / vacuous / mock-drift.

**Invocation:**
```
Agent(
  subagent_type: "ci-investigator",
  prompt: <inject DYNAMIC CONTEXT>
)
```

**DYNAMIC CONTEXT:**
```
## DYNAMIC CONTEXT

**MANDATE:** Classify each pytest failure in {TARGET_RUN_ID or PR latest run} against the 4-way taxonomy (real regression / flaky / vacuous test / mock-target drift). Group by classification. For real regressions, identify the introducing commit if obvious.
**RUN_ID:** {TARGET_RUN_ID or null if PR mode}
**RUN_IDS:** null
**TARGET_PR:** {TARGET_PR or null}
**POST_SUMMARY:** false
**ALLOW_REPOST:** false
**WORKTREE_PATH:** {pwd}
```

**Expected output:** `<ci_report>` with `failures[]`, `classifications[]`, `coverage_assessment`.

**Decision point:**
- `failures[]` empty → STOP — no failures to investigate. Operator was wrong about the symptom, OR the run already passed on re-trigger.
- All failures classified `vacuous` or `mock-drift` → continue to Step 3 (likely no DB correlate; skip to operator handoff)
- ≥1 failure classified `real-regression` → continue to Step 3 (DB correlate likely)

### Step 3 — ask need-db-side

**Purpose:** Decide whether to dispatch db-investigator. Some failures are pure code regressions; some are caused by DB state drift between local and CI. Operator picks.

**Invocation:** AskUserQuestion.

> ci-investigator found $N failures: $CLASSIFICATION_SUMMARY.
> Some of these may be caused by DB-side state drift (e.g., a table got dropped, a row count diverges between local and CI). Should I dispatch db-investigator in parallel?

Options:
- "Yes — investigate DB-side" — continue to Step 4
- "No — code-only, skip DB" — skip to Step 5
- "Show me the failure list first" — print the failures, re-ask

### Step 4 — agent db-investigator

**Purpose:** Read-only DB forensics on tables the failed tests touch.

**Invocation:**
```
Agent(
  subagent_type: "db-investigator",
  prompt: <inject DYNAMIC CONTEXT>
)
```

**DYNAMIC CONTEXT:**
```
## DYNAMIC CONTEXT

**MANDATE:** Investigate whether the test failures correlate with DB-side state drift. Compare prod-PG vs test-PG (per arcis_config.yaml pg.prod_dsn_signatures vs pg.test_dsn). Look at: row counts, table ownership, recent schema changes via the capability registry.
**INVESTIGATION_MODE:** surface
**INITIAL_HYPOTHESIS:** Test fixtures may be missing tables, or test-PG snapshot is stale.
**FOCUS_TABLES:** {tables mentioned in the failed test file names — parsed from <ci_report>.failures[*].test_path}
**WORKTREE_PATH:** {pwd}
```

**Expected output:** `<db_report>` with `findings[]`.

**Decision point:**
- `findings[]` empty → continue to Step 5 (informational; no DB correlate)
- `findings[]` non-empty with severity ≥ anomaly → continue to Step 5 (compose into report)

### Step 5 — compose findings + report

**Purpose:** Merge `<ci_report>` + `<db_report>` (when present) into a unified operator-facing report. Per FA13 composition algorithm.

**Decision point:**
- Severity rollup per the algorithm in commands/operate.md.
- Each real-regression finding gets a recommendation: "open hotfix issue", "investigate commit SHA via /arcis:operate triage", or "rerun CI to confirm flaky."
- **No out-of-scope deferral:** if 5 failures classified and 3 are vacuous tests, surface ALL 3 vacuous tests with a recommendation to fix them. Do not silently defer.

### Step 6 — ask post-summary

**Purpose:** Offer to post the forensic summary as a PR comment if a TARGET_PR is set.

**Invocation:** AskUserQuestion. SKIP if TARGET_PR is null.

> ci-investigator's forensic summary can be posted as a comment on PR $TARGET_PR (repost-idempotent via SHA-256 fingerprint footer — safe to re-run).
> Post the summary now?

Options:
- "Yes — post summary" — invoke `/arcis:operate act post-pr-summary $TARGET_PR` (this is a mutation; goes through act's confirm gate, but the runbook's already-confirmed nature can pass through with single-confirm)
- "No — diagnostic only, don't post" — STOP

## Success criteria

Runbook produces:
1. A composed `<ci_report>` + `<db_report>` (when dispatched) summary to the operator
2. Each failure classified
3. Each real-regression has a recommendation
4. PR comment posted (if operator opted in) — verified via `prcomments --pr $TARGET_PR --tail 1`

## Rollback

This runbook is diagnostic-only. The only mutation is the optional PR comment post in Step 6, which is repost-idempotent (DA4 — ci-investigator's fingerprint footer prevents duplicates). Rollback = manually delete the PR comment if undesired.

## Abandonment recovery (DA9)

Predominantly read-only — see §3 Phase R3 abandonment recovery sub-section. The only mutation is Step 6's optional PR-comment post; abandonment between Step 6 mutation and its verify (`prcomments --tail 1`) triggers the standard abandonment-event write per §3.

## Escalation

- ci-investigator returns no classifications: try with `INVESTIGATION_MODE=deep` or fall back to `/arcis:operate triage "CI red — manual investigation"` with reduced scope.
- db-investigator finds schema drift: open a hotfix issue; do NOT auto-remediate (schema mutations are out of scope for this runbook).
- Multiple PRs touch the same failing test: run git-historian via `/arcis:operate triage` to identify the introducing commit.
```

### 5.3 — `runbooks/training-failed.md`

```markdown
---
name: training-failed
verb: runbook
symptom-matchers:
  - "training failed"
  - "training corpus stuck"
  - "corpus 0 examples"
  - "trainer crashed"
  - "training did not run"
  - "GGUF not produced"
required-tools:
  - processmanager
  - logtail
  - dbquery
  - tradingstate
required-agents:
  - live-monitor
  - db-investigator
expected-duration: 15-25 min
mutations: false  # diagnostic; remediation is operator-decided per finding
risk-level: low
references:
  - reference_gpu_upgrade
  - feedback_complete_efforts_no_deferral
---

# Runbook — training-failed

## When to use

The overnight training run did not produce a fresh GGUF, OR the training corpus shows <90 examples (the floor seen in #74), OR the training service exited non-zero, OR Ollama loaded the previous-day GGUF this morning.

## Prerequisites

- Operator is investigating in the morning after an overnight cycle. Live training is not currently running (training is overnight-only on dual-GPU).
- VRAM is not currently held by Ollama (or the operator accepts that Ollama may unload during investigation).

## Steps

### Step 1 — tool processmanager status (per-service, all three)

**Purpose:** Snapshot the current process state before any diagnosis.

> **Per-service invocation (FB4):** `processmanager/__main__.py:42` takes a single `service` arg per call and returns single-service JSON (`{"service": <name>, "state": ..., ...}`). There is no verified `status all` aggregator verb. Issue 3 sequential CLI calls and aggregate client-side.

**Invocation (sequential, all three services):**
```bash
python -m src.tools.processmanager status ArcisWatchLoop --json
python -m src.tools.processmanager status ArcisOllamaWatchdog --json
python -m src.tools.processmanager status ArcisDashboard --json
```

**Aggregated expected shape:** 3 separate JSON envelopes, each of shape:
```json
{"service": "ArcisWatchLoop", "state": "RUNNING", "pid": 12345, "started_at": "...", ...}
```
The runbook composes them client-side into a `{services: [...]}` virtual aggregate for downstream decision-making.

**Decision point** (evaluated against the 3-element aggregate):
- All three services `state = RUNNING` → continue to Step 2 (training is not currently active; investigate completed run)
- `ArcisWatchLoop.state = STOPPED` → BRANCH to watchloop-wedged runbook first (training depends on watch loop)
- `ArcisOllamaWatchdog.state = STOPPED` → flag; Ollama unload is part of the training cycle and stop is expected mid-cycle. But STOPPED in the morning is unexpected.

**On any one service call failing (e.g., ERROR envelope):** treat as partial snapshot — continue with the 2 services that returned successfully, surface the failed-service envelope in the report.

### Step 2 — tool logtail trainer

**Purpose:** Read the trainer's last log session to find the exit reason.

**Invocation:**
```bash
python -m src.tools.logtail --service trainer --json --lines 200
```

**Expected output:**
```json
{"lines": [{"ts": "...", "level": "ERROR|INFO", "msg": "..."}, ...]}
```

Look for: `level=ERROR` lines, `CUDA out of memory` patterns, `WinError 2`, `'str' has no attribute as_posix`, exit code in final line.

**Decision point:**
- ERROR found → record the error class, continue to Step 3
- No ERROR, but training "skipped" / "no corpus" message → continue to Step 4 (corpus issue, not crash)
- No log lines at all (trainer never started) → BRANCH: investigate scheduler — `/arcis:operate triage "trainer did not start overnight"` (dispatches live-monitor with FOCUS=ArcisWatchLoop + git-historian on scheduler.py)

### Step 3 — agent live-monitor (if crash)

**Purpose:** Cross-correlate the trainer crash with GPU state at crash time.

**Invocation:**
```
Agent(
  subagent_type: "live-monitor",
  prompt: <inject DYNAMIC CONTEXT>
)
```

**DYNAMIC CONTEXT:**
```
## DYNAMIC CONTEXT

**MANDATE:** Cross-correlate trainer crash (error: "{ERROR_CLASS_FROM_STEP_2}") with system state. Focus on GPU memory, ollama state, NSSM service state at the crash timestamp.
**FOCUS_SERVICES:** ArcisOllamaWatchdog,ArcisWatchLoop
**INCLUDE_TRADING_STATE:** false
**INCLUDE_CI_CONTEXT:** false
**WORKTREE_PATH:** {pwd}
```

**Expected output:** `<live_report>` with `correlations[]` linking crash to GPU/Ollama state.

**Decision point:**
- Correlation found → record + continue to Step 5
- No correlation → continue to Step 5 (code-level crash, not env-level)

### Step 4 — agent db-investigator (if corpus issue)

**Purpose:** Determine why corpus is small. Check shadow_trades + recommendations row counts vs expected.

**Invocation:**
```
Agent(
  subagent_type: "db-investigator",
  prompt: <inject DYNAMIC CONTEXT>
)
```

**DYNAMIC CONTEXT:**
```
## DYNAMIC CONTEXT

**MANDATE:** Determine why the training corpus has fewer rows than expected. Check the row counts and date filters for the corpus query (typically `shadow_trades` joined to `recommendations` over the last 30 days). Compare to expectation: ~900+ examples.
**INVESTIGATION_MODE:** deep
**INITIAL_HYPOTHESIS:** Date filter may be wrong, or shadow_trades has rows missing closed_at, or join is filtering out too many.
**FOCUS_TABLES:** shadow_trades,recommendations
**WORKTREE_PATH:** {pwd}
```

**Expected output:** `<db_report>` with `findings[]` explaining the corpus size.

**Decision point:** Surface findings to operator. Common patterns from #74:
- shadow_trades missing closed_at on recent rows → orphan-source bug (see `project_orphan_source_investigation`)
- Date filter applied at trainer level (not query level) → trainer-side bug
- Genuine low volume (markets closed, low recommendation count) → informational

### Step 5 — compose + report

Print the unified findings per FA13 composition. **No out-of-scope deferral** — if 3 issues found (crash + corpus + ollama state), surface all 3.

### Step 6 — ask remediation

**Purpose:** Offer the operator a remediation path based on the findings.

**Invocation:** AskUserQuestion.

> Training-failed runbook complete. $N findings surfaced.
> Top recommendation: $REC (e.g., "rerun trainer manually with `python -m src.train --confirm`", "fix orphan source bug first (issue #82)", "investigate VRAM handoff in /arcis:operate triage 'gpu degraded'")
> What now?

Options:
- "Rerun training manually" — surface the command line, do NOT execute (training is out of `act` scope in v1)
- "Open hotfix issue" — print the issue template (referencing the findings)
- "Investigate further via gpu-degraded runbook" — chain
- "Stop here — I'll act manually"

## Success criteria

Runbook produces:
1. Classification of WHY training failed (crash | corpus | not_started | success_but_no_gguf)
2. Top recommendation
3. All findings surfaced (no deferral)

## Rollback

Diagnostic-only. No mutations.

## Abandonment recovery (DA9)

Diagnostic-only — no mutations in this runbook. Abandonment recovery is a no-op (see §3 Phase R3).

## Escalation

If no findings emerge from either agent: fall back to manual log inspection. Trainer logs at `paths.logs_runtime/trainer/*.log`.
```

### 5.4 — `runbooks/gpu-degraded.md`

```markdown
---
name: gpu-degraded
verb: runbook
symptom-matchers:
  - "gpu degraded"
  - "VRAM handoff failed"
  - "nvidia-smi anomaly"
  - "nvidia-smi N/A"
  - "ollama VRAM stuck"
  - "GPU memory leak"
required-tools:
  - processmanager
  - healthprobe
  - logtail
required-agents:
  - live-monitor
expected-duration: 10-20 min
mutations: true  # may restart ArcisOllamaWatchdog
risk-level: medium
references:
  - reference_gpu_upgrade
  - feedback_no_restart_during_overnight_window
---

# Runbook — gpu-degraded

## When to use

VRAM handoff between Ollama and Trainer failed (Trainer cannot allocate GPU memory because Ollama did not unload), OR `nvidia-smi` reports `[N/A]` for memory (per `system_metrics.py` parser issue #117), OR GPU utilization is stuck at 100% with no active job, OR the dual-GPU topology shows the wrong device pinned to the wrong process.

## Prerequisites

- Operator can confirm the host has NVIDIA driver loaded (`nvidia-smi --query-gpu=name --format=csv` returns the device name).
- Current ET is outside `safety_windows.no_restart_overnight` OR operator has `--emergency`.

## Steps

### Step 1 — tool nvidia-smi capture

**Purpose:** Capture the current GPU state before any mutation.

**Invocation:**
```bash
nvidia-smi --query-gpu=index,name,memory.used,memory.total,utilization.gpu --format=csv,noheader
```

**Expected output:** N rows for N devices. Should show non-`[N/A]` memory values.

**Decision point:**
- All `[N/A]` → BRANCH: `nvidia-smi` parser issue per #117. Surface to operator; runbook cannot continue (no GPU state visibility).
- One GPU 100% memory, no Ollama process → continue to Step 2 (VRAM leak)
- All GPUs free, but Trainer reports OOM → continue to Step 3 (driver-level issue, not allocation)
- Healthy state → STOP. Runbook does not apply.

### Step 2 — agent live-monitor

**Purpose:** Cross-correlate VRAM state with Ollama process state.

**Invocation:**
```
Agent(
  subagent_type: "live-monitor",
  prompt: <inject DYNAMIC CONTEXT>
)
```

**DYNAMIC CONTEXT:**
```
## DYNAMIC CONTEXT

**MANDATE:** Diagnose VRAM handoff state. Is Ollama holding VRAM it shouldn't? Is the watchdog stale? Cross-correlate ollama process PID, nvidia-smi memory.used per device, and the heartbeat file.
**FOCUS_SERVICES:** ArcisOllamaWatchdog
**INCLUDE_TRADING_STATE:** false
**INCLUDE_CI_CONTEXT:** false
**WORKTREE_PATH:** {pwd}
```

**Expected output:** `<live_report>` with `service_state[0]` for ArcisOllamaWatchdog (with `composite_verdict ∈ {healthy, degraded, unhealthy, unknown}`) and `correlations[]` describing the handoff state. The runbook composes the "VRAM-stuck" condition from `service_state` + `correlations` + the GPU evidence captured in Step 1.

**Decision point** (composed from `service_state[0].composite_verdict`, correlation types, and Step 1 nvidia-smi data):
- VRAM held by Ollama (Step 1) AND watchdog is **wedged-equivalent** (`composite_verdict = "unhealthy" AND any(c.type == "heartbeat_stale" for c in correlations)`) → continue to Step 3 (restart needed)
- VRAM held by Ollama (Step 1) AND `composite_verdict = "healthy"` (no stale-heartbeat correlation) → this is normal (model is loaded). Likely the operator's "leak" perception is wrong. Surface this and STOP.
- VRAM NOT held by Ollama (Step 1), but trainer can't allocate → ESCALATE (driver-level issue, not VRAM-handoff)

### Step 3 — ask confirm-restart-ollama-watchdog

**Purpose:** Operator approval gate before restarting ArcisOllamaWatchdog (which kills Ollama and releases VRAM per the v0.36.24 hotfix path).

**Invocation:** AskUserQuestion. Subject to Safety Window Gate.

> live-monitor confirms VRAM is held by Ollama with watchdog wedged (last heartbeat $AGE).
> Current ET: $NOW_ET.
> Proposed action: `python -m src.tools.processmanager restart ArcisOllamaWatchdog --confirm --json`
> This will: kill Ollama → release VRAM → restart the watchdog → re-load the model.
> Verify after: `nvidia-smi` shows VRAM freed; healthprobe shows watchdog RUNNING.
> Proceed?

Options:
- "Approve — restart Ollama watchdog" — continue to Step 4
- "Cancel" — STOP

If in safety window AND not emergency: REFUSE per Safety Window Gate.

### Step 4 — act restart-ollama-watchdog

**Invocation:** `/arcis:operate act restart-ollama-watchdog` (inherits incident id).

Under the hood: `python -m src.tools.processmanager restart ArcisOllamaWatchdog --confirm --json`.

**Expected output:** Success envelope (FA8 shape).

**Decision point:**
- Success → continue to Step 5
- Error → escalate

### Step 5 — verify nvidia-smi

**Purpose:** Confirm VRAM was actually freed. Don't trust the process restart alone — the VRAM matter is what the operator cares about.

**Invocation:**
```bash
nvidia-smi --query-gpu=index,memory.used --format=csv,noheader
```

Compare to Step 1 baseline. Expected: memory.used drops by ≥4GB on the device Ollama was using.

**Decision point:**
- VRAM freed (delta ≥ 4GB) → continue to Step 6
- VRAM NOT freed → ESCALATE. Possibly a leaked GPU context (driver-level); recommend host reboot.

### Step 6 — verify ollama healthprobe

**Invocation:**
```bash
python -m src.tools.healthprobe --service ArcisOllamaWatchdog --json
```

**Expected output:** `{"service": "ArcisOllamaWatchdog", "state": "RUNNING", "heartbeat_age_s": <60, "passed": true}`.

**Decision point:**
- Pass → SUCCESS. Runbook complete.
- Fail → ESCALATE.

## Success criteria

1. nvidia-smi reports the expected idle memory level (per topology)
2. ArcisOllamaWatchdog healthprobe passes
3. Trainer (if re-attempted) can allocate VRAM successfully — this is NOT verified in this runbook; trainer is its own concern

## Rollback

Restarting the watchdog is non-destructive. If the restart somehow leaves Ollama in a worse state (no model loaded, repeated crash loop), rollback = stop the watchdog (`python -m src.tools.processmanager stop ArcisOllamaWatchdog --confirm`) and investigate manually.

## Abandonment recovery (DA9)

If the operator cancels or the AskUserQuestion at Step 3 times out AFTER Step 4 (`act restart-ollama-watchdog`) has executed but BEFORE Steps 5+6 (verify nvidia-smi + verify ollama healthprobe) have completed — i.e., the watchdog restart fired but verification didn't:

1. Orchestrator MUST attempt Step 5 (`nvidia-smi`) AND Step 6 (`healthprobe --service ArcisOllamaWatchdog --json`) on a best-effort basis, time-boxed to 60 seconds combined.
2. Capture both verify results.
3. Write `arcis_operate.runbook.gpu-degraded.abandoned_after_mutation` event with `last_mutation="Step 4 restart-ollama-watchdog"`, `verify_result=<step-5 + step-6 combined>`, `step=5`.
4. On next `/arcis:operate status` invocation in the next 24h, prompt operator to re-verify before continuing.

## Escalation

- VRAM persistently held after restart: driver-level leak. Recommend host reboot (out of skill scope).
- nvidia-smi `[N/A]` persists: issue #117 hotfix needed. Surface this AND open a hotfix issue.
- Watchdog won't start: investigate `paths.logs_service/ollama_watchdog/*.log` directly.
```

### 5.5 — `runbooks/data-anomaly.md`

```markdown
---
name: data-anomaly
verb: runbook
symptom-matchers:
  - "data anomaly"
  - "row count drift"
  - "orphan FK"
  - "missing table"
  - "shadow trades missing"
  - "recommendations missing"
  - "macro_snapshots gap"
  - "duplicate rows"
required-tools:
  - dbquery
  - capabilityregistry
  - logtail
required-agents:
  - db-investigator
expected-duration: 10-20 min
mutations: false  # diagnostic; remediation = operator-issued hotfix
risk-level: low
references:
  - project_orphan_source_investigation
  - feedback_complete_efforts_no_deferral
---

# Runbook — data-anomaly

## When to use

A table-level anomaly observed: row count drift between prod-PG and registry expectation, orphan FK rows (shadow_trades referencing non-existent recommendations), missing collector tables (Finnhub dead-weight per #71), duplicate rows (the macro_snapshots dedupe issue #52), date gaps.

## Prerequisites

- Operator can name the affected table(s) OR the anomaly type. If neither, the runbook starts by listing all tables and asking.

## Steps

### Step 1 — ask which-anomaly

**Purpose:** Scope the investigation to specific tables. Avoid scanning all 80+ tables for every invocation.

**Invocation:** AskUserQuestion if `RUNBOOK_ARG[1]` not provided.

> Which data anomaly should this runbook investigate?

Options:
- "Specific table(s) — name them" — sub-prompt for table names
- "Orphan FK forensics" — set INVESTIGATION_HYPOTHESIS = orphan_fk
- "Row count drift vs registry" — set INVESTIGATION_HYPOTHESIS = registry_drift
- "Missing collector tables" — set INVESTIGATION_HYPOTHESIS = collector_missing
- "Duplicate rows" — set INVESTIGATION_HYPOTHESIS = duplicates
- "I'm not sure — surface a summary first" — set INVESTIGATION_HYPOTHESIS = broad_surface

### Step 2 — agent db-investigator

**Purpose:** Read-only forensics on the scoped tables.

**Invocation:**
```
Agent(
  subagent_type: "db-investigator",
  prompt: <inject DYNAMIC CONTEXT>
)
```

**DYNAMIC CONTEXT:**
```
## DYNAMIC CONTEXT

**MANDATE:** Investigate the data anomaly. Type: {INVESTIGATION_HYPOTHESIS}. Tables: {FOCUS_TABLES if provided else null}. Read-only — no DML, no schema changes.
**INVESTIGATION_MODE:** {deep if INVESTIGATION_HYPOTHESIS != broad_surface else surface}
**INITIAL_HYPOTHESIS:** {derived from operator selection}
**FOCUS_TABLES:** {list or null for broad}
**WORKTREE_PATH:** {pwd}
```

**Expected output:** `<db_report>` with `findings[]`.

**Decision point:**
- `findings[]` empty → STOP. No anomaly found at this depth. Suggest deepening: rerun with `INVESTIGATION_MODE=deep` if surface yielded nothing, OR investigate manually.
- `findings[]` populated → continue to Step 3

### Step 3 — compose + categorize findings

**Purpose:** Group findings by remediation class.

**Decision point:** For each finding, categorize:

- **A. Schema-fixable** (missing index, wrong column type, missing FK) → recommendation: open hotfix issue
- **B. Backfill-fixable** (orphan rows, date-gap rows missing from collector) → recommendation: write backfill script (operator's pattern: mark-attempted + batch commits ≥50 per `feedback_backfill_patterns`)
- **C. Upstream-source bug** (e.g., orphan-source investigation #82) → recommendation: investigate upstream
- **D. Informational only** (row count is low but expected — markets closed, low volume) → no action

**No out-of-scope deferral** — if 5 findings, surface all 5 categorized. Even if only 2 are "real" issues by operator's standard, list the 3 informational ones.

### Step 4 — ask backfill-now

**Purpose:** Offer to draft a backfill script for B-class findings. Drafting is out of scope; we surface the pattern only.

**Invocation:** AskUserQuestion if any B-class finding.

> $N findings are backfill-class. Backfill scripts are written by the operator (see `feedback_backfill_patterns`: mark-attempted '{}' not NULL + batch commits ≥50 rows).
> Should I print the backfill skeleton for the most-affected table?

Options:
- "Yes — print skeleton" — print a Python skeleton matching the operator's backfill pattern
- "No — I'll write it manually" — continue to Step 5
- "Skip — no backfill needed" — continue to Step 5

### Step 5 — operator-facing report

```
DATA-ANOMALY $INCIDENT_ID — INVESTIGATION COMPLETE
Hypothesis: $HYPOTHESIS
Tables investigated: $FOCUS_TABLES
Findings ($N total):

[A-class: schema] $N
  1. ...

[B-class: backfill] $N
  1. ...

[C-class: upstream] $N
  1. ...

[D-class: informational] $N
  1. ...

Recommendations:
  A-class → open hotfix issue (use issue template above)
  B-class → write backfill script (skeleton printed above if requested)
  C-class → /arcis:operate triage "<upstream symptom>"
  D-class → no action
```

## Success criteria

1. db-investigator returned a `<db_report>` with `findings[]` populated OR empty + `coverage_assessment` informative
2. All findings categorized
3. All findings surfaced — no deferral

## Rollback

Diagnostic-only. No mutations.

## Abandonment recovery (DA9)

Diagnostic-only — no mutations in this runbook. Abandonment recovery is a no-op (see §3 Phase R3).

## Escalation

- db-investigator returns no findings but operator believes there is an issue: rerun with `INVESTIGATION_MODE=deep`.
- Operator wants to remediate via schema mutation: out of skill scope. Open a hotfix issue + use `/arcis:code` with a spec.
- Cross-table anomaly (multiple tables affected, complex correlation): fall back to /arcis:operate triage with broader scope.
```

---

## 6. Safety Window Enforcement (skill-layer)

### Mechanism

Per FA9 (`src/tools/_safety.py:239-255`), the canonical safety-window evaluator is `_in_window()` — inclusive-start, exclusive-end, supports cross-midnight windows. The current `no_restart_overnight` window is 21:30–22:30 ET (`config/arcis_config.yaml:118-128`).

The skill **does not import Python** (skill is markdown-only per the constraint). The skill therefore cannot directly call `_in_window()`. Three viable mechanisms exist:

**Option A — TZ='America/New_York' date + hardcoded HH:MM compare (RECOMMENDED).**
```bash
TZ='America/New_York' date '+%H:%M'
```
Skill prose hardcodes the comparison: `if 21:30 <= HH:MM < 22:30 then IN WINDOW`. Cheap, no Python subprocess, no PYTHONPATH concerns.

**Option B — Subprocess Python one-liner reading the YAML.**
```bash
python -c "from src.tools._safety import _now_et, _in_window; from src.tools._config import load_arcis_config; cfg = load_arcis_config(); w = cfg.safety_windows['no_restart_overnight']; print('IN' if _in_window(_now_et(), w.start_et, w.end_et) else 'OUT')"
```
Authoritative — reads the same YAML as the decorator. Adds ~200ms per check. Requires PYTHONPATH to include repo root (which is guaranteed if running from `pwd = repo root` per Step 0.2).

**Option C — Call HealthProbe with a `--check-safety-window` flag (not currently supported).**
Would require a tool-side change (out of scope for #109).

### Decision

**Option A (hardcoded compare in skill prose).** Rationale (DD7):

1. **Performance:** Status verb must return <30s; safety gate must not add noticeable latency. Option A is <1ms; Option B is ~200ms; multiplied across N gates per incident, this adds up.
2. **No-Python in skill:** Option B violates the markdown-only constraint by requiring a Python subprocess for safety-gate evaluation. The defense-in-depth principle holds: the tool-layer decorator is the authoritative source; the skill-layer check is UX.
3. **Drift risk acknowledged:** if the operator changes the YAML window times, BOTH the skill prose (`commands/operate.md` Safety Window Gate section) AND the YAML must be updated. The tool-layer decorator picks up the YAML change automatically; the skill is a UX pre-check. **The implementing PM must add a comment in `commands/operate.md` Safety Window Gate section noting the drift risk and pointing to `config/arcis_config.yaml:118-128` as the source-of-truth.**

### Exact refuse prose (verbatim in commands/operate.md)

```
REFUSE — safety_windows.no_restart_overnight active.
  Current ET: $NOW_ET
  Window: 21:30–22:30 (no_restart_overnight)
  Reason: mid-cycle restart forces a redundant overnight re-launch (memory: feedback_no_restart_during_overnight_window)

Options:
  1. Wait until 22:30 ET and re-run the same command.
  2. Re-run with --emergency if this is a genuine emergency. You will be asked to confirm.

No mutation attempted. No audit event for mutation written.
```

### --emergency override flow

When `EMERGENCY = true` AND in-window:

1. AskUserQuestion (BLOCKING — single confirm):

   > You are bypassing safety_windows.no_restart_overnight (21:30–22:30 ET).
   > Current ET: $NOW_ET. The window exists because mid-cycle restart forces a redundant overnight re-launch from scratch (incident 2026-05-18 v0.36.22 deploy).
   > Action to execute: $PROPOSED_ACTION
   > Proceed with emergency override?
   
   Options:
   - "No — wait until 22:30 ET" → STOP + `arcis_operate.<verb>.emergency_denied` audit
   - "Yes — emergency override" → proceed; set `EMERGENCY_OVERRIDE_CONFIRMED = true`

2. The skill then proceeds to verb-specific phases. The tool-layer `--emergency` flag is passed down. The decorator stack writes `success` with `params.emergency = true` for grep-ability.

### Coverage caveat for implementing PM

**The skill-layer pre-check uses hardcoded 21:30–22:30; the YAML is the authoritative source.** If the YAML changes, the skill prose must change. Two safeguards:

1. The tool-layer decorator (`@safety_window`) reads the YAML at runtime and is always authoritative — if the YAML changes and the skill prose lags, the tool will still refuse (decorator is the floor, skill is the UX ceiling).
2. The implementing PM must add a comment in `commands/operate.md` Safety Window Gate section: `<!-- DRIFT RISK: hardcoded 21:30-22:30 must match config/arcis_config.yaml:safety_windows.no_restart_overnight. Update both. -->`.

### Worked example — long-running act crossing 21:30 (DA1 verification)

**Scenario:** Operator invokes `/arcis:operate act restart-watchloop --emergency` at 21:28 ET. Step 0.1 captures `NOW_ET = "2026-05-25 21:28 EDT"` (outside window).

The act phase runs:
- A1 resolve action (instant)
- A2 dry-run preview (calls `processmanager restart ... --json` without --confirm) — takes 90s due to a slow service-state probe
- A3 SAFETY WINDOW GATE entry at **21:31 ET** (90s of A2 has elapsed since Step 0.1)

**Without the fix (stale capture):** A3 reads stale `NOW_ET = "21:28 EDT"` (outside window) → gate passes → restart fires inside window → operator's evening cycle disrupted.

**With the fix (re-capture at gate entry):** A3 runs the Python one-liner fresh:
```bash
NOW_ET_GATE=$(python -c "import os, datetime; from zoneinfo import ZoneInfo; o=os.environ.get('ARCIS_NOW_ET_OVERRIDE'); now=datetime.datetime.fromisoformat(o) if o else datetime.datetime.now(ZoneInfo('America/New_York')); print(now.strftime('%Y-%m-%d %H:%M %Z'))")
# NOW_ET_GATE = "2026-05-25 21:31 EDT"
```
21:31 ≥ 21:30 → IN WINDOW. Operator passed `--emergency`, so the gate fires the emergency-confirm prompt: `"You are bypassing safety_windows.no_restart_overnight (21:30–22:30 ET). Current ET: 2026-05-25 21:31 EDT. ..."` The operator sees the override prompt at the actual current time, not the stale 21:28 capture, and confirms with full knowledge of the in-window status.

**Test seam (per §12 item 3):** `ARCIS_NOW_ET_OVERRIDE=2026-05-25T21:31:00-04:00` env var feeds the Python one-liner deterministically, so the fix is unit-testable.

---

## 7. Action Authorization Matrix

Source-of-truth: `.claude/plugins/arcis/skills/operate/references/action-authorization-matrix.md`.

The orchestrator (`commands/operate.md`) reads this file at Phase A1 to resolve action names. Each row defines:

- `action`: the operator-facing name passed as `POSITIONAL_INPUT[1]`
- `auth_class`: one of {`auto-approved`, `confirm`, `confirm+safety_window`, `emergency-only-in-window`}
- `cli_invocation`: the verbatim tool call (orchestrator substitutes args)
- `verify_step`: post-execution verification (orchestrator runs after success)
- `risk_level`: low | medium | high (operator-facing context only)
- `notes`: short prose explaining when to use

### Full v1 matrix

> **Verification status column (FB3):** values `{verified, unverified-presumed, removed}`. `verified` = CLI shape directly confirmed against the codebase by the architect at spec time. `unverified-presumed` = CLI is presumed at spec time and MUST be verified by the implementing PM via `python -m src.tools.<name> --help` at impl start; if the tool/verb doesn't exist the row is `removed` (and the action is DROPPED from any v1 runbook that referenced it — see §14 OQ#2/3/4). Rows prefixed `[UNVERIFIED — see §14 OQ#N]` are flagged for the implementer at a glance.

| Action | Verification | Auth class | CLI invocation | Verify step | Risk | Notes |
|---|---|---|---|---|---|---|
| `status-snapshot` | verified | auto-approved | per-service: `python -m src.tools.processmanager status <ArcisWatchLoop\|ArcisOllamaWatchdog\|ArcisDashboard> --json` (composed in Phase S1, FB4 per-service pattern) | none (read-only) | low | Operator's "first thing I run." Same as `/arcis:operate status`. |
| `restart-watchloop` | verified | confirm+safety_window | `python -m src.tools.processmanager restart ArcisWatchLoop --confirm --json` | `python -m src.tools.healthprobe --service ArcisWatchLoop --json` | medium | Restart the watch loop NSSM service. Honors overnight window. |
| `restart-ollama-watchdog` | verified | confirm+safety_window | `python -m src.tools.processmanager restart ArcisOllamaWatchdog --confirm --json` | `python -m src.tools.healthprobe --service ArcisOllamaWatchdog --json` + `nvidia-smi --query-gpu=memory.used --format=csv,noheader` | medium | Restart the Ollama watchdog — frees VRAM as side effect. |
| `restart-dashboard` | verified | confirm+safety_window | `python -m src.tools.processmanager restart ArcisDashboard --confirm --json` | `python -m src.tools.healthprobe --service ArcisDashboard --json` | low | Restart dashboard. Lowest-risk of the 3 services. |
| **[UNVERIFIED — see §14 OQ#4]** `post-pr-summary <pr>` | unverified-presumed | confirm | `python -m src.tools.ci_summary_post --pr <pr> --confirm --json` (presumed CLI of ci-investigator's mutation path; check at impl time) | `python -m src.tools.prcomments --pr <pr> --tail 1 --json` (verify post landed) | low | Repost-idempotent per DA4 fingerprint. **REMOVE row + drop action from runbooks if CLI does not exist at impl start.** |
| `verify-nvidia-smi` | verified | confirm | `nvidia-smi --query-gpu=index,name,memory.used,memory.total --format=csv,noheader` | (re-run; verify no [N/A]) | low | Sanity check the parser fix from #117. |
| **[UNVERIFIED — see §14 OQ#2]** `force-broker-poll` | unverified-presumed | confirm+safety_window | `python -m src.tools.processmanager force-broker-poll --confirm --json` (presumed CLI; verify at impl) | `python -m src.tools.tradingstate --json` | medium | Force the watch loop to refresh broker state out-of-cycle. **REMOVE row + drop action from runbooks if CLI does not exist at impl start.** |
| **[UNVERIFIED — see §14 OQ#3]** `regenerate-stale-audit` | unverified-presumed | confirm | `python -m src.tools.auditor --regenerate --confirm --json` (presumed CLI; verify at impl) | `python -m src.tools.dbquery --select "SELECT max(generated_at) FROM audit_reports" --json` | low | Two-layer staleness mitigation per `feedback_hotfix_deploy_two_layer_staleness`. **REMOVE row + drop action from runbooks if CLI does not exist at impl start.** |

### Implementing PM verification

For actions where the CLI invocation is marked "presumed" above (`post-pr-summary`, `force-broker-poll`, `regenerate-stale-audit`), the implementing PM MUST verify the exact tool CLI shape at impl time by running `python -m src.tools.<name> --help` and updating the matrix file. If a tool does NOT have a CLI for that action (e.g., `regenerate-stale-audit` may not have an existing CLI handle), the action is REMOVED from the v1 matrix and flagged in §14.

**Auto-approved actions** skip the Safety Window Gate. Only `status-snapshot` qualifies in v1. Everything else requires explicit operator confirm.

**Emergency-only-in-window** is a runtime marker, not a separate row — it's applied to any `confirm+safety_window` action when EMERGENCY=true AND in-window.

---

## 8. Cross-Agent Finding Composition

When the triage verb dispatches 2+ agents (e.g., live-monitor + db-investigator + ci-investigator), or when a runbook composes multiple agent outputs (`pg-tests-red.md` composes `<ci_report>` + `<db_report>`), the orchestrator must merge findings into a single operator-facing report.

### Algorithm (per FA13)

**Phase 1 — Collect:**

```pseudo
all_findings = []
for agent in dispatched_agents:
    report_tag = "<{agent}_report>"
    parsed = parse_tagged_json(agent_output, report_tag)
    if parsed is None:
        all_findings.append({
            "source": agent,
            "severity": "must_fix",
            "type": "agent_dispatch_failure",
            "title": "Agent " + agent + " did not return a parseable " + report_tag,
            "evidence": agent_output[:200] + " [truncated]" if len(agent_output) > 200 else "",
            "confidence": "high",
        })
        continue
    for finding in parsed.findings or parsed.failures or parsed.correlations:
        all_findings.append({
            "source": agent,
            "severity": finding.severity,
            "type": finding.type,
            "title": finding.title,
            "evidence": finding.evidence,
            "confidence": finding.confidence,
            "raw": finding,
        })
```

**Phase 2 — Dedup:**

Two findings are duplicates if they share `(canonical_target, defect_type)`:

- `canonical_target` = table name | symbol name | file path | service name (extracted from finding.target field if present, else from title via regex)
- `defect_type` = the finding's `type` field (e.g., "heartbeat_stale", "row_count_drift", "vacuous_test")

When duplicates detected:
- Merge into a single finding
- Combine `evidence_sources[]` (preserve both source agents)
- Take the HIGHER of the two severities
- Take the HIGHER of the two confidences

**Phase 3 — Severity rollup:**

```pseudo
if any(f.severity == "must_fix" for f in all_findings):
    incident_severity = "critical"
elif any(f.severity == "anomaly" for f in all_findings):
    incident_severity = "degraded"
elif all(f.severity == "informational" for f in all_findings) or len(all_findings) == 0:
    incident_severity = "clear"
```

**Phase 4 — Ordering:**

Sort by:
1. Severity descending (must_fix > anomaly > informational)
2. Confidence descending (high > medium > low)
3. Source priority: live > db > ci > git (live is the snapshot, comes first on ties)

**Phase 5 — Recommendation synthesis:**

For each of the top 3 findings:
1. Check the 5 runbook frontmatters' `symptom-matchers` for a match against `finding.title + finding.evidence`. If matched, recommend `/arcis:operate runbook <name>`.
2. Else, check the Action Authorization Matrix for a relevant `act <action>`. If matched, recommend `/arcis:operate act <action>`.
3. Else, recommend "no automated remediation available — investigate manually" + a suggested next-triage symptom.

### Worked example

Symptom: `"trades stopped firing this morning"`.

Dispatched: live-monitor + db-investigator (DOMAIN=data).

Agents return:

- `<live_report>`: `correlations[]` = [{"severity": "anomaly", "type": "broker_poll_lag", "target": "ArcisWatchLoop", "title": "last_broker_poll 32min ago"}, {"severity": "informational", "type": "nvidia_state", "target": "GPU0", "title": "VRAM 6GB/24GB"}]
- `<db_report>`: `findings[]` = [{"severity": "must_fix", "type": "missing_recent_rows", "target": "shadow_trades", "title": "no shadow_trades rows in last 30min"}, {"severity": "anomaly", "type": "row_count_drift", "target": "recommendations", "title": "30min gap in recommendations vs 7-day median"}]

**Compose:**

1. Dedup: live's broker_poll_lag and db's missing_recent_rows share canonical target adjacency (broker → shadow_trades) but different types → no dedup. Both preserved.
2. Severity rollup: db has must_fix → `incident_severity = critical`.
3. Order: db.missing_recent_rows (must_fix) → live.broker_poll_lag (anomaly) → db.row_count_drift (anomaly) → live.nvidia_state (informational).
4. Recommendations:
   - Top: matches `data-anomaly` runbook → recommend `/arcis:operate runbook data-anomaly`
   - 2nd: matches `watchloop-wedged` runbook (broker_poll_lag IS a watch-loop symptom) → recommend `/arcis:operate runbook watchloop-wedged`
   - 3rd: same as top — same runbook recommended

The operator-facing report lists ALL 4 findings (per no-out-of-scope-deferral), with top-2 distinct runbook recommendations highlighted at the bottom.

---

## 9. Audit Trail

Two layers of audit, both writing to `data/logs/tool-execution.log` (the canonical log per FA10).

### Layer 1 — Inherited per-tool events (FREE)

Every `python -m src.tools.<name> --json` subprocess writes 1+ events automatically via the `@safe_op` / `@safety_window` / `@prod_guard` decorator stack. Schema per FA10 (`src/tools/_execution_log.py:161-198`):

```json
{
  "timestamp": "2026-05-25T14:32:01.123456-04:00",
  "tool_name": "processmanager.restart",
  "params": {"service": "ArcisWatchLoop", "confirm": true},
  "result": "success",
  "duration_ms": 8200,
  "session_id": null
}
```

`session_id` will be NULL unless the orchestrator propagates it. **See §9.3 for the propagation strategy.**

### Layer 2 — Skill-level bracketing events (NEW)

The orchestrator writes its own events at verb start and verb end. These are the operator's grep-handle for reconstructing an incident timeline.

**Event types written by the skill:**

| Event tool_name | When | params shape |
|---|---|---|
| `arcis_operate.<verb>.start` | At Step 0.3 (skip for status) | `{"positional": [...], "flags": {...}}` |
| `arcis_operate.triage.cancelled` | Operator cancels at AskUserQuestion T2 | `{"reason": "operator_cancel_at_T2", "prompt_hash": "<sha256>", "option_text": "Cancel — abort triage"}` |
| `arcis_operate.triage.recheck_result` | Phase T4.5 (DA5) | `{"recheck_evidence": "...", "downgrade_applied": bool, "recheck_skipped": bool}` |
| `arcis_operate.triage.completed` | Phase T7 | `{"symptom": "...", "domain": "...", "dispatch_list": [...], "severity": "...", "finding_count": N, "chained_to": "..."}` |
| `arcis_operate.act.unknown_action` | Phase A1 fail | `{"action_name": "..."}` |
| `arcis_operate.act.<action>.confirmed` | Operator approves at A4 (DA8) | `{"action": "...", "prompt_hash": "<sha256 of prompt prose>", "option_text": "Approve — execute", "inherited_from_runbook": bool}` |
| `arcis_operate.act.cancelled` | Operator cancels at A4 | `{"action": "...", "reason": "operator_cancel", "prompt_hash": "<sha256>", "option_text": "Cancel"}` |
| `arcis_operate.act.cancelled_state_changed` | Phase A5.1 re-approve denied (DA10) | `{"action": "...", "a2_preview": "...", "a5_preview": "...", "diff": "..."}` |
| `arcis_operate.act.dry_run` | DRY_RUN=true | `{"action": "...", "planned_cmd": "..."}` |
| `arcis_operate.act.<action>.completed` | Phase A7 | `{"result": "success\|tool_error\|verify_failed", "elapsed_s": ..., "evidence_ref": "..."}` |
| `arcis_operate.<verb>.safety_window_refused` | In-window without emergency | `{"window": "no_restart_overnight", "now_et": "..."}` |
| `arcis_operate.<verb>.emergency_denied` | Operator denies emergency override | `{"prompt_hash": "<sha256>", "option_text": "No — wait until 22:30 ET"}` |
| `arcis_operate.runbook.unknown` | Unknown runbook name | `{"runbook_name": "..."}` |
| `arcis_operate.runbook.<name>.confirm_contract_failed_at_step_<N>` | DA2 contract failure at step N | `{"step": N, "failed_requirement": "(i)\|(ii)\|(iii)\|(iv)\|(v)", "detail": "..."}` |
| `arcis_operate.runbook.<name>.abandoned_after_mutation` | DA9 mid-runbook cancel/timeout after mutation | `{"last_mutation": "<step description>", "verify_result": "pass\|fail\|attempted_but_timed_out", "step": N}` |
| `arcis_operate.runbook.<name>.completed` | Runbook all-steps-done | `{"step_count": N, "elapsed_s": ..., "result": "completed"}` |
| `arcis_operate.runbook.<name>.escalated_at_step_<N>` | Runbook escalation | `{"step": N, "reason": "..."}` |

**prompt_hash + option_text (DA8 fix):** Every event with `*.confirmed | *.cancelled | *.completed | *.emergency_denied` MUST include `prompt_hash` (SHA-256 hex digest of the prompt prose shown to operator) AND `option_text` (verbatim string of the option operator selected). Computed via:

```bash
PROMPT_HASH=$(printf '%s' "$PROMPT_PROSE" | python -c "import hashlib,sys; print(hashlib.sha256(sys.stdin.read().encode()).hexdigest())")
```

This is the immutable record that closes post-incident disputes ("I never approved that restart").

### Layer 2 — Skill-side write mechanism (DA3 fix — JSON-injection safe)

The skill cannot import Python directly. The naive `python -c "...$PARAMS_JSON..."` form is REJECTED — operator-typed symptom strings containing single-quote / backtick / dollar-sign / newline corrupt the inline-JSON interpolation and may allow shell injection. v1 uses a stdin-driven CLI wrapper that JSON-escapes every operator-typed input:

**Step 1 — JSON-escape every operator-typed string field BEFORE building $PARAMS_JSON.** On any platform with jq:

```bash
ESCAPED_SYMPTOM=$(printf '%s' "$RAW_SYMPTOM" | jq -Rs .)
ESCAPED_ACTION=$(printf '%s' "$RAW_ACTION" | jq -Rs .)
# ... one ESCAPED_* per raw string field
```

If `jq` is unavailable (Windows default), substitute Python `json.dumps`:

```bash
ESCAPED_SYMPTOM=$(printf '%s' "$RAW_SYMPTOM" | python -c "import json,sys; print(json.dumps(sys.stdin.read()))")
```

This escape step is MANDATORY for every operator-typed input that appears in audit params. Skipping is a DA3-class defect.

Example: a symptom `she said "it's broken" $(rm -rf /)` becomes the JSON literal `"she said \"it's broken\" $(rm -rf /)"` — the dollar-sign-substitution string is now data, not shell.

**Step 2 — Write the event via stdin-driven CLI.** Build $PARAMS_JSON from the escaped fields and pipe to a CLI entry point that reads JSON from stdin:

```bash
printf '%s' "$PARAMS_JSON" | python -m src.tools._execution_log_writer \
  --tool-name "$EVENT_NAME" \
  --session-id "$INCIDENT_ID" \
  --result success \
  --duration-ms 0 \
  2>/dev/null \
  || { echo "WARNING: audit log write failed (non-blocking, may indicate input corruption — see §10.9)" >&2; }
```

**Implementing PM action (per §14 OQ#7):** if `src/tools/_execution_log_writer` CLI entry point does NOT exist at impl time, add a ~6-line CLI wrapper to `src/tools/_execution_log.py` exposing `write_event()` via stdin-JSON. This is in-scope for #109 (it is a defect-blocker, not a new feature). Surface in PR description with the wrapper diff.

Failure of an audit write is NON-BLOCKING for verb progression. BUT — unlike the prior spec — failure now triggers a VISIBLE WARNING to the operator (§10.9 envelope), not just stderr drop. A failed audit write may signal input corruption (and therefore an unescaped operator string slipping through Step 1).

### Per-incident grepability

To reconstruct an incident timeline:

```bash
jq -c "select(.session_id == \"$INCIDENT_ID\")" data/logs/tool-execution.log
```

This returns ALL events (Layer 1 + Layer 2) tagged with that incident's session_id, sorted by line order = timestamp order.

### Per-incident timeline file (NOT used in v1) — DA14 operator-confirmed

Per-incident JSONL files at `data/logs/incidents/` — **DECIDED AGAINST** (DD11). **Operator approved 2026-05-26 via AskUserQuestion** (architect-recommended pattern over the requirements.md MUST). The requirements.md MUST is **formally superseded by DD11**. Reconstruct incidents via:

```bash
jq -c 'select(.session_id == "<incident-id>")' data/logs/tool-execution.log
```

The spec considered a separate `data/logs/incidents/<timestamp>.jsonl` file per FA10 alternative. Operator-confirmed rejection rationale:

- FA10 explicitly notes the operator's "single answer to where do I find logs" preference (line 8 of `_execution_log.py` docstring)
- Rotation policy already exists for `tool-execution.log` (10MB → .1); a new directory adds operational complexity (no rotation, manual cleanup)
- session_id-keyed grep accomplishes the same goal
- DD20 (below) records the operator override of the requirements.md MUST

**Implementing PM should NOT create `data/logs/incidents/`.** The single-file pattern wins.

### session_id propagation gap (Open Question, see §14)

`_execution_log.write_event` accepts `session_id` as a kwarg, but `_cli_envelope.run_cli` (the standard CLI wrapper) does NOT currently read `ARCIS_SESSION_ID` env var and pass it down. This means Layer 1 (per-tool) events will have `session_id=null` for tools invoked from this skill.

**v1 workaround:** The skill writes its own bracketing events with session_id populated. Layer 1 events without session_id remain greppable by timestamp + tool_name within the bracket pair.

**Post-v1:** A one-line patch to `_cli_envelope.run_cli` to read `os.environ.get("ARCIS_SESSION_ID")` and pass to `write_event` would close this gap. **Flagged in §14.**

---

## 10. Error Envelopes

Every failure class has a defined operator-facing shape. Stored in `references/error-envelopes.md` for orchestrator reference.

### 10.1 — Verb unknown

**Trigger:** `POSITIONAL_INPUT[0]` not in {triage, act, status, runbook}.

**Output:**
```
ERROR — unknown verb: "<received>". Expected one of: triage, act, status, runbook.
Usage:
  /arcis:operate triage "<symptom>"           — investigate (no mutations)
  /arcis:operate act <action> [args]          — execute mutation with confirm
  /arcis:operate status [service]             — read-only health snapshot
  /arcis:operate runbook <name> [--dry-run]   — run a named flow
```

**Audit:** NO event (no incident).
**Exit:** Skill stops immediately.

### 10.2 — Tier 3 tool unavailable

**Trigger:** `python -m src.tools.<name> --help` returns non-zero (tool not yet shipped per #107).

**Output (inline in verb output, NOT a hard error):**
```
Tool <name> not yet shipped, gated on #107 — skipping <step description>.
Surfacing partial findings only.
```

**Audit:** `arcis_operate.<verb>.tier3_degraded` event with `params.missing_tools = [...]`.
**Exit:** Skill continues with remaining tools.

### 10.3 — Safety window block (no emergency)

**Trigger:** Mutation verb, in-window, EMERGENCY=false.

**Output:** Verbatim REFUSE prose from §6.

**Audit:** `arcis_operate.<verb>.safety_window_refused` event.
**Exit:** Skill stops; no tool invocation.

### 10.4 — Agent dispatch failure

**Trigger:** Agent returns no `<*_report>` tag, or Agent tool errors.

**Output (within composed findings):**
```
[must_fix] Agent <name> did not return a parseable <name>_report.
Source: orchestrator
Evidence: <first 200 chars of agent output> [truncated]
Confidence: high
Recommendation: Re-run /arcis:operate triage with this agent slate manually, or investigate the agent's golden test.
```

**Audit:** Surfaced in the composed report; the agent's MaxTurns / error is logged by the agent dispatcher itself (out of skill scope).
**Exit:** Skill continues with remaining agents per composition algorithm.

### 10.5 — Tool ERROR envelope

**Trigger:** Underlying tool returns `{"error": {"type": "...", "message": "...", "tool": "..."}}` per FA8.

**Output:**
```
TOOL ERROR — $tool failed during $verb.
  Type: <error.type>
  Message: <error.message>
  Tool: <error.tool>
  Step: <runbook step N> | <act phase A5>

Recommendation: investigate via /arcis:operate triage "<derived symptom>", or check $tool's logs directly.

No further mutations attempted.
```

**Audit:** `arcis_operate.<verb>.tool_error` event with `params.error = error_envelope`.
**Exit:** For `act`: STOP. For `runbook`: per the runbook's `## Escalation` section.

### 10.6 — Operator denial at confirm

**Trigger:** Operator picks "Cancel" at AskUserQuestion.

**Output:**
```
CANCELLED — operator declined at $PROMPT_NAME.
Incident: $INCIDENT_ID. No mutation attempted. No further action.
```

**Audit:** `arcis_operate.<verb>.cancelled` event.
**Exit:** Skill stops.

### 10.7 — Runbook step timeout

**Trigger:** A tool subprocess or agent dispatch exceeds the runbook's step timeout (default 5 min per agent, 90s per tool).

**Output:**
```
RUNBOOK TIMEOUT — step $N of runbook $RUNBOOK_NAME exceeded $TIMEOUT.
Last output: <truncated>

Escalating per runbook's escalation policy:
$ESCALATION_PROSE
```

**Audit:** `arcis_operate.runbook.<name>.timeout_at_step_<N>` event.
**Exit:** Skill stops; runbook in escalated state.

### 10.8 — Working directory cannot be resolved

**Trigger:** `git rev-parse --show-toplevel` fails AND `WORKTREE_PATH` not set.

**Output:**
```
ERROR — cannot resolve repo root via git rev-parse. Pass --incident-id and rerun from a known repo path.
```

**Audit:** NO event (no working repo to log against).
**Exit:** Skill stops immediately.

### 10.9 — Audit write failure (non-blocking, may indicate input corruption) — DA3 fix

**Trigger:** Layer 2 skill-level audit write (the `python -m src.tools._execution_log_writer` invocation) returns non-zero. Most common cause: an operator-typed string slipped through without `jq -Rs .` / `json.dumps` escaping in Step 1 of §9 Layer 2 write mechanism.

**Output (VISIBLE WARNING — not stderr drop):**
```
WARNING — audit-log write failed for event $EVENT_NAME (session_id=$INCIDENT_ID).
  This may indicate an operator-typed string was not JSON-escaped before audit write (DA3-class defect — see §9 Layer 2).
  The verb continues (audit is non-blocking) but this incident's bracket events may be incomplete.
  Recommendation: after this verb completes, grep tool-execution.log for $INCIDENT_ID and verify event sequence; if events are missing, file a bug.
```

**Audit:** No further audit attempt for this event (it already failed). The verb's NEXT audit write attempts normally — this is a per-event failure, not a session-wide gate.
**Exit:** Verb continues. Operator sees the WARNING in skill output.

---

## 11. Golden Transcripts

### 11.1 — Triage transcript

**Operator command:**
```
/arcis:operate triage "trades stopped firing this morning"
```

**Skill output (paraphrased to capture flow):**

```
Capturing ET wall-clock... NOW_ET = 2026-05-25 09:15 EDT
Verifying repo root... pwd = C:/arcis/halcyon-lab
Writing arcis_operate.triage.start audit event (session_id=incident-2026-05-25T13-15-00Z)

PHASE T1 — Classification
  Symptom: "trades stopped firing this morning"
  Domain: data (keywords: trades, recommendation)
  Proposed dispatch: live-monitor + db-investigator

PHASE T2 — AskUserQuestion
  > Proceed with dispatch: live-monitor + db-investigator?
  Operator: "Approve — dispatch the slate"

PHASE T3 — Parallel agent dispatch
  Dispatching live-monitor (DYNAMIC CONTEXT: SYMPTOM=..., FOCUS_SERVICES=ArcisWatchLoop,..., INCLUDE_TRADING_STATE=true)
  Dispatching db-investigator (DYNAMIC CONTEXT: SYMPTOM=..., INVESTIGATION_MODE=surface, FOCUS_TABLES=shadow_trades,recommendations)
  Waiting (max 5 min per agent)...
  
  live-monitor returned <live_report> in 47s
  db-investigator returned <db_report> in 1m 12s

PHASE T4 — Composition
  Collected 5 findings (2 live, 3 db)
  Dedup: no duplicates
  Severity rollup: db has 1 must_fix → incident_severity = critical
  Order applied
  Recommendation synthesis...

PHASE T5 — Report
  INCIDENT incident-2026-05-25T13-15-00Z — TRIAGE COMPLETE
  Symptom: trades stopped firing this morning
  Severity: critical
  Captured: 2026-05-25 09:15 EDT
  Agents dispatched: live-monitor, db-investigator
  Agents succeeded: live-monitor, db-investigator
  Agents failed: (none)
  
  FINDINGS (5 total, top 5 shown):
  
  1. [must_fix] No shadow_trades rows in last 30min
     Source: db-investigator
     Evidence: SELECT count(*) FROM shadow_trades WHERE created_at > NOW() - INTERVAL '30 min' = 0; vs 7-day median 4.3 [truncated]
     Confidence: high
     Recommendation: /arcis:operate runbook data-anomaly
  
  2. [anomaly] last_broker_poll 32min ago (threshold 5min)
     Source: live-monitor
     Evidence: tradingstate.last_broker_poll_age_s = 1920
     Confidence: high
     Recommendation: /arcis:operate runbook watchloop-wedged
  
  3. [anomaly] 30min gap in recommendations vs 7-day median
     Source: db-investigator
     Evidence: SELECT count(*) FROM recommendations WHERE created_at > NOW() - INTERVAL '30 min' = 0; vs median 12 [truncated]
     Confidence: medium
     Recommendation: (covered by finding 1)
  
  4. [informational] ArcisDashboard running normally
     Source: live-monitor
     Evidence: heartbeat 8s old, state RUNNING
     Confidence: high
     Recommendation: no action
  
  5. [informational] GPU0 VRAM 6GB/24GB used (Ollama loaded)
     Source: live-monitor
     Evidence: nvidia-smi memory.used=6128MiB
     Confidence: high
     Recommendation: no action
  
  PROPOSED NEXT ACTIONS:
    A. /arcis:operate runbook watchloop-wedged    (matches finding 2 — broker poll lag = watch-loop wedge symptom)
    B. /arcis:operate runbook data-anomaly        (matches finding 1 — investigates the missing rows)
    C. Continue investigation manually

PHASE T6 — AskUserQuestion
  > Triage produced a remediation recommendation. Execute it now?
  Operator: "Yes — invoke watchloop-wedged"
  Setting CHAIN_VERB=runbook, CHAIN_ARG=watchloop-wedged. Continuing with incident-2026-05-25T13-15-00Z.

PHASE T7 — Audit
  Writing arcis_operate.triage.completed event with severity=critical, finding_count=5, chained_to=runbook.watchloop-wedged

→ Continuing to runbook watchloop-wedged...
```

### 11.2 — Act transcript (in-window refusal + emergency override)

**Operator command (at 21:45 ET):**
```
/arcis:operate act restart-watchloop
```

**Skill output:**

```
Capturing ET wall-clock... NOW_ET = 2026-05-25 21:45 EDT
Verifying repo root... pwd = C:/arcis/halcyon-lab
Writing arcis_operate.act.start audit event (session_id=incident-2026-05-26T01-45-00Z)

PHASE A1 — Resolve action
  Action: restart-watchloop
  Auth class: confirm+safety_window
  Verify step: python -m src.tools.healthprobe --service ArcisWatchLoop --json

PHASE A2 — Action plan (dry-run preview)
  Invoking dry-run: python -m src.tools.processmanager restart ArcisWatchLoop --json
  Result: {"tool_name": "processmanager.restart", "would_do": "Stop ArcisWatchLoop, wait for STOPPED, start, wait for RUNNING + heartbeat <60s", "params": {"service": "ArcisWatchLoop"}, "timestamp": "..."}

PHASE A3 — Safety Window Gate
  Current ET: 21:45 EDT
  Window: 21:30–22:30 (no_restart_overnight) → IN WINDOW
  EMERGENCY flag: false
  
REFUSE — safety_windows.no_restart_overnight active.
  Current ET: 2026-05-25 21:45 EDT
  Window: 21:30–22:30 (no_restart_overnight)
  Reason: mid-cycle restart forces a redundant overnight re-launch (memory: feedback_no_restart_during_overnight_window)

Options:
  1. Wait until 22:30 ET and re-run the same command.
  2. Re-run with --emergency if this is a genuine emergency. You will be asked to confirm.

No mutation attempted. No audit event for mutation written.

Writing arcis_operate.act.safety_window_refused event
```

**Operator retries with --emergency:**

```
/arcis:operate act restart-watchloop --emergency
```

**Skill output:**

```
Capturing ET wall-clock... NOW_ET = 2026-05-25 21:46 EDT
...

PHASE A3 — Safety Window Gate
  Current ET: 21:46 EDT → IN WINDOW
  EMERGENCY flag: true
  
AskUserQuestion (BLOCKING):
> You are bypassing safety_windows.no_restart_overnight (21:30–22:30 ET).
> Current ET: 2026-05-25 21:46 EDT. The window exists because mid-cycle restart forces a redundant overnight re-launch from scratch (incident 2026-05-18 v0.36.22 deploy).
> Action to execute: restart-watchloop
> Proceed with emergency override?

Operator: "Yes — emergency override"

Setting EMERGENCY_OVERRIDE_CONFIRMED=true

PHASE A4 — Confirmation
> Action: restart-watchloop
> Auth class: confirm+safety_window (emergency-bypassed)
> Planned command: python -m src.tools.processmanager restart ArcisWatchLoop --confirm --emergency --json
> Dry-run preview: Stop ArcisWatchLoop, wait for STOPPED, start, wait for RUNNING + heartbeat <60s
> Post-execution verification: python -m src.tools.healthprobe --service ArcisWatchLoop --json
> Approve?

Operator: "Approve — execute"

PHASE A5 — Execute
  $ ARCIS_SESSION_ID=incident-2026-05-26T01-45-00Z python -m src.tools.processmanager restart ArcisWatchLoop --confirm --emergency --json
  → {"service": "ArcisWatchLoop", "restarted": true, "verified": true, "elapsed_s": 9.4, "log_evidence": "2026-05-26T01:46:38Z INFO Heartbeat written", "state": "RUNNING"}

PHASE A6 — Post-execution verification
  $ python -m src.tools.healthprobe --service ArcisWatchLoop --json
  → {"service": "ArcisWatchLoop", "state": "RUNNING", "heartbeat_age_s": 7, "passed": true}

  Two-layer staleness check: no stale audit_reports row detected. Skipping.

PHASE A7 — Report + audit
  ACT restart-watchloop — success
  Incident: incident-2026-05-26T01-45-00Z
  Executed: 2026-05-25 21:46 EDT
  Elapsed: 9.4s
  Verify: PASS (heartbeat 7s)
  Evidence: <log line>

  Writing arcis_operate.act.restart-watchloop.completed event with result=success, emergency=true
```

### 11.3 — Runbook transcript (watchloop-wedged, fully outside window)

**Operator command (at 14:00 ET):**
```
/arcis:operate runbook watchloop-wedged
```

**Skill output (condensed):**

```
NOW_ET = 2026-05-25 14:00 EDT
INCIDENT = incident-2026-05-25T18-00-00Z

PHASE R1 — Resolve
  Reading .claude/plugins/arcis/skills/operate/runbooks/watchloop-wedged.md
  Frontmatter: required-tools=[processmanager, healthprobe, logtail]; required-agents=[live-monitor]; mutations=true; risk-level=medium
  All required tools available (Tier 1+2). live-monitor agent file present.

PHASE R2 — Begin steps

Step 1 — agent live-monitor
  Dispatching live-monitor...
  Returned <live_report>:
    service_state[0] = {"name": "ArcisWatchLoop", "composite_verdict": "unhealthy", "heartbeat_age_s": 1840, "process_state": "RUNNING"}
    correlations[0] = {"severity": "must_fix", "type": "heartbeat_stale", "evidence": "..."}
  
  Decision: composite_verdict="unhealthy" AND correlations[*].type contains "heartbeat_stale" → wedged-equivalent → continue to Step 2

Step 2 — ask confirm-restart
  > live-monitor confirms ArcisWatchLoop is wedged (heartbeat age 30min; last log "broker_poll start" at 13:30 EDT).
  > Current ET: 2026-05-25 14:00 EDT (outside safety window).
  > Proposed action: python -m src.tools.processmanager restart ArcisWatchLoop --confirm --json
  > Verify after: python -m src.tools.healthprobe --service ArcisWatchLoop --json
  > Proceed?
  
  Operator: "Approve — restart now"

Step 3 — act restart-watchloop
  Invoking nested act verb (inherits incident=incident-2026-05-25T18-00-00Z)
  Safety Window Gate: outside window, skipping.

  Confirm-inheritance contract check (§3.A4.1):
    (i)   Step 2's prose names "act restart-watchloop" verbatim? YES
    (ii)  Step 2's prose shows the CLI "python -m src.tools.processmanager restart ArcisWatchLoop --confirm --json"? YES
    (iii) Step 2's prose shows the verify_step "python -m src.tools.healthprobe --service ArcisWatchLoop --json"? YES
    (iv)  Step 2 has an option exactly "Approve — restart now" matching auth-matrix? YES
    (v)   Approve option carried verified=true bit (RUNBOOK_CONFIRM_VERIFIED=true)? YES
    → Contract SATISFIED. A4 inherits.

  Writing arcis_operate.act.restart-watchloop.confirmed event with prompt_hash=<sha256 of Step 2 prose>, option_text="Approve — restart now", inherited_from_runbook=true.

  Executing: python -m src.tools.processmanager restart ArcisWatchLoop --confirm --json
  → {"service": "ArcisWatchLoop", "restarted": true, "verified": true, "elapsed_s": 7.8, ...}
  
  Decision: restarted=true + verified=true → continue to Step 4

Step 4 — verify healthprobe
  Executing: python -m src.tools.healthprobe --service ArcisWatchLoop --json
  → {"service": "ArcisWatchLoop", "state": "RUNNING", "heartbeat_age_s": 4, "passed": true}
  
  Decision: passed=true + age<60 → continue to Step 5

Step 5 — verify trading-state
  Executing: python -m src.tools.tradingstate --json
  → {"last_broker_poll_ts": "2026-05-25T14:00:32Z", "last_broker_poll_age_s": 18, ...}
  
  Decision: poll age 18s (< 5min) → SUCCESS

PHASE R4 — Success criteria
  healthprobe passed: ✓
  poll age < 300s: ✓
  outside window: ✓
  All criteria met.

PHASE R5 — Report + audit
  RUNBOOK watchloop-wedged — completed
  Incident: incident-2026-05-25T18-00-00Z
  Steps: 5 of 5
  Elapsed: 1m 12s
  
  Writing arcis_operate.runbook.watchloop-wedged.completed event
```

### 11.3b — Runbook transcript (NEGATIVE — confirm-inheritance contract failure, DA2)

**Scenario:** A hypothetical post-merge operator-authored runbook `custom-restart-experiment.md` has a step:

```markdown
### Step 2 — ask confirm

> The system needs a restart. Continue?
Options:
- "OK"
- "Cancel"
```

This ask **fails** contract requirements (i) (no `act <action>` named), (ii) (no CLI shown), (iii) (no verify_step shown), and (iv) (option is "OK" not "Approve <action>"). Contract not satisfied.

**Operator command (outside window):**
```
/arcis:operate runbook custom-restart-experiment
```

**Skill output (condensed, showing the contract failure path):**

```
NOW_ET = 2026-05-25 14:30 EDT
INCIDENT = incident-2026-05-25T18-30-00Z-7f3a2b

PHASE R2 — Read runbook (validator gate)
  Loading data/cache/runbooks/custom-restart-experiment.validated
  Cache miss — running 5-check validator
  Validator PASS (frontmatter clean; symptom-matchers narrow; no cycles).

PHASE R3 — Steps

Step 1 — agent live-monitor
  Returned <live_report>: composite_verdict=unhealthy
  Continue to Step 2.

Step 2 — ask confirm
  > The system needs a restart. Continue?
  Operator: "OK"

Step 3 — act restart-watchloop
  Invoking nested act verb.
  Safety Window Gate: outside window, skipping.

  Confirm-inheritance contract check (§3.A4.1):
    (i)   Step 2's prose names "act restart-watchloop" verbatim? NO (step prose mentions only "the system" — generic)
    (ii)  Step 2's prose shows the CLI "python -m src.tools.processmanager restart ArcisWatchLoop --confirm --json"? NO
    (iii) Step 2's prose shows the verify_step? NO
    (iv)  Step 2 has an option exactly "Approve restart-watchloop" / "Approve — restart now"? NO ("OK" does not name the action)
    → Contract FAILED at requirement (i) (and also ii, iii, iv).

  Writing arcis_operate.runbook.custom-restart-experiment.confirm_contract_failed_at_step_2 event with failed_requirement="(i)_action_not_named", detail="step 2 prose did not include 'act restart-watchloop'".

  A4 fires fresh inside act:

  PHASE A4 — Confirmation (fresh, not inherited)
  > Action: restart-watchloop
  > Auth class: confirm+safety_window
  > Planned command: python -m src.tools.processmanager restart ArcisWatchLoop --confirm --json
  > Dry-run preview: Stop ArcisWatchLoop, wait for STOPPED, start, wait for RUNNING + heartbeat <60s
  > Post-execution verification: python -m src.tools.healthprobe --service ArcisWatchLoop --json
  > preview captured at 2026-05-25T18:30:42Z; if state changes before execute, the actual action may differ.
  > Approve?

  Operator: "Approve — execute"
  (Operator sees TWO confirms — Step 2 "OK" + A4 "Approve — execute" — the auth matrix's UX hardening is restored.)

  Writing arcis_operate.act.restart-watchloop.confirmed event with prompt_hash=<sha256 of A4 prose>, option_text="Approve — execute", inherited_from_runbook=false.

  Continue to A5 / A5.1 / Execute / A6 / A7 normally.
```

**Why this matters (DA2):** the auth matrix's confirm prose is the source of truth. Operator-authored runbooks with ambiguous single-button asks do NOT bypass the auth matrix — A4 fires fresh, and the operator sees the well-formed confirm.

---

## 12. Manual Verification Checklist

The implementing PM completes this checklist BEFORE declaring done. Each item is operator-verifiable in <2 minutes.

1. [ ] **Cold-read by fresh session.** Open a NEW Claude Code session (no prior context). Invoke `/arcis:operate triage "test symptom"`. The skill self-describes its phases, asks the dispatch confirmation, and proceeds. **PASS criteria:** the fresh session knows what to do from `commands/operate.md` alone — no need to read SKILL.md or runbooks.

2. [ ] **Verb-unknown error.** Invoke `/arcis:operate foobar`. Skill returns the verb-unknown ERROR envelope (§10.1) verbatim. No audit event written (verify via `tail -5 data/logs/tool-execution.log`).

3. [ ] **Refuse-in-window verification.** Set fake ET via `ARCIS_NOW_ET_OVERRIDE=2026-05-25T22:00:00-04:00` env var (per FA9 test seam) AND invoke `/arcis:operate act restart-watchloop`. Skill returns REFUSE prose (§6 verbatim). **No tool subprocess invoked** (verify by checking that `data/logs/tool-execution.log` has only the `arcis_operate.act.safety_window_refused` event, no `processmanager.restart` event).

4. [ ] **Emergency override flow.** Same env override + `--emergency` flag. Skill asks the emergency-confirm AskUserQuestion. Picking "No" stops without mutation. Picking "Yes" proceeds to confirm + tool invocation.

5. [ ] **Tier 3 graceful degradation.** Move (rename) `src/tools/contractcheck/` aside if it exists, OR confirm it does not exist (pre-#107). Invoke a runbook that lists `contractcheck` in required-tools (NONE in v1 — but verify by manually editing a runbook to add `contractcheck` to required-tools). Skill prints the "tool not yet shipped" warning + skips the step.

6. [ ] **Audit-log presence.** After any verb completes, `tail -10 data/logs/tool-execution.log | jq '.tool_name'` shows the `arcis_operate.<verb>.start` and `arcis_operate.<verb>.completed` events for the run.

7. [ ] **Status verb fast-path.** `/arcis:operate status` returns within 30s. No agent dispatch (verify by checking that no agent is active in the session).

8. [ ] **Runbook resolution.** `/arcis:operate runbook nonexistent` returns the unknown-runbook ERROR envelope. `/arcis:operate runbook watchloop-wedged --dry-run` parses the runbook, prints the step plan, and does NOT execute any mutations.

9. [ ] **Cross-agent composition.** Trigger a triage that dispatches 2+ agents (e.g., `/arcis:operate triage "trades stopped firing"`). Verify the operator-facing report lists findings from BOTH agents, with the severity rollup applied per §8.

10. [ ] **No out-of-scope deferral.** Triage a multi-symptom incident with 8+ findings. The composed report MUST list ALL findings — first 5 in detail + remaining N-5 as one-line summaries (DA4 fix). Implementing PM grep for "deferred to" or "follow-up task" in any output — should be zero hits.

10a. [ ] **DA1 — NOW_ET re-capture at gate entry.** Set `ARCIS_NOW_ET_OVERRIDE=2026-05-25T21:31:00-04:00` AND inject a 90s delay between Step 0.1 and SAFETY WINDOW GATE entry (e.g., spec an act with a deliberately slow A2 dry-run preview). Verify the gate's prose shows the FRESH 21:31 capture (in-window), not the stale Step 0.1 21:28 capture. Refusal/emergency prompts must reference NOW_ET_GATE, not NOW_ET.

10b. [ ] **DA2 — confirm-inheritance contract.** Author the §11.3b NEGATIVE runbook (`custom-restart-experiment.md` with ambiguous "OK" ask). Run it. Verify (i) the runbook's Step 2 fails the 5-point contract, (ii) the `arcis_operate.runbook.custom-restart-experiment.confirm_contract_failed_at_step_2` audit event is written, (iii) the inner act's A4 fires fresh with the full auth-matrix prompt prose. Run §5.1 watchloop-wedged (POSITIVE) — verify contract satisfies and A4 inherits via the `arcis_operate.act.restart-watchloop.confirmed` event with `inherited_from_runbook=true`. For every runbook's ask-then-act chain in §5.x, verify contract satisfaction explicitly.

10c. [ ] **DA3 — JSON injection safety.** Paste a symptom containing `she said "it's broken" $(rm -rf /)` (with single-quote + double-quote + backtick + dollar-sign + newline). Verify (i) the audit lines land intact via `jq -c 'select(.session_id == ...)'` (no JSON parse error), (ii) the symptom prose appears in events un-truncated and un-escaped-in-meaning (the dollar-sign substitution is literal data, not shell-expanded), (iii) no shell-side effect occurred (no rm called), (iv) §10.9 VISIBLE WARNING appeared if escaping was skipped accidentally.

10d. [ ] **DA4 — ≤3 binding prompts in worst-case triage.** Run a triage with unclear-symptom (forces T1 disambig) + a "Modify" pick at T2 (forces modify-subprompt) + SEVERITY != clear (forces T6). Count mandatory checkpoints — must be ≤3. Conditional subprompts (modify-subprompt, show-runbook-first) are unbounded but operator-initiated and don't count against budget.

10e. [ ] **DA5 — self-resolution downgrade.** Mock a primary symptom that self-resolves between agent dispatch and T4 (e.g., temporarily mock `healthprobe` to first return `passed=false` then `passed=true` 30s later). Verify the orchestrator's T4.5 re-check fires, detects self-resolution, DOWNGRADES severity to `monitor`, and the T6 prompt becomes `"symptom appears resolved during triage; investigate root cause or close?"` (replacing the standard recommendation prompt).

10f. [ ] **DA6 — incident-id collision.** Fire 2 triage in parallel within 1 second (concurrent shells). Verify two distinct incident-ids (different 6-hex suffixes) appear in audit log. Also test `--incident-id` regex validation: pass `incident-bogus` (no time) → ERROR envelope. Pass a valid format but pre-existing id (with audit events in last 1h) → AskUserQuestion merge-streams prompt.

10g. [ ] **DA7 — runbook validation gate.** Place a malformed runbook at `runbooks/broken-frontmatter.md` (e.g., missing required key, `mutations: "not_a_bool"`). Run `/arcis:operate runbook broken-frontmatter`. Verify graceful refuse via §10-class envelope (NOT a crash). Also test (b) — runbook with `required-tools: [capabilityregistryquery]` (typo) fails the resolves-to-real-module check. Verify validator cache populates at `data/cache/runbooks/<name>.validated`.

10h. [ ] **DA8 — audit event prompt_hash + option_text.** Invoke `act restart-watchloop` (outside window), approve. Grep audit log for the `arcis_operate.act.restart-watchloop.confirmed` event. Verify (i) `prompt_hash` is a 64-char lowercase hex string and matches `sha256(prompt prose shown)`, (ii) `option_text` equals the verbatim string the operator picked (e.g., `"Approve — execute"`). Repeat for cancel + emergency_denied events.

10i. [ ] **DA9 — abandonment recovery.** Run `/arcis:operate runbook gpu-degraded`. At Step 3 ask, after Step 4 act has fired but before Step 5+6 verify completes, send a cancel. Verify (i) Step 5+6 attempted on best-effort 60s time-box, (ii) `arcis_operate.runbook.gpu-degraded.abandoned_after_mutation` event written, (iii) running `/arcis:operate status` within 24h surfaces the abandonment prompt.

10j. [ ] **DA10 — re-capture preview before execute.** Invoke `act restart-watchloop` outside window. At A4 approve. Between A4 and A5.1, inject a service-state change (manually stop ArcisWatchLoop via `sc stop`). Verify A5.1 re-runs the dry-run, detects diff (`would_do` changed from "Stop+Start" to "Start" since service is now STOPPED), and fires the re-approval AskUserQuestion.

11. [ ] **All 5 runbooks parse.** For each of the 5 v1 runbooks, invoke `/arcis:operate runbook <name> --dry-run`. All 5 parse, print step plan, no syntax errors.

12. [ ] **Sibling-search applied.** Read the spec's golden transcripts (§11). Implementing PM checks that the runbooks reference each other (e.g., `pg-tests-red` mentions `git-historian` if regression suspected). No isolated silos.

13. [ ] **Plugin registration.** `/help` or similar lists `/arcis:operate` as a known command. Frontmatter from `commands/operate.md` is parseable.

14. [ ] **CHANGELOG entry.** v0.36.6X entry mentions "Skill: `/arcis:operate` ships with 4 verbs + 5 runbooks."

---

## 13. Implementation Discipline

Inherited from existing arcis-code patterns. The implementing PM must apply these to the #109 PR:

1. **Sibling-search rule** (memory: `feedback_review_sibling_search`). When reviewing a runbook or section, if a fix or convention is applied at file:line, GREP the surrounding file(s) for the same anti-pattern at other lines. Specifically: if one runbook handles "tool not yet shipped" warning, ALL 5 must handle it consistently.

2. **Verify-by-mutation** (memory: `feedback_strict_rigor_no_handwave`). Every claim in the spec that maps to runtime behavior must have a verification step in §12. Implementing PM runs all 14 checklist items and posts evidence (screenshot or `data/logs/tool-execution.log` tail) in the PR description.

3. **No out-of-scope deferral** (memory: `feedback_complete_efforts_no_deferral`). If during implementation the PM discovers an adjacent defect (e.g., `_cli_envelope.run_cli` doesn't propagate `ARCIS_SESSION_ID`), surface it in the PR description. Either fix in-scope (preferred) or open a tracking issue AND link it in the PR. Do not silently defer.

4. **Dual-Opus QA merge gate** (memory: `feedback_use_coding_team_skill`). #109 is operator-experience capstone. Merge requires TWO independent Opus QA reviews. Each must certify: root-cause / hardening / ripple / noise / 100% confidence. PM-merge ONLY after both PASS.

5. **Per-PR versioning.** Re-baseline at impl time. Current main: v0.36.64. Target: v0.36.6X (impl-time pick). Update `CHANGELOG.md` AND any version constants.

6. **Worktree isolation** (memory: `feedback_strict_rigor_no_handwave`). All developer worktrees verify isolation on first tool use:
   ```bash
   pwd && git rev-parse --show-toplevel && git branch --show-current
   ```
   Expected: under `.claude/worktrees/agent-X/`, NOT main repo.

7. **Windows UTF-8 encoding** (memory: `feedback_windows_utf8_encoding`). All markdown files written with `encoding='utf-8'` if produced via Python; prefer Edit tool / sed for any file with existing non-ASCII glyphs.

8. **CLI subprocess pattern.** Every audit-log write from skill prose follows the bracketing wrapper (`|| echo "warning..." >&2`). Failures are non-blocking.

9. **AskUserQuestion budget enforcement.** ≤3 per triage, ≤2 per act. Implementing PM counts the AskUserQuestion blocks per verb section. Excess prompts trigger spec revision before merge.

10. **Spec-as-deliverable-0.** The spec.md AND plan.json that produced this PR are committed alongside the implementation (per `commands/code.md` lines 44-55 convention).

---

## 14. Open Questions & Design Boundaries

The implementing PM must address these before merge.

### Open Questions (require operator decision or impl-time verification)

1. **session_id propagation.** `_cli_envelope.run_cli` does NOT currently propagate `ARCIS_SESSION_ID` env var to `write_event`. The skill's v1 workaround is bracketing events with session_id; Layer 1 (per-tool) events have null session_id. **Should the implementing PM include a one-line patch to `_cli_envelope.run_cli`?** Recommended: yes, as a co-shipped change (~3 lines). Affects every Tier 1+2 tool's audit trail. Operator decides.

2. **`force-broker-poll` action.** The Action Authorization Matrix lists this action, but its CLI may not exist yet. **Impl-time action (mandatory, MUST run at start of T8):** the implementing PM runs `python -m src.tools.processmanager --help` (and `python -m src.tools.processmanager force-broker-poll --help`) and confirms the verb exists. **If the tool/verb does NOT exist:** REMOVE the row from §7 AND from `references/action-authorization-matrix.md`, AND DROP `force-broker-poll` from any v1 runbook that references it (no v1 runbook currently does; defense-in-depth). Mark Verification column as `removed` and add a 1-line note in the matrix file explaining the drop, plus a follow-up backlog entry.

3. **`regenerate-stale-audit` action.** **Impl-time action (mandatory, MUST run at start of T8):** the implementing PM runs `python -m src.tools.auditor --help` AND greps `src/tools` for `auditor` to confirm the tool exists. **If the tool does NOT exist OR does not support `--regenerate`:** REMOVE the row from §7 AND from `references/action-authorization-matrix.md`, AND DROP `regenerate-stale-audit` from any v1 runbook that references it (no v1 runbook currently does). Mark Verification column as `removed`.

4. **`post-pr-summary` action CLI shape.** The matrix references `ci_summary_post --pr <pr> --confirm --json` — this is the presumed mutation path of ci-investigator's posting capability. **Impl-time action (mandatory, MUST run at start of T8):** the implementing PM runs `python -m src.tools.ci_summary_post --help` (alternate names to try: `python -m src.tools.cisummarypost --help`, `python -m src.tools.ci_investigator --help`). **If no separable mutation CLI exists**, EITHER (a) rewrite the row to use Agent dispatch with `POST_SUMMARY=true` (matrix row's "CLI invocation" cell becomes an Agent block, not a Bash subprocess); OR (b) REMOVE the row entirely and DROP `post-pr-summary` from any v1 runbook that references it. Mark Verification column as `unverified-presumed-resolved` or `removed`.

5. **Runbook required-agents existence.** All 4 #108 agents are designed/in-implementation per `taskList:#108`. If #108 has not landed at #109 impl time, the skill cannot dispatch the agents. **The implementing PM must verify at impl start that all 4 agent files exist at `.claude/plugins/arcis/agents/{db-investigator,ci-investigator,git-historian,live-monitor}.md`.** If not, BLOCK #109 on #108 completion.

6. **Tier 3 availability at impl time.** #107 (ContractCheck, GitArchaeology, DocConsistency) is in-progress. The v1 runbooks (5 named flows) do NOT depend on Tier 3 — this was deliberate. If the implementing PM adds future runbooks that DO depend on Tier 3, the graceful-degradation pattern (§10.2) applies.

7. **`_execution_log_writer` CLI entry point (DA3).** §9 Layer 2 audit writes require a stdin-driven CLI invocable as `python -m src.tools._execution_log_writer --tool-name X --session-id Y --result success --duration-ms 0`. The current `src/tools/_execution_log.py` exposes `write_event()` as a Python function only — no CLI. **Implementing PM action (mandatory, in-scope for #109):** add ~6 lines to `src/tools/_execution_log.py` exposing the CLI entry point that reads JSON from stdin and calls `write_event()`. Surface the diff in PR description. This is a defect-blocker (DA3 critical-injection-surface mitigation), not a future enhancement.

8. **Auth matrix checksum on edit (DA7).** Should `references/action-authorization-matrix.md` be checksummed at impl time so post-merge edits to the matrix trigger a re-validation prompt (analogous to runbook content-hash drift detection)? **Open for operator decision.** v1 ships without checksum; v2 enhancement.

### Design Boundaries (explicitly OUT of scope)

1. **Trading strategy ideation/backtest** — `/arcis:strategy` (#110, future spec).
2. **Periodic discipline / skill-audit / memory curator** — #111, future spec.
3. **Auto-triggering ContractCheck on certain symptoms.** Operator-explicit only in v1 per the brief. Auto-trigger is post-v1.
4. **Dashboard mirroring for `/arcis:operate`.** `/arcis:code` mirrors to `.arcis/coding-dashboard.json` per code.md lines 106-110. `/arcis:operate` v1 does NOT mirror. Post-v1 if operator requests.
5. **Mutating any of the 13 tools or 4 #108 agents.** Frozen. The skill INHERITS them.
6. **Implementing the skill.** This is spec + plan only. `/arcis:code --spec ... --plan ...` consumes the output.
7. **Runbook content beyond the 5 v1 named flows.** Additional runbooks are operator-added post-merge per the runbook convention in §4.

### Coverage caveats (from deep_report)

- Did NOT read `src/tools/processmanager/core.py` (the actual `restart()` implementation). The CLI shape and JSON envelope are documented; the core's retry-and-verify logic is not. The implementing PM does not need to re-read this — the JSON envelope is the contract.
- Did NOT read all 4 golden test files in full detail. Sufficient for orchestrator design; gaps are around edge-case sample data that the implementing PM can read on demand if a runbook DYNAMIC CONTEXT seems ambiguous.
- Did NOT verify `force-broker-poll` / `regenerate-stale-audit` / `post-pr-summary` CLIs exist. Implementing PM verifies at impl time per Open Questions 2-4.
- Tier 3 tool CLI shape (`contractcheck`, `gitarchaeology`, `docconsistency`) was NOT examined — they don't ship yet. v1 doesn't depend on them; graceful degradation is the contract.

### Sibling-search self-audit

Per `feedback_review_sibling_search`: while writing this spec, the architect noted:

- **session_id propagation gap** (§9 / §14 OQ#1) — surfaced rather than silently leaving Layer 1 events with null session_id.
- **Tool CLI verification gaps** for 3 actions (§7 / §14 OQ#2-4) — surfaced rather than assuming.
- **YAML drift risk** for safety-window comparison (§6) — surfaced with mitigation comment.
- **#108 agent existence dependency** (§14 OQ#5) — surfaced with explicit verification step.

No silent deferrals.

---

## Known Considerations (devils-advocate review findings — non-blocking, deferred to v2 or accepted-with-mitigation)

| # | Severity | Concern | v1 mitigation | v2 enhancement |
|---|---------|---------|---------------|----------------|
| DA11 | MINOR | Verb-typo refuses without did-you-mean | List valid verbs in error envelope | Levenshtein-distance-2 fuzzy suggestion |
| DA13 | MINOR | Hardcoded 21:30-22:30 in skill prose drifts from arcis_config.yaml | DRIFT RISK comment in operate.md | Cache YAML parse at Step 0.0 |
| DA15 | NIT | Two-layer staleness check enumerated only for watchloop restart | None (single instance) | Add `staleness_checks` column to §7 action matrix |

(Per devils-advocate review 2026-05-26.)

---

**END OF SPEC**
