# Action Authorization Matrix

This file is the source-of-truth for every `/arcis:operate act <action>` invocation. The orchestrator (`commands/operate.md`) reads it at Phase A1 to resolve action names to authorized CLI calls. Each row defines exactly one action: its verification status, auth class, the verbatim CLI invocation, the post-execution verify step, the risk level, and usage notes. The `auth_class` column drives the Safety Window Gate (skip for `auto-approved`; require confirm for all others). The `verify_step` column is printed to the operator in the Phase A4 confirm prompt and run in Phase A6.

Column definitions: **Action** = operator-facing name passed as `POSITIONAL_INPUT[1]`; **Verification** = one of `{verified, unverified-presumed, removed}` (no row remains `unverified-presumed` after impl-time probe — see PM verification section below); **Auth class** = one of `{auto-approved, confirm, confirm+safety_window, emergency-only-in-window}`; **CLI invocation** = verbatim subprocess command the orchestrator runs; **Verify step** = post-execution health check; **Risk** = operator-facing context (`low | medium | high`); **Notes** = usage guidance.

| Action | Verification | Auth class | CLI invocation | Verify step | Risk | Notes |
|---|---|---|---|---|---|---|
| `status-snapshot` | verified | auto-approved | per-service: `python -m src.tools.processmanager status {ArcisWatchLoop,ArcisOllamaWatchdog,ArcisDashboard} --json` (one call per service, composed in Phase S1, FB4 per-service pattern) | none (read-only) | low | Operator's "first thing I run." Same as `/arcis:operate status`. |
| `restart-watchloop` | verified | confirm+safety_window | `python -m src.tools.processmanager restart ArcisWatchLoop --confirm --json` | `python -m src.tools.healthprobe --service ArcisWatchLoop --json` | medium | Restart the watch loop NSSM service. Honors overnight window. Never use `python -m src.main startup` directly (memory: `reference_watch_loop_management`). |
| `restart-ollama-watchdog` | verified | confirm+safety_window | `python -m src.tools.processmanager restart ArcisOllamaWatchdog --confirm --json` | `python -m src.tools.healthprobe --service ArcisOllamaWatchdog --json` + `nvidia-smi --query-gpu=memory.used --format=csv,noheader` | medium | Restart the Ollama watchdog — frees VRAM as side effect. |
| `restart-dashboard` | verified | confirm+safety_window | `python -m src.tools.processmanager restart ArcisDashboard --confirm --json` | `python -m src.tools.healthprobe --service ArcisDashboard --json` | low | Restart dashboard. Lowest-risk of the 3 services. |
| `verify-nvidia-smi` | verified | confirm | `nvidia-smi --query-gpu=index,name,memory.used,memory.total --format=csv,noheader` | (re-run; verify no `[N/A]` in output) | low | Sanity check GPU visibility and VRAM allocation. |

---

## Removed actions (impl-time probe, 2026-05-26)

The following actions were listed as `unverified-presumed` in spec §7 and have been REMOVED after the mandatory impl-time CLI probe. No v1 runbook should reference these action names after the minimal runbook edits noted below.

| Action | Removed reason | CLI probed | Evidence |
|---|---|---|---|
| `force-broker-poll` | `src.tools.processmanager` subverb does not exist | `python -m src.tools.processmanager force-broker-poll --help` → exit 2: `invalid choice: 'force-broker-poll' (choose from status, start, stop, restart)` | Spec §14 OQ#2 — subverb never implemented |
| `post-pr-summary <pr>` | `src.tools.ci_summary_post` module does not exist | `python -m src.tools.ci_summary_post --help` → `No module named src.tools.ci_summary_post` | Spec §14 OQ#4 — module never created. Alternate `prcomments post` exists but takes `--body TEXT` not `--pr/--confirm` as presumed. |
| `regenerate-stale-audit` | `src.tools.auditor` module does not exist | `python -m src.tools.auditor --help` → `No module named src.tools.auditor` | Spec §14 OQ#3 — module never created |

**Runbook edits required:** `pg-tests-red.md` Step 6 referenced `post-pr-summary`. That step was edited to invoke `prcomments post` directly (the actual existing CLI) instead of routing through the removed act action.

---

## Implementing PM verification at impl time

**Date:** 2026-05-26  
**Branch:** `worktree-agent-affaefb641a4abfe4`

The following probes were run before writing matrix row content:

### Verified CLIs (rows kept)

`processmanager` (for `restart-*` and `status-snapshot`):
```
usage: python -m src.tools.processmanager [-h] [--confirm] [--emergency]
                                          [--json]
                                          {status,start,stop,restart} service
```
Verbs confirmed: `status`, `start`, `stop`, `restart`. Flags confirmed: `--confirm`, `--emergency`, `--json`.

`nvidia-smi` (for `verify-nvidia-smi`): confirmed available on host; `--query-gpu` and `--format=csv,noheader` flags are standard nvidia-smi invocation confirmed by spec author at spec time (pre-probe verified).

### Failed probes (rows removed)

1. `python -m src.tools.processmanager force-broker-poll --help`  
   Exit code 2. Output: `error: argument verb: invalid choice: 'force-broker-poll' (choose from status, start, stop, restart)`  
   → **Row removed.**

2. `python -m src.tools.ci_summary_post --help`  
   Exit code 1. Output: `No module named src.tools.ci_summary_post`  
   Also probed alternate: `python -m src.tools.prcomments post --help` — EXISTS, but CLI shape is `prcomments post <pr> --body TEXT [--confirm] [--json]` (not matching the specced `--pr <pr> --confirm --json` shape of the presumed `ci_summary_post` module).  
   → **`post-pr-summary` row removed.** Runbook `pg-tests-red.md` Step 6 edited minimally to invoke `prcomments post` directly.

3. `python -m src.tools.auditor --help`  
   Exit code 1. Output: `No module named src.tools.auditor`  
   → **Row removed.**

### Post-probe runbook grep

Grep of all 5 runbooks for removed action names before edits:

- `force-broker-poll`: 0 references found
- `ci_summary_post`: 0 references found
- `post-pr-summary`: 1 reference found — `pg-tests-red.md` line 155, Step 6 "Yes — post summary" option
- `regenerate-stale-audit`: 0 references found

Minimal edit applied to `pg-tests-red.md` Step 6 "Yes — post summary" option: replaced the removed act invocation with a direct `prcomments post` invocation.
