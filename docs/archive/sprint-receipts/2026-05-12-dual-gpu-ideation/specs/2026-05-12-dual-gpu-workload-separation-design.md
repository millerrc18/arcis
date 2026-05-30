# Dual-GPU Workload Separation — Strategy A Design Spec

**Brief:** `docs/audits/2026-05-12-dual-gpu-ideation/brief.md` (task #91)
**Status:** Spec-only deliverable. Implementation deferred to the first post-Sprint-5 maintenance window (Sprint 5 is the final sprint per `feedback_sprint_5_is_final`).
**Authoritative codebase reports:** deep report (Architect-side ingested), surface report (highlights only — Unsloth-pin-stale claim corrected by deep report).
**Hardware floor:** RTX 3090 (PCIe 01:00.0, 24 GB, 82 SMs) + RTX 3060 (PCIe 08:00.0, 12 GB, 28 SMs), Driver 596.36, CUDA 12.4 runtime, both Ampere CC 8.6. Identity of "GPU 0" and "GPU 1" is pinned by `CUDA_DEVICE_ORDER=PCI_BUS_ID` (see §5.0).
**Revision:** v3 (2026-05-12) — addresses Devil's Advocate findings: (a) replaced destructive `nssm set` copy-paste hazard with read-merge-write pattern citing post-cutover canonical env from Sprint 5 §J close / PR #1056, (b) pinned `CUDA_DEVICE_ORDER=PCI_BUS_ID` at every CUDA boundary, (c) tightened spec-vs-implementation boundary — prescriptive Python/PowerShell/dict literals moved to new non-normative Appendix D and the external `operator-guide-insert.md`, (d) downgraded OLLAMA_NUM_PARALLEL default 4→2 (operator-validated; 4 documented as opt-in after load-testing), (e) NSSM-wrapped `ollama_watchdog.ps1` as a new `ArcisOllamaWatchdog` service to resolve reboot survival (§16 Q5 resolved in-spec). New §21 Known Considerations captures 4 minor findings as acknowledged caveats. Prior v2 deltas retained.

---

## 1. Executive Summary

**Recommendation: Strategy A — disjoint workload pinning via `CUDA_VISIBLE_DEVICES` + `CUDA_DEVICE_ORDER=PCI_BUS_ID`.**

- **GPU 0 (RTX 3090, 24 GB, PCIe 01:00.0):** Training subprocess (`scripts/overnight_train.py` invoked via `vram_manager.launch_training_subprocess` → CURRICULUM_TRAIN_SCRIPT and DPO_TRAIN_SCRIPT) and `verify_training_readiness.py` dry-run.
- **GPU 1 (RTX 3060, 12 GB, PCIe 08:00.0):** Ollama daemon (serving `halcyon-v1` Qwen3-8B quantized; serves council inference; serves grammar_client when llama-cpp toggled).

**One-sentence justification:** Strategy A trades zero training-vs-inference VRAM contention for six env-var boundary discipline points (five `CUDA_VISIBLE_DEVICES` + one shared `CUDA_DEVICE_ORDER` pin), matching the strict-rigor mandate (`feedback_strict_rigor_no_handwave`) — every other candidate strategy (B/C/D/E) either (a) bottlenecks on the 3060's 12 GB cap for shared weights, (b) introduces PCIe round-trip latency on a non-NVLink link, or (c) leaves a GPU idle 99% of the time.

**Why now (operator memory):** RTX 3060 reinstalled 2026-05-12 03:50 ET alongside existing 3090; Sprint 5 is the final sprint (`feedback_sprint_5_is_final`); implementation deferred to the first post-Sprint-5 maintenance window per operator instruction.

**Net deliverable for post-Sprint-5 implementation:**
- ~15 file edits (no new modules in src/; one new NSSM service definition)
- One new NSSM-managed Windows service: `ArcisOllamaWatchdog`
- vram_manager.py deletion (Option A) — net -21 tests, must be replaced by ≥22 new dual-GPU tests to preserve 5050 test floor
- New operator-guide section (delivered via external `operator-guide-insert.md`) + 4 stale-text fixes
- One `verify_training_readiness.py` extension
- Zero schema changes (system_metrics widening optional; flagged as post-Sprint-5 follow-up if column-widening preferred)

---

## 2. Scope

### 2.1 In Scope (this spec)

- Recommendation of Strategy A with strict-rigor justification grounded in deep_report findings.
- Mechanism: the five `CUDA_VISIBLE_DEVICES` boundaries plus the shared `CUDA_DEVICE_ORDER=PCI_BUS_ID` pin (§5.0–§5.2).
- Explicit handling of the three deep-report footguns: `device_map='auto'` (trainer.py:154), the silent Ollama-restart-loses-GPU-pin path (client.py:107-137), the `n_gpu_layers=-1` watch-loop pinning case (grammar_client.py:145).
- vram_manager.py fate decision: **Option A — delete**, with Option B (gut+rename) documented as fallback; Option C (no-op wrapper) explicitly REJECTED per operator memory.
- Reboot survival: NSSM-wrap `ollama_watchdog.ps1` as a second managed service (resolves prior §16 Q5).
- Operator-guide additions: new "Dual-GPU Operation" subsection (delivered as `docs/audits/2026-05-12-dual-gpu-ideation/operator-guide-insert.md`, inserted immediately before the `### "Ollama crashes / corpus producing template fallbacks"` heading in `docs/operator-guide.md`) + enumerated stale-text fixes at lines 265, 632–635, 691–694, 159–161.
- Failure modes per card + recovery procedures.
- Verification plan (operator-runnable; extends `scripts/verify_training_readiness.py`).
- Test plan with named test functions and explicit test-count delta against the 5400 floor.
- post-Sprint-5 implementation read-list to close coverage gaps from deep report.
- Risk register.
- Open questions for post-Sprint-5 implementation.

### 2.2 Out of Scope (deferred or explicitly rejected)

| Item | Status | Rationale |
|---|---|---|
| Strategy E (3060 for sentence-transformers/embeddings) | Deferred to separate post-Sprint-5 design | Operator instruction: "separate post-Sprint-5 design". Single embedding call site in current codebase doesn't justify a dedicated card without explicit embedding workload scoping. *Note: the existing single embedding call site in `src/intel/leakage_detector.py` (POST /api/embeddings) already executes against Ollama on GPU 1 under Strategy A — incidental, not designed.* |
| Walk-forward framework GPU usage | Out of scope (post-Sprint-5 sprint) | Per brief §90 and operator instruction. |
| DPO_TRAIN_SCRIPT rewrite off Unsloth | Out of scope | **GPU upgrade update (`project_gpu_upgrade`):** CURRICULUM_TRAIN_SCRIPT has been rewritten to Transformers+PEFT+TRL (12→24 GB VRAM upgrade, 2026-05-10). DPO_TRAIN_SCRIPT (trainer.py:290–327) and CURRICULUM_TRAIN_SCRIPT GGUF-export fallback (lines 247–250) still require Unsloth; surface report's blanket "stale pin" claim is incorrect for DPO path. |
| Schema widening (per-GPU columns in `system_metrics`) | **Promoted to required (test set only)** | Implementation of widening itself remains optional. If operator declines schema change, the 4 tests become guard tests asserting current single-GPU behavior. Discussed in §13. |
| Telegram `/health` and `/gpu` per-GPU rendering | Deferred (flagged as post-Sprint-5 follow-up) | Touches `src/notifications/telegram_commands.py:672-691` and `:749-761`. Not blocking. |
| Implementation of Strategy A | Out of scope | SPEC_ONLY=true. Plan.md generated in the post-Sprint-5 window. |
| Strategy B (DDP/FSDP), C (pipeline parallel), D (hot-spare/OOM-rescue) | Rejected in §4.2 | Strict-rigor analysis below. |
| Cloud-burst, multi-host, AMD GPU support | Out of scope | Per brief §92–95. |

### 2.3 Hard Constraints (must not violate)

- **Test count floor: 5050.** Any tests deleted must be net-replaced. CI enforces (pg-tests.yml EXPECTED=5050 as of Sprint 5 Phase 2).
- **Schema registry discipline.** No DDL outside `src/schema/registry.py`.
- **Subprocess-exits-reclaim-VRAM invariant must be preserved.** Training process MUST remain a subprocess.
- **No Unsloth removal.** DPO + GGUF export still depend on it.
- **No new embedding/sentence-transformers surface introduced.** Strategy E is a separate spec.
- **Same-PR operator-guide rule (`CLAUDE.md`).**
- **vram_manager Option C (no-op wrapper) is REJECTED** per operator strict-rigor memory.
- **NSSM AppEnvironmentExtra is replacement, not append.** Any change to NSSM env MUST follow the read-merge-write pattern in §5.2 B1. **Verbatim copy-paste of partial env blocks is forbidden** — it silently strips required production vars (post-cutover state: `ARCIS_DB_PATH`, `SYNC_THREAD_ENABLED=false`, `DATABASE_URL`, `ARCIS_PG_CUTOVER_ENABLED=1`, `PYTHONUTF8=1`). Reference: Sprint 5 §J close (PR #1056), operator memory `reference_watch_loop_management`.
- **`CUDA_DEVICE_ORDER=PCI_BUS_ID` MUST be set at every CUDA-consuming boundary.** Default (`FASTEST_FIRST`) can re-order GPUs across driver upgrades or PCIe reseats, silently flipping GPU 0 / GPU 1 identity (see §5.0).

---

## 3. Current State Architecture (Pre-Strategy-A)

### 3.1 Single-GPU mutual-exclusion contract (today)

The codebase is built around the premise that **Ollama and PyTorch training cannot coexist on the 3060's 12 GB** (vram_manager.py docstring, lines 10–11). This drives a coordinated handoff protocol:

```
6:50 PM ET — run_evening_handoff (overnight.py:827)
  └─ vram_manager.handoff_to_training()
      ├─ POST /api/chat with keep_alive=0 (unload Ollama model)
      ├─ poll get_vram_used_mb until <2500 MB OR taskkill ollama
      ├─ torch.cuda.empty_cache() ×3 with 15s backoff
      └─ verify VRAM clear
  └─ vram_manager.launch_training_subprocess('overnight', ['-m','scripts.overnight_train'])
      └─ bare subprocess.Popen(...) — NO env= kwarg; inherits OS env

5:15 AM ET — run_morning_handoff (overnight.py:874)
  └─ vram_manager.handoff_to_inference()
      ├─ ensure no training subprocess running
      ├─ POST /api/generate with keep_alive='18h'
      └─ verify Ollama serving
```

### 3.2 Verified call-graph facts (from deep report)

| Site | File:Line | Behavior | Strategy A implication |
|---|---|---|---|
| `get_vram_used_mb` | `vram_manager.py:85-100` | `nvidia-smi --query-gpu=memory.used` (no `-i` flag) → `split("\n")[0]` | Reads GPU 0 only. Whole-system semantics broken on dual-GPU. |
| `launch_training_subprocess` | `vram_manager.py:365-383` | `subprocess.Popen([sys.executable]+script_args, ...)` | NO `env=` kwarg. CUDA_VISIBLE_DEVICES inherits from parent (NSSM ArcisWatchLoop). |
| `_kill_ollama_processes` | `vram_manager.py:180-194` | `taskkill /f /im ollama.exe + ollama_llama_server.exe` | Under Strategy A this kills the wrong-card workload — completely unnecessary. |
| `_reload_ollama` `keep_alive="18h"` | `vram_manager.py:145` | Morning warm-load TTL | Becomes redundant under Strategy A. |
| `_check_ollama_health_or_restart` | `client.py:107-137` (function spans full range; Popen at lines 122-127; WARN log at line 117-118) | `subprocess.Popen(['ollama','serve'], ...)` with no env= | **FOOTGUN:** if watch loop restarts Ollama, it inherits watch-loop env, NOT watchdog's GPU 1 pinning. |
| `Llama(model_path=..., n_gpu_layers=-1)` | `grammar_client.py:140-150` | llama-cpp loads in watch-loop process | Defaults to GPU 0 absent CUDA_VISIBLE_DEVICES — competes with training. |
| `device_map="auto"` (training) | `trainer.py:154` (CURRICULUM_TRAIN_SCRIPT) | accelerate auto-shards across visible GPUs | Without CUDA_VISIBLE_DEVICES=0, shards 4-bit Qwen3-8B across both. |
| `device_map="auto"` (regenerated artifact) | `training_data/train.py:23` | Overwritten by trainer.py:744-745 on every fine-tune | NOT a separate source. |
| `device_map="auto"` (dry-run) | `verify_training_readiness.py:174` | Qwen2.5-0.5B single-step dry-run | Same auto-shard footgun. |
| `torch.cuda.get_device_name(0)` | `verify_training_readiness.py:61` | Hard-coded GPU 0 device-name probe | Strategy A wants 3090 on GPU 0 — extend check to fail loud if not. |
| `subprocess.run(...)` for trainer dry-run | `trainer.py:756-761` | `subprocess.run([sys.executable, str(script_path)], ...)` with no env= | Inherits OS env. |
| `Start-OllamaHeadless` | `ollama_watchdog.ps1:60-72` | `Start-Process -FilePath $ollamaExe -ArgumentList 'serve' ...` | NO env injection. Child process inherits PARENT shell env. |
| `_collect_gpu_metrics` | `system_metrics.py:33-59` | `nvidia-smi --query-gpu=...` no `-i` | Captures FIRST GPU only. |
| `_cmd_health` | `telegram_commands.py:672-691` | parses nvidia-smi CSV with `split(', ')` | Single-line assumption — misrenders on dual-GPU. |
| `_cmd_gpu` | `telegram_commands.py:749-761` | passes raw nvidia-smi stdout | Already dual-GPU-friendly. |

### 3.3 What works today (pre-Strategy-A) and must continue to work

- Ollama serves `halcyon-v1` Qwen3-8B (~5–6 GB resident) during market hours.
- Council inference funnels through `src/llm/client.py:generate()` (1 chokepoint; ~20+ call sites).
- Evening at 6:50 PM ET, training subprocess launches via `scripts.overnight_train`.
- Morning at 5:15 AM ET, Ollama is reloaded with `keep_alive='18h'`.
- Test floor 5050. Schema 70 tables.

### 3.4 What fails or becomes brittle under dual-GPU without Strategy A

1. `device_map='auto'` shards 4-bit Qwen3-8B across BOTH cards — 3060 caps throughput.
2. `get_vram_used_mb` returns only GPU 0 memory — Ollama on GPU 1 is invisible.
3. Operator runs `nvidia-smi`, sees idle on one card, and runs another job — silent collision.
4. Watch loop's `_check_ollama_health_or_restart` could relaunch Ollama on the wrong card.
5. system_metrics table reports one card's stats.

### 3.5 NSSM `ArcisWatchLoop` post-Sprint-5 canonical env state

Per operator memory `reference_watch_loop_management` and Sprint 5 §J close (PR #1056), the **current production** `AppEnvironmentExtra` block contains (at minimum) the following five variables. **Any post-Sprint-5 change to this block MUST preserve all of them**:

| Variable | Current value | Source / why required |
|---|---|---|
| `ARCIS_DB_PATH` | `C:/arcis/data/ai_research_desk.sqlite3` | CLAUDE.md repo-layout contract; src/config/__init__.py:55-56 |
| `SYNC_THREAD_ENABLED` | `false` | Sprint 5 §J: SQLite→Postgres dual-write sync thread is OFF post-cutover. Defaults to `true`; silently re-enabling it brings back the deprecated sync path. |
| `DATABASE_URL` | `postgresql://halcyon_app:<password>@localhost:5433/halcyon` | Sprint 5 §J: Postgres is now primary read path. |
| `ARCIS_PG_CUTOVER_ENABLED` | `1` | Sprint 5 §J: gates the read-from-Postgres code paths. Cutover-gate flag. |
| `PYTHONUTF8` | `1` | UTF-8 encoding for training logs (subject to operator's local config — verify via `nssm get` before assuming presence). |

post-Sprint-5 work's job is to **append** two new variables to this block: `CUDA_VISIBLE_DEVICES=0` and `CUDA_DEVICE_ORDER=PCI_BUS_ID`. The procedural pattern in §5.2 B1 enforces this — read first, merge in code, write the merged block.

---

## 4. Target State Architecture (Strategy A)

### 4.1 Disjoint workload pinning

```
┌──────────────────────────────────┐    ┌──────────────────────────────────┐
│  GPU 0 — RTX 3090 (24 GB)         │    │  GPU 1 — RTX 3060 (12 GB)         │
│  PCIe 01:00.0                     │    │  PCIe 08:00.0                     │
│                                  │    │                                  │
│  Training subprocess              │    │  Ollama daemon (always-on)        │
│  ─ overnight_train.py             │    │  ─ halcyon-v1 (Qwen3-8B q4)       │
│  ─ verify_training_readiness.py   │    │  ─ council inference              │
│  ─ trainer.run_fine_tune dry-run  │    │  ─ grammar_client llama-cpp       │
│                                  │    │    (if use_grammar_enforcement)   │
│  Pinned via:                     │    │                                  │
│  CUDA_VISIBLE_DEVICES=0           │    │  Pinned via:                     │
│  CUDA_DEVICE_ORDER=PCI_BUS_ID     │    │  CUDA_VISIBLE_DEVICES=1           │
│  (NSSM ArcisWatchLoop env +       │    │  CUDA_DEVICE_ORDER=PCI_BUS_ID     │
│   operator interactive shell)     │    │  (NSSM ArcisOllamaWatchdog env +  │
│                                  │    │   ollama_watchdog.ps1)            │
└──────────────────────────────────┘    └──────────────────────────────────┘
```

### 4.2 Why not strategies B/C/D/E (strict-rigor justification)

**Strategy B — Asymmetric DDP / FSDP.** Mixed-VRAM DDP requires each GPU to hold a full model replica; the 3060's 12 GB caps replica size. FSDP can shard parameters, but inter-GPU bandwidth on PCIe (no NVLink) bottlenecks every all-gather. trainer.py:CURRICULUM_TRAIN_SCRIPT does NOT currently use DDP/FSDP — rewrite is high-risk for marginal throughput gain. Rejected.

**Strategy C — Pipeline parallel.** Qwen3-8B 4-bit fits comfortably on the 3090 alone (~5 GB resident); pipeline-parallel adds per-step PCIe activation transfer with no offsetting win. Rejected.

**Strategy D — Hot-spare / OOM rescue.** 3060 sits idle 99% of the time; OOM-rescue triggers the `device_map='auto'` footgun we're trying to eliminate. Rejected.

**Strategy E — 3060 for embeddings.** Surface report finds 1 embedding call site. Not enough work to justify a dedicated card. Properly scoped as a separate post-Sprint-5 design. *Note: the existing single embedding call site in `src/intel/leakage_detector.py` already executes against Ollama on GPU 1 incidentally — Strategy A subsumes it without explicit design.* Deferred.

**Strategy A wins because:** (a) zero training-vs-inference contention, (b) minimal code change, (c) preserves the subprocess-exits-reclaim-VRAM invariant, (d) operator-controllable via two NSSM services + one ps1 script (three clear ownership surfaces).

### 4.3 Invariants preserved

- **Subprocess training architecture.** Process exit guarantees VRAM reclamation on GPU 0.
- **Single Ollama chokepoint.** `src/llm/client.py:generate()` remains the only Ollama-callsite path.
- **Schema unchanged (default).**
- **Test floor 5400.**
- **Same-PR operator-guide rule.**
- **Post-Sprint-5 NSSM env preserved** (see §3.5).

### 4.4 Invariants broken (intentionally)

- **Evening/morning handoff cadence.** Deprecated.
- **vram_manager.py mutual-exclusion contract.** Premise invalidated. Module deleted (Option A) or gutted (Option B).
- **`keep_alive='18h'`.** Redundant.
- **`ollama_watchdog.ps1` launched only via `start_ollama_watchdog.bat` from an SSH shell.** Replaced by NSSM service `ArcisOllamaWatchdog` (§6 required item) for reboot survival.

---

## 5. Mechanism — Env-Var Boundaries

The load-bearing mechanism is two CUDA env vars set at six process boundaries (one CUDA_DEVICE_ORDER pin shared across all, five CUDA_VISIBLE_DEVICES bindings — three target 0, two target 1, plus the watch-loop process whose pin matches B1). Missing any one creates a silent footgun.

### 5.0 CUDA enumeration order pin (B0 — applies to every boundary)

**Boundary:** every CUDA-consuming process — same boundaries as B1–B5 below plus the new `ArcisOllamaWatchdog` NSSM env.

**Variable:** `CUDA_DEVICE_ORDER=PCI_BUS_ID`

**Why:** CUDA's default `CUDA_DEVICE_ORDER=FASTEST_FIRST` ranks devices by compute capability × SM count × clock, which for an RTX 3090 + RTX 3060 mix puts the 3090 at index 0 today — but this is **not guaranteed across driver upgrades, GPU swaps, or PCIe reseats**. NVIDIA driver release notes have changed the FASTEST_FIRST tie-breaker before. A silent flip of GPU 0 / GPU 1 identity would route training to the 3060 (catastrophic — 12 GB insufficient for Qwen3-8B fine-tune) and Ollama to the 3090 (works but wastes the bigger card).

Pinning `PCI_BUS_ID` makes ordering deterministic from PCIe enumeration. With the 3090 in PCIe slot 01:00.0 (lower bus number) and the 3060 in 08:00.0, GPU 0 = 3090 is stable as long as the hardware layout is unchanged.

**Where it must be set:** at every boundary listed in §5.1. Defense-in-depth: also at the source level inside `scripts/verify_training_readiness.py` (set in `os.environ` at module top before any torch import) so even a manually-invoked dry-run on a misconfigured shell is protected. (Implementation guidance: see Appendix D §D.1.)

**Where it is currently UNSET (verified gap):** all five boundaries. post-Sprint-5 implementation closes this.

### 5.1 Boundary inventory

| # | Boundary | Owner surface | `CUDA_VISIBLE_DEVICES` | `CUDA_DEVICE_ORDER` | Why |
|---|---|---|---|---|---|
| B0 | Every CUDA-consuming process | (cross-cutting) | (varies — see B1–B5) | `PCI_BUS_ID` | Pin enumeration order so GPU 0 = 3090 is deterministic. See §5.0. |
| B1 | NSSM `ArcisWatchLoop` service env | `nssm set ArcisWatchLoop AppEnvironmentExtra ...` (read-merge-write pattern — see §5.2 B1) | `0` | `PCI_BUS_ID` | Watch loop spawns training subprocess via `launch_training_subprocess` (Popen with no env=). Subprocess inherits parent env. **Primary training-pin path.** |
| B2 | `scripts/ollama_watchdog.ps1` (process scope) | Script edit at script top, before `Start-OllamaHeadless` | `1` | `PCI_BUS_ID` | `Start-Process` with no `-Environment` inherits parent shell env. |
| B2′ | NEW: NSSM `ArcisOllamaWatchdog` service env | `nssm set ArcisOllamaWatchdog AppEnvironmentExtra ...` | `1` | `PCI_BUS_ID` | When watchdog is NSSM-managed (§6 required item), its env carries the GPU 1 pin so reboot recovery is automatic — even if `ollama_watchdog.ps1` is later edited and the in-script `$env:` lines stripped, the service env still provides the pin. |
| B3 | Operator interactive shell (PowerShell) | User-scope persistent env var (training context); or per-shell `$env:` assignment | `0` (training context) | `PCI_BUS_ID` | When operator runs `python scripts/verify_training_readiness.py` or training directly. |
| B4 | `scripts/overnight_train.py` invocation env | Inherited from B1 (watch-loop NSSM) OR explicit operator export when run manually | `0` | `PCI_BUS_ID` | The actual training entrypoint. Deep report coverage gap: file not read; post-Sprint-5 plan reads to confirm no env-stripping. |
| B5 | Watch-loop process itself (for grammar_client llama-cpp) | NSSM `ArcisWatchLoop` env via B1 | `0` (matches B1) | `PCI_BUS_ID` (matches B1) | grammar_client.py:145 loads llama-cpp in the watch-loop process with `n_gpu_layers=-1` if grammar enforcement on. Inherits B1. |

### 5.2 Operator-runnable commands per boundary

#### B1 — NSSM ArcisWatchLoop env injection (training-pin) — READ-MERGE-WRITE

**HAZARD WARNING.** NSSM `AppEnvironmentExtra` is a **replacement** operation, not append. Naive copy-paste of a partial env block silently wipes the post-cutover production env state (§3.5) — re-enabling the deprecated SQLite→Postgres sync thread, reverting the cutover gate, and breaking the Postgres primary read path. The procedure below MUST be followed.

**Procedure (prose; exact commands in Appendix D §D.2):**

1. **Capture current env.** Run `nssm get ArcisWatchLoop AppEnvironmentExtra > pre-change-env.txt` and include the captured block in the post-Sprint-5 PR description (per §13 guardrail). The captured block IS the source of truth; do not rely on the values in §3.5 if they have drifted.
2. **Verify post-Sprint-5 canonical vars are present.** Confirm presence of: `ARCIS_DB_PATH`, `SYNC_THREAD_ENABLED=false`, `DATABASE_URL`, `ARCIS_PG_CUTOVER_ENABLED=1`. If any are missing, **STOP** and escalate to the operator — a missing post-cutover var indicates env drift independent of this work. Note `PYTHONUTF8=1` as currently-present-or-absent (don't add it if absent).
3. **Merge in the two new vars.** Construct the new env block as (captured vars) ∪ {`CUDA_VISIBLE_DEVICES=0`, `CUDA_DEVICE_ORDER=PCI_BUS_ID`}.
4. **Write the merged block.** Issue a single `nssm set ArcisWatchLoop AppEnvironmentExtra` with the full list (one `"NAME=VALUE"` per line in PowerShell back-tick continuation).
5. **Restart and verify.** `nssm restart ArcisWatchLoop`. Wait 5–10s. Verify with the §5.2-B1 startup-banner approach below (NOT via `Get-Process StartInfo.EnvironmentVariables` — see §21 minor #1).

**Verification (post-restart):** Add a startup-banner log line to `src/scheduler/watch.py` startup path that emits the current CUDA env at INFO level. Operator tails `C:\arcis\logs\watchdog.log` for the banner. Required post-Sprint-5 addition (see §6). Expected line: `[startup] CUDA env: CUDA_VISIBLE_DEVICES=0 CUDA_DEVICE_ORDER=PCI_BUS_ID device_count=1 gpu0=NVIDIA GeForce RTX 3090`.

**Why a startup banner instead of `Get-Process StartInfo.EnvironmentVariables`:** the latter does not return child env for processes you didn't start (Windows ACL behavior), so the verification command would silently return empty for the NSSM-spawned watch loop and confuse the operator. The log-line approach reads back what the process actually saw.

**Sibling-search reminder (`feedback_review_sibling_search`):** when post-Sprint-5 implementation hardens this path, GREP `subprocess.Popen` and `subprocess.run` across `src/` for OTHER call sites that need similar env discipline. Known sites: `vram_manager.py:376`, `client.py:107-137`, `trainer.py:756-761`, `vram_manager.py:266`. Each audited for env-stripping.

#### B2 — ollama_watchdog.ps1 script edit (inference-pin)

**Change in prose:** at the top of `scripts/ollama_watchdog.ps1` (after param block, before `Start-OllamaHeadless` is defined), assign:
- `$env:CUDA_VISIBLE_DEVICES = '1'`
- `$env:CUDA_DEVICE_ORDER = 'PCI_BUS_ID'`
- `$env:OLLAMA_NUM_PARALLEL = '2'` (default; see §6.4 for the rationale and the opt-in path to 4)

Add `Log` lines immediately after that emit the three values. Add a corresponding `Log` line at the `Start-Process` invocation in `Start-OllamaHeadless` recording the resolved env that Ollama will inherit.

**Why option `$env:` assignment (vs `setx` User-scope or `Start-Process -Environment`):** inspectable in source control, no system-wide pollution, survives ps1 edits.

Exact code snippet for post-Sprint-5 implementer reference: Appendix D §D.3 (non-normative).

**Verify after edit:** stop Ollama (`Get-Process ollama,ollama_llama_server -ErrorAction SilentlyContinue | Stop-Process -Force`), relaunch via the new NSSM service (§6 — `nssm restart ArcisOllamaWatchdog`), wait 10s, and confirm Ollama is on GPU 1 only via `nvidia-smi -i 1 --query-compute-apps=pid,process_name,used_memory --format=csv` (expect `ollama_llama_server.exe` with non-zero memory) and `nvidia-smi -i 0 ...` (expect empty).

#### B2′ — NEW: NSSM `ArcisOllamaWatchdog` service env

Same procedure as B1 (read-merge-write), but for the new service. Initial install has no pre-existing env, so the procedure simplifies to: `nssm set ArcisOllamaWatchdog AppEnvironmentExtra "CUDA_VISIBLE_DEVICES=1" "CUDA_DEVICE_ORDER=PCI_BUS_ID"`. post-Sprint-5 implementer codifies the install command in `scripts/install_ollama_watchdog_service.ps1` (per §6) so the install is reproducible and reviewable.

#### B3 — Operator interactive shell (one-off training commands)

Operator-side procedure (prose): set persistent User-scope env vars `CUDA_VISIBLE_DEVICES=0` and `CUDA_DEVICE_ORDER=PCI_BUS_ID` via the User-scope Environment API; open a fresh PowerShell window for the values to take effect; verify with `echo $env:CUDA_VISIBLE_DEVICES` and the dual-GPU readiness check (see §10.4).

#### B4 — scripts/overnight_train.py (training entrypoint, env-inherit)

No direct edit needed if B1 is set correctly — Popen inheritance propagates. **Coverage gap from deep report:** `scripts/overnight_train.py` was NOT read in this dispatch. post-Sprint-5 plan must read it (§15) to confirm no `env=` override or `os.environ.pop('CUDA_VISIBLE_DEVICES')` anti-pattern. Defense-in-depth: if env-stripping found, set both `CUDA_VISIBLE_DEVICES` and `CUDA_DEVICE_ORDER` at script top via `os.environ.setdefault(...)` before any torch import.

#### B5 — Watch-loop process for grammar_client.py llama-cpp

Inherits B1's `CUDA_VISIBLE_DEVICES=0` + `CUDA_DEVICE_ORDER=PCI_BUS_ID`. If `llm.use_grammar_enforcement: false` (current default per `config/settings.example.yaml:315`), this is a no-op — `_load_runtime` is never called.

**Footgun if grammar is enabled later:** llama-cpp with `n_gpu_layers=-1` loads in the watch-loop process and competes with training on GPU 0. Mitigations in §9.

### 5.3 Mechanism summary

- **Two code edits:** `trainer.py:154` (device_map fail-fast) and `verify_training_readiness.py:60-76` (extend device check + CUDA_DEVICE_ORDER assertion).
- **One script edit:** `ollama_watchdog.ps1` top (env injection: `CUDA_VISIBLE_DEVICES=1`, `CUDA_DEVICE_ORDER=PCI_BUS_ID`, `OLLAMA_NUM_PARALLEL=2`).
- **One client-path simplification:** `client.py:107-137` (delegate restart to watchdog — §8).
- **Two NSSM service env updates:** `ArcisWatchLoop` (read-merge-write) and new `ArcisOllamaWatchdog` (install + initial env).
- **One new install script:** `scripts/install_ollama_watchdog_service.ps1` (NSSM service install + env).
- **Zero schema changes. Zero API changes.**

---

## 6. Code Changes Catalog

Described at the file-and-change level; prescriptive code blocks belong in Appendix D (non-normative implementation guidance). post-Sprint-5 implementers produce the diffs.

### 6.1 `src/training/trainer.py`

**Change:** Replace `device_map='auto'` with `device_map={'': 0}` in `CURRICULUM_TRAIN_SCRIPT` at line 154.

**Why:** Fail-fast belt-and-suspenders. If `CUDA_VISIBLE_DEVICES=0` is missing, `device_map='auto'` silently shards across both visible GPUs; `device_map={'': 0}` raises a clear error.

**Where:** trainer.py:154 inside the `CURRICULUM_TRAIN_SCRIPT` triple-quoted string. **Note:** `training_data/train.py:23` is the regenerated artifact; do NOT edit directly.

**Test coverage:** new test `test_curriculum_train_script_pins_device_zero`.

### 6.2 `src/training/trainer.py` (secondary — DPO_TRAIN_SCRIPT)

**Change:** Audit DPO_TRAIN_SCRIPT (lines 290–327) for any `device_map` references. Unsloth's `FastLanguageModel.from_pretrained` defaults single-device. **post-Sprint-5 plan verifies by reading DPO_TRAIN_SCRIPT in full.**

### 6.3 `scripts/verify_training_readiness.py`

**Change:** Extend `_check_cuda()` (lines 53–76) and add a new check function `_check_dual_gpu_layout()`.

**Specifics (prose):**
- Tighten the soft warning at line 66 to a HARD FAIL if `torch.cuda.device_count() >= 2` AND GPU 0 is not the 3090. Under dual-GPU, mismatched ordering = silently training on the 3060.
- New `_check_dual_gpu_layout`:
  - Read `torch.cuda.device_count()`. Log the count.
  - **NEW:** assert `os.environ.get('CUDA_DEVICE_ORDER') == 'PCI_BUS_ID'`; emit WARNING (not FAIL) if unset, FAIL if set to a different value. Rationale: hard-pin protects against driver-upgrade enumeration flips.
  - If count >= 2 AND `CUDA_VISIBLE_DEVICES` is unset, emit WARNING.
  - If count >= 2 AND GPU 0 is not the 3090, HARD FAIL.
  - If count == 1 AND GPU 0 is not the 3090, HARD FAIL.
- Also fix the dry-run footgun at line 174 (`device_map='auto'` → `{'': 0}`).

**Test coverage:**
- `test_check_cuda_fails_when_gpu0_not_3090_on_dual_gpu`
- `test_check_cuda_warns_when_cuda_visible_devices_unset_on_dual_gpu`
- `test_check_cuda_passes_when_gpu0_is_3090_with_cuda_visible_devices_set`
- `test_check_cuda_fails_when_single_gpu_is_not_3090`
- `test_dual_gpu_layout_warns_when_cuda_device_order_unset` (NEW — B0 coverage)

### 6.4 `scripts/ollama_watchdog.ps1`

**Change (prose):** at the top of the script (after param block, before any function definition), set three env variables in process scope: `CUDA_VISIBLE_DEVICES = '1'`, `CUDA_DEVICE_ORDER = 'PCI_BUS_ID'`, `OLLAMA_NUM_PARALLEL = '2'` (default 2 — see rationale below). Add three `Log` lines immediately after these assignments emitting the chosen values. In `Start-OllamaHeadless` (around line 67), add one `Log` line immediately before the `Start-Process` invocation recording the env that Ollama will inherit.

**Why `OLLAMA_NUM_PARALLEL = '2'` (not 4):** the operator-validated configuration from `feedback project_gpu_upgrade` and operator-guide §5 reports NUM_PARALLEL=4 = ~10.4 GB resident on the 3060, leaving ~0.4 GB cushion. That cushion is **below typical CUDA workspace transient allocations** (~512 MB) and is insufficient for 5-agent concurrent council bursts — which can spike beyond model+KV resident memory by hundreds of MB. NUM_PARALLEL=2 is operator-validated as steady-state safe (~1.7 GB cushion). NUM_PARALLEL=4 remains available as an **opt-in** configuration after the operator runs the §10.6 load-test and confirms `nvidia-smi -i 1 memory.used` stays below 11.5 GB.

**Why option `$env:` (vs `setx` User-scope or `Start-Process -Environment`):** inspectable in source control. No system-wide env pollution. Survives ps1 edits.

For the implementer's reference code, see Appendix D §D.3.

**Test coverage:** None at pytest level. Source-level guardrail test in §13 (`test_ollama_watchdog_ps1_sets_cuda_env_vars`) checks the file contents.

### 6.5 `scripts/start_ollama_watchdog.bat`

**Coverage gap:** Deep report did not read this file. post-Sprint-5 plan reads it to confirm it doesn't strip env vars. Likely a no-op wrapper. Note: under the new NSSM-managed model (§6.x), the .bat may become unused (replaced by NSSM service start). Decision deferred to the post-Sprint-5 window.

### 6.6 `src/llm/client.py`

**Change:** Replace the Ollama-restart-from-watch-loop path at `client.py:107-137` (`_check_ollama_health_or_restart`) with a health-check + log function. **Remove the `subprocess.Popen` invocation entirely** (lines 122-127). On unavailability, log at ERROR level and return False. **Rename** `_check_ollama_health_or_restart` → `_check_ollama_health` (truthful name).

**Why (deep report focus area 4 footgun):** the current Popen at lines 122-127 inherits the watch-loop's `CUDA_VISIBLE_DEVICES=0` env from B1, launching Ollama on the 3090 — wrong card. The `ollama_watchdog.ps1` (running under the new `ArcisOllamaWatchdog` NSSM service) already monitors Ollama health and restarts it with the correct GPU 1 pinning. Single-responsibility: watchdog owns Ollama lifecycle.

**Test coverage:**
- `test_check_ollama_health_returns_true_when_available`
- `test_check_ollama_health_returns_false_and_does_not_relaunch_when_unavailable`
- `test_check_ollama_health_logs_at_error_level`

### 6.7 `src/llm/grammar_client.py`

**Change:** Read `n_gpu_layers` from config with default `0` (CPU-only). Adds a `llm.grammar_n_gpu_layers` config key (default 0).

**Test coverage:** new file `tests/test_grammar_client_device_binding.py` (2 tests). See §9.

### 6.8 `src/scheduler/vram_manager.py` — DELETE (Option A)

See §7 for full rationale. Module deleted in entirety; callers in `src/scheduler/overnight.py:827, 874` and `src/scheduler/watch.py:2155, 2161` updated.

### 6.9 `src/scheduler/overnight.py`

**Change:** Delete `run_evening_handoff` (around line 827) and `run_morning_handoff` (around line 874). Training-launch path moves to `src/training/launcher.py` (§6.10).

### 6.10 NEW: `src/training/launcher.py`

**Change:** New module with one function: `launch_training_subprocess(task_name: str, script_args: list[str]) -> subprocess.Popen | None`. Function signature preserves the existing one in `vram_manager.py`.

**Implementation note for post-Sprint-5 (non-normative):** the implementer must decide between (a) bare Popen (relies on NSSM B1 env propagation) and (b) explicit `env=` kwarg merging os.environ with `CUDA_VISIBLE_DEVICES='0'` and `CUDA_DEVICE_ORDER='PCI_BUS_ID'`. Defense-in-depth (option b) is **recommended** because it makes the GPU binding inspectable in source; NSSM env remains the primary operational config. Reference dict shape: Appendix D §D.4 (non-normative).

**Test coverage:**
- `test_launch_training_subprocess_returns_popen_handle`
- `test_launch_training_subprocess_injects_cuda_visible_devices_zero`
- `test_launch_training_subprocess_injects_cuda_device_order_pci_bus_id` (NEW — B0 coverage)
- `test_launch_training_subprocess_preserves_other_env_vars` — assert ARCIS_DB_PATH, SYNC_THREAD_ENABLED, DATABASE_URL, ARCIS_PG_CUTOVER_ENABLED, PYTHONUTF8 all propagate when present in the fixture environment
- `test_launch_training_subprocess_redirects_stdout_to_log_file`
- `test_launch_training_subprocess_redirects_stderr_to_log_file`

### 6.11 `src/scheduler/watch.py`

**Changes:**
- Update calls at lines ~2155 and ~2161 (handoff invocations) — remove or convert to direct training-launch call.
- **NEW:** Add a CUDA env startup banner emission at watch-loop startup path. Log line: `[startup] CUDA env: CUDA_VISIBLE_DEVICES=<value> CUDA_DEVICE_ORDER=<value> device_count=<n> gpu0=<name>`. INFO level. Required for §5.2 B1 verification path. Cross-references §10.2.

post-Sprint-5 plan greps `vram_handoff_*` metric writes; removes obsolete ones.

### 6.12 `tests/test_vram_manager.py` — DELETE

**21 tests removed** (verified by `grep -c '^def test_' tests/test_vram_manager.py` = 21).

### 6.13 `src/monitoring/system_metrics.py` — OPTIONAL (implementation), REQUIRED (tests)

**Change:** Per-GPU iteration in `_collect_gpu_metrics` is implementation-deferred. Tests REQUIRED (see §13).

### 6.14 `src/notifications/telegram_commands.py` — OPTIONAL

**Change (deferred):** Per-GPU rendering for `_cmd_health`.

### 6.15 `config/settings.example.yaml` — OPTIONAL informational keys

**Change (deferred):** `llm.gpu_device: 1` and `training.gpu_device: 0` as informational keys.

**ALSO (required if §9 hardening lands):** add `llm.grammar_n_gpu_layers: 0` as documented default.

### 6.16 NEW: `scripts/install_ollama_watchdog_service.ps1` — NSSM service install (REQUIRED for reboot survival)

**Change:** New PowerShell script that installs `ollama_watchdog.ps1` as an NSSM service called `ArcisOllamaWatchdog`. Idempotent — safe to re-run.

**What it does (prose):**
1. Check if `ArcisOllamaWatchdog` already exists; if so, stop and remove (idempotent install).
2. `nssm install ArcisOllamaWatchdog <path-to-powershell.exe> -ExecutionPolicy Bypass -NoProfile -File C:\arcis\halcyon-lab\scripts\ollama_watchdog.ps1`
3. `nssm set ArcisOllamaWatchdog AppDirectory C:\arcis\halcyon-lab`
4. `nssm set ArcisOllamaWatchdog AppEnvironmentExtra "CUDA_VISIBLE_DEVICES=1" "CUDA_DEVICE_ORDER=PCI_BUS_ID"`
5. `nssm set ArcisOllamaWatchdog AppStdout C:\arcis\logs\ollama-watchdog.log`
6. `nssm set ArcisOllamaWatchdog AppStderr C:\arcis\logs\ollama-watchdog.log`
7. `nssm set ArcisOllamaWatchdog Start SERVICE_AUTO_START`
8. `nssm start ArcisOllamaWatchdog`
9. Operator-readable status check at end.

**Why a service install script instead of operator manual:** install is part of the post-Sprint-5 PR (same-PR rule). Operator runs the script once at deploy time; subsequent reboots have Ollama survival baked in. The script is checked into source control so SP7+ operators can audit how the service was installed.

**Test coverage:** none at pytest level. Source-level guardrail test in §13: `test_install_ollama_watchdog_service_ps1_pins_gpu_one_and_pci_bus_id` (greps the install script for the two CUDA env values).

### 6.17 Summary table — files touched in post-Sprint-5 implementation

| File | Change type | Lines impacted | Required/optional |
|---|---|---|---|
| `src/training/trainer.py` | device_map fail-fast | 1 line | Required |
| `scripts/verify_training_readiness.py` | extend device check + dry-run device_map + CUDA_DEVICE_ORDER assertion | ~35 lines | Required |
| `scripts/ollama_watchdog.ps1` | env injection at top + 3 Log lines | ~7 lines | Required |
| `src/llm/client.py` | remove restart-Popen path at lines 107-137 | ~30 lines deleted | Required |
| `src/scheduler/vram_manager.py` | DELETE | full file (~400 lines) | Required (Option A) |
| `src/scheduler/overnight.py` | gut handoff wrappers | ~80 lines | Required |
| `src/scheduler/watch.py` | update call sites + ADD startup CUDA-env banner | ~15 lines | Required |
| `src/llm/grammar_client.py` | config-driven n_gpu_layers (default 0) | ~3 lines | Required (§9 promoted) |
| NEW `src/training/launcher.py` | new file with `launch_training_subprocess` | ~40 lines | Required |
| NEW `scripts/install_ollama_watchdog_service.ps1` | NSSM service install script | ~50 lines | Required (reboot survival) |
| `tests/test_vram_manager.py` | DELETE | full file (~400 lines, 21 tests) | Required |
| NEW `tests/test_training_launcher.py` | new tests (7 — was 6, +1 for CUDA_DEVICE_ORDER) | ~110 lines | Required |
| `tests/test_verify_training_readiness.py` | extend coverage (6 — was 5, +1 for CUDA_DEVICE_ORDER warning) | ~95 lines added | Required |
| `tests/test_llm_client.py` (NEW if absent) | client tests (3) | ~60 lines | Required |
| `tests/test_trainer.py` | add device_map assertion test (1) | ~20 lines | Required |
| NEW `tests/test_strategy_a_env_discipline.py` | guardrail tests (6 — was 4, +2 for CUDA_DEVICE_ORDER + install script) | ~120 lines | Required |
| NEW `tests/test_grammar_client_device_binding.py` | grammar device tests (2) | ~40 lines | Required |
| NEW `tests/test_system_metrics_dual_gpu.py` | per-GPU metrics tests (4) | ~80 lines | Required |
| `docs/operator-guide.md` | new subsection (sourced from `operator-guide-insert.md`) + 4 stale-text fixes | ~150 new lines + edits at 4 locations | Required (same-PR rule) |
| `config/settings.example.yaml` | informational keys + `llm.grammar_n_gpu_layers: 0` | ~7 lines | Optional (informational) / Required (grammar key) |
| `src/monitoring/system_metrics.py` | per-GPU collection implementation | ~40 lines | Deferred |
| `src/notifications/telegram_commands.py` | per-GPU rendering | ~30 lines | Deferred |
| `CHANGELOG.md` | `[Unreleased]` entry | ~10 lines | Required |

---

## 7. vram_manager.py Fate — Option A (Delete) vs Option B (Gut + Rename)

### 7.1 Decision: Option A — Delete the module entirely

**Recommended.** Net change: -1 module, -21 tests, +new minimal `src/training/launcher.py`, +new tests.

### 7.2 Why Option A wins over Option B

The vram_manager module's load-bearing premise (docstring lines 10–11):

> "The RTX 3060 has 12GB VRAM. Ollama inference uses ~5-6GB. PyTorch training uses ~10-11GB. They CANNOT coexist."

Strategy A invalidates the premise wholesale. Under Strategy A: different cards, no mutual exclusion, no handoff, no unload/reload, no `keep_alive='18h'`, no `_kill_ollama_processes`, no `torch.cuda.empty_cache()` escalation.

**Why Option A beats Option B:**
1. **Less code surface.** A 40-line module that only does "launch training subprocess" doesn't earn the name `gpu_monitor`.
2. **`get_vram_used_mb` is non-essential** under per-GPU monitoring via `src/monitoring/system_metrics.py`.
3. **Documentation hygiene.** vram_manager.py's name implies mutual-exclusion semantics. Better to delete.
4. **Test surface clarity.** 21 vram_manager tests test a contract that no longer exists.
5. **Operator memory `feedback_strict_rigor_no_handwave`.** Option C (no-op wrapper) is REJECTED. Gutting to a 40-line shell is half-way; full delete is cleaner.

### 7.3 Cleanup checklist for Option A

- [ ] Delete `src/scheduler/vram_manager.py`
- [ ] Delete `tests/test_vram_manager.py`
- [ ] Update `src/scheduler/watch.py:2155, 2161`
- [ ] Delete `src/scheduler/overnight.py:run_evening_handoff` / `run_morning_handoff`
- [ ] Create `src/training/launcher.py`
- [ ] Update overnight.py / watch.py to call new launcher
- [ ] Grep for vram_manager imports across `src/`, `tests/`, `scripts/`
- [ ] Grep for `handoff_to_training`, `handoff_to_inference`, `run_evening_handoff`, `run_morning_handoff` across the repo
- [ ] Remove `vram_handoff_*` metric writes
- [ ] Update `CLAUDE.md` if it mentions vram_manager

### 7.4 If operator chooses Option B instead (fallback)

Rename file, keep `launch_training_subprocess` + `get_vram_used_mb` (extended), delete handoff code. Tests rewrite. Math: -21 + ~12 = -9 (would need 10 more net-add tests elsewhere; Option A is simpler).

---

## 8. client.py:107-137 — Silent Ollama-Restart-Loses-GPU-Pin Fix

### 8.1 The footgun

`src/llm/client.py:107-137` — `_check_ollama_health_or_restart` runs in the watch-loop process. On 3+ consecutive Ollama failures, the body at lines 122-127 invokes `subprocess.Popen(['ollama', 'serve'], ...)` with no `env=` kwarg. Popen inherits the watch-loop's `CUDA_VISIBLE_DEVICES=0` (B1). **Result:** Ollama would launch on GPU 0 — colliding with training.

### 8.2 The fix (recommended): delete the restart path

Rationale: the NSSM-managed `ArcisOllamaWatchdog` service (§6.16) owns Ollama lifecycle with the correct GPU 1 pinning. The watch-loop attempting its own restart duplicates responsibility and lands Ollama on the wrong card.

**Edit (prose):** Replace the body of `_check_ollama_health_or_restart` with a function that returns `is_llm_available()` (True path) or logs at ERROR level and returns False (False path). No `subprocess.Popen` call remains in the function. Rename `_check_ollama_health_or_restart` → `_check_ollama_health` (truthful name). Update callers.

Reference implementation for post-Sprint-5 implementer: Appendix D §D.5 (non-normative).

### 8.3 Test coverage for the fix

- `test_check_ollama_health_returns_true_when_available`
- `test_check_ollama_health_returns_false_and_does_not_relaunch_when_unavailable`
- `test_check_ollama_health_logs_at_error_level`

### 8.4 Risk: what if the watchdog is down too?

**Mitigation:** Operator-facing log message tells the operator to check the `ArcisOllamaWatchdog` service (`nssm status ArcisOllamaWatchdog`). The new NSSM-managed watchdog (§6.16) eliminates this scenario as a routine concern — if NSSM is up, the watchdog auto-restarts.

---

## 9. grammar_client.py — Watch-Loop-Process llama-cpp Pinning

### 9.1 The case

`src/llm/grammar_client.py:140-150` — `_load_runtime` loads llama-cpp-python with `n_gpu_layers=-1` in the watch-loop process. Under Strategy A B1, the watch-loop has `CUDA_VISIBLE_DEVICES=0` — llama-cpp lands on the 3090, competing with training.

### 9.2 Current default protects us

`config/settings.example.yaml:315` — `use_grammar_enforcement: false` is the default. Footgun dormant.

### 9.3 Hardening recommended for post-Sprint-5 (PROMOTED to required)

**Change (prose):** at `grammar_client.py:144` (the `Llama(...)` call site), read `n_gpu_layers` from config with default `0` (CPU-only). The config key `llm.grammar_n_gpu_layers` defaults to 0; operator-explicit opt-in is required to put llama-cpp on GPU.

**Why default 0:** CPU is safe — no GPU contention with training. Grammar enforcement is rarely used; latency hit acceptable.

Reference implementation for post-Sprint-5 implementer: Appendix D §D.6 (non-normative).

### 9.4 Future option (out of scope here)

If grammar enforcement becomes critical, refactor grammar_client to run in a separate subprocess pinned to GPU 1 (sharing with Ollama).

### 9.5 Test coverage (REQUIRED)

`tests/test_grammar_client_device_binding.py` (2 tests):
- `test_grammar_client_n_gpu_layers_defaults_to_zero`
- `test_grammar_client_n_gpu_layers_respects_config_override`

---

## 10. Verification Plan (Operator-Runnable)

Post-implementation walkthrough.

### 10.0 Post-reboot pre-flight (NEW — reboot survival check)

After every Windows reboot, before relying on the system:

```powershell
# Verify both NSSM services are running
nssm status ArcisWatchLoop          # Expect: SERVICE_RUNNING
nssm status ArcisOllamaWatchdog     # Expect: SERVICE_RUNNING

# Verify NSSM env for each service
nssm get ArcisWatchLoop AppEnvironmentExtra
# Expect lines include: CUDA_VISIBLE_DEVICES=0, CUDA_DEVICE_ORDER=PCI_BUS_ID,
#   plus post-Sprint-5 vars (ARCIS_DB_PATH, SYNC_THREAD_ENABLED=false,
#   DATABASE_URL, ARCIS_PG_CUTOVER_ENABLED=1, PYTHONUTF8=1 if present)

nssm get ArcisOllamaWatchdog AppEnvironmentExtra
# Expect: CUDA_VISIBLE_DEVICES=1, CUDA_DEVICE_ORDER=PCI_BUS_ID

# Verify Ollama is up on GPU 1 and watch loop is up
curl http://localhost:11434/api/tags         # Expect 200 OK with model list
nvidia-smi -i 1 --query-compute-apps=pid,process_name --format=csv
# Expect: ollama_llama_server.exe

Get-Content C:\arcis\logs\watchdog.log -Tail 50 |
  Select-String 'startup.*CUDA'
# Expect a startup banner: "[startup] CUDA env: CUDA_VISIBLE_DEVICES=0 CUDA_DEVICE_ORDER=PCI_BUS_ID ..."
```

If any of these checks fail post-reboot, see §11.5 (reboot recovery).

### 10.1 Pre-flight: NSSM service env (READ-MERGE-WRITE pattern)

**Step 1 — capture current env.**

```powershell
nssm get ArcisWatchLoop AppEnvironmentExtra > C:\arcis\halcyon-lab\pre-change-env-watchloop.txt
Get-Content C:\arcis\halcyon-lab\pre-change-env-watchloop.txt
```

Expected output should include (post-Sprint-5 canonical state, per §3.5):
- `ARCIS_DB_PATH=C:/arcis/data/ai_research_desk.sqlite3`
- `SYNC_THREAD_ENABLED=false`
- `DATABASE_URL=postgresql://halcyon_app:<password>@localhost:5433/halcyon`
- `ARCIS_PG_CUTOVER_ENABLED=1`
- `PYTHONUTF8=1` (if currently set)

**Step 2 — verify post-cutover canonical vars present.** If `SYNC_THREAD_ENABLED`, `DATABASE_URL`, or `ARCIS_PG_CUTOVER_ENABLED` is missing, **STOP** and escalate to operator. The post-Sprint-5 production state requires these.

**Step 3 — merge new vars.** Construct the new env block as (captured vars) ∪ {`CUDA_VISIBLE_DEVICES=0`, `CUDA_DEVICE_ORDER=PCI_BUS_ID`}.

**Step 4 — write the merged block via `nssm set`.** The PowerShell invocation pattern uses one quoted `"NAME=VALUE"` per backtick-continued argument. Exact command template in Appendix D §D.2.

**Step 5 — restart and wait.**

```powershell
nssm restart ArcisWatchLoop
Start-Sleep -Seconds 10
```

**Step 6 — verify via startup banner** (NOT via Get-Process; see §21 minor #1).

```powershell
Get-Content C:\arcis\logs\watchdog.log -Tail 100 |
  Select-String 'startup.*CUDA'
# Expect: "[startup] CUDA env: CUDA_VISIBLE_DEVICES=0 CUDA_DEVICE_ORDER=PCI_BUS_ID device_count=1 gpu0=NVIDIA GeForce RTX 3090"
```

**Critical reminder:** The post-Sprint-5 PR description MUST include the captured pre-change env (Step 1 output) so reviewers can confirm no production var was dropped.

### 10.2 Verify watch loop sees only GPU 0 (3090)

The startup banner (added in §6.11) is the canonical verification path — it reads back what the process actually saw, which is robust against the Windows Get-Process child-env limitation noted in §21 minor #1.

```powershell
Get-Content C:\arcis\logs\watchdog.log -Tail 100 |
  Select-String 'startup.*CUDA'
```

Do NOT rely on `Get-Process StartInfo.EnvironmentVariables` for the NSSM-spawned watch loop — Windows ACL behavior typically returns empty.

### 10.3 Verify Ollama is on GPU 1 (3060)

```powershell
nvidia-smi -i 1 --query-compute-apps=pid,process_name,used_memory --format=csv
# Expect: ollama_llama_server.exe ~5-6 GB resident

nvidia-smi -i 0 --query-compute-apps=pid,process_name,used_memory --format=csv
# Expect: empty (unless training subprocess in flight)

nvidia-smi --query-gpu=index,name,memory.used,memory.total --format=csv
# Expect: GPU 0 = RTX 3090 idle, GPU 1 = RTX 3060 ~5-9 GB
```

### 10.4 Verify training readiness probe

Fresh PowerShell window with User-scope env set:

```powershell
echo $env:CUDA_VISIBLE_DEVICES   # Expect: 0
echo $env:CUDA_DEVICE_ORDER       # Expect: PCI_BUS_ID
python scripts/verify_training_readiness.py
# Expect all checks PASS including:
#   Device: NVIDIA GeForce RTX 3090, ~24.0 GB free VRAM
#   GPU 0 maps to 3090 (Strategy A invariant verified)
#   CUDA_VISIBLE_DEVICES=0 detected
#   CUDA_DEVICE_ORDER=PCI_BUS_ID detected
#   Trainer dry-run: PASS
```

### 10.5 Verify training subprocess inherits env correctly

During a training run, confirm via `nvidia-smi -i 0` / `nvidia-smi -i 1` per §10.3. Also confirm via the training subprocess log (TRL emits a device info line at startup).

### 10.6 Verify simultaneous operation (no contention)

```powershell
# Confirm Ollama is responsive WHILE training is running
curl http://localhost:11434/api/tags                            # Expect 200 OK
curl -X POST http://localhost:11434/api/generate `
  -d '{"model":"halcyon-v1","prompt":"hello","stream":false}'
# Expect: response within ~2-5s (no slowdown from training competition)

nvidia-smi
# Expect: GPU 0 high util ~14-18 GB (training); GPU 1 moderate util ~5-9 GB (Ollama)
```

**NUM_PARALLEL=4 opt-in load test (only if operator chooses to opt in):**

```powershell
# Edit scripts/ollama_watchdog.ps1 setting $env:OLLAMA_NUM_PARALLEL = '4', commit, restart service.
# Run a council scan with 5 concurrent agents (production-realistic burst):
python -m src.main scan --verbose            # or similar that exercises council parallelism

# Concurrently, monitor GPU 1 memory:
1..120 | ForEach-Object {
  $mem = (nvidia-smi -i 1 --query-gpu=memory.used --format=csv,noheader,nounits).Trim()
  "$(Get-Date -Format 'HH:mm:ss')  GPU1 mem.used=$mem MiB"
  Start-Sleep -Seconds 1
}
# REQUIREMENT for NUM_PARALLEL=4 to be safe: memory.used MUST stay below 11500 MiB across
# the entire 2-minute load test. If it ever spikes above, revert to NUM_PARALLEL=2.
```

### 10.7 Extend `verify_training_readiness.py`

New `_check_dual_gpu_layout()` runs after `_check_cuda`. See §6.3.

### 10.8 Operator-friendly one-liner status check

```powershell
python -c "import torch, os; print(f\"order={os.environ.get('CUDA_DEVICE_ORDER','UNSET')}, visible={os.environ.get('CUDA_VISIBLE_DEVICES','UNSET')}, count={torch.cuda.device_count()}, gpu0={torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'NONE'}\")"
# In training shell: order=PCI_BUS_ID, visible=0, count=1, gpu0=RTX 3090
# In Ollama watchdog shell: order=PCI_BUS_ID, visible=1, count=1, gpu0=RTX 3060
```

---

## 11. Failure Modes + Recovery Procedures

### 11.1 Failure mode matrix

| # | Failure | Symptom | Detection | Recovery |
|---|---|---|---|---|
| F1 | GPU 0 (3090) driver hiccup mid-training | Training subprocess hangs or OOMs; `nvidia-smi -i 0` shows `ERR!` | Watch-loop sees training subprocess exit code != 0 | Restart driver: `nvidia-smi -i 0 -r`. Re-run training from checkpoint. |
| F2 | GPU 1 (3060) driver hiccup mid-trading | Ollama 503/timeout | `is_llm_available()` False after 3 polls | `ArcisOllamaWatchdog` NSSM service auto-restarts. If repeated failures: `nvidia-smi -i 1 -r`. |
| F3 | VRAM exhaustion on GPU 0 (training) | CUDA OOM | trainer.py catches OOM, exits non-zero | Reduce per_device_train_batch_size. Process exit reclaims VRAM. |
| F4 | VRAM exhaustion on GPU 1 (Ollama) | Ollama 500 or model swap loop | Ollama logs "out of memory" | Default NUM_PARALLEL is 2; if opt-in 4 is in use, revert to 2 immediately. Check ollama-watchdog.log. |
| F5 | GPU 1 fails entirely (hardware) | Ollama daemon can't start; `nvidia-smi -i 1` errors | Operator manual / daily preflight | Fallback per §11.3. |
| F6 | GPU 0 fails entirely (hardware) | Training subprocess fails immediately | verify_training_readiness.py fails CUDA check | Fallback per §11.4. |
| F7 | NSSM env not picked up after `nssm set` (operator forgot restart) | Training subprocess sees CUDA_VISIBLE_DEVICES=unset | `verify_training_readiness.py` warns | `nssm restart ArcisWatchLoop` (mandatory after env change). |
| F8 | `ollama_watchdog.ps1` started without env (operator ran `ollama serve` directly) | Ollama binds to GPU 0 | Verification §10.3 fails | Stop Ollama, restart via `nssm restart ArcisOllamaWatchdog`. |
| F9 | Two training subprocesses launched simultaneously | Both compete on GPU 0; one OOMs | nvidia-smi shows two python.exe on GPU 0 | watch.py PID lockfile; operator discipline. |
| F10 | `_check_ollama_health` False but `ArcisOllamaWatchdog` also down | Council inference returns None >5min | Operator notices in dashboard | `nssm restart ArcisOllamaWatchdog`. If service won't start: `nssm status ArcisOllamaWatchdog` → diagnose via Event Viewer. |
| F11 | `device_map={'': 0}` raises on 3060-only box (3090 swapped out) | Training fails to load | Logged at trainer.py:154 | Operator decision: disable training OR temporarily revert device_map. |
| F12 | `grammar_client.py` loads llama-cpp with `n_gpu_layers=-1` mid-training | Training OOMs from llama-cpp's carve-out | Hard to detect without instrumentation | Keep `use_grammar_enforcement: false` AND `llm.grammar_n_gpu_layers: 0` defaults. See §9.3. |
| F13 | NEW — CUDA enumeration order flipped (driver upgrade, PCIe reseat, GPU swap) | Training lands on 3060 / Ollama lands on 3090 | `verify_training_readiness.py` HARD FAIL on "GPU 0 not 3090" check; §10.0 post-reboot pre-flight catches it | Verify `CUDA_DEVICE_ORDER=PCI_BUS_ID` in NSSM env. If still wrong, physically check PCIe slots — 3090 should be in 01:00.0 (lower bus). Reseat if necessary. |
| F14 | NEW — Post-reboot: Ollama not running | Council inference returns None at first scan after reboot | §10.0 pre-flight: `nssm status ArcisOllamaWatchdog` not SERVICE_RUNNING | `nssm start ArcisOllamaWatchdog`. If service doesn't exist: re-run `scripts/install_ollama_watchdog_service.ps1`. |
| F15 | NEW — Partial driver crash (GPU enumerable but CUDA-unresponsive / "soft hang") | Training subprocess hangs forever; no OOM signal; nvidia-smi shows device exists | No standard detection; operator notices wall-clock training time exceeding expected | **Mitigation deferred to SP7+ hardening:** training subprocess emits heartbeat to file every N minutes; watch loop kills subprocess if heartbeat stale. Tracked as §21 known consideration #2. Manual recovery: `taskkill /pid <training pid> /f`. |

### 11.2 Recovery decision tree (operator-guide content)

```
Is Ollama responsive?
├─ Yes
│   └─ Is training subprocess running?
│       ├─ Yes — both healthy, no action
│       └─ No — was it scheduled?
│           ├─ Yes — check logs/training_overnight.log
│           └─ No — normal idle state
└─ No (curl http://localhost:11434/api/tags timed out)
    └─ Is ArcisOllamaWatchdog service running? (nssm status ArcisOllamaWatchdog)
        ├─ Yes — check logs/ollama-watchdog.log; daemon stuck. Restart service.
        └─ No — nssm start ArcisOllamaWatchdog
            └─ Still fails? Re-run scripts/install_ollama_watchdog_service.ps1.
```

### 11.3 Fallback to single-GPU operation (3060 dead)

Prose: edit `scripts/ollama_watchdog.ps1` to remove the `CUDA_VISIBLE_DEVICES=1` and `CUDA_DEVICE_ORDER=PCI_BUS_ID` lines (so Ollama falls back to GPU 0). Disable overnight training via `config/settings.local.yaml`. Restart `ArcisOllamaWatchdog`. Verify Ollama on 3090. Note: NUM_PARALLEL=4 is viable on the 3090 (24 GB VRAM per `project_gpu_upgrade` 2026-05-10 hardware swap); no headroom concern at rollback.

### 11.4 Fallback to single-GPU operation (3090 dead)

Disable training (`training.enabled: false` in config/settings.local.yaml). Ollama on 3060 continues. Council inference continues. Overnight training paused.

### 11.5 Reboot recovery (when something didn't auto-start)

If §10.0 pre-flight fails on either NSSM service:

```powershell
# If ArcisOllamaWatchdog is not running
nssm start ArcisOllamaWatchdog
nssm status ArcisOllamaWatchdog              # Should now report SERVICE_RUNNING

# If service doesn't exist at all (first deploy after reboot, install script not run)
C:\arcis\halcyon-lab\scripts\install_ollama_watchdog_service.ps1

# If ArcisWatchLoop is not running
nssm start ArcisWatchLoop
```

Do NOT run `python -m src.main startup` while NSSM is responsible for the watch loop — per operator memory `reference_watch_loop_management`, that creates a duplicate process racing the NSSM-managed instance.

---

## 12. Operator-Guide Additions

Same-PR rule (CLAUDE.md): the post-Sprint-5 implementation PR also lands these operator-guide changes.

### 12.1 NEW subsection: "Dual-GPU Operation (Strategy A)"

**Insertion location:** insert as a new subsection **immediately before the literal heading** `### "Ollama crashes / corpus producing template fallbacks"` in `docs/operator-guide.md` (currently line 618 — post-Sprint-5 implementer reconfirms via `grep -n` at implementation time).

**Section content:** delivered as a separate authored draft file at `docs/audits/2026-05-12-dual-gpu-ideation/operator-guide-insert.md`. post-Sprint-5 implementer copies the content of that file into `docs/operator-guide.md` at the anchor heading (with light prose refinement for style consistency if needed). The draft includes: dual-GPU layout table, CUDA enumeration pin rationale, verification commands, per-card VRAM math (with NUM_PARALLEL=2 default and the NUM_PARALLEL=4 opt-in path), deprecated handoff cadence, env-var boundary quick-reference, post-reboot recovery commands, and a cross-reference back to this spec for the failure matrix.

**Why the content lives in a separate file:** keeps this spec at the WHAT-changes level and avoids prescriptive prose drift. The standalone file is reviewable independently and can be polished by the post-Sprint-5 implementer without spec churn.

### 12.2 Stale-text fix at line 265 (hardware row)

**Current (stale):**
```
Hardware | NVIDIA GPU with ≥12 GB VRAM | Required for Ollama inference. Current: RTX 3060 12 GB; planned upgrade to RTX 3090 24 GB.
```

**Replace with:**
```
Hardware | 2× NVIDIA GPUs (RTX 3090 24 GB + RTX 3060 12 GB) | Strategy A dual-GPU layout (see Dual-GPU Operation section in §5). GPU 0 (PCIe 01:00.0) = 3090 = training; GPU 1 (PCIe 08:00.0) = 3060 = Ollama inference. Enumeration pinned via CUDA_DEVICE_ORDER=PCI_BUS_ID.
```

### 12.3 Stale-text fix in §5 VRAM math (lines 632–635)

**Current (stale):**
References like "arcis:v1.0.0 model = ~9.12 GiB resident at NUM_PARALLEL=2... NUM_PARALLEL=4 needs ~10.4 GiB resident leaving ~0.4 GiB cushion."

**Replace with:** the per-card math from the operator-guide-insert.md draft (§12.1 source). Crucial reconciliation: NUM_PARALLEL default is now 2 (validated steady-state safe). NUM_PARALLEL=4 is opt-in only after the §10.6 load test confirms `nvidia-smi -i 1 memory.used` stays below 11.5 GB during 5-agent concurrent council bursts. The 0.4 GB cushion at NUM_PARALLEL=4 is below typical CUDA transient workspace (~512 MB) and is insufficient.

### 12.4 Stale-text fix in §3 corpus generation (lines 691–694)

Replace references to corpus generation "competing with Ollama for VRAM" with: corpus generation runs in the watch-loop process (CPU-bound for the most part; LLM calls hit Ollama over HTTP on GPU 1). No VRAM competition.

### 12.5 Stale-text fix in daily ops cadence (line 159–161)

**Current (stale):**
```
VRAM handoff — Ollama unloads, training process can claim GPU
```

**Replace with:**
```
Training launches on GPU 0 (RTX 3090, PCIe 01:00.0) at scheduled overnight time. Ollama continues serving on GPU 1 (RTX 3060, PCIe 08:00.0) — no handoff required. See the Dual-GPU Operation subsection in §5 for the layout.
```

### 12.6 §7 watchdog section additions (line ~1027)

Add notes:

```markdown
### NSSM-managed lifecycle

The Ollama watchdog is now NSSM-managed as the `ArcisOllamaWatchdog` service. It auto-starts on Windows boot, survives operator SSH disconnects, and is restartable via `nssm restart ArcisOllamaWatchdog`. The install script is `scripts/install_ollama_watchdog_service.ps1` (one-time per deploy).

### GPU binding

The NSSM service env pins Ollama to GPU 1 via two variables: `CUDA_VISIBLE_DEVICES=1` and `CUDA_DEVICE_ORDER=PCI_BUS_ID`. The watchdog also sets these in process scope at the top of `scripts/ollama_watchdog.ps1` as defense-in-depth. The watchdog log line at startup confirms the binding:

```
[2026-05-12 09:00:00] GPU binding: CUDA_VISIBLE_DEVICES=1 CUDA_DEVICE_ORDER=PCI_BUS_ID (RTX 3060)
[2026-05-12 09:00:00] OLLAMA_NUM_PARALLEL=2
```

If the watchdog log shows `CUDA_VISIBLE_DEVICES=` (empty) or `=0`, Strategy A is broken — verify both the NSSM service env (`nssm get ArcisOllamaWatchdog AppEnvironmentExtra`) and the ps1 script.
```

### 12.7 Env-var inventory update (line 1671)

**Current:**
```
If PYTHONUTF8 or ARCIS_DB_PATH is missing, the TRL training pipeline will break silently.
```

**Replace with:**
```
If any of the following NSSM ArcisWatchLoop env vars is missing or wrong, the system misbehaves:
- PYTHONUTF8 missing → encoding errors in training logs.
- ARCIS_DB_PATH missing → training reads/writes the wrong DB.
- SYNC_THREAD_ENABLED unset → defaults to true → re-enables deprecated SQLite→Postgres sync thread.
- DATABASE_URL missing → Postgres read path 500s.
- ARCIS_PG_CUTOVER_ENABLED missing → cutover-gate code re-routes to SQLite.
- CUDA_VISIBLE_DEVICES missing → training auto-shards across both GPUs (3060 caps throughput).
- CUDA_DEVICE_ORDER missing → driver upgrades or PCIe reseats can silently flip GPU 0/1 identity.
Verify with `nssm get ArcisWatchLoop AppEnvironmentExtra`. Capture pre-change env before any modification (read-merge-write pattern).
```

---

## 13. Test Plan (post-Sprint-5 Implementation)

### 13.1 Test-count delta accounting (5400 floor) — REVISED v3

**Verified delete count:** 21 (re-verified at post-Sprint-5 start).

| Action | Test delta | Required? |
|---|---|---|
| Delete `tests/test_vram_manager.py` | **-21** | Required |
| Add `tests/test_training_launcher.py` | +7 (was +6; +1 for CUDA_DEVICE_ORDER injection) | Required |
| Add `tests/test_verify_training_readiness.py` dual-GPU coverage | +6 (was +5; +1 for CUDA_DEVICE_ORDER warning) | Required |
| Add `tests/test_llm_client.py` `_check_ollama_health` tests | +3 | Required |
| Add `tests/test_trainer.py` device_map fail-fast test | +1 | Required |
| Add `tests/test_strategy_a_env_discipline.py` guardrails | +6 (was +4; +1 for CUDA_DEVICE_ORDER source-guardrail, +1 for install script guardrail) | Required |
| Add `tests/test_grammar_client_device_binding.py` | +2 | Required |
| Add `tests/test_system_metrics_dual_gpu.py` | +4 | Required |
| **Required net** | **-21 + 7 + 6 + 3 + 1 + 6 + 2 + 4 = +8** | — |
| Optional: `tests/test_telegram_commands_dual_gpu.py` | +2 | Optional |
| **With optional adds** | **+10** | — |

**Floor check:** 5400 + 8 = **5408** (minimum required deliverable). With optional adds, 5410. Comfortable margin.

### 13.2 New test enumeration (required set)

#### `tests/test_training_launcher.py` (NEW, 7 tests)

1. `test_launch_training_subprocess_returns_popen_handle`
2. `test_launch_training_subprocess_injects_cuda_visible_devices_zero`
3. `test_launch_training_subprocess_injects_cuda_device_order_pci_bus_id` — **NEW.** Assert `env` kwarg includes `CUDA_DEVICE_ORDER='PCI_BUS_ID'`.
4. `test_launch_training_subprocess_preserves_existing_env` — assert all five post-Sprint-5 vars (ARCIS_DB_PATH, SYNC_THREAD_ENABLED, DATABASE_URL, ARCIS_PG_CUTOVER_ENABLED, PYTHONUTF8) propagate when present in the fixture environment.
5. `test_launch_training_subprocess_redirects_stdout_to_log_file`
6. `test_launch_training_subprocess_redirects_stderr_to_log_file`
7. `test_launch_training_subprocess_handles_missing_log_dir`

#### `tests/test_verify_training_readiness.py` additions (6 tests)

1. `test_check_cuda_fails_when_gpu0_not_3090_on_dual_gpu`
2. `test_check_cuda_warns_when_cuda_visible_devices_unset_on_dual_gpu`
3. `test_check_cuda_passes_when_gpu0_is_3090_with_cuda_visible_devices_set`
4. `test_check_cuda_fails_when_single_gpu_is_not_3090`
5. `test_dry_run_uses_device_map_zero_not_auto`
6. `test_dual_gpu_layout_warns_when_cuda_device_order_unset` — **NEW (B0 coverage).** Mock env with CUDA_DEVICE_ORDER absent, assert WARNING emitted.

#### `tests/test_llm_client.py` additions (3 tests)

1. `test_check_ollama_health_returns_true_when_available`
2. `test_check_ollama_health_returns_false_and_does_not_relaunch_when_unavailable`
3. `test_check_ollama_health_logs_at_error_level`

#### `tests/test_trainer.py` addition (1 test)

1. `test_curriculum_train_script_pins_device_zero`

#### `tests/test_strategy_a_env_discipline.py` (NEW, 6 tests — guardrails)

1. `test_no_subprocess_popen_ollama_in_src_llm_client` — grep src/llm/client.py for `subprocess.Popen.*ollama`; assert NOT present.
2. `test_no_device_map_auto_in_curriculum_train_script` — read trainer.py source; regex for `device_map=['\"]auto['\"]` in CURRICULUM_TRAIN_SCRIPT; assert NOT present.
3. `test_ollama_watchdog_ps1_sets_cuda_visible_devices_one` — read scripts/ollama_watchdog.ps1; assert `CUDA_VISIBLE_DEVICES = '1'` literal present.
4. `test_grammar_client_default_n_gpu_layers_is_zero_in_source` — assert `n_gpu_layers=-1` literal NOT present at `Llama(...)` call site.
5. **NEW** — `test_ollama_watchdog_ps1_sets_cuda_device_order_pci_bus_id` — read ollama_watchdog.ps1; assert `CUDA_DEVICE_ORDER = 'PCI_BUS_ID'` literal present.
6. **NEW** — `test_install_ollama_watchdog_service_ps1_pins_gpu_one_and_pci_bus_id` — read scripts/install_ollama_watchdog_service.ps1; assert both `CUDA_VISIBLE_DEVICES=1` and `CUDA_DEVICE_ORDER=PCI_BUS_ID` literals present in the `AppEnvironmentExtra` argument list. Source-level guardrail against accidental edits to the install script that strip the GPU pin.

Additional consideration (deferred — see §21 minor #3): a startup-time config-validation check that refuses to start the watch loop if `llm.use_grammar_enforcement: true` AND `llm.grammar_n_gpu_layers > 0` AND training is enabled simultaneously. Not in the required test set; flagged for SP7+ as a config-level guardrail.

#### `tests/test_grammar_client_device_binding.py` (NEW, 2 tests)

1. `test_grammar_client_n_gpu_layers_defaults_to_zero`
2. `test_grammar_client_n_gpu_layers_respects_config_override`

#### `tests/test_system_metrics_dual_gpu.py` (NEW, 4 tests)

1. `test_collect_gpu_metrics_emits_rows_per_gpu`
2. `test_collect_gpu_metrics_handles_single_gpu_fallback`
3. `test_system_metrics_schema_includes_gpu_index_column`
4. `test_collect_gpu_metrics_uses_explicit_index_flag`

### 13.3 Net-replacement tests for the 21 deleted vram_manager tests

(Enumerated test names from `tests/test_vram_manager.py` — full list of 21 retained from v2; see Appendix B for the cross-reference table mapping each deleted test to its replacement coverage area.)

**Net effect:** 21 deleted, 29 required new tests across the new test files. 29 − 21 = **+8 net**. Floor cleared with margin.

### 13.4 Test infrastructure dependencies

- `tests/conftest.py` has NO existing GPU mocking fixtures. post-Sprint-5 plan adds:
  - `mock_torch_cuda_dual_gpu` — patches `device_count()=2`, `get_device_name(0)='RTX 3090'`, `get_device_name(1)='RTX 3060'`.
  - `mock_torch_cuda_single_3090` — patches count=1, gpu0=3090.
  - `mock_nvidia_smi_dual_gpu` — subprocess.run side-effect returning multi-line CSV.
  - `mock_post_cutover_env` — fixture that injects ARCIS_DB_PATH, SYNC_THREAD_ENABLED, DATABASE_URL, ARCIS_PG_CUTOVER_ENABLED, PYTHONUTF8 into os.environ for env-propagation tests.

### 13.5 Optional test sets

`tests/test_telegram_commands_dual_gpu.py` (if §6.14 fix chosen) — 2 tests.

### 13.6 Test sweep command (post-implementation)

```powershell
python -m pytest tests/ -q --timeout=60
# Expect: >= 3690 tests passed, 0 failed, 0 errors
```

### 13.7 post-Sprint-5 PR description requirements (operator-side discipline)

The post-Sprint-5 PR description MUST include:
1. **Pre-change NSSM env capture** for `ArcisWatchLoop` (output of `nssm get ArcisWatchLoop AppEnvironmentExtra` before any change). Reviewer cross-checks against post-change env to confirm no production var was dropped.
2. **NUM_PARALLEL decision rationale.** Either: (a) shipped at default 2 (no load test required), OR (b) shipped at opt-in 4 with §10.6 load-test results attached (memory.used stayed below 11.5 GB across 2-minute 5-agent test). Default for the PR is (a).
3. **Service install evidence.** Output of `nssm status ArcisOllamaWatchdog` post-install showing SERVICE_RUNNING.
4. **Test sweep output.** `python -m pytest tests/ -q --timeout=60` showing ≥3690 passing.
5. **`validate-schema` output** (only if §6.13 widening included).

---

## 14. Risk Register

| # | Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|---|
| R1 | Operator forgets to set NSSM `CUDA_VISIBLE_DEVICES=0`; training auto-shards | Med | High | `device_map={'': 0}` fail-fast in trainer.py; `verify_training_readiness.py` dual-GPU check. |
| R2 | `ollama_watchdog.ps1` edit reverted; Ollama lands on 3090 | Low | Med | Guardrail tests + NSSM service env still carries the pin (defense-in-depth via `ArcisOllamaWatchdog` env). |
| R3 | watch-loop's `_check_ollama_health` Popen accidentally re-introduced | Low | Med | Guardrail test `test_no_subprocess_popen_ollama_in_src_llm_client`. |
| R4 | Grammar enforcement enabled later; llama-cpp grabs GPU 0 | Low | Med | Config-driven default 0; behavioral + source-level guardrail tests. Future startup-time config validation per §21 minor #3. |
| R5 | 3060 fails during a critical trading window | Low | Med | §11.3 fallback. |
| R6 | 3090 fails during overnight training | Low | High | §11.4 fallback. |
| R7 | `scripts/overnight_train.py` strips env vars (coverage gap) | Low | High | post-Sprint-5 reads file; defense-in-depth `os.environ.setdefault` if found. |
| R8 | `scripts/start_ollama_watchdog.bat` strips env vars (coverage gap) | Low | Med | post-Sprint-5 reads file. Likely obsolete under NSSM-managed model. |
| R9 | Test floor drop on PR; CI blocks | Low | Low | §13 enumerated +8 net; PR description includes sweep output. |
| R10 | Schema-registry violation if system_metrics widening done outside registry | Low | High | Deferred; if chosen, MASTER.md schema rules strict. |
| R11 | Operator's User-scope env conflicts with NSSM env | Low | Med | Operator-guide §5 documents shell role discipline. |
| R12 | `device_map={'': 0}` incompatible with future accelerate version | Low | Low | Pinned in `requirements-training.txt`; guardrail test catches regression. |
| R13 | Worktree env drift — post-Sprint-5 worktree doesn't carry .env or NSSM env | High | Med | post-Sprint-5 tests hermetic (don't depend on real env). |
| R14 | DPO_TRAIN_SCRIPT inadvertently shards | Med | Med | post-Sprint-5 reads DPO_TRAIN_SCRIPT in full; Unsloth defaults single-device; test asserts no `device_map='auto'`. |
| R15 | Operator-guide gets stale after Strategy A lands | Med | Low | Same-PR rule. |
| **R16** | **NEW — Destructive NSSM env copy-paste wipes post-Sprint-5 production vars (SYNC_THREAD_ENABLED, DATABASE_URL, ARCIS_PG_CUTOVER_ENABLED)** | **Med (if procedure not followed)** | **Critical — re-enables deprecated SQLite→Postgres sync thread, breaks Postgres primary read path, reverts cutover gate** | **Read-merge-write procedure (§5.2 B1 + §10.1); pre-change env capture mandatory in PR description (§13.7); operator-guide §12.7 enumerates each required var; post-Sprint-5 task spec includes "verify SYNC_THREAD_ENABLED still =false post-restart" as explicit verification step. Reference: PR #1056, operator memory `reference_watch_loop_management`.** |
| **R17** | **NEW — NUM_PARALLEL=4 cushion too thin on 3060 (0.4 GB cushion vs ~512 MB CUDA transient workspace; 5-agent council bursts can push past)** | **Med (only if operator opts in without load-testing)** | **Med — Ollama OOM, model swap loop, council inference fails during burst** | **Default NUM_PARALLEL=2 (operator-validated steady-state safe, ~1.7 GB cushion); NUM_PARALLEL=4 is opt-in only after §10.6 load test confirms `nvidia-smi -i 1 memory.used` stays below 11.5 GB during a 5-agent concurrent council scan; revert to 2 immediately on first observed spike above threshold.** |
| **R18** | **NEW — Post-reboot Ollama not running (pre-post-Sprint-5: ollama_watchdog.ps1 not NSSM-managed; only launched by `start_ollama_watchdog.bat` from operator SSH session)** | **High (post-reboot, pre-post-Sprint-5) / Low (post-post-Sprint-5)** | **High — first scan post-reboot returns no LLM; council inference falls back to templates** | **NSSM-wrap ollama_watchdog.ps1 as `ArcisOllamaWatchdog` service (§6.16); install script `scripts/install_ollama_watchdog_service.ps1`; §10.0 post-reboot pre-flight verification. F14 covers detection; §11.5 covers manual recovery.** |
| **R19** | **NEW — CUDA enumeration order flipped by driver upgrade, PCIe reseat, or GPU swap (default `CUDA_DEVICE_ORDER=FASTEST_FIRST` tie-breaker is not contractual across NVIDIA driver releases)** | **Low (no scheduled changes) / Med (during driver upgrade)** | **High — training lands on 3060 (OOM), Ollama lands on 3090 (works but wastes card)** | **Pin `CUDA_DEVICE_ORDER=PCI_BUS_ID` at every CUDA boundary (B0, §5.0); behavioral test in verify_training_readiness; source-level guardrail tests against ollama_watchdog.ps1 and install script; F13 in failure matrix; §10.0 pre-flight checks the pin post-reboot.** |

---

## 15. post-Sprint-5 Implementation Read-List (closing coverage gaps from deep report)

1. **`scripts/overnight_train.py`** — confirm no env-stripping.
2. **`scripts/start_ollama_watchdog.bat`** — confirm no env-stripping. May become obsolete under NSSM-managed model.
3. **NSSM `ArcisWatchLoop` current `AppEnvironmentExtra`** — captured pre-change per §10.1 step 1.
4. **`src/council/*`** — confirm no independent inference path.
5. **`src/schema/registry.py`** — `system_metrics` TableDef columns (if widening chosen).
6. **`src/training/trainer.py:290-327` DPO_TRAIN_SCRIPT in full**.
7. **`tests/test_trainer.py`** (full file).
8. **All `src/` callers of `vram_manager`** — grep for imports.
9. **`CLAUDE.md`** — search for `vram_manager` references; re-verify 21-test count.
10. **NSSM documentation** — confirm `AppEnvironmentExtra` syntax for the new `ArcisOllamaWatchdog` install script.
11. **`scripts/ollama_watchdog.ps1`** in full — confirm safe NSSM-wrapping (no operations that require an interactive console / no reliance on operator SSH session).

---

## 16. Open Questions for post-Sprint-5 Implementation

1. **Should `system_metrics` be widened to per-GPU?** Default (a) — least invasive. 4 tests required either way.
2. **Should `_check_ollama_health` attempt explicit `nssm start ArcisOllamaWatchdog` on detected outage?** Pro: closes the gap when NSSM service crashed. Con: adds a new restart path. Recommend NO — rely on `nssm` auto-restart policy (configurable via `AppExit Default Restart`).
3. **Should `launch_training_subprocess` set `env={**os.environ, 'CUDA_VISIBLE_DEVICES': '0', 'CUDA_DEVICE_ORDER': 'PCI_BUS_ID'}` explicitly?** Recommend BOTH (defense-in-depth).
4. **Should `OLLAMA_NUM_PARALLEL` move to config?** Keep in ps1 for now; consider config-driven knob in SP7+.
5. **Should the Ollama watchdog be NSSM-wrapped?** **RESOLVED in v3 — YES.** §6.16 makes it a required item; the new `ArcisOllamaWatchdog` service install lands in the same post-Sprint-5 PR.
6. **Should Telegram `/health` be fixed in the post-Sprint-5 window or deferred?** Deferred. Operator decision at plan-review.
7. **Should `llm.gpu_device` / `training.gpu_device` config keys be added?** Yes (informational); no enforcement path.
8. **Should `verify_training_readiness.py` HARD FAIL on unset CUDA_VISIBLE_DEVICES?** WARN, not FAIL.
9. **DPO_TRAIN_SCRIPT rewrite off Unsloth — separate spec?** Yes.
10. **Should `n_gpu_layers` config hardening for grammar_client (§9.3) be in the post-Sprint-5 window?** YES — promoted to required.
11. **What's the rollback procedure if Strategy A causes a regression?** post-Sprint-5 PR includes 1-command rollback (revert PR + restart both NSSM services).
12. **Should `pre-commit` hook block `device_map='auto'` in `src/training/`?** CI tests suffice; no extra hook ceremony.
13. **NEW — Should `nssm` `AppExit Default Restart` be set on both services so a crash auto-recovers?** Recommend YES. post-Sprint-5 plan adds `nssm set <service> AppExit Default Restart` to the install scripts.
14. **NEW — When operator physically swaps a GPU, what's the audit trail?** Recommend: post-Sprint-5 adds an operator-guide one-liner: after any GPU swap, run §10.0 post-reboot pre-flight AND `python scripts/verify_training_readiness.py`. The latter HARD FAILs if GPU 0 is not the 3090.

---

## 17. Appendix A — Cross-References to Operator Memory

| Memory key | Applied where |
|---|---|
| `feedback_strict_rigor_no_handwave` | §4.2, §7.2, §13.1, §14 R16/R17/R18/R19 mitigations. |
| `feedback_fix_before_trade` | §6, deferred items explicitly marked. |
| `feedback_review_sibling_search` | §5.2 B1 sibling-search reminder; §15 grep items. |
| `feedback_sprint_5_is_final` | §1 (post-Sprint-5 catch-all bucket). |
| `feedback_worktree_env_drift` | §14 R13; §13.4 fixtures. |
| `feedback_use_coding_team_skill` | Implementation phase uses `arcis:code`. |
| `reference_watch_loop_management` | §3.5 (post-cutover canonical env); §5.2 B1 (NSSM-managed; restart via `nssm restart`); §14 R16. |
| `project_gpu_upgrade` | §1, §3, §12 (operator-guide-insert.md); NUM_PARALLEL discussion. |
| `feedback_pm_dispatch_path_verification` | post-Sprint-5 plan Glob-verifies paths. |
| `user_preferences` (Quality over speed) | Thoroughness across §11, §13, §14, §16. |

---

## 18. Appendix B — Cross-References to Deep Report Findings

| Deep report area | Spec section that addresses |
|---|---|
| Focus 1 (vram_manager.py) | §7; §6.8–6.11; §13.3. |
| Focus 2 (trainer.py device_map='auto') | §5; §6.1; §13.2. |
| Focus 3 (training_data/train.py regeneration) | §3.2; §6.1; §12. |
| Focus 4 (client.py + grammar_client.py) | §8; §9; §6.6, §6.7. |
| Focus 5 (ollama_watchdog.ps1) | §5 B2; §6.4; §6.16; §13.2 guardrails. |
| Focus 6 (verify_training_readiness.py) | §6.3; §10.7; §13.2. |
| Focus 7 (settings.example.yaml) | §6.15. |
| Focus 8 (system_metrics + telegram_commands) | §6.13, §6.14; §13.2. |
| Focus 9 (tests patterns) | §13.4 fixtures. |
| Focus 10 (operator-guide) | §12 + external `operator-guide-insert.md`. |
| Coverage gap: overnight_train.py | §15 item 1; §14 R7. |
| Coverage gap: start_ollama_watchdog.bat | §15 item 2; §14 R8. |
| Surface report correction: Unsloth pin NOT stale | §2.2; §6.2; §16 Q9. |
| Operator memory: post-Sprint-5 NSSM env state | §3.5; §5.2 B1; §10.1; §14 R16. |

---

## 19. Appendix C — Strategy A Mechanism Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│  Operator Box (Windows 11)                                            │
│                                                                       │
│  ┌────────────────────────────────────────────────────────────────┐  │
│  │  NSSM Service: ArcisWatchLoop                                   │  │
│  │  AppEnvironmentExtra (post-Sprint-5 + post-Sprint-5 additions):           │  │
│  │    ARCIS_DB_PATH=C:/arcis/data/ai_research_desk.sqlite3         │  │
│  │    SYNC_THREAD_ENABLED=false                                    │  │
│  │    DATABASE_URL=postgresql://halcyon_app:...@localhost:5433/... │  │
│  │    ARCIS_PG_CUTOVER_ENABLED=1                                   │  │
│  │    PYTHONUTF8=1                                                 │  │
│  │    CUDA_VISIBLE_DEVICES=0    ← B1 (post-Sprint-5 addition)                │  │
│  │    CUDA_DEVICE_ORDER=PCI_BUS_ID  ← B0 (post-Sprint-5 addition)            │  │
│  └─────────────────┬──────────────────────────────────────────────┘  │
│                    │ Popen inherits env                              │
│                    ▼                                                  │
│  ┌────────────────────────────────────────────────────────────────┐  │
│  │  python -m src.main startup (watch loop)                        │  │
│  │  Sees only GPU 0 (RTX 3090) per PCI_BUS_ID ordering             │  │
│  │  Startup banner emitted to logs/watchdog.log                    │  │
│  └─────────────────┬──────────────────────────────────────────────┘  │
│                    │ Popen inherits env                              │
│                    ▼                                                  │
│  ┌────────────────────────────────────────────────────────────────┐  │
│  │  python -m scripts.overnight_train                              │  │
│  │  CUDA_VISIBLE_DEVICES=0, CUDA_DEVICE_ORDER=PCI_BUS_ID            │  │
│  │  trainer.py: device_map={'': 0} (fail-fast)                     │  │
│  │  All CUDA work on RTX 3090                                      │  │
│  └────────────────────────────────────────────────────────────────┘  │
│                                                                       │
│  ──────────────────────────────────────────────────────────────────   │
│                                                                       │
│  ┌────────────────────────────────────────────────────────────────┐  │
│  │  NSSM Service: ArcisOllamaWatchdog (NEW in the post-Sprint-5 window)                 │  │
│  │  AppEnvironmentExtra:                                           │  │
│  │    CUDA_VISIBLE_DEVICES=1    ← B2′                              │  │
│  │    CUDA_DEVICE_ORDER=PCI_BUS_ID                                 │  │
│  │  Executable: powershell -File scripts/ollama_watchdog.ps1       │  │
│  └─────────────────┬──────────────────────────────────────────────┘  │
│                    │ Start-Process inherits parent shell env         │
│                    ▼                                                  │
│  ┌────────────────────────────────────────────────────────────────┐  │
│  │  ollama_watchdog.ps1 (process scope, defense-in-depth)          │  │
│  │    $env:CUDA_VISIBLE_DEVICES = '1'                              │  │
│  │    $env:CUDA_DEVICE_ORDER = 'PCI_BUS_ID'                        │  │
│  │    $env:OLLAMA_NUM_PARALLEL = '2'                               │  │
│  └─────────────────┬──────────────────────────────────────────────┘  │
│                    │ Start-Process inherits parent shell env         │
│                    ▼                                                  │
│  ┌────────────────────────────────────────────────────────────────┐  │
│  │  ollama.exe + ollama_llama_server.exe                           │  │
│  │  CUDA_VISIBLE_DEVICES=1, CUDA_DEVICE_ORDER=PCI_BUS_ID            │  │
│  │  Serves halcyon-v1 on RTX 3060                                  │  │
│  │  Listens on localhost:11434                                     │  │
│  └────────────────────────────────────────────────────────────────┘  │
│                                                                       │
│  ┌─────────────────────────────────────────────────────────────────┐ │
│  │  Hardware (enumeration order pinned via PCI_BUS_ID):             │ │
│  │    PCIe 01:00.0 — RTX 3090 24 GB → GPU 0                         │ │
│  │    PCIe 08:00.0 — RTX 3060 12 GB → GPU 1                         │ │
│  └─────────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 20. Document Control

- **Spec authoritative path:** `docs/audits/2026-05-12-dual-gpu-ideation/spec.md`
- **Operator-guide insert authoritative path:** `docs/audits/2026-05-12-dual-gpu-ideation/operator-guide-insert.md`
- **Brief:** `docs/audits/2026-05-12-dual-gpu-ideation/brief.md`
- **Plan:** deferred to the post-Sprint-5 window (`docs/audits/2026-05-12-dual-gpu-ideation/plan.md` to be generated by post-Sprint-5 Architect pass).
- **Spec consumable by:** `arcis:code --spec ... --plan ...` once plan is generated.
- **Strict-rigor receipt:** every recommendation in §5–§13 carries a "why" line grounded in deep_report findings or operator memory.
- **Revision log:**
  - **v1 (initial draft):** Feasibility reviewer findings (1 major + 4 minor) returned REQUEST_CHANGES.
  - **v2 (Feasibility revision):** corrected test count 17→21; fixed `get_vram_used_mb` method name; standardized `client.py:107-137` line range; promoted optional tests to required; pinned operator-guide insertion point.
  - **v3 (Devil's Advocate revision, this document):** (a) replaced destructive NSSM env copy-paste with read-merge-write pattern + post-Sprint-5 canonical env preservation (§3.5, §5.2 B1, §10.1, §13.7, R16); (b) pinned `CUDA_DEVICE_ORDER=PCI_BUS_ID` at every boundary as B0 with new failure mode F13 and risk R19 (§5.0, §6 various, §13.2, §14); (c) tightened spec-vs-impl boundary — prescriptive code blocks moved to non-normative Appendix D, operator-guide §12.1 prose moved to external `operator-guide-insert.md` (§6 prose-only, §12.1); (d) downgraded OLLAMA_NUM_PARALLEL default 4→2 with opt-in load-test path and risk R17 (§6.4, §10.6, §12.3, R17); (e) NSSM-wrapped ollama_watchdog as `ArcisOllamaWatchdog` service for reboot survival — new §6.16 + §10.0 pre-flight + §11.5 recovery + F14 + R18 + resolved Q5. New §21 Known Considerations captures 4 minor findings. Required net test delta updated +4→+8 (3690 floor minimum).

---

## 21. Known Considerations (minor findings acknowledged — not blocking)

The following minor findings were raised by Devil's Advocate review and acknowledged as accepted considerations. Each is either already addressed elsewhere in the spec or scoped as a follow-up for SP7+ hardening; none blocks post-Sprint-5 implementation.

### 21.1 Get-Process child env limitation on Windows

**Finding:** the `Get-Process StartInfo.EnvironmentVariables` verification command in early drafts contradicted Windows ACL behavior — `Get-Process` does not expose child env for processes you didn't start, returning empty results. An operator following the command verbatim would see an empty result and become confused.

**Status:** addressed in this revision. §5.2 B1, §10.1 step 6, and §10.2 all use the startup-banner log-line approach. §6.11 promotes the startup banner emission to a Required watch.py addition. Cross-reference: §5.2 ↔ §10.2 both link to the same canonical verification path.

### 21.2 Partial driver crash ("soft hang") not in original matrix

**Finding:** Windows NVIDIA drivers exhibit a "soft hang" state where the GPU remains enumerable but CUDA work hangs indefinitely. F1/F2 (full driver crashes) cover hard failures; soft hangs are detected only by wall-clock training time exceeding expected duration.

**Status:** captured as F15 in §11.1. Mitigation deferred to SP7+ hardening — proposed mechanism: training subprocess emits a heartbeat to a small status file every N minutes; watch loop polls the file and kills the training subprocess if heartbeat is stale beyond a threshold (e.g., 15 min). Out of scope for post-Sprint-5 because (a) it requires new instrumentation in `scripts/overnight_train.py`, (b) it overlaps with broader observability work, (c) no documented incident to date — preventive rather than reactive.

### 21.3 Grammar config-level validation gap

**Finding:** R4 mitigation covers source-level guardrails (no hardcoded `n_gpu_layers=-1`). But an operator can set `llm.use_grammar_enforcement: true` + `llm.grammar_n_gpu_layers: -1` + training enabled simultaneously in `config/settings.local.yaml`, and the source-level test passes (because the code reads from config). The runtime collision is real.

**Status:** acknowledged. Test `test_strategy_a_env_discipline.py` covers source-level regression only. Recommended SP7+ follow-up: add a startup-time config validation in `src/main.py` (or wherever `startup` lives) that refuses to start the watch loop if all three conditions are simultaneously true (grammar enabled + grammar_n_gpu_layers > 0 + training enabled), with a clear error message pointing to the grammar/training contention. Lower-priority alternative: emit a startup warning rather than refusing — operator decides at plan-review which severity is appropriate.

### 21.4 Strategy E incidentally already happening

**Finding:** the existing single embedding call site in `src/intel/leakage_detector.py` (POST /api/embeddings) already executes against Ollama on GPU 1 under Strategy A — incidental, not designed. The original §2.2 "Strategy E deferred" row did not acknowledge this.

**Status:** addressed in §2.2 — the Strategy E row now notes the existing call site as incidentally executed against Ollama on GPU 1. No design change required; the observation simply ensures the spec does not misrepresent the actual runtime state. If embedding workload grows substantially, the separate post-Sprint-5 Strategy E design (per the original deferral) would formalize this and decide whether to keep it on Ollama / GPU 1 or split off a dedicated embedding service.

---

## Appendix D — Implementation Guidance (non-normative)

This appendix contains prescriptive code snippets useful to the post-Sprint-5 implementer. **These are non-normative** — they illustrate one valid implementation but do not constrain the implementer to specific syntax. Spec sections §5–§13 describe the WHAT; this appendix offers reference HOW. The implementer remains responsible for matching codebase conventions, refactoring as needed, and adapting to context discovered during implementation.

### D.1 verify_training_readiness.py — module-top env pin

Reference pattern for defense-in-depth in the verification script (before any torch import):

```python
import os
os.environ.setdefault('CUDA_DEVICE_ORDER', 'PCI_BUS_ID')
```

Rationale: even if an operator runs the script from a shell without the User-scope env set, the script's own runtime sees deterministic device order. The check itself can still WARN that `CUDA_DEVICE_ORDER` wasn't set externally so the operator knows to fix the shell.

### D.2 NSSM ArcisWatchLoop env — write the merged block

Reference PowerShell command (after capturing pre-change env per §10.1 Step 1 and constructing the merged variable list in Step 3):

```powershell
# Replace each $... with the value captured from the pre-change snapshot;
# DO NOT remove any variable that was present pre-change.
nssm set ArcisWatchLoop AppEnvironmentExtra `
  "ARCIS_DB_PATH=$arcisDbPath" `
  "SYNC_THREAD_ENABLED=$syncThreadEnabled" `
  "DATABASE_URL=$databaseUrl" `
  "ARCIS_PG_CUTOVER_ENABLED=$pgCutoverEnabled" `
  "PYTHONUTF8=$pythonUtf8" `
  "CUDA_VISIBLE_DEVICES=0" `
  "CUDA_DEVICE_ORDER=PCI_BUS_ID"
nssm restart ArcisWatchLoop
```

Implementer should parameterize via a helper PowerShell function that reads the pre-change snapshot file and emits the merged invocation programmatically, to remove copy-paste hazard at execution time.

### D.3 ollama_watchdog.ps1 — env block at script top

Reference snippet to add at script top:

```powershell
# Strategy A — pin Ollama to GPU 1 (RTX 3060)
$env:CUDA_VISIBLE_DEVICES = '1'
$env:CUDA_DEVICE_ORDER = 'PCI_BUS_ID'
# NUM_PARALLEL default 2 (operator-validated safe); only set to 4 after §10.6 load test confirms < 11.5 GB peak.
if (-not $env:OLLAMA_NUM_PARALLEL) { $env:OLLAMA_NUM_PARALLEL = '2' }
Log "GPU binding: CUDA_VISIBLE_DEVICES=$env:CUDA_VISIBLE_DEVICES CUDA_DEVICE_ORDER=$env:CUDA_DEVICE_ORDER (RTX 3060)"
Log "OLLAMA_NUM_PARALLEL=$env:OLLAMA_NUM_PARALLEL"
```

And inside `Start-OllamaHeadless`:

```powershell
Log "Launching Ollama: CUDA_VISIBLE_DEVICES=$env:CUDA_VISIBLE_DEVICES CUDA_DEVICE_ORDER=$env:CUDA_DEVICE_ORDER NUM_PARALLEL=$env:OLLAMA_NUM_PARALLEL"
```

### D.4 launch_training_subprocess — explicit env (defense-in-depth)

Reference Python pattern for the new `src/training/launcher.py` (one valid implementation; structure to match codebase conventions):

```python
env = {**os.environ, 'CUDA_VISIBLE_DEVICES': '0', 'CUDA_DEVICE_ORDER': 'PCI_BUS_ID'}
proc = subprocess.Popen([sys.executable, *script_args], env=env, stdout=log_file, stderr=subprocess.STDOUT)
```

### D.5 client.py — _check_ollama_health replacement

Reference Python pattern for the function body replacement at `src/llm/client.py:107-137`:

```python
def _check_ollama_health(consecutive_failures: int) -> bool:
    """Check Ollama health. Restart is delegated to ArcisOllamaWatchdog NSSM service."""
    if is_llm_available():
        return True
    logger.error(
        "[LLM] Ollama unresponsive after %d consecutive failures — "
        "watchdog should restart within ~30s. If not, check `nssm status ArcisOllamaWatchdog`.",
        consecutive_failures,
    )
    return False
```

Implementer adapts the function signature and module-globals access to match the actual class/module structure of `src/llm/client.py`.

### D.6 grammar_client.py — config-driven n_gpu_layers

Reference pattern at `src/llm/grammar_client.py:144`:

```python
n_gpu_layers = config.get('llm', {}).get('grammar_n_gpu_layers', 0)
llm = Llama(model_path=str(model_path), n_gpu_layers=n_gpu_layers, ...)
```


## 22. Design Decisions (recorded)

| # | Decision | Rationale (one-line) | Alternatives rejected |
|---|---|---|---|
| 1 | NSSM AppEnvironmentExtra changes follow read-merge-write pattern, not copy-paste | NSSM AppEnvironmentExtra is a replacement operation (verbatim overwrite of the entire block). The post-Sprint-5 / PR #1056 production env contains five load-bearing vars (ARCIS_DB_PATH, SYNC_THREAD_EN |  |
| 2 | Pin CUDA_DEVICE_ORDER=PCI_BUS_ID at every CUDA-consuming boundary | CUDA's default `FASTEST_FIRST` ordering is governed by a heuristic (compute capability × SM count × clock × tie-breaker) that NVIDIA does not guarantee stable across driver releases. PCI_BUS_ID is det |  |
| 3 | OLLAMA_NUM_PARALLEL default = 2 (operator-validated); 4 is opt-in after load test | Operator memory `project_gpu_upgrade` and operator-guide §5 establish that NUM_PARALLEL=4 on the 3060 (12 GB) yields ~10.4 GB resident with ~0.4 GB cushion. Typical CUDA workspace transient allocation |  |
| 4 | Strict spec-vs-implementation boundary: prescriptive code moves to non-normative Appendix D | The earlier draft included Python function bodies, exact env-dict literals, complete PowerShell blocks, and 60 lines of operator-guide prose inline in the spec. This drifts from SPEC_ONLY discipline — |  |
| 5 | NSSM-wrap ollama_watchdog.ps1 as ArcisOllamaWatchdog service for reboot survival | Original Q5 in §16 deferred this as a future hardening pass. Devil's Advocate identified the gap: NSSM auto-starts ArcisWatchLoop on reboot, but ollama_watchdog.ps1 (launched via `start_ollama_watchdo |  |
