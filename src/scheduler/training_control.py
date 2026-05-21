"""Bounded-escalation stop for the GPU0 training subprocess.

Called by: scheduler.watch_handlers (morning + market-open guard; wired later)
Calls: scheduler.training_stop (request/clear), config (DB_PATH)
Owns tables: none
Owns files: logs/training.pid (read-only here; written by the launcher)
Config keys: none
Tests: tests/scheduler/test_stop_training_bounded.py

The stop is a bounded escalation (dual-GPU separation design §4.3):
  1. request_training_stop() — touch the cooperative flag.
  2. Wait up to ``timeout`` for clean self-exit (preferred — staged save).
  3. If still alive, HARD-TERMINATE THE TRACKED TRAINING PID ONLY:
     terminate() -> wait(30) -> kill() -> wait(10); lost-handle fallback is a
     PID-escalation (taskkill /f /t /pid -> Stop-Process -Force -> wmic delete)
     read from logs/training.pid.
  4. clear_training_stop().

ABSOLUTE INVARIANT: never an ``/im`` name-kill, never kill by process name,
never touch Ollama. Only the specific tracked training PID. The 4 prior
handoff failures were all caused by name-killing a CUDA-wedged Ollama; under
dual-GPU separation the training process is isolated on GPU0, so killing its
PID is safe.
"""

import logging
import os
import platform
import subprocess
import time

from src.config import DB_PATH
from src.scheduler.training_stop import (
    STOP_FLAG,
    clear_training_stop,
    request_training_stop,
)

logger = logging.getLogger(__name__)

MORNING_STOP_TIMEOUT = 300  # seconds

_POLL_INTERVAL = 1.0


def _resolve_pid_file() -> str:
    """Absolute path to logs/training.pid, resolved like STOP_FLAG's dir."""
    if DB_PATH:
        base_dir = os.path.dirname(os.path.abspath(DB_PATH))
    else:
        base_dir = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "..", "data")
        )
    return os.path.join(base_dir, "logs", "training.pid")


TRAINING_PID_FILE = _resolve_pid_file()


def _pid_escalate(pid: int) -> None:
    """Kill a single PID via the Windows escalation ladder (PID-only).

    Order: taskkill /f /t /pid <PID> -> PowerShell Stop-Process -Id <PID>
    -Force -> wmic process where ProcessId=<PID> delete. Linux fallback:
    kill -9 <PID>. NEVER an ``/im`` name-kill.
    """
    if platform.system() != "Windows":
        try:
            subprocess.run(["kill", "-9", str(pid)], capture_output=True, timeout=5)
        except (subprocess.TimeoutExpired, OSError):
            pass
        return

    try:
        result = subprocess.run(
            ["taskkill", "/f", "/t", "/pid", str(pid)],
            capture_output=True, timeout=10,
        )
        if result.returncode == 0:
            logger.info("[STOP] Killed training PID %d via taskkill", pid)
            return
    except subprocess.TimeoutExpired:
        logger.warning("[STOP] taskkill /pid %d timed out, escalating", pid)

    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             f"Stop-Process -Id {pid} -Force -ErrorAction Stop"],
            capture_output=True, timeout=10,
        )
        if result.returncode == 0:
            logger.info("[STOP] Killed training PID %d via Stop-Process", pid)
            return
    except subprocess.TimeoutExpired:
        logger.warning("[STOP] Stop-Process %d timed out, escalating to wmic", pid)

    try:
        subprocess.run(
            ["wmic", "process", "where", f"ProcessId={pid}", "delete"],
            capture_output=True, timeout=10,
        )
        logger.info("[STOP] wmic delete attempted for training PID %d", pid)
    except subprocess.TimeoutExpired:
        logger.warning("[STOP] wmic kill PID %d timed out — methods exhausted", pid)


def _read_pidfile() -> int | None:
    try:
        with open(TRAINING_PID_FILE, encoding="utf-8") as f:
            return int(f.read().strip())
    except (OSError, ValueError):
        return None


def stop_training_bounded(proc, timeout: int = MORNING_STOP_TIMEOUT) -> dict:
    """Bounded-escalation stop of the tracked training process.

    ``proc`` is a subprocess.Popen-like handle, or None when the handle was
    lost (e.g. across a watch-loop restart) — then the PID is read from
    ``logs/training.pid`` and the escalation ladder is applied to it.

    Returns ``{"stopped_via": ..., "elapsed_s": ...}`` where stopped_via is
    one of "cooperative", "hard_terminate", or "already_exited".
    """
    start = time.monotonic()

    # 1. Touch the cooperative flag.
    request_training_stop(STOP_FLAG)

    try:
        # Lost handle: PID-escalate from the pidfile (no cooperative wait
        # possible without a poll-able handle).
        if proc is None:
            pid = _read_pidfile()
            if pid is not None:
                _pid_escalate(pid)
            return {
                "stopped_via": "hard_terminate",
                "elapsed_s": round(time.monotonic() - start, 3),
            }

        # Already exited before we did anything.
        if proc.poll() is not None:
            return {
                "stopped_via": "already_exited",
                "elapsed_s": round(time.monotonic() - start, 3),
            }

        # 2. Cooperative wait up to timeout for clean self-exit.
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                return {
                    "stopped_via": "cooperative",
                    "elapsed_s": round(time.monotonic() - start, 3),
                }
            time.sleep(_POLL_INTERVAL)

        # Final poll after the deadline (covers timeout=0 and last-moment exit).
        if proc.poll() is not None:
            return {
                "stopped_via": "cooperative",
                "elapsed_s": round(time.monotonic() - start, 3),
            }

        # 3. Hard-terminate the tracked PID only:
        #    terminate() -> wait(30) -> kill() -> wait(10) (design §4.3).
        logger.warning("[STOP] Cooperative stop ignored — hard-terminating training PID")
        proc.terminate()
        try:
            proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            pass
        proc.kill()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            pass

        return {
            "stopped_via": "hard_terminate",
            "elapsed_s": round(time.monotonic() - start, 3),
        }
    finally:
        # 4. Always clear the flag.
        clear_training_stop(STOP_FLAG)
