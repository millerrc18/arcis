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
confirm-inheritance:
  - step: 3
    satisfies_act_step: 4
    target_action: restart-ollama-watchdog
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

**On failure:** Surface the stderr verbatim. If `nvidia-smi` is not installed or driver unavailable, escalate per `## Escalation`.

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

**On failure:** Agent dispatch returns no `<live_report>` → AskUserQuestion fallback:
> live-monitor failed to return a report. Fall back to manual check?
- "Yes — Bash: `python -m src.tools.processmanager status ArcisOllamaWatchdog --json`"
- "No — abort"

### Step 3 — ask confirm-restart-ollama-watchdog

**Purpose:** Operator approval gate before restarting ArcisOllamaWatchdog (which kills Ollama and releases VRAM per the v0.36.24 hotfix path). This ask satisfies the confirm-inheritance contract for `act restart-ollama-watchdog` at Step 4 (per spec §3.A4.1).

**Invocation:** AskUserQuestion (BLOCKING). Subject to Safety Window Gate.

**Safety Window Gate:** If current ET is between 21:30–22:30 ET AND `EMERGENCY = false`, this step is REFUSED per the Safety Window Gate (memory: `feedback_no_restart_during_overnight_window`). The restart is blocked — mid-cycle restart during this window forces a redundant overnight re-launch from scratch. Show the override options (wait until 22:30 ET, or re-run with `--emergency` for a genuine emergency).

> live-monitor confirms VRAM is held by Ollama with watchdog wedged (last heartbeat $AGE).
> Current ET: $NOW_ET.
> Action: `act restart-ollama-watchdog`
> Proposed command: `python -m src.tools.processmanager restart ArcisOllamaWatchdog --confirm --json`
> This will: kill Ollama → release VRAM → restart the watchdog → re-load the model.
> Verify step after restart: `python -m src.tools.healthprobe --service ArcisOllamaWatchdog --json`
> Proceed?

Options:
- "Approve — restart now" — continue to Step 4 (verified=true; satisfies confirm-inheritance contract §3.A4.1 requirements i–v)
- "Cancel" — STOP, audit event `arcis_operate.runbook.gpu-degraded.cancelled_at_step_3`

### Step 4 — act restart-ollama-watchdog

**Invocation:** `/arcis:operate act restart-ollama-watchdog` (inherits incident id).

Under the hood: `python -m src.tools.processmanager restart ArcisOllamaWatchdog --confirm --json`.

**Expected output:** Success envelope (FA8 shape):
```json
{"service": "ArcisOllamaWatchdog", "restarted": true, "verified": true, "elapsed_s": 8.2, "log_evidence": "...", "state": "RUNNING"}
```

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
