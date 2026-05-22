"""Bounded cooperative-then-hard stop for the GPU0 training subprocess.

Called by: scheduler.watch_handlers (T10 morning/market-open stop), cutover rollback (T17)
Calls: training.training_stop (set_stop/clear_stop), psutil
Owns tables: none
Config keys: none
Tests: tests/test_training_control.py

SAFETY-CRITICAL (dual-GPU re-cutover, MAJOR-3). This module runs as LocalSystem.
Windows recycles PIDs, so "the PID in logs/training.pid still exists" is NOT
sufficient to authorize a hard kill — the recycled PID could be ArcisWatchLoop
itself or an operator process. `stop_training_bounded` therefore validates the
tracked PID against `_is_tracked_training_proc` (cmdline marker + alive + CVD=0)
before terminating ANYTHING, and terminates ONLY that exact tracked PID. It NEVER
name-kills (taskkill /im), and NEVER touches Ollama. On a missing / dead /
mismatched pidfile it logs the reason, clears the stale pidfile best-effort, and
terminates nothing.
"""

import logging
import os
import time

import psutil

from src.config import DB_PATH
from src.training.training_stop import set_stop, clear_stop

logger = logging.getLogger(__name__)

# logs/training.pid lives in the runtime logs dir (C:\arcis\logs), a sibling of
# the data dir that holds DB_PATH (C:\arcis\data). T9 writes this file after it
# spawns the training subprocess; this constant is the single source of truth
# for both the writer (T9) and this reader so the path can never drift.
TRAINING_PID_FILE: str = os.path.join(
    os.path.dirname(os.path.dirname(DB_PATH)), "logs", "training.pid"
)

# Authoritative markers that identify the generated train script / training
# module in a process cmdline. The CUDA_VISIBLE_DEVICES=0 marker is a
# best-effort secondary signal; the cmdline marker is authoritative.
_TRAIN_SCRIPT_MARKER = os.path.join("training_data", "train.py")
_TRAIN_MODULE_MARKERS = ("-m training", "python -m training")


def _read_tracked_pid() -> int | None:
    """Return the int PID recorded in TRAINING_PID_FILE, or None on any error."""
    try:
        with open(TRAINING_PID_FILE, encoding="utf-8") as f:
            return int(f.read().strip())
    except (FileNotFoundError, ValueError, OSError):
        return None


def _clear_stale_pidfile() -> None:
    """Best-effort removal of a stale pidfile so it can't mislead next cycle."""
    try:
        os.remove(TRAINING_PID_FILE)
    except FileNotFoundError:
        pass
    except OSError as exc:
        logger.warning("[TRAIN_STOP] Could not clear stale pidfile %s: %s",
                       TRAINING_PID_FILE, exc)


def _is_tracked_training_proc(pid: int) -> bool:
    """Return True ONLY if `pid` is the genuine tracked GPU0 training process.

    ALL must hold (MAJOR-3): pidfile parses to an int matching `pid`;
    psutil.pid_exists(pid); the process is alive (status != ZOMBIE); its cmdline
    carries the generated train-script path OR the training-module marker; and
    (best-effort) a CUDA_VISIBLE_DEVICES=0 marker is present in environ or
    cmdline. Any NoSuchProcess / AccessDenied / parse error returns False.
    """
    tracked = _read_tracked_pid()
    if tracked is None or tracked != pid:
        return False
    try:
        if not psutil.pid_exists(pid):
            return False
        proc = psutil.Process(pid)
        if proc.status() == psutil.STATUS_ZOMBIE:
            return False
        cmdline = proc.cmdline()
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess,
            ValueError, OSError):
        return False

    cmdline_str = " ".join(cmdline)
    has_script = _TRAIN_SCRIPT_MARKER in cmdline_str or "train.py" in cmdline_str
    has_module = any(m in cmdline_str for m in _TRAIN_MODULE_MARKERS)
    if not (has_script or has_module):
        return False

    # Best-effort CVD=0 confirmation. The cmdline/script marker above is the
    # authoritative check; a missing environ (AccessDenied) does not by itself
    # disqualify a process whose cmdline already proved it is the trainer.
    try:
        environ = proc.environ()
    except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
        environ = {}
    cvd_present = (
        environ.get("CUDA_VISIBLE_DEVICES") == "0"
        or "CUDA_VISIBLE_DEVICES=0" in cmdline_str
    )
    if environ and not cvd_present:
        return False

    return True


def _cooperative_then_hard_stop(pid: int, timeout_s: int) -> None:
    """Wait up to timeout_s for the VALIDATED tracked pid to exit, else kill it.

    Caller guarantees `pid` already passed `_is_tracked_training_proc`. The pid
    is re-validated immediately before the hard kill so a PID recycled out from
    under us during the cooperative wait is never terminated.
    """
    proc = psutil.Process(pid)

    deadline = time.monotonic() + max(0, timeout_s)
    while time.monotonic() < deadline:
        if not proc.is_running():
            logger.info("[TRAIN_STOP] Tracked PID %s exited cooperatively.", pid)
            _clear_stale_pidfile()
            return
        time.sleep(0.5)

    if not _is_tracked_training_proc(pid):
        logger.warning(
            "[TRAIN_STOP] PID %s no longer the tracked training process after "
            "cooperative wait — terminating NOTHING.", pid,
        )
        _clear_stale_pidfile()
        return

    logger.warning(
        "[TRAIN_STOP] Tracked PID %s still alive after %ss cooperative wait "
        "— hard-terminating tracked process only.", pid, timeout_s,
    )
    try:
        proc.terminate()
        psutil.wait_procs([proc], timeout=10)
    except (psutil.NoSuchProcess, psutil.AccessDenied) as exc:
        logger.warning("[TRAIN_STOP] terminate(%s) raced/denied: %s", pid, exc)
    _clear_stale_pidfile()


def stop_training_bounded(timeout_s: int) -> None:
    """Cooperatively stop the tracked GPU0 training subprocess, then hard-stop.

    Sequence: (1) set_stop() so the in-loop StopOnFlagCallback checkpoints and
    exits; (2) cooperative wait on the TRACKED pid up to timeout_s, polling for
    exit; (3) if still alive AND still the tracked training proc, hard-terminate
    that pid ONLY; (4) clear_stop().

    No-op-safe: if the pidfile is missing / its PID is dead / the predicate
    mismatches (recycled to an unrelated process), this logs the reason, clears
    the stale pidfile best-effort, and terminates NOTHING. It never name-kills
    and never touches Ollama.
    """
    set_stop()
    try:
        pid = _read_tracked_pid()
        if pid is None:
            logger.info("[TRAIN_STOP] No tracked pidfile (%s) — nothing to stop.",
                        TRAINING_PID_FILE)
            return

        if not _is_tracked_training_proc(pid):
            # Either dead, a zombie, or recycled to an unrelated process.
            reason = ("dead" if not psutil.pid_exists(pid)
                      else "not the tracked training process (recycled PID)")
            logger.warning(
                "[TRAIN_STOP] PID %s is %s — terminating NOTHING; clearing stale pidfile.",
                pid, reason,
            )
            _clear_stale_pidfile()
            return

        _cooperative_then_hard_stop(pid, timeout_s)
    finally:
        clear_stop()
