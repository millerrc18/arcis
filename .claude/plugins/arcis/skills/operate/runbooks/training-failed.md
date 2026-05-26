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
- ERROR found → record the error class, continue to Step 3 (crash branch)
- No ERROR, but training "skipped" / "no corpus" message → continue to Step 4 (corpus-stale branch, not crash)
- No log lines at all (trainer never started) → BRANCH: investigate scheduler — `/arcis:operate triage "trainer did not start overnight"` (dispatches live-monitor with FOCUS=ArcisWatchLoop + git-historian on scheduler.py). This is the not_started branch.

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

**Purpose:** Determine why corpus is small or corpus-stale. Check shadow_trades + recommendations row counts vs expected.

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
