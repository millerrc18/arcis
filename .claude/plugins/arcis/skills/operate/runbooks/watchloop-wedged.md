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
confirm-inheritance:
  - step: 2
    satisfies_act_step: 3
    target_action: restart-watchloop
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

**Purpose:** Operator approval gate before any service mutation. This is the Safety Window Gate + Auth confirm rolled into one (per the `act restart-watchloop` Auth Matrix row). This ask satisfies the A4 confirm-inheritance contract (§3.A4.1) for Step 3's `act restart-watchloop`.

**Invocation:** AskUserQuestion (BLOCKING).

> live-monitor confirms ArcisWatchLoop is wedged (heartbeat age $AGE; last log $LAST_LOG).
> Current ET: $NOW_ET.
> Action: `act restart-watchloop`
> CLI invocation: `python -m src.tools.processmanager restart ArcisWatchLoop --confirm --json`
> Verify step after restart: `python -m src.tools.healthprobe --service ArcisWatchLoop --json`
> Proceed?

Options:
- "Approve — restart now" [verified=true] — continue to Step 3
- "Cancel — abort runbook" — STOP, audit event `arcis_operate.runbook.watchloop-wedged.cancelled_at_step_2`

If in safety window AND `EMERGENCY = false`: this step is REFUSED per the Safety Window Gate; show the override prompt.

**Confirm-inheritance contract checklist (§3.A4.1):**
- (i) Names the verb+action: `act restart-watchloop` — present above.
- (ii) Shows the CLI invocation verbatim: `python -m src.tools.processmanager restart ArcisWatchLoop --confirm --json` — present above.
- (iii) Shows the verify_step: `python -m src.tools.healthprobe --service ArcisWatchLoop --json` — present above.
- (iv) Approve option is exactly `"Approve — restart now"` — present above.
- (v) Approve option carries `verified=true` — marked `[verified=true]` above; orchestrator sets `RUNBOOK_CONFIRM_VERIFIED = true` on selection.

### Step 3 — act restart-watchloop

**Purpose:** Restart the wedged service via the canonical NSSM-managed path. **NEVER** call `python -m src.main startup` directly (memory: `reference_watch_loop_management`).

**Invocation:** `/arcis:operate act restart-watchloop` (inherits this runbook's `$INCIDENT_ID` for audit-trail continuity). Inherits A4 confirm from Step 2 (confirm-inheritance contract satisfied).

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

If the operator denies Step 2's confirm ("Cancel — abort runbook"):
- Stop the runbook sequence here.
- Leave the incident verdict as **Wedged-Unrecovered** (no mutation was attempted).
- Dispatch live-monitor with a hold-until note: `MANDATE: ArcisWatchLoop remains wedged. Runbook cancelled at Step 2 (operator declined restart). Monitor service state and hold restart evaluation until after 22:30 ET if currently inside the overnight window.`
- The incident audit event `arcis_operate.runbook.watchloop-wedged.cancelled_at_step_2` captures the abandonment for continuity.

## Escalation

If the runbook escalates from any step:

1. Capture the current state via `/arcis:operate status` (the snapshot survives the runbook failure).
2. Surface the captured findings + the runbook step trace to the operator.
3. Suggest:
   - If SCM wedge: follow `reference_scm_dependency_wedge` manually (~13 min).
   - If heartbeat stale but service running: code-level wedge — investigate `src/scheduler/watch.py` recent changes via `/arcis:operate triage "watch loop running but not progressing"` (will dispatch git-historian).
   - If verification persistently fails: page operator out-of-band.
