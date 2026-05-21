# Dual-GPU Workload Separation — Design Spec (v6, revised)

> Produced by the ARCIS Design Team pipeline (codebase analysis → architect →
> feasibility review → adversarial review → 2 revision passes). Supersedes the
> deferred `docs/audits/2026-05-12-dual-gpu-ideation/` spec.
>
> **Review summary:** Feasibility REQUEST_CHANGES (2 major) → revised. Devil's
> Advocate CONCERNS (1 critical + 5 major) → revised. 3 minors retained as Known
> Considerations (§7). Hardware **confirmed live**: GPU0 RTX 3090 24 GB (PCI
> 01:00.0), GPU1 RTX 3060 12 GB (PCI 08:00.0).

## 1. Overview

### 1.1 Problem
The host treats its two GPUs (RTX 3090 24 GB = GPU0, RTX 3060 12 GB = GPU1) as a
single shared VRAM pool. Ollama inference and PyTorch fine-tuning are mutually
exclusive: the watch loop runs a nightly **VRAM handoff** (`src/scheduler/vram_manager.py`)
that unloads/kills Ollama before training and reloads it after. This handoff has
failed 4+ times (tasks #54, #56, #66, #80) because the morning force-kill targets the
**Ollama** process on the shared GPU — and an Ollama runner wedged in a CUDA syscall
cannot be killed, leaving VRAM held and inference dead into market hours. The deepest
root cause (this session): the watch loop runs as **LocalSystem** while Ollama is a
**per-user** install, so `_find_ollama` resolves `%LOCALAPPDATA%` to the systemprofile
and the graceful `ollama stop` never even executes — every night silently falls
through to the failing force-kill path.

### 1.2 Solution
Statically partition the workloads by physical GPU and remove the handoff entirely:
- **Training → GPU0 (RTX 3090, 24 GB):** training subprocess launched with
  `CUDA_VISIBLE_DEVICES=0` + `CUDA_DEVICE_ORDER=PCI_BUS_ID`.
- **Ollama → GPU1 (RTX 3060, 12 GB):** Ollama runs under a dedicated NSSM service
  (`ArcisOllamaWatchdog`) with `CUDA_VISIBLE_DEVICES=1` + `CUDA_DEVICE_ORDER=PCI_BUS_ID`.
- **Delete** `src/scheduler/vram_manager.py` and its handoff calls. The two workloads
  coexist on separate physical GPUs; there is no VRAM to hand off.
- **Replace** the evening/morning handoff with: (evening) launch training in the
  off-hours window; (morning + market-open guard) a **bounded-escalation stop** of the
  training process so GPU0 + CPU are free before the trading day. Ollama is never
  touched by the stop — it lives on GPU1 under the watchdog.
- **Migrate telemetry** from `vram_handoff_*` to `gpu_health_*`.

### 1.3 What v6 fixes (vs the v5 / 2026-05-12 design)
- **CRITICAL — guaranteed stop.** The morning/market-open stop is a **bounded
  escalation**: request cooperative stop → wait up to `MORNING_STOP_TIMEOUT` for clean
  self-exit → if the tracked training PID is still alive, **hard-terminate that PID**
  (GPU0 training process *only*) → clear flag. Force-killing the **isolated** training
  PID is safe — it cannot touch Ollama on GPU1; worst case is a partial checkpoint
  (handled by staged save-on-stop). The 4 prior handoff failures were caused by killing
  **Ollama** wedged on a shared GPU; that anti-pattern does not apply here.
- **MAJOR-1 — absolute flag path.** `STOP_OVERNIGHT` resolved to an **absolute** path
  (no relative-cwd landmine under LocalSystem's `C:\Windows\System32` cwd).
- **MAJOR-2 — concurrency + overrun.** Documented RAM/CPU/disk/SQLite budget; off-hours
  launch fence + market-open guard (hard stop by 09:25 ET); below-normal CPU priority on
  the training subprocess; explicit worst-case-overrun behavior.
- **MAJOR-3 — single-owner Ollama.** Watchdog pre-flight terminates/adopts any
  pre-existing Ollama; Ollama per-user autostart disabled.
- **MAJOR-4 — deploy atomicity.** Startup guard fails loud if `ArcisOllamaWatchdog` is
  not running; ordered deploy + explicit rollback.
- **MAJOR-5 — behavioral tests** for the stop mechanism, not just a test count.

### 1.4 Proportionality
Training is presently **dormant** — `get_training_split_viability()` returns
`HOLDOUT EMPTY` and `run_fine_tune()` blocks promotion, so no model is trained tonight.
The separation work is therefore low-urgency. The low-risk pieces (GPU pinning,
watchdog, telemetry rename, startup guard) can land independently of the dormant
training path; the operator decides timing (Known Consideration §7.3).

---

## 2. Architecture

```
  GPU0  RTX 3090 (24 GB, PCI 01:00.0)        GPU1  RTX 3060 (12 GB, PCI 08:00.0)
   PyTorch fine-tune subprocess               Ollama inference server
   CUDA_VISIBLE_DEVICES=0                      CUDA_VISIBLE_DEVICES=1
   CUDA_DEVICE_ORDER=PCI_BUS_ID               CUDA_DEVICE_ORDER=PCI_BUS_ID
   launched by run_fine_tune()                owned by ArcisOllamaWatchdog (always up)
        ^   ^                                       ^
        |   | stop flag + PID hard-terminate        | single-owner, never unloaded
  ArcisWatchLoop (NSSM, LocalSystem) — watch.py + watch_handlers.py
   evening: launch training (off-hours fence)
   morning + market-open guard: bounded-escalation stop of the training PID
   startup: FAIL LOUD if ArcisOllamaWatchdog not running
```

**Pinning:** `CUDA_DEVICE_ORDER=PCI_BUS_ID` everywhere so `CUDA_VISIBLE_DEVICES=0` is
deterministically the 3090 and `=1` the 3060 (NVIDIA's default `FASTEST_FIRST` can flip
indices on driver upgrade/reseat).

**New service `ArcisOllamaWatchdog`** (`src/scheduler/ollama_watchdog.py` under NSSM):
single-owner pre-flight (terminate/adopt any existing Ollama) → `ollama serve` pinned to
GPU1 → 30 s health loop emitting `gpu_health_ollama_ok`. Ollama per-user autostart is
disabled so the watchdog is the sole owner.

---

## 3. Data Model

No schema changes. Telemetry metric-key rename only:

| Old (delete) | New (add) |
|---|---|
| `vram_handoff_training_ok` | `gpu_health_training_ok` |
| `vram_handoff_inference_ok` | `gpu_health_ollama_ok` |
| `safe_send("vram_handoff", ...)` | `safe_send("gpu_health", ...)` |

`reports._latest_vram_handoff_ok` → `_latest_gpu_health_ok`, with a 30-day
backward-compatible read window accepting old keys to avoid a post-deploy reporting gap.

The only persistent-state surface is the absolute filesystem flag `STOP_OVERNIGHT`
(now actually read) + a `logs/training.pid` pidfile for the lost-handle kill fallback.

---

## 4. Control Flow

### 4.1 Stop flag (absolute path)
`STOP_FLAG = os.path.join(os.path.dirname(DB_PATH), "STOP_OVERNIGHT")` — absolute,
derived from `src.config.DB_PATH`. The generated inline training script receives the
**resolved literal** baked in AND reads `os.environ["ARCIS_STOP_FLAG"]` as a fallback;
the launch sets `cwd=<repo_root>`. Writer API: `request_training_stop()` / `clear_training_stop()`.

### 4.2 Training subprocess launch
`run_fine_tune` sets `CUDA_VISIBLE_DEVICES=0`, `CUDA_DEVICE_ORDER=PCI_BUS_ID`,
`ARCIS_STOP_FLAG`; `cwd=<repo_root>`; `creationflags=BELOW_NORMAL_PRIORITY_CLASS`;
tracks the `Popen` handle + writes `logs/training.pid`. The `timeout=7200` backstop is
retained as a ceiling but is no longer the only guaranteed stop.

### 4.3 Bounded-escalation stop (the critical fix)
`stop_training_bounded(pid_handle, timeout=MORNING_STOP_TIMEOUT≈300s)`:
1. `request_training_stop()` (touch flag).
2. Cooperative wait up to timeout for clean self-exit (preferred — saves partial
   progress to staging).
3. If still alive: **hard-terminate the tracked training PID only** —
   `terminate()`→`wait(30)`→`kill()`→`wait(10)`; lost-handle fallback = PID-escalation
   (`taskkill /f /t /pid` → `Stop-Process -Force` → `wmic delete`) from `logs/training.pid`.
   **Never** an `/im` name-kill, **never** Ollama.
4. `clear_training_stop()`.
5. Emit `gpu_health_training_ok` with `{stopped_via, stalled_phase}`.

### 4.4 Cooperative checks in non-step phases
`STOP_OVERNIGHT` polls added before/after tokenization, before GGUF export, and between
curriculum stages (where `on_step_end` never fires) — clean exit + staged partial save.
The hard-terminate (§4.3 step 3) covers residual native-call stalls.

### 4.5 Scheduling fence + market-open guard
- Off-hours fence: training launches only within ~18:30–04:00 ET AND market closed.
- Market-open guard: if a training PID is alive and `now >= 09:25 ET` on a trading day,
  `stop_training_bounded` fires **regardless of `MORNING_STOP_TIMEOUT`** — the hard
  ceiling guaranteeing GPU0/CPU free before 09:30. Max GPU0 exposure to a stalled run:
  `MORNING_STOP_TIMEOUT + 40 s` (morning) or ~40 s (market-open guard) — never 7200 s.

### 4.6 Startup deploy-atomicity guard
`WatchLoop` startup runs `_assert_ollama_watchdog_present()`: if `ArcisOllamaWatchdog`
is not `RUNNING`, alert (`safe_send("gpu_health", success=False, ...)`) and exit non-zero
— prevents the half-applied state (code merged, watchdog absent → no Ollama owner).

### 4.7 Concurrency budget
- **VRAM:** train ≈ 11–14 GB on the 3090 (24 GB); Ollama ≈ 5–9 GB on the 3060 (12 GB) —
  separate cards, no contention.
- **System RAM:** train ≈ 8–12 GB + Ollama ≈ 2–3 GB + watch loop ≈ 1–2 GB → ≤ 32 GB host
  coexists; `paged_adamw_8bit` offloads optimizer state.
- **CPU:** training subprocess `BELOW_NORMAL_PRIORITY_CLASS` so the watch loop + Ollama
  stay responsive.
- **Disk/SQLite:** training reads `training_examples` (read-only export), writes only to
  `training_data/`; WAL mode tolerates the concurrent reader. No new lock contention.

---

## 5. Error Handling

| Condition | Handling |
|---|---|
| Cooperative stop ignored (non-step stall) | Bounded escalation hard-terminates the tracked training PID. Guaranteed. |
| Training PID handle lost (watch-loop restart) | PID-escalation kill from `logs/training.pid`. Never name-kill. |
| `ArcisOllamaWatchdog` down at watch start | Startup guard fails loud + alerts + exits non-zero. |
| Pre-existing Ollama on GPU0 | Watchdog pre-flight terminates/adopts before launching GPU1 instance. |
| Ollama crash mid-day | Watchdog health loop restarts (re-runs pre-flight). |
| Partial checkpoint on hard-terminate | Written to **staging**, promoted only on completeness check (§7.2). |
| Market-open guard fires mid-stage | Bounded escalation; incomplete checkpoint discarded; next evening re-runs. |

---

## 6. Testing Strategy (behavioral, not count-only)

1. Stop-during-step-loop → loop exits within N steps, partial saved to staging.
2. Stop-during-non-step-phase → bounded escalation `terminate()`→`kill()` on the tracked
   PID; assert **no** Ollama/name-kill.
3. Absolute path + cwd: `os.path.isabs(STOP_FLAG)`; inline script has the literal + reads
   `ARCIS_STOP_FLAG`; launch passes `cwd=<repo_root>` + `CUDA_VISIBLE_DEVICES=0`.
4. Watchdog single-owner pre-flight terminates/adopts a faked pre-existing Ollama.
5. Market-open guard at faked `now=09:26 ET` with live PID invokes the bounded stop.
6. Startup guard with watchdog not-RUNNING raises + alerts + non-zero exit.
7. Telemetry: handlers emit `gpu_health_*`; `reports._latest_gpu_health_ok` reads them.
8. Supplementary: `pytest --collect-only` count vs CI floor **EXPECTED=5100**
   (`.github/workflows/pg-tests.yml:98`) after deleting the ~49 vram_manager tests —
   guardrail-or-justified-bump in the same PR. (Count is supplementary, not the gate.)

---

## 7. Known Considerations (the 3 minors)

1. **Reboot ordering.** Declare `ArcisOllamaWatchdog` as a dependency of `ArcisWatchLoop`
   (NSSM `DependOnService` or a watch-loop readiness gate) so the startup guard (§4.6)
   does not false-fail during a cold-boot race.
2. **Staged partial-export.** Save-on-stop + GGUF export write to a staging path
   (`training_data/halcyon-staging/`) and promote to `halcyon-latest` only after a
   completeness check — a partial hard-terminate checkpoint never overwrites a good model.
3. **Proportionality / timing.** Training is dormant (`HOLDOUT EMPTY`). The low-risk
   separation pieces (watchdog GPU1 pin, telemetry rename, startup guard) can land now;
   the training-launch rewiring can be deferred until the holdout corpus is viable. Land
   in two waves if preferred.

---

## 8. Design Decisions

| Decision | Rationale |
|---|---|
| Bounded-escalation stop (cooperative → hard-terminate the tracked training PID) instead of clear-flag-and-give-up | v5's give-up left a 300s–7200s window where a non-step-phase stall ran on GPU0 into market hours. The training process is isolated on GPU0, so killing its PID is safe (cannot touch Ollama on GPU1; worst case = partial checkpoint, handled by staged save). Restores a guaranteed pre-open stop. |
| Hard-terminate targets the tracked training PID only (Popen + `logs/training.pid` escalation), never `/im`, never Ollama | The 4 prior handoff failures were caused by name-killing Ollama wedged in a kernel-mode CUDA call. Killing a specific isolated training PID on GPU0 is a different, safe operation. |
| `STOP_OVERNIGHT` resolved to an absolute path, baked literal + `ARCIS_STOP_FLAG` env + explicit `cwd` | NSSM LocalSystem cwd is `C:\Windows\System32`, so a relative `data/STOP_OVERNIGHT` makes `os.path.exists` always False → silent stop failure. Three independent guarantees harden it. |
| `ArcisOllamaWatchdog` single-owner pre-flight + disable Ollama per-user autostart | `CUDA_VISIBLE_DEVICES=1` only constrains a newly launched process; a pre-existing Ollama (autostart/manual/prior boot) keeps running on GPU0 and would contend with training. Pre-flight guarantees exactly one Ollama, pinned to GPU1. |
| WatchLoop startup FAILS LOUD if `ArcisOllamaWatchdog` not RUNNING; ordered deploy + rollback | The watchdog install is out-of-band ops; a half-applied state (code merged, watchdog absent) leaves no Ollama lifecycle owner. Failing loud converts a silent dual-loss into an obvious, recoverable error. |
| Market-open guard (hard stop by 09:25 ET) + off-hours launch fence + below-normal CPU priority | Training + Ollama now run concurrently; a hard ceiling guarantees GPU0/CPU free before the open even if the morning window is missed, and CPU niceness prevents starving live inference. |
| Behavioral test suite replaces the count-only guardrail | A `--collect-only` count proves nothing about whether the new stop works. The 49 deleted vram tests covered "training stops when asked"; replacements must cover the new mechanism. |
| Eliminate the handoff via static dual-GPU pinning rather than fix `_find_ollama` | Four hotfixes patched symptoms of the same coordination protocol. Both GPUs are physically present, so deleting the protocol removes the entire failure class instead of repairing it. |
| Staged partial-export then promote-on-completeness (Known Consideration) | A hard-terminate can leave an incomplete artifact; staging + completeness check makes it non-destructive to a known-good model. |

## 9. Review Provenance

- **Codebase analysis** (surface + deep): confirmed the root cause in code, found the
  deferred 2026-05-12 spec as prior art, the `client.py:122` sibling bug, the two-launcher
  fork, the ~49-test reality (vs the old spec's 21), and the live CI floor (5100).
- **Feasibility review:** REQUEST_CHANGES (2 major) — `overnight_train.py` had no
  `STOP_OVERNIGHT` poll (the morning stop only worked via force-kill); flag-name
  conflation (`_vram_handoff_done` vs `_morning_handoff_done`). Both fixed in revision 1.
- **Devil's Advocate:** CONCERNS (1 critical + 5 major) — the 300s-vs-7200s guaranteed-stop
  gap, the relative-cwd silent landmine, non-GPU concurrency contention, two-Ollama
  single-owner gap, deploy atomicity, behavioral test gap. All fixed in revision 2 (this v6).

