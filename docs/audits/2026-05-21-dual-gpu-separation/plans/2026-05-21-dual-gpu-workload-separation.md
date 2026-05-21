# Implementation Plan — Dual-GPU Workload Separation (v6)

**Spec:** `../specs/2026-05-21-dual-gpu-workload-separation-design.md`
**Complexity:** complex (~14 files, ~49 tests deleted + ~30 behavioral added; CI floor EXPECTED=5100)
**Execution order (parallel batches):** `[[1, 6], [2, 3, 4], [5], [7], [8], [9, 10]]`

> Implement via `/arcis:code --spec <spec> --plan <this>`. Each task lists scope fences;
> obey the "never kill Ollama / never `/im` name-kill" and "absolute flag path" invariants.

## File structure

- **New:** `src/scheduler/training_stop.py`, `src/scheduler/training_control.py`,
  `src/scheduler/ollama_watchdog.py`, `src/training/stop_callback.py`,
  `docs/ops/dual_gpu_separation.md`, behavioral test modules.
- **Modified:** `src/training/trainer.py`, `src/scheduler/watch_handlers.py`,
  `src/scheduler/watch.py`, `src/scheduler/overnight.py`, `src/scheduler/reports.py`.
- **Deleted:** `src/scheduler/vram_manager.py`, 5× `tests/test_vram_manager*.py` (~49 tests).

## Tasks

### Task 1 — Absolute stop-flag module + writer/reader API  *(batch 1)*
`src/scheduler/training_stop.py`: `STOP_FLAG` = absolute path from `src.config.DB_PATH`;
`request_training_stop()`, `clear_training_stop()` (unlink missing_ok), `is_stop_requested()`
(checks `ARCIS_STOP_FLAG` env then absolute default). No relative paths.
- Tests: `os.path.isabs(STOP_FLAG)`; create/clear idempotent; env override honored; relative cwd doesn't change resolution.
- Fence: no trainer/watch edits; no kill logic; don't touch vram_manager.

### Task 2 — GPU-pin training subprocess + bake absolute flag into inline script  *(batch 2, dep 1)*
`trainer.py`: `_training_subprocess_env()` adds `CUDA_VISIBLE_DEVICES=0`, `CUDA_DEVICE_ORDER=PCI_BUS_ID`, `ARCIS_STOP_FLAG`; `run_fine_tune` launches with `cwd=<repo_root>`, `BELOW_NORMAL_PRIORITY_CLASS`, tracks Popen + writes `logs/training.pid`; bake resolved absolute flag literal into the inline scripts + add stop polls before/after tokenization, before GGUF export, between curriculum stages.
- Tests: env vars present; `cwd=repo_root`; inline script has literal + reads `ARCIS_STOP_FLAG` + has non-step polls; pidfile written.
- Fence: don't delete vram_manager (T7); don't change hyperparameters/holdout; don't rewire handlers (T5).

### Task 3 — TrainerCallback cooperative stop (step/epoch)  *(batch 2, dep 1)*
`src/training/stop_callback.py` + inline wiring: `on_step_end`/`on_epoch_end` check `is_stop_requested()` → save partial to **staging** + `control.should_training_stop=True`.
- Tests: fake Trainer/control; flag → stop within one step → staged save (not overwriting `halcyon-latest`).
- Fence: no hard-terminate (T4); no curriculum stage-list changes.

### Task 4 — Bounded-escalation `stop_training_bounded()`  *(batch 2, dep 1)*
`src/scheduler/training_control.py`: cooperative wait → hard-terminate **tracked training PID only** (terminate→kill, with `taskkill /pid`→`Stop-Process`→`wmic` fallback from `logs/training.pid`); never `/im`, never Ollama; clear flag; return `{stopped_via, stalled_phase}`.
- Tests: cooperative exit path; ignore-flag → terminate()+kill() invoked, **no** Ollama/name-kill; lost-handle reads pidfile + PID-escalates.
- Fence: don't call from handlers yet (T5); never kill Ollama; no GPU-pin edits.

### Task 5 — Rewire watch handlers (evening launch + morning bounded stop + market-open guard)  *(batch 3, dep 4)*
`watch_handlers.py`/`watch.py`: `maybe_evening_training` (off-hours fence), `maybe_morning_training_stop` (bounded stop), new `maybe_market_open_training_stop` (≥09:25 ET → bounded stop regardless of timeout); register in handler tuple replacing the two vram handoff entries; rename both flags (`_vram_handoff_done` evening / `_morning_handoff_done` morning).
- Tests: evening launches only in-window; market-open guard at 09:26 ET invokes stop ignoring timeout; morning invokes bounded stop; tuple no longer references handoff handlers.
- Fence: no telemetry rename (T8); no startup guard (T6); don't delete vram_manager (T7).

### Task 6 — Watchdog service + single-owner pre-flight + startup deploy guard  *(batch 1)*
`src/scheduler/ollama_watchdog.py`: pre-flight detect/terminate/adopt existing Ollama → `ollama serve` pinned GPU1 → 30s health loop (`gpu_health_ollama_ok`). `watch.py`: `_assert_ollama_watchdog_present()` startup guard (fail loud + alert + non-zero exit if service not RUNNING).
- Tests: faked pre-existing Ollama terminated/adopted (single owner); launch env `CUDA_VISIBLE_DEVICES=1`+PCI_BUS_ID; startup guard not-RUNNING → raise+alert+exit; RUNNING → proceed.
- Fence: don't install NSSM from code (ops, T9); no training-launch edits; no telemetry rename (T8).

### Task 7 — Delete `vram_manager.py` + handoff call sites  *(batch 4, deps 4,5,6)*
Delete `src/scheduler/vram_manager.py`; remove `VRAMManager`/`handoff_to_training`/`handoff_to_inference` imports + call sites in `overnight.py` + `watch.py`. (`_kill_pid` escalation already salvaged into `training_control.py` in T4.)
- Tests: grep-assert no remaining references in `src/`; import-smoke the scheduler package.
- Fence: don't delete vram TEST files here (T10); don't touch unrelated overnight collector logic.

### Task 8 — Telemetry migration `vram_handoff` → `gpu_health`  *(batch 5, deps 5,7)*
Emit `gpu_health_training_ok`/`gpu_health_ollama_ok` + `safe_send("gpu_health", ...)`; `reports._latest_vram_handoff_ok` → `_latest_gpu_health_ok` reading new keys with a 30-day legacy read window.
- Tests: handlers/overnight emit `gpu_health_*`; reports reads new keys AND resolves a recent legacy row.
- Fence: layout unchanged beyond the key rename; keep the legacy-read window.

### Task 9 — Ops runbook: ordered deploy, watchdog install, rollback  *(batch 6, dep 6)*
`docs/ops/dual_gpu_separation.md`: REQUIRED pre-deploy watchdog install + verify (`nssm install`, GPU1 env, `DependOnService`), disable-Ollama-autostart, ordered deploy (watchdog→code), single-owner invariant, rollback (revert + `nssm remove`).
- Doc-only; verify it lists `sc query ArcisOllamaWatchdog`, DependOnService, autostart-disable, rollback.

### Task 10 — Behavioral test suite + delete obsolete vram tests  *(batch 6, deps 4,5,6,7)*
Delete `tests/test_vram_manager*.py` (~49). Add `tests/scheduler/test_dual_gpu_separation.py` covering: (a) flag during step-loop stops within N steps; (b) non-step-phase → bounded escalation hard-terminate (no Ollama/name-kill); (c) absolute path + cwd asserted; (d) watchdog single-owner; (e) market-open guard triggers stop. Supplementary collect-only count vs EXPECTED=5100.
- Fence: no dead vram_manager imports; if >4 files, delete the extra vram test files in a follow-up sweep.

## Notes
Architecture (GPU0=training, GPU1=Ollama, PCI_BUS_ID, watchdog ownership, telemetry
rename, dual-flag handling) is fixed. v6 hardens the stop mechanism (critical + MAJOR-1/2),
single-owner watchdog (MAJOR-3), deploy atomicity (MAJOR-4), and tests (MAJOR-5).
**Optional two-wave landing** (proportionality): Wave A = Tasks 1, 6, 9 (watchdog GPU1 pin
+ telemetry-adjacent + startup guard + docs) — low-risk, delivers separation of the
*inference* side now; Wave B = Tasks 2,3,4,5,7,8,10 (training-launch rewiring + handoff
deletion) when the holdout corpus is viable. Operator decides.
