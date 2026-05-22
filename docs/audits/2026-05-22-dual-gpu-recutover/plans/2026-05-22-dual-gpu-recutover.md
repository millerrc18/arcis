# Dual-GPU Re-Cutover — Implementation Plan (v7 — adversarial-revision pass)

**MERGE-ORDER (updated):** sim #1162 is HELD for #97, so dual-GPU may merge FIRST. Whichever lands second resolves the guaranteed 9-file conflict (`watch.py`, `watch_handlers.py`, `handler_registration.py`, `overnight.py`, `reports.py`, `telegram.py`, `activity_logger.py`, `test_watch_handlers.py`, `tests/scheduler/test_schedule_health_report.py`). The sim ticks `WatchLoop` generically (no handler-name dependency), so its later rebase is mostly mechanical — BUT the two TEST files need a **semantic** review (old `vram_handoff` assertions → `gpu_health`/new-handler) plus a post-rebase `grep -r "vram_handoff" tests/` == 0 guard (MINOR-2).

**Phasing:** Phase 1 = independent low-risk pieces (land+validate first). Phase 2 = training-lifecycle rewrite. Phase 3 = operator-gated live cutover (doc only — DO NOT EXECUTE).

**Execution order (dependency-ordered batches):** [1,3,5,6,13] → [2,4,7,18] → [9,10] → [11,12] → [14] → [15,16] → [17]

**Discipline:** all dispatches use isolation:worktree; each runs `tests/test_repo_structure.py` in its receipt; worktrees branch from origin/main (PM cherry-picks onto the feature branch); worktrees don't carry `.env` — GPU/Ollama/sc-query/nvidia-smi/psutil tests MUST mock external deps (no real GPU in CI). Tasks 5, 10, 18 all edit watch.py in DISJOINT regions (startup guard / handoff methods / runtime liveness monitor) — sequenced apart; later implementers read earlier changes.

---

## Phase 1 — independent low-risk

## Task 1: Author Ollama watchdog module + steady-state empty-store invariant _(medium)_
**Depends on:** none
Author `src/scheduler/ollama_watchdog.py` against current main (clean re-derivation). `resolve_ollama_exe` (OLLAMA_EXE/OLLAMA_PATH>PATH>per-user glob, NOT %LOCALAPPDATA%), `preflight` (graceful `ollama stop` + PID-scoped kill), `_launch` (Popen with CUDA_VISIBLE_DEVICES=1, CUDA_DEVICE_ORDER=PCI_BUS_ID, OLLAMA_NUM_PARALLEL=2, OLLAMA_MODELS=C:\Users\mille\.ollama\models, CREATE_NO_WINDOW; 8s grace), `ensure_owner` (adopt-if-healthy via GET /api/version **AND non-empty-store assert** else preflight+_launch), `run` (30s health loop emitting gpu_health_ollama_ok). **MAJOR-4:** both the adopt branch AND post-_launch MUST assert the store is non-empty via `GET /api/tags` with the expected model tag present; if absent emit gpu_health_ollama_ok=False with detail empty_model_store/missing_model_tag + loud (safe_send). `__main__`-runnable for NSSM.
**Files:** `src/scheduler/ollama_watchdog.py`, `tests/test_ollama_watchdog.py` | **Read-only:** `src/scheduler/metrics.py`, `src/config/__init__.py`
**Test:** preflight graceful-stop+PID-scoped-kill (mock psutil); ensure_owner adopt-vs-launch; _launch env includes the 3 CUDA/OLLAMA_MODELS vars; single-owner (no double launch); **empty-store: /api/version 200 but /api/tags empty ⇒ gpu_health_ollama_ok=False + loud; missing expected tag ⇒ same**.
**Fence:** No NSSM script (T2). No client.py. No startup guard (T5). No runtime liveness monitor (T18). Defense-in-depth OLLAMA_MODELS in _launch env IS in scope.

## Task 3: Author training_stop.py (absolute STOP path) _(low)_
**Depends on:** none
`STOP_FLAG = os.path.join(os.path.dirname(DB_PATH), 'STOP_OVERNIGHT')`; helpers set_stop/clear_stop/is_stop_requested. Fixes the relative-cwd landmine.
**Files:** `src/training/training_stop.py`, `tests/test_training_stop.py` | **Read-only:** `src/config/__init__.py`
**Test:** STOP_FLAG absolute + anchored at dirname(DB_PATH); set/clear/is round-trip via tmp DB_PATH monkeypatch.
**Fence:** No overnight.py (T11). No stop orchestration (T4). Path + flag helpers only.

## Task 5: Watch-loop startup guard _(low)_
**Depends on:** none
`watch._assert_ollama_watchdog_present()`: `sc query ArcisOllamaWatchdog` → require RUNNING; if not and `ARCIS_SKIP_WATCHDOG_GUARD != '1'`, log loud + raise. Call early in startup. NO SCM DependOnService. Factor the `sc query` RUNNING-parse into a small reusable helper (T18's runtime monitor reuses it).
**Files:** `src/scheduler/watch.py`, `tests/test_startup_guard.py`
**Test:** passes when RUNNING (mock subprocess); raises when not; bypassed when escape hatch set.
**Fence:** Do NOT touch handoff dispatch / flag inits (T10) or the runtime-monitor tick (T18) — same file, DISJOINT regions. Guard method + its call site + the shared sc-query parse helper only.

## Task 6: client.py unpinned-restart race fix (Option a) + call-site fail-soft audit _(low)_
**Depends on:** none
In `_check_ollama_health_or_restart` (client.py:107): keep the health probe; DELETE the Popen(['ollama','serve']) spawn (L120-127) + the 5s re-probe (L128-134). On unhealthy: log watchdog-owns-recovery + return False. **MAJOR-2 audit:** confirm (read-only, document in receipt) that the council-synthesis, premarket-scan, and intraday LLM call sites all treat a False/None return as fail-soft (advisory degrade), never as a hard input that blocks trade execution.
**Files:** `src/llm/client.py`, `tests/test_client_ollama_health.py`
**Test:** healthy→True; unhealthy→False + logs + asserts subprocess.Popen NEVER called (mock); receipt enumerates the 3 call sites as fail-soft.
**Fence:** Don't change the breaker logic or generate/generate_structured call sites. Only the function body (+ the read-only audit note).

## Task 13: Telemetry rename (string-key only) _(medium)_
**Depends on:** none
reports._latest_vram_handoff_ok→_latest_gpu_health_ok (reports.py:64) widen cutoff 3→30 days (reports.py:70) + IN both old+new keys; telegram.notify_vram_handoff→notify_gpu_health (telegram.py:613) + dispatch key 'gpu_health' (telegram.py:1414); activity_logger VRAM_HANDOFF→GPU_HEALTH (activity_logger.py:43). Emit gpu_health_training_ok / gpu_health_ollama_ok. NO schema change.
**Files:** `src/scheduler/reports.py`, `src/notifications/telegram.py`, `src/utils/activity_logger.py`, `tests/test_gpu_health_telemetry.py`
**Test:** reports reads both old+new keys, 30-day window; notify_gpu_health under 'gpu_health'; const renamed.
**Fence:** No schema change. No overnight metric writes (T11). 4 src files intentionally move atomically (the rename can't half-land).

## Phase 2 — training-lifecycle rewrite

## Task 2: NSSM install for watchdog + OLLAMA_MODELS env + AppExit/AppThrottle _(low)_
**Depends on:** 1
Extend `scripts/install_service.ps1` to install ArcisOllamaWatchdog (nssm install ... -m src.scheduler.ollama_watchdog; AppDirectory; AppStdout/Stderr; AppRestartDelay). ADD AppEnvironmentExtra: OLLAMA_MODELS=C:\Users\mille\.ollama\models, CUDA_VISIBLE_DEVICES=1, CUDA_DEVICE_ORDER=PCI_BUS_ID. **MAJOR-2:** set `AppExit Default Restart` + `AppThrottle`/`AppRestartDelay` so a recurring crash escalates (paired with T18's monitor) rather than silently throttle-exhausting. NO DependOnService.
**Files:** `scripts/install_service.ps1` | **Read-only:** `src/scheduler/ollama_watchdog.py`
**Test:** static review — AppEnvironmentExtra has all 3 vars; AppExit Restart + AppThrottle present; no DependOnService; module path matches T1.
**Fence:** No DependOnService (wedge). No watchdog module. No shell-script retire (T16).

## Task 4: Author training_control.py + stop_callback.py + tracked-PID predicate _(medium)_
**Depends on:** 3
`stop_training_bounded(timeout_s)` — set_stop → cooperative wait on tracked PID (logs/training.pid) → hard-terminate TRACKED PID ONLY → clear_stop. **MAJOR-3:** implement `_is_tracked_training_proc(pid)` predicate — ALL of: pidfile parses to int, psutil.pid_exists, proc alive (not zombie), cmdline contains the generated train-script path OR the training-module marker, CVD=0 marker present (best-effort); any NoSuchProcess/AccessDenied/parse error ⇒ False. No-op-safe: missing pidfile / dead PID / mismatch ⇒ LOG + RETURN, terminate NOTHING, clear stale pidfile best-effort. Never /im, NEVER Ollama. `StopOnFlagCallback(TrainerCallback)` — on_step_end/on_evaluate set should_save+should_training_stop when flag set.
**Files:** `src/training/training_control.py`, `src/training/stop_callback.py`, `tests/test_training_control.py`, `tests/test_stop_callback.py` | **Read-only:** `src/training/training_stop.py`
**Test:** bounded stop requests flag, waits, hard-terminates only tracked PID (assert never /im, never Ollama); **predicate cases: missing pidfile no-op; dead PID no-op+clear; PID recycled to watch-loop/unrelated proc ⇒ no-op terminate NOTHING; valid tracked PID ⇒ terminate-tracked-only**; callback sets the control flags.
**Fence:** No trainer.py (T9). No handler wiring (T10). Use training_stop helpers.

## Task 7: GPU-placement + identity smoke test _(medium)_
**Depends on:** 1
`scripts/gpu_placement_smoke.py`: **MAJOR-5 identity check first** — `nvidia-smi --query-gpu=index,name,uuid --format=csv,noheader`; assert index0==24GB 3090 (name/UUID), index1==3060; fail (nonzero) on mismatch. Then placement: launch Ollama under GPU1 pin, load model, query nvidia-smi compute-apps, assert model VRAM on GPU1 NOT GPU0; nonzero exit on fail (gates cutover). `tests/test_gpu_placement_smoke.py` wraps with mocked nvidia-smi+Ollama.
**Files:** `scripts/gpu_placement_smoke.py`, `tests/test_gpu_placement_smoke.py` | **Read-only:** `src/scheduler/ollama_watchdog.py`
**Test:** parse mocked nvidia-smi identity output; pass when index0==3090 & VRAM on GPU1; **fail (nonzero) on simulated index-flip (index0==3060)**; fail when placement VRAM on GPU0.
**Fence:** No live cutover. No watchdog module. Smoke script + mocked test only.

## Task 18: Runtime watchdog-liveness monitor _(medium)_ — NEW (MAJOR-2)
**Depends on:** 1, 13
Add a periodic check INSIDE the WatchLoop tick (~60s cadence, keyed in the per-task `_backoff`): authoritative signal = `sc query ArcisOllamaWatchdog` RUNNING (reuse T5's shared parse helper); corroborating signal = freshness of the gpu_health_ollama_ok metric (stale > N min ⇒ not ticking). Track last-known state; on RUNNING→not-RUNNING (or fresh→stale) transition, emit a LOUD Telegram alarm via existing safe_send/notify (NOT debug log); re-arm on recovery. Monitor never blocks the tick and never restarts the watchdog (NSSM owns restart) — it makes a silent NSSM give-up visible.
**Files:** `src/scheduler/watch.py`, `tests/test_watchdog_liveness_monitor.py` | **Read-only:** `src/scheduler/reports.py`, `src/notifications/telegram.py`
**Test:** RUNNING→not-RUNNING transition emits loud alarm (mock sc query + safe_send); stale gpu_health_ollama_ok metric corroborates; re-arms after recovery; tick never blocked on alarm path.
**Fence:** Disjoint region in watch.py from T5 (startup guard) and T10 (handoff methods) — read both first. Monitor tick + its registration only. Do NOT restart the watchdog from code. No NSSM edits (T2).

## Task 9: Trainer GPU0 pin + identity preflight + stop-aware wait loop _(high)_
**Depends on:** 3, 4
Convert subprocess.run (trainer.py:814)→Popen. Extend _training_subprocess_env (L1062): CUDA_VISIBLE_DEVICES=0 + CUDA_DEVICE_ORDER=PCI_BUS_ID. BELOW_NORMAL_PRIORITY_CLASS; write logs/training.pid after Popen. **MAJOR-5 launch preflight:** before Popen, `nvidia-smi --query-gpu=index,name,uuid` and assert index0==24GB 3090; if not, ABORT loud (raise) — do not train on the 3060. Replace blocking run(timeout=7200) with a STOP-AWARE WAIT LOOP (poll proc.poll(); STOP flag→stop_training_bounded(); 7200s ceiling; MUST NOT return until exit — else canary/holdout at L876+ breaks). DPO subprocess (L1035) inherits the pin. Inject StopOnFlagCallback into the generated script. Do NOT touch as_posix L1221-1230 (#68, disjoint).
**Files:** `src/training/trainer.py`, `tests/test_trainer_gpu_pin.py` | **Read-only:** `src/training/training_stop.py`, `src/training/training_control.py`, `src/training/stop_callback.py`
**Test:** Popen env has CUDA_VISIBLE_DEVICES=0 + CUDA_DEVICE_ORDER; pid written; wait loop no early return; STOP→stop_training_bounded; DPO inherits; script has device_map + callback; **identity preflight aborts/raises when mocked nvidia-smi shows index0==3060**.
**Fence:** Don't modify _modelfile_content/as_posix (#68). Don't change canary/holdout logic. No handlers.

## Task 10: Handler rename/replace + flag disambiguation + tz/calendar semantics _(high)_
**Depends on:** 4, 5
Replace handoff handlers (watch_handlers.py) + dispatch methods (watch.py:2349-2358). NEW: maybe_evening_training_launch (18:30-04:00 ET + market closed; flag _evening_training_done); maybe_morning_training_stop (morning window; stop_training_bounded; flag _morning_training_stop_done); maybe_market_open_training_stop (NEW DAYTIME, >=09:25 ET; flag _market_open_stop_done). watch._run_*_handoff→_run_evening_training_launch/_run_morning_training_stop (call training_control, no VRAMManager). Disambiguate conflated flags at watch.py:244 AND :364 → the 3 new names. **MAJOR-6:** ALL ET comparisons tz-aware via existing `ET = ZoneInfo("America/New_York")` / `datetime.now(ET)` (NO naive datetime.now, NO fixed offset); "market closed" via `src.scheduler.holidays.is_market_open(now_et)` (honors half-days) — same path watch._is_market_open delegates to; do NOT re-implement. Wire maybe_market_open_training_stop into the DAYTIME tick path (the one already calling _is_market_open).
**Files:** `src/scheduler/watch_handlers.py`, `src/scheduler/watch.py`, `tests/test_watch_handlers.py` | **Read-only:** `src/training/training_control.py`, `src/scheduler/holidays.py`
**Test:** evening launch fires only in window + market closed; morning stop in window; market-open stop >=09:25; each guarded by its flag; flags reset in daily-reset block; **all ET comparisons tz-aware (assert America/New_York used); market-closed via holidays.is_market_open; loop-restarted-at-09:20 ⇒ _market_open_stop_done inits False so maybe_market_open_training_stop still fires >=09:25; daytime tick path invokes it**.
**Fence:** Don't delete overnight handoff fns (T11) or vram_manager (T14). Don't touch the startup-guard region (T5) or runtime-monitor region (T18) — read their changes first. No registration (T12).

## Task 11: Delete overnight handoff functions + remove VRAMManager refs _(medium)_
**Depends on:** 10
Delete overnight.run_morning_handoff (L1068+) + run_evening_handoff + their VRAMManager imports/calls + metric writes at the `upsert_daily_metric(` calls on lines **1037 / 1055 / 1085 / 1099** (the metric-name string args are on 1038/1056/1086/1100 — locate by the upsert call OR by the metric-name string, NOT a bare line number). Remove the relative STOP_OVERNIGHT touch (L1073) — STOP now owned by training_stop. No remaining vram_manager import.
**Files:** `src/scheduler/overnight.py`, `tests/test_overnight_handoff_removed.py` | **Read-only:** `src/training/training_stop.py`
**Test:** run_*_handoff absent; no vram_manager import; no relative Path('data/STOP_OVERNIGHT'); no residual vram_handoff_*_ok metric writes.
**Fence:** Don't delete vram_manager.py (T14). Don't modify watch/watch_handlers (T10).

## Task 12: Re-register handlers under new names _(low)_
**Depends on:** 10
Update handler_registration.py: replace morning_vram_handoff (L32) + evening_vram_handoff (L44) with the 3 new handlers wired to the renamed watch methods.
**Files:** `src/scheduler/handler_registration.py`, `tests/test_handler_registration.py` | **Read-only:** `src/scheduler/watch_handlers.py`
**Test:** registry has the 3 new keys, no *_vram_handoff keys; each maps to a WatchLoop callable.
**Fence:** Don't modify the handlers (T10). Registration wiring only.

## Task 14: Delete vram_manager + its 5 test files _(low)_
**Depends on:** 10, 11
DELETE `src/scheduler/vram_manager.py` + its 5 test files (49 tests). Confirm zero remaining importers.
**Files:** `src/scheduler/vram_manager.py` (+ the 5 test files) | **Read-only:** `src/scheduler/overnight.py`, `src/scheduler/watch.py`
**Test:** grep zero `import vram_manager`/`from src.scheduler.vram_manager` in src/; full collection succeeds.
**Fence:** Don't delete until T10+T11 remove importers. Module + its 5 test files only.

## Task 15: CI test floor + CLAUDE.md adjustment (show arithmetic) _(low)_
**Depends on:** 13, 14, 18
**MINOR-1:** compute M = count of NEW behavioral tests landed across T1/T4/T7/T9/T10/T13/T18/this task. pg-tests.yml EXPECTED 5100→(5100−49+M) (L98) + CLAUDE.md 5300→(5300−49+M), with floor-lineage justification AND the explicit arithmetic (deleted 49, added M, net −49+M). Run `python -m pytest --collect-only -q | tail -1` and PUT THE COLLECTED COUNT in the PR receipt so it's auditable the new tests landed. Update `tests/scheduler/test_schedule_health_report.py:41` fixture to the renamed gpu_health key (path is `tests/scheduler/`, NOT bare `tests/` — do not create a duplicate).
**Files:** `.github/workflows/pg-tests.yml`, `CLAUDE.md`, `tests/scheduler/test_schedule_health_report.py`
**Test:** EXPECTED=5100−49+M; floor=5300−49+M + lineage note + arithmetic; fixture uses gpu_health key; test_schedule_health_report green; collected count in receipt.
**Fence:** No other CI gates. Floor + note + the one fixture only.

## Task 16: Retire superseded shell watchdog scripts _(low)_
**Depends on:** 2
Delete `scripts/ollama_watchdog.ps1` + `scripts/start_ollama_watchdog.bat` (superseded by the Python watchdog under NSSM). Confirm nothing references them.
**Files:** `scripts/ollama_watchdog.ps1`, `scripts/start_ollama_watchdog.bat` | **Read-only:** `scripts/install_service.ps1`
**Test:** grep zero references in scripts/ or docs.
**Fence:** Don't modify install_service.ps1 (T2). Deletion + reference-check only.

## Phase 3 — OPERATOR-GATED (doc only — DO NOT EXECUTE)

## Task 17: Cutover runbook + two-path rollback + sim semantic-rebase note (design doc) _(low)_
**Depends on:** 2, 7, 9, 18
Author the operator-gated cutover sequence (merge → install ArcisOllamaWatchdog with AppEnvironmentExtra + AppExit/AppThrottle → disable HKCU Run\Ollama → run gpu_placement_smoke.py [must pass identity AND placement] → nssm restart ArcisWatchLoop respecting 21:30-22:30 ET → verify GPU identity+placement + gpu_health telemetry + runtime-monitor first ticks). **MAJOR-1 two-path rollback:** (a) CLEAN rollback (no training in flight): stop watchdog → re-enable HKCU autostart → git revert → restart loop. (b) MID-OVERNIGHT rollback (training IN FLIGHT) — PRE-REVERT TEARDOWN BEFORE reverting code: stop_training_bounded()/kill tracked PID → delete logs/training.pid → clear STOP at BOTH new absolute dirname(DB_PATH)/STOP_OVERNIGHT AND old relative data/STOP_OVERNIGHT → confirm GPU0 idle via nvidia-smi → THEN the clean steps. State rollback is "clean" only when no training subprocess is in flight. **MINOR-2:** add the sim later-rebase note — SEMANTIC review of test_watch_handlers.py + tests/scheduler/test_schedule_health_report.py (old vram_handoff assertions → gpu_health), then `grep -r "vram_handoff" tests/` must be 0.
**Files:** `docs/operator-guide.md`, `CHANGELOG.md` | **Read-only:** `scripts/gpu_placement_smoke.py`, `scripts/install_service.ps1`
**Test:** doc review — sequence complete/ordered/respects no-restart window; BOTH rollback paths present with the pre-revert teardown enumerated; sim semantic-rebase + grep guard noted. NO execution.
**Fence:** DO NOT EXECUTE any cutover step. Documentation + CHANGELOG only. No service installs, no registry edits, no restarts.
