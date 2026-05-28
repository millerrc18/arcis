"""GPU0-pinned training-subprocess launch, checkpoint-stop, and PID tracking.

Called by: training.trainer (run_fine_tune), scripts.gpu0_training_partition_smoke
Calls: training.training_control (stop_training_bounded), training.training_stop, psutil
Owns tables: none
Config keys: none
Tests: tests/test_trainer_gpu_pin.py, tests/test_trainer_pid_resolution.py, tests/test_trainer_holdout_alert.py

WHY this module is split from trainer.py (Phase 5 PR-C T12):
    trainer.py was a 1530-line orchestrator mixing data export, holdout
    evaluation, promotion-gate plumbing, AND the dual-GPU (MAJOR-5)
    subprocess-launch machinery. The launch machinery is a cohesive unit:
    it pins training to GPU0 (the 24 GB RTX 3090), confirms GPU identity via
    nvidia-smi before launch, spawns the training subprocess at below-normal
    priority, resolves the actual GPU-using child PID (Windows venv launcher
    escape, #118), records that PID for T4's bounded-stop logic, and runs a
    stop-aware wait loop that honors the overnight STOP flag. These six
    functions share the same module globals (os, subprocess, time, psutil,
    training_stop, training_control, the GPU0 identity constants) and have no
    dependency on the export/eval/gate code, so they extract cleanly.

    trainer.py re-exports every public symbol from this module so existing
    imports (`from src.training.trainer import _resolve_tracked_pid`, etc.)
    keep working unchanged.
"""

import logging
import os
import subprocess
import time

import psutil

from src.training import training_control, training_stop

logger = logging.getLogger(__name__)

# MAJOR-5 (dual-GPU re-cutover): the 24 GB RTX 3090 MUST be CUDA index 0 before
# any training launch. A configured UUID (env override) takes precedence over
# the name substring so a BIOS/driver reseat that renames but keeps the same
# card can still be authorized. Mirrors scripts/gpu_placement_smoke.py (T7).
_TRAIN_GPU0_NAME_SUBSTR = "3090"
_TRAIN_GPU0_UUID = os.environ.get("ARCIS_TRAIN_GPU0_UUID", "").strip()


def _training_subprocess_env() -> dict[str, str]:
    """Environment for Windows-safe UTF-8 training subprocesses.

    Pins training to GPU0 (the 24 GB RTX 3090) via CUDA_VISIBLE_DEVICES=0 and
    CUDA_DEVICE_ORDER=PCI_BUS_ID. CVD=0 is also the secondary signal T4's
    `_is_tracked_training_proc` checks before authorizing a bounded stop.
    """
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    env["CUDA_VISIBLE_DEVICES"] = "0"
    env["CUDA_DEVICE_ORDER"] = "PCI_BUS_ID"
    # Absolute STOP-flag path so the subprocess's inlined StopOnFlagCallback
    # watches the same file as training_control / scheduler.overnight.
    env["ARCIS_STOP_FLAG"] = training_stop.STOP_FLAG
    return env


def _assert_gpu0_identity() -> None:
    """MAJOR-5 launch preflight: abort loud if GPU0 is not the RTX 3090.

    Runs `nvidia-smi --query-gpu=index,name,uuid --format=csv,noheader`, parses
    it, and raises RuntimeError unless CUDA index 0 is the 3090 (name substring
    or configured UUID). NEVER train on the 12 GB 3060 and OOM.
    """
    result = subprocess.run(
        ["nvidia-smi", "--query-gpu=index,name,uuid", "--format=csv,noheader"],
        capture_output=True, text=True, timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"MAJOR-5 preflight: nvidia-smi failed (rc={result.returncode}) — "
            f"refusing to launch training without GPU identity confirmation: "
            f"{result.stdout}{result.stderr}"
        )
    gpu0 = None
    for line in result.stdout.strip().splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 3:
            continue
        try:
            idx = int(parts[0])
        except ValueError:
            continue
        if idx == 0:
            gpu0 = {"name": parts[1], "uuid": parts[2]}
            break
    if gpu0 is None:
        raise RuntimeError("MAJOR-5 preflight: nvidia-smi reported no GPU at index 0")
    if _TRAIN_GPU0_UUID:
        if gpu0["uuid"] != _TRAIN_GPU0_UUID:
            raise RuntimeError(
                f"MAJOR-5 IDENTITY FLIP: index0 uuid {gpu0['uuid']!r} != configured "
                f"{_TRAIN_GPU0_UUID!r}. Aborting launch — would train on the wrong card."
            )
    elif _TRAIN_GPU0_NAME_SUBSTR not in gpu0["name"]:
        raise RuntimeError(
            f"MAJOR-5 IDENTITY FLIP: index0 is {gpu0['name']!r} (expected RTX 3090). "
            "Aborting launch — would train on the 12 GB 3060 and OOM. "
            "Resolve BIOS/driver index assignment before proceeding."
        )


def _wait_for_training_proc(
    proc, timeout_s: int = 7200, poll_interval: float = 2.0,
) -> int | None:
    """Block until the training subprocess exits; honor the overnight STOP flag.

    Polls proc.poll(); if training_stop.is_stop_requested() flips True, hands
    off to training_control.stop_training_bounded(...) for a bounded cooperative
    -then-hard stop. Enforces a timeout_s ceiling. MUST NOT return until the
    subprocess has exited (or a stop/timeout has driven termination) — downstream
    canary/holdout logic assumes training completed on return.
    """
    deadline = time.monotonic() + max(0, timeout_s)
    while True:
        rc = proc.poll()
        if rc is not None:
            return rc
        if training_stop.is_stop_requested():
            logger.warning("[TRAINING] STOP flag observed — bounded-stopping training subprocess.")
            training_control.stop_training_bounded(min(300, timeout_s))
            return proc.poll()
        if time.monotonic() >= deadline:
            logger.error("[TRAINING] Training exceeded %ss ceiling — bounded-stopping.", timeout_s)
            training_control.stop_training_bounded(min(300, timeout_s))
            return proc.poll()
        time.sleep(poll_interval)


def _write_training_pid(pid: int) -> None:
    """Record the training subprocess PID at training_control.TRAINING_PID_FILE.

    Single source of truth shared with T4's stop logic (do NOT hardcode a
    relative logs/training.pid — it resolves wrong under LocalSystem cwd).
    """
    pid_file = training_control.TRAINING_PID_FILE
    try:
        os.makedirs(os.path.dirname(pid_file), exist_ok=True)
        with open(pid_file, "w", encoding="utf-8") as f:
            f.write(str(pid))
    except OSError as exc:
        logger.warning("[TRAINING] Could not write training pidfile %s: %s", pid_file, exc)


def _resolve_tracked_pid(popen_pid: int, settle_timeout_s: float = 5.0) -> int:
    """Resolve the actual GPU-using python PID, transparently handling the
    Windows venv launcher-wrapper pattern (#118 mitigation, 2026-05-24).

    On Windows, ``.venv\\Scripts\\python.exe`` is a thin launcher that re-execs
    the real interpreter as a CHILD python.exe — Popen.pid is the wrapper, but
    the GPU-using process is the child. Writing the wrapper PID to
    training.pid is a hard-kill silent-leak hazard because
    training_control._cooperative_then_hard_stop calls proc.terminate()
    (TerminateProcess on Windows), which does NOT cascade to children — the
    GPU-using child can survive a "successful" training-stop, holding GPU0
    VRAM until manual intervention.

    Discovery: gpu0_training_partition_smoke.py 2026-05-24 observed a 40-PID
    gap between Popen.pid (3408480) and the child's os.getpid() (3408520).
    Verified via psutil that the child has identical cmdline + CVD=0, so
    writing the child PID is compatible with _is_tracked_training_proc's
    validation.

    Strategy:
      * If popen process has zero python children within settle_timeout_s,
        assume it IS the trainer (Linux/Mac/non-venv Windows). Return
        popen_pid.
      * If exactly one python child exists, return that child PID
        (Windows venv case).
      * If multiple children exist (unexpected), warn loudly and fall back
        to popen_pid so behavior matches pre-fix and the operator can
        investigate.
      * If the process is dead or inaccessible, return popen_pid — caller's
        existing pidfile-stale path handles the rest.

    Settle timeout is bounded to keep launch latency small. The poll cadence
    is short (0.2s) so most cases resolve in <1s.
    """
    deadline = time.monotonic() + max(0.0, settle_timeout_s)
    while True:
        try:
            proc = psutil.Process(popen_pid)
            python_children = [
                c for c in proc.children(recursive=False)
                if c.name().lower().startswith("python")
            ]
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            return popen_pid
        if len(python_children) == 1:
            return python_children[0].pid
        if len(python_children) > 1:
            logger.warning(
                "[TRAINING] Popen pid %s has %d python children — "
                "#118 mitigation cannot uniquely identify the GPU-using "
                "child. Falling back to wrapper pid; hard-kill may leak GPU0.",
                popen_pid, len(python_children),
            )
            return popen_pid
        if time.monotonic() >= deadline:
            # No child appeared within the settle window. Most likely the
            # Popen target IS the trainer (Linux/Mac/non-venv). Use the
            # popen_pid as before.
            return popen_pid
        time.sleep(0.2)


def _launch_and_wait_training(cmd: list[str], env: dict[str, str]) -> int | None:
    """Popen the training cmd pinned to GPU0, record the PID, then stop-aware wait.

    Uses BELOW_NORMAL_PRIORITY_CLASS on Windows so inference stays responsive.
    Writes the PID to TRAINING_PID_FILE AFTER Popen so T4's stop logic can find
    it. The pid written is the actual GPU-using child python (see
    _resolve_tracked_pid for the Windows venv wrapper-escape mitigation).
    Returns the subprocess returncode (never returns before exit/stop).
    """
    creationflags = getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0)
    proc = subprocess.Popen(cmd, env=env, creationflags=creationflags)
    tracked_pid = _resolve_tracked_pid(proc.pid)
    _write_training_pid(tracked_pid)
    try:
        return _wait_for_training_proc(proc, timeout_s=7200)
    finally:
        # Clear our pidfile best-effort so a recycled PID can't mislead T4 later.
        try:
            os.remove(training_control.TRAINING_PID_FILE)
        except FileNotFoundError:
            pass
        except OSError:
            pass
