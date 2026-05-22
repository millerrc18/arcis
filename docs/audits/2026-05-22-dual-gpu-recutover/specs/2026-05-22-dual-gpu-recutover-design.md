# Dual-GPU Re-Cutover Design Spec (v7 — adversarial-revision pass)

> **Revision note (v7):** Folds the feasibility 2 precision fixes (overnight metric anchors; test path) and resolves the 6 devil's-advocate MAJORs at the historical failure points. Architecturally unchanged — static partition, OLLAMA_MODELS defense-in-depth, absolute STOP, no-DependOnService, disjoint-region fencing are all preserved. The additions are guards/mechanisms for a LIVE-infra cutover: (1) pre-revert teardown for mid-overnight rollback, (2) a runtime watchdog-liveness monitor (new Task 18), (3) a precise tracked-PID match predicate + stale/missing-pidfile no-op, (4) a steady-state empty-store invariant in the watchdog, (5) GPU **identity** (name/UUID) verification not just index, (6) explicit tz-aware America/New_York + holidays.py calendar sourcing for every ET/market comparison.

## 1. Overview

### 1.1 Problem
The RTX 3060 (12 GB) currently time-shares VRAM between Ollama inference and PyTorch training via a fragile morning/evening **VRAM handoff** orchestrated by `src/scheduler/vram_manager.py`. The handoff unloads Ollama before training (evening, 18:50 ET) and reloads it after (morning, 05:15 ET). This handoff has produced 7+ hotfixes on the same wound — Ollama failing to restart, training subprocess not stopping, VRAM not freeing, model loading onto the wrong device. It is an irreducible failure class because the handoff *itself* is the fragile coupling.

### 1.2 Solution — static physical partition
The 2026-05-10 hardware upgrade added an RTX 3090 (24 GB). This design deploys a **permanent physical GPU separation**:
- **GPU0 (RTX 3090, 24 GB)** — training ONLY, pinned via `CUDA_VISIBLE_DEVICES=0`.
- **GPU1 (RTX 3060, 12 GB)** — Ollama inference ONLY, pinned via `CUDA_VISIBLE_DEVICES=1`.
- `CUDA_DEVICE_ORDER=PCI_BUS_ID` is set **everywhere** so device indices are stable and match `nvidia-smi`.

With a static partition there is **no handoff to fail**. The evening task becomes simply *launch training* (off-hours-fenced); the morning task becomes *stop training*. Ollama never moves. This eliminates the entire failure class structurally rather than patching it.

**GPU index ≠ physical identity (MAJOR-5).** `CUDA_DEVICE_ORDER=PCI_BUS_ID` stabilizes indices to PCI-bus order, but a BIOS update, driver reinstall, or a physical reseat can flip which card is index 0. If index 0 silently becomes the 12 GB 3060, training lands on the small card and OOMs — and an index-only smoke check would not catch it. Therefore the design verifies **physical GPU identity (name + UUID)**, not just index, at cutover (smoke test) and at every trainer/watchdog launch (preflight). The invariant is "index 0 == the 24 GB 3090, index 1 == the 3060" verified by `nvidia-smi --query-gpu=index,name,uuid`; a mismatch fails loud.

### 1.3 Scope of this design
- Re-derive the fully-reviewed design against **current main** (do NOT rebase the stale `hl-dualgpu` branch).
- Phase 1: independent low-risk pieces (watchdog module, NSSM install + `OLLAMA_MODELS`, GPU-placement/identity smoke test, `client.py` race fix, startup guard).
- Phase 2: training-lifecycle rewrite (GPU0 pin, bounded-stop trio, handler rename/replace, overnight handoff deletion, `vram_manager` delete, telemetry rename, runtime watchdog-liveness monitor, CI floor adjustment).
- Phase 3 (OPERATOR-GATED, design only): live cutover sequence + rollback (incl. the mid-overnight pre-revert teardown).
- Out of scope: live cutover execution (operator runs it); sim #1162 merge (prerequisite ordering — see 1.4).

### 1.4 Merge order (critical — updated)
Original recommendation was sim-first. Operator HELD sim #1162 for follow-up #97, so the order flips: **dual-GPU may merge FIRST.** The sim's `scenario.py:51` ticks `WatchLoop` generically with no handler-name string dependency, so when #97 completes the sim rebases its baseline copies of the 9 shared scheduler files onto the dual-GPU-renamed versions. Whichever merges second resolves the conflict. The 9 conflict files: `watch.py`, `watch_handlers.py`, `handler_registration.py`, `overnight.py`, `reports.py`, `telegram.py`, `activity_logger.py`, `test_watch_handlers.py`, `tests/scheduler/test_schedule_health_report.py`.

**Semantic-conflict caveat (MINOR-2).** Of the 9, two are TESTS — `test_watch_handlers.py` and `tests/scheduler/test_schedule_health_report.py` — whose sim-side baseline copies may still assert on the OLD `*_vram_handoff` metric keys. That is a **semantic** conflict, not a textual one: a blind textual resolve can leave assertions referencing deleted keys. The runbook (Task 17) flags these two for SEMANTIC review (old `vram_handoff` assertions → `gpu_health`/new-handler assertions) and adds a post-rebase guard: `grep -r "vram_handoff" tests/` must return zero hits in the merged tree.

## 2. Architecture

### 2.1 Process & ownership model
- **ArcisWatchLoop (NSSM, LocalSystem):** overnight scheduler; launches the training subprocess on GPU0 (`CUDA_VISIBLE_DEVICES=0`); bounded-stop owner (tracked PID only); hosts the runtime watchdog-liveness monitor (§4.11).
- **ArcisOllamaWatchdog (NSSM, LocalSystem):** 30s health loop; the SINGLE Ollama recovery owner; launches Ollama on GPU1 (`CUDA_VISIBLE_DEVICES=1`).

**Single-owner principle:** Ollama recovery is owned EXCLUSIVELY by `ArcisOllamaWatchdog`'s 30s loop. No other code path spawns `ollama serve` (hence the `client.py` race fix deletes the spawn). Training subprocess lifecycle is owned EXCLUSIVELY by `WatchLoop` via the tracked PID. Neither owner ever name-kills (`/im`) or touches the other's process.

**Recovery-owner SPOF mitigation (MAJOR-2).** Because the `client.py` self-restart is deleted, the watchdog's 30s loop becomes the SOLE Ollama recovery owner. A startup-only presence check (`_assert_ollama_watchdog_present`) does not cover the case where the watchdog dies mid-day (crash, or NSSM throttle-exhaustion on a recurring fault). The design therefore adds: (a) NSSM `AppExit`/`AppThrottle` config so a recurring crash escalates rather than silently stops; (b) a **runtime liveness monitor** inside the WatchLoop tick (§4.11) that detects RUNNING→not-RUNNING and emits a LOUD Telegram alarm; (c) an explicit per-call-site audit (§5.1) confirming every LLM call site treats a False/None health return as fail-soft, never as a hard input.

### 2.2 Service relationship — NO SCM DependOnService
The two NSSM services are **siblings under LocalSystem** with NO SCM `DependOnService` link. On 2026-05-22 a `DependOnService` wedge caused a 13-minute loop-down (SCM cache corruption, 1068/1075). Instead: a **code-level startup guard** (`watch._assert_ollama_watchdog_present()`): on startup, run `sc query ArcisOllamaWatchdog`, require `RUNNING`, fail loud otherwise. Escape hatch `ARCIS_SKIP_WATCHDOG_GUARD=1`. Start ordering is handled at install time, not via SCM dependency. The runtime liveness monitor (§4.11) extends this same fail-loud philosophy from startup-only to continuous.

### 2.3 New modules (authored against main — do NOT exist today)
- `src/scheduler/ollama_watchdog.py` — NSSM-run watchdog (clean drop-in re-authored from the stale branch).
- `src/training/training_stop.py` — STOP flag path constant + flag set/clear/check helpers.
- `src/training/training_control.py` — `stop_training_bounded()` cooperative-stop orchestration + the tracked-PID match predicate.
- `src/training/stop_callback.py` — `StopOnFlagCallback(TrainerCallback)` polling the flag inside the training loop.

### 2.4 Module changes
`src/llm/client.py` (delete the unpinned-restart spawn); `src/training/trainer.py` (GPU0 Popen + GPU-identity launch preflight + stop-aware wait); `src/scheduler/watch_handlers.py` + `watch.py` + `handler_registration.py` (handler rename/replace + startup guard + runtime liveness monitor + flag disambiguation); `src/scheduler/overnight.py` (delete handoff functions, metric writes at the `upsert_daily_metric(` calls on lines **1037/1055/1085/1099**); `src/scheduler/reports.py` + `src/notifications/telegram.py` + `src/utils/activity_logger.py` (telemetry rename); DELETE `src/scheduler/vram_manager.py`; `scripts/install_service.ps1` (watchdog install + AppEnvironmentExtra + AppExit/AppThrottle).

## 3. Data Model
**No schema change.** `schedule_metrics.metric_name` is free-text. Telemetry keys renamed at the string level only: `vram_handoff_training_ok`→`gpu_health_training_ok`; `vram_handoff_inference_ok`→`gpu_health_ollama_ok`; `safe_send('vram_handoff')`→`safe_send('gpu_health')`; telegram dispatch key `'gpu_health'` (telegram.py:1414); `activity_logger.VRAM_HANDOFF`→`GPU_HEALTH` (activity_logger.py:43).
**Backward-compat:** `reports._latest_vram_handoff_ok`→`_latest_gpu_health_ok`, widen the lookback 3→30 days (reports.py:70) and `IN (...)` queries BOTH old AND new keys so the health report stays green across the boundary. No migration — old rows remain readable.

## 4. Component Design

### 4.1 Ollama watchdog (`src/scheduler/ollama_watchdog.py`)
`resolve_ollama_exe()` (OLLAMA_EXE/OLLAMA_PATH > PATH > per-user glob; NOT %LOCALAPPDATA% — mis-resolves under LocalSystem); `preflight()` (graceful `ollama stop` then PID-scoped kill, never `/im`); `_launch()` (Popen `ollama serve` with env `CUDA_VISIBLE_DEVICES=1`, `CUDA_DEVICE_ORDER=PCI_BUS_ID`, `OLLAMA_NUM_PARALLEL=2`, **`OLLAMA_MODELS=C:\Users\mille\.ollama\models`**, `CREATE_NO_WINDOW`; 8s grace); `ensure_owner()` (adopt-if-healthy via `GET /api/version` AND non-empty-store assert, else preflight+_launch); `run()` (30s health loop emitting `gpu_health_ollama_ok`). `__main__`-runnable for NSSM. Deps: `src.config.load_config`, `src.scheduler.metrics.upsert_daily_metric` (stable).

**Why OLLAMA_MODELS matters (v0.36.47 root cause):** under LocalSystem `~/.ollama` resolves to `C:\Windows\system32\config\systemprofile\.ollama` = empty store. Set it in BOTH the NSSM env AND `_launch()`'s env (defense-in-depth).

**Steady-state empty-store invariant (MAJOR-4).** `GET /api/version` returns 200 even against an EMPTY model store — exactly the v0.36.47 silent-failure shape. `OLLAMA_MODELS` is a *cutover-time* defense; it does not catch a store that goes empty later (manual purge, disk issue, a future LocalSystem env regression). So both `ensure_owner()`'s adopt branch AND post-`_launch()` MUST additionally assert the store is non-empty via `GET /api/tags` and confirm the expected model tag (`halcyon-v1`, configurable) is present. If absent, the watchdog does NOT report healthy: it emits `gpu_health_ollama_ok=False` with a `detail` of `empty_model_store`/`missing_model_tag` and fails loud (Telegram via existing `safe_send`). This makes "Ollama up but no model" a steady-state invariant, checked every 30s loop, not merely a one-time cutover gate.

### 4.2 client.py race fix (`src/llm/client.py:107-137`) — Option a
Keep the health probe; DELETE the `subprocess.Popen(['ollama','serve'])` spawn (L120-127) + the 5s re-probe (L128-134). On unhealthy: log `[LLM] Ollama unresponsive — ArcisOllamaWatchdog owns recovery (30s loop); failing soft` and `return False`. **Rationale:** the deleted spawn was UNPINNED — could spawn Ollama on GPU0, colliding with training. The watchdog's 30s loop is the single recovery owner. Fail-soft window ≈38s (30s poll + 8s grace) acceptable — LLM is graceful-fallback, not on the trading path (see §5.1 per-call-site audit).

### 4.3 Trainer GPU0 pin + identity preflight (`src/training/trainer.py`)
Convert `subprocess.run` (L814) → `Popen`: extend `_training_subprocess_env` (L1062) with `CUDA_VISIBLE_DEVICES=0` + `CUDA_DEVICE_ORDER=PCI_BUS_ID`; `BELOW_NORMAL_PRIORITY_CLASS`; write `logs/training.pid` after Popen; replace blocking `run(timeout=7200)` with a **STOP-AWARE WAIT LOOP** (poll `proc.poll()`; if `training_stop` flag set, delegate to `stop_training_bounded()`; 7200s ceiling; MUST NOT return until the subprocess exits — else the downstream canary/holdout at L876+ breaks). DPO subprocess (L1035) inherits the pin. **No collision with #68** (`_modelfile_content`/as_posix at L1221-1230 is a disjoint function — do not touch).

**Launch preflight — GPU identity (MAJOR-5).** Immediately before the Popen, the trainer runs a cheap identity preflight: `nvidia-smi --query-gpu=index,name,uuid --format=csv,noheader` and asserts that index 0 is the 24 GB 3090 (name match on `3090`, or a configured UUID). If index 0 is NOT the 3090, ABORT the launch loud (raise) rather than train on the 3060 and OOM. This is a guard, not a remediation — a flip is an operator-attention event. The preflight is mockable (subprocess) for CI.

### 4.4 Absolute STOP path (`src/training/training_stop.py`)
`STOP_FLAG = os.path.join(os.path.dirname(DB_PATH), 'STOP_OVERNIGHT')`. Fixes the confirmed-live relative-cwd landmine at overnight.py:1073 (`Path("data/STOP_OVERNIGHT")` resolved wrong under LocalSystem cwd=System32). Helpers: `set_stop()`, `clear_stop()`, `is_stop_requested()`.

### 4.5 Bounded cooperative stop (`src/training/training_control.py`)
`stop_training_bounded(timeout_s)`: set_stop → cooperative wait on the tracked PID (`logs/training.pid`) → hard-terminate the TRACKED PID ONLY → clear_stop.

**Tracked-PID match predicate (MAJOR-3).** Windows recycles PIDs, so "the PID in `logs/training.pid` exists" is insufficient — the recycled PID could be ArcisWatchLoop itself or an operator process. `stop_training_bounded()` (and `maybe_*_training_stop`) MUST validate via a precise predicate before terminating:

```
def _is_tracked_training_proc(pid) -> bool:
    # ALL must hold:
    #  1. logs/training.pid exists and parses to an int PID
    #  2. psutil.pid_exists(pid) is True
    #  3. proc = psutil.Process(pid); proc is alive (status != ZOMBIE)
    #  4. cmdline contains the generated train-script path (the .py we wrote)
    #     OR the 'python -m training'/training-module marker
    #  5. environ/cmdline carries the CUDA_VISIBLE_DEVICES=0 marker
    #     (best-effort; cmdline marker is the authoritative check)
    # Any psutil.NoSuchProcess / AccessDenied / parse error => return False.
```

**No-op-safe behavior:** if `logs/training.pid` is **missing**, or its PID is **dead**, or the predicate **mismatches** (recycled to an unrelated process), `stop_training_bounded()` LOGS the reason and RETURNS — it terminates NOTHING. Never terminate a PID that fails the predicate. The stale pidfile is then cleared (best-effort) so it doesn't mislead the next cycle. Tests cover: (a) missing pidfile → no-op; (b) PID dead → no-op + pidfile cleared; (c) PID recycled to a non-training process (e.g. the watch loop's own PID) → no-op, NOTHING terminated; (d) valid tracked PID → cooperative wait then terminate-tracked-only, never `/im`, NEVER Ollama.

### 4.6 Stop callback (`src/training/stop_callback.py`)
`StopOnFlagCallback(TrainerCallback)` — `on_step_end`/`on_evaluate` check `is_stop_requested()`; if set, `control.should_save=True` + `control.should_training_stop=True` for clean checkpoint+exit. Injected into the generated train script's `Trainer(callbacks=[...])`.

### 4.7 Handler rename/replace
**Old chain (deleted):** `maybe_{morning,evening}_vram_handoff` → `watch._run_{morning,evening}_handoff` (watch.py:2349-2358) → `overnight.run_{morning,evening}_handoff` → `VRAMManager`.
**New chain:**
- `maybe_evening_training_launch` (overnight) — off-hours fence 18:30–04:00 ET AND market closed; launches training (GPU0); flag `_evening_training_done`.
- `maybe_morning_training_stop` (overnight) — morning window; `stop_training_bounded()`; flag `_morning_training_stop_done`.
- `maybe_market_open_training_stop` (**NEW DAYTIME**) — `>=09:25 ET` hard ceiling safety net; `stop_training_bounded()`; flag `_market_open_stop_done`.

**Flag disambiguation:** replace the conflated `_vram_handoff_done` (evening) + `_morning_handoff_done` (morning), double-init at watch.py:244 AND :364, with the three distinctly-named flags in both blocks.

**Time/calendar semantics — tz-aware America/New_York + holidays.py (MAJOR-6).** Every ET comparison in these handlers MUST be tz-aware against the codebase's existing `ET = ZoneInfo("America/New_York")` (watch.py:59) via `datetime.now(ET)` — NEVER `datetime.now()` (naive) or a fixed UTC offset. A fixed offset would shift the 18:30/09:25 boundaries by an hour at each DST transition, twice a year, on a market-hours SAFETY NET. "Market closed" MUST use the codebase calendar source: `src.scheduler.holidays.is_market_open(now_et)` (which already honors weekends, full holidays, AND half-day early closes via `is_market_half_day`) — the same path `watch._is_market_open()` already delegates to (watch.py:417/431). Do not re-implement a market-open check.

**Fresh-restart correctness:** the three new flags init `False` on every WatchLoop construction, so a loop restarted at, say, 09:20 ET starts with `_market_open_stop_done=False` and `maybe_market_open_training_stop` still fires at >=09:25. The daytime tick path (the same path that already calls `_is_market_open(now)`) MUST invoke `maybe_market_open_training_stop` so the safety net runs after a mid-morning restart, not only on the overnight path.

### 4.8 Startup guard
`watch._assert_ollama_watchdog_present()`: `sc query ArcisOllamaWatchdog` → require `RUNNING`; if not and `ARCIS_SKIP_WATCHDOG_GUARD != '1'`, log loud + raise.

### 4.9 GPU-placement + identity smoke test
`scripts/gpu_placement_smoke.py`:
1. **Identity check (MAJOR-5):** `nvidia-smi --query-gpu=index,name,uuid --format=csv,noheader`; assert index 0 == the 24 GB 3090 (name/UUID) and index 1 == the 3060. FAIL the cutover if identities don't match — this catches a BIOS/driver/reseat index flip before it lands training on the 3060.
2. **Placement check:** launch Ollama under the GPU1 pin, load the model, query `nvidia-smi` compute-apps, assert model VRAM is on **GPU1 (3060)** NOT GPU0.

Nonzero exit on any failure. **Gates the live cutover.** `tests/test_gpu_placement_smoke.py` wraps it with mocked nvidia-smi/Ollama for CI (including a mocked identity-flip case that must fail); the real assertion runs on-box at cutover.

### 4.10 Delete vram_manager + retire shell scripts
DELETE `src/scheduler/vram_manager.py` + its 5 test files (49 tests). RETIRE `scripts/ollama_watchdog.ps1` + `scripts/start_ollama_watchdog.bat`.

**CI floor arithmetic (MINOR-1).** Show the math, don't hand-wave a "-49". Deleted = 49 (vram tests). Added = M new behavioral tests (watchdog, training_control incl. PID-predicate cases, stop_callback, trainer-pin incl. identity-preflight, startup guard, gpu_health telemetry, gpu_placement+identity smoke, runtime-liveness monitor). The implementer MUST report the post-change `pytest --collect-only -q | tail -1` count in the PR receipt and set the floor to `5300 − 49 + M` (CLAUDE.md) and the pg-tests.yml EXPECTED to its conservative analogue (`5100 − 49 + M`). The net delta and the collected count both appear in the receipt so it's auditable whether the new tests actually landed (a floor that merely drops by the deletion count would mask a failure-to-add).

### 4.11 Runtime watchdog-liveness monitor (`src/scheduler/watch.py`) — NEW (MAJOR-2)
A periodic check INSIDE the WatchLoop tick (cadence ~60s, keyed in the per-task `_backoff` like other ticks) that detects the watchdog dying mid-day:
- **Mechanism:** `sc query ArcisOllamaWatchdog` parsed for `RUNNING` (reuses the startup-guard's parser), OR heartbeat-freshness on the `gpu_health_ollama_ok` metric (the watchdog upserts it every 30s; staleness > N minutes ⇒ watchdog not ticking). Use the `sc query` state as the authoritative signal and metric-staleness as a corroborating signal.
- **Edge-triggered alarm:** track last-known state; on a RUNNING→not-RUNNING (or fresh→stale) transition, emit a LOUD Telegram alarm via the existing `safe_send`/notify path (NOT a silent debug log). Re-arm on recovery so a flapping watchdog re-alerts.
- **Fail-soft:** the monitor NEVER blocks the trading path; it only alarms. It does not itself restart the watchdog (NSSM owns restart) — it makes a silent NSSM give-up VISIBLE.
- **NSSM escalation:** paired with the install-time `AppExit Default Restart` + `AppThrottle`/`AppRestartDelay` config (Task 2) so a recurring crash that exhausts NSSM's throttle surfaces as the monitor's alarm instead of dying quietly.

This converts the watchdog from a startup-only-checked SPOF into a continuously-monitored one with a loud failure signal — strictly better than today's client.py self-restart, not worse.

## 5. Error Handling

### 5.1 LLM call-site fail-soft audit (MAJOR-2)
Deleting the client.py self-restart is only safe if NO call site treats a False/None Ollama-health return as a hard input. Enumerated (Task 6 verifies each remains fail-soft, not hard-fail):
- **Council synthesis** — multi-model vote; a missing local model degrades to the remaining members / cached prior; tolerated.
- **Pre-market scan** — LLM commentary is advisory annotation on top of the quantitative scan; absence drops the annotation, scan proceeds.
- **Intraday** — LLM is graceful-fallback, off the order-submission path (risk governor + quant signals own trades).
None gate trade execution on a True health return. The ~38s fail-soft window is therefore acceptable.

### 5.2 Failure table
| Failure | Handling |
|---|---|
| Ollama unresponsive (client.py) | Fail-soft return False; watchdog owns recovery; ~38s window; no call site hard-fails (§5.1) |
| Ollama dead (watchdog) | 30s loop preflight + _launch on GPU1 |
| Empty model store at cutover | Prevented by OLLAMA_MODELS in NSSM + _launch env |
| Empty model store at steady state | `GET /api/tags` non-empty + expected-tag assert every 30s loop → gpu_health_ollama_ok=False + loud (MAJOR-4) |
| Watchdog dies mid-day | Runtime liveness monitor (§4.11) edge-alarms RUNNING→not-RUNNING; NSSM AppExit/AppThrottle escalation (MAJOR-2) |
| Training hangs past 7200s | Stop-aware wait loop ceiling → stop_training_bounded hard-terminates tracked PID |
| STOP flag not seen | Absolute STOP_FLAG under dirname(DB_PATH) |
| Training bleeds into market hours | maybe_market_open_training_stop 09:25 ET safety net; fires after fresh restart (flag inits False) |
| DST shifts ET boundary | All ET comparisons tz-aware America/New_York; market-closed via holidays.py (half-days incl.) (MAJOR-6) |
| Watchdog not running at startup | _assert_ollama_watchdog_present fails loud (unless escape hatch) |
| GPU index flipped (3060 became index 0) | Identity (name/UUID) assert in smoke test + trainer launch preflight → fail loud (MAJOR-5) |
| Model on wrong GPU | GPU-placement smoke test gates cutover |
| GPU0 autostart adopted | Disable HKCU Run\Ollama during cutover |
| Hard-terminate wrong/recycled PID | `_is_tracked_training_proc` predicate (cmdline + alive + CVD marker); missing/dead/mismatched pidfile ⇒ no-op (MAJOR-3) |
| Mid-overnight rollback orphans training | Pre-revert teardown: stop tracked PID, delete pidfile, clear BOTH STOP paths, confirm GPU0 idle (MAJOR-1) |

## 6. Testing Strategy
Behavioral tests (mock external deps; no real GPU/Ollama/network in CI):
- `test_ollama_watchdog.py` — preflight/adopt-vs-launch/single-owner/GPU1+OLLAMA_MODELS env; **steady-state empty-store: adopt-branch and post-launch `GET /api/tags` empty ⇒ gpu_health_ollama_ok=False + loud (MAJOR-4)**.
- `test_training_control.py` — bounded stop; tracked-PID-only; **`_is_tracked_training_proc` predicate: missing pidfile no-op, dead PID no-op+clear, recycled-to-watchloop-PID no-op (terminate NOTHING), valid PID terminates tracked-only never /im never Ollama (MAJOR-3)**.
- `test_trainer_gpu_pin.py` — CUDA_VISIBLE_DEVICES=0 + CUDA_DEVICE_ORDER + absolute STOP + device_map/callbacks + wait-loop-no-early-return; **launch identity preflight: index0!=3090 ⇒ abort/raise (MAJOR-5)**.
- `test_stop_callback.py`.
- `test_watch_handlers.py` — new gating + flag disambiguation; **all ET comparisons tz-aware (America/New_York); market-closed via holidays.is_market_open; loop-restarted-at-09:20 ⇒ _market_open_stop_done inits False so maybe_market_open_training_stop still fires >=09:25; daytime tick path invokes it (MAJOR-6)**.
- `test_startup_guard.py`.
- `test_watchdog_liveness_monitor.py` — **NEW: RUNNING→not-RUNNING transition emits loud alarm (mock sc query + safe_send); stale gpu_health_ollama_ok metric corroborates; re-arms on recovery; never blocks tick (MAJOR-2)**.
- `test_gpu_health_telemetry.py` — renamed keys + dual-read + 30-day window.
- `tests/scheduler/test_schedule_health_report.py` — L41 fixture renamed to gpu_health key (path is `tests/scheduler/`, not bare `tests/`).
- `test_gpu_placement_smoke.py` — mocked placement AND mocked identity-flip-must-fail.

Floor: deleted 49 + added M; report collected count + net delta in the PR receipt; floor = `5300 − 49 + M` (CLAUDE.md) / `5100 − 49 + M` (pg-tests.yml EXPECTED).

## 7. Phase 3 — Live Cutover Sequence (OPERATOR-GATED, design only — DO NOT EXECUTE)
1. Merge dual-GPU to main (sim held; dual-GPU goes first). If sim later ready, it rebases — **SEMANTIC review the two test files** (`test_watch_handlers.py`, `tests/scheduler/test_schedule_health_report.py`) for stale `vram_handoff` assertions, then `grep -r "vram_handoff" tests/` must be zero (MINOR-2).
2. Install `ArcisOllamaWatchdog` via `install_service.ps1` with `AppEnvironmentExtra` (OLLAMA_MODELS, CUDA_VISIBLE_DEVICES=1, CUDA_DEVICE_ORDER=PCI_BUS_ID) AND `AppExit Default Restart` + `AppThrottle`/`AppRestartDelay` (MAJOR-2).
3. Disable GPU0 Ollama autostart: remove `HKCU\Software\Microsoft\Windows\CurrentVersion\Run\Ollama` so the watchdog launches a fresh GPU1 Ollama.
4. Run `scripts/gpu_placement_smoke.py` — MUST pass BOTH identity (index0==3090, index1==3060) AND placement (model VRAM on GPU1). If fail → STOP.
5. `nssm restart ArcisWatchLoop` — respect the **21:30–22:30 ET no-restart window**.
6. Verify live: GPU identity via `nvidia-smi --query-gpu=index,name,uuid`; training on GPU0, Ollama on GPU1.
7. Monitor `gpu_health_*` telemetry + first overnight training launch + morning stop + the runtime liveness monitor's first ticks.

### 7.1 Rollback — two distinct paths (MAJOR-1)
The static partition has no PERSISTENT cross-process state, but a revert can still orphan an IN-FLIGHT training subprocess: the cutover restarts ArcisWatchLoop near the overnight launch time, so a mid-overnight revert can leave a live GPU0 training process (with `logs/training.pid` written) and a SET STOP flag that the reverted OLD code — which knows nothing about `training_control` or the new absolute `STOP_FLAG` — cannot reconcile. Result: an orphaned process pinning GPU0.

**Clean rollback (no training in flight)** — only valid when no training subprocess exists:
1. Stop `ArcisOllamaWatchdog`.
2. Re-enable `HKCU\...\Run\Ollama`.
3. `git revert` the merge; restart `ArcisWatchLoop` on the prior commit (respect the 21:30–22:30 ET window).

**Mid-overnight rollback (training IN FLIGHT) — PRE-REVERT TEARDOWN, run BEFORE reverting code:**
1. `stop_training_bounded()` (or, if the new code is already gone, manually validate `logs/training.pid` via the `_is_tracked_training_proc` predicate and terminate that tracked PID) — kill the in-flight GPU0 training subprocess FIRST.
2. Delete `logs/training.pid`.
3. Clear the STOP flag at BOTH paths: the new absolute `dirname(DB_PATH)/STOP_OVERNIGHT` AND the old relative `data/STOP_OVERNIGHT` (the reverted OLD code only knows the relative one; leaving either set wedges the next launch).
4. Confirm GPU0 is idle via `nvidia-smi` (no training compute-app on index 0).
5. ONLY THEN proceed with the clean-rollback steps (stop watchdog, re-enable autostart, git revert, restart loop).

The rollback is "clean" ONLY when no training subprocess is in flight; otherwise the mid-overnight teardown is mandatory first.

## Design Decisions

| Decision | Rationale |
|---|---|
| Static physical GPU partition (GPU0=training / GPU1=Ollama) replacing the VRAM handoff | The handoff IS the failure class (7+ hotfixes); the RTX 3090 makes a permanent partition viable; no handoff = nothing to fail. #91 proved viability. |
| Verify GPU physical IDENTITY (name/UUID), not just index, at smoke + trainer launch preflight | PCI_BUS_ID stabilizes index order but a BIOS/driver/reseat can flip index 0 to the 3060; an index-only check would silently train on the 12 GB card and OOM. Identity assert fails loud before the launch (MAJOR-5). |
| Runtime watchdog-liveness monitor in the WatchLoop tick + NSSM AppExit/AppThrottle | Deleting client.py self-restart makes the watchdog the SOLE recovery owner; a startup-only check leaves a mid-day watchdog death silent. Edge-triggered loud alarm makes a silent NSSM give-up visible — strictly better than today (MAJOR-2). |
| Steady-state empty-store invariant via GET /api/tags every 30s loop | /api/version is 200 against an empty store (the v0.36.47 silent-failure shape); OLLAMA_MODELS only defends at cutover. Checking /api/tags continuously catches a later store-empty regression and reports gpu_health_ollama_ok=False loud (MAJOR-4). |
| Precise tracked-PID predicate + no-op on missing/dead/mismatched pidfile | Windows recycles PIDs; "PID exists" could match the watch loop itself or an operator process. Match on cmdline (train-script/module) + alive + CVD marker; terminate NOTHING on mismatch — never name-kill (MAJOR-3). |
| Mid-overnight rollback gets an explicit PRE-REVERT TEARDOWN | A revert near overnight launch can orphan a live GPU0 training process + leave a STOP flag the reverted OLD code can't reconcile (knows only the relative path). Teardown (kill tracked PID → delete pidfile → clear BOTH STOP paths → confirm GPU0 idle) makes rollback safe; "clean" only when nothing is in flight (MAJOR-1). |
| All ET comparisons tz-aware America/New_York; market-closed via holidays.is_market_open (half-days incl.) | Naive/fixed-offset ET shifts the 18:30/09:25 safety-net boundaries by an hour each DST transition. Reuse the existing ET=ZoneInfo + holidays.py path (watch.py:59/431) rather than re-implement. Fresh-restart: flags init False so the 09:25 net still fires after a 09:20 restart (MAJOR-6). |
| DELETE vram_manager.py + its 49 tests; floor = 5300−49+M with collected count in receipt | Under a static partition it's dead code; deleted tests covered deleted code. Showing the arithmetic + post-change collected count prevents a floor that merely drops by the deletion count from masking a failure to land the new tests (MINOR-1). |
| Sim later-rebase of the two TEST conflict files needs SEMANTIC review + grep guard | test_watch_handlers.py and test_schedule_health_report.py may assert on OLD vram_handoff keys; a blind textual resolve leaves dead assertions. Require semantic review + `grep -r vram_handoff tests/` == 0 (MINOR-2). |
| client.py Option a — delete the unpinned spawn, fail soft, single recovery owner | The spawn was unpinned (could land Ollama on GPU0, colliding with training); watchdog is the single owner; ~38s fail-soft acceptable — confirmed no LLM call site hard-fails on a False health return (§5.1). |
| NO SCM DependOnService; code-level startup guard + runtime monitor instead | The 2026-05-22 DependOnService wedge (13-min loop-down); the guard + runtime monitor give fail-loud safety without the brittle SCM dependency graph. |
| OLLAMA_MODELS in BOTH NSSM AppEnvironmentExtra AND _launch() env | v0.36.47 root cause (empty store under LocalSystem); defense-in-depth on the exact bug that failed the last cutover. |
| Absolute STOP_FLAG = dirname(DB_PATH)/STOP_OVERNIGHT | overnight.py:1073 relative path resolved wrong under LocalSystem cwd=System32 (confirmed live); absolute anchor is cwd-independent. |
| Stop-aware wait loop must not return until subprocess exits | run_fine_tune's downstream canary/holdout (L876+) assume training completed on return; a naive Popen returning early would break them. |
| Telemetry rename string-key only + 30-day dual-read window | metric_name is free-text (no schema change); dual-read keeps the health report green across the historical boundary. |
