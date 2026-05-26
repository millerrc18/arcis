# Error Envelopes — `/arcis:operate`

Every failure class has a defined operator-facing shape. This file is the
orchestrator reference for all 9 error classes produced by the operate skill.
Stored at `references/error-envelopes.md` per spec §10.

---

## 10.1 — Verb unknown

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

---

## 10.2 — Tier 3 tool unavailable

**Trigger:** `python -m src.tools.<name> --help` returns non-zero (tool not yet
shipped per #107).

**Output (inline in verb output, NOT a hard error):**
```
Tool <name> not yet shipped, gated on #107 — skipping <step description>.
Surfacing partial findings only.
```

**Audit:** `arcis_operate.<verb>.tier3_degraded` event with
`params.missing_tools = [...]`.

**Exit:** Skill continues with remaining tools.

---

## 10.3 — Safety window block (no emergency)

**Trigger:** Mutation verb, in-window, EMERGENCY=false.

**Output:** Verbatim REFUSE prose from §6.

**Audit:** `arcis_operate.<verb>.safety_window_refused` event.

**Exit:** Skill stops; no tool invocation.

---

## 10.4 — Agent dispatch failure

**Trigger:** Agent returns no `<*_report>` tag, or Agent tool errors.

**Output (within composed findings):**
```
[must_fix] Agent <name> did not return a parseable <name>_report.
Source: orchestrator
Evidence: <first 200 chars of agent output> [truncated]
Confidence: high
Recommendation: Re-run /arcis:operate triage with this agent slate manually, or investigate the agent's golden test.
```

**Audit:** Surfaced in the composed report; the agent's MaxTurns / error is
logged by the agent dispatcher itself (out of skill scope).

**Exit:** Skill continues with remaining agents per composition algorithm.

---

## 10.5 — Tool ERROR envelope

**Trigger:** Underlying tool returns
`{"error": {"type": "...", "message": "...", "tool": "..."}}` per FA8.

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

**Audit:** `arcis_operate.<verb>.tool_error` event with
`params.error = error_envelope`.

**Exit:** For `act`: STOP. For `runbook`: per the runbook's `## Escalation`
section.

---

## 10.6 — Operator denial at confirm

**Trigger:** Operator picks "Cancel" at AskUserQuestion.

**Output:**
```
CANCELLED — operator declined at $PROMPT_NAME.
Incident: $INCIDENT_ID. No mutation attempted. No further action.
```

**Audit:** `arcis_operate.<verb>.cancelled` event.

**Exit:** Skill stops.

---

## 10.7 — Runbook step timeout

**Trigger:** A tool subprocess or agent dispatch exceeds the runbook's step
timeout (default 5 min per agent, 90s per tool).

**Output:**
```
RUNBOOK TIMEOUT — step $N of runbook $RUNBOOK_NAME exceeded $TIMEOUT.
Last output: <truncated>

Escalating per runbook's escalation policy:
$ESCALATION_PROSE
```

**Audit:** `arcis_operate.runbook.<name>.timeout_at_step_<N>` event.

**Exit:** Skill stops; runbook in escalated state.

---

## 10.8 — Working directory cannot be resolved

**Trigger:** `git rev-parse --show-toplevel` fails AND `WORKTREE_PATH` not set.

**Output:**
```
ERROR — cannot resolve repo root via git rev-parse. Pass --incident-id and rerun from a known repo path.
```

**Audit:** NO event (no working repo to log against).

**Exit:** Skill stops immediately.

---

## 10.9 — Audit write failure (non-blocking, may indicate input corruption) — DA3 fix

**Trigger:** Layer 2 skill-level audit write (the
`python -m src.tools._execution_log_writer` invocation) returns non-zero. Most
common cause: an operator-typed string slipped through without `jq -Rs .` /
`json.dumps` escaping in Step 1 of §9 Layer 2 write mechanism.

**Output (VISIBLE WARNING — not stderr drop):**
```
WARNING — audit-log write failed for event $EVENT_NAME (session_id=$INCIDENT_ID).
  This may indicate an operator-typed string was not JSON-escaped before audit write (DA3-class defect — see §9 Layer 2).
  The verb continues (audit is non-blocking) but this incident's bracket events may be incomplete.
  Recommendation: after this verb completes, grep tool-execution.log for $INCIDENT_ID and verify event sequence; if events are missing, file a bug.
```

**Audit:** No further audit attempt for this event (it already failed). The
verb's NEXT audit write attempts normally — this is a per-event failure, not a
session-wide gate.

**Exit:** Verb continues. Operator sees the WARNING in skill output.
