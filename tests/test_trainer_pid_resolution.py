"""Tests for src.training.trainer._resolve_tracked_pid — the #118 Windows venv
wrapper-PID escape mitigation.

The Windows venv launcher (.venv\\Scripts\\python.exe) is a thin shim that
re-execs the real interpreter as a CHILD python.exe. Popen.pid is the wrapper;
the GPU-using process is the child. Without this helper, _write_training_pid
records the wrapper PID, and stop_training_bounded's hard-kill path (which
calls TerminateProcess on Windows) hits the wrapper only — the GPU-using
child survives as an orphan with VRAM allocated.

Discovery: gpu0_training_partition_smoke.py 2026-05-24 observed a 40-PID gap
between Popen.pid and the child's os.getpid().

These tests use mocked psutil.Process so they're cross-platform and fast.
A real-subprocess test at the end exercises the end-to-end path on Windows.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from unittest.mock import patch, MagicMock

import psutil
import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_proc(children: list[MagicMock] | None = None,
               raise_on_children: type[BaseException] | None = None) -> MagicMock:
    """Build a MagicMock that quacks like a psutil.Process."""
    proc = MagicMock(spec=psutil.Process)
    if raise_on_children is not None:
        proc.children.side_effect = raise_on_children
    else:
        proc.children.return_value = children or []
    return proc


def _mock_child(pid: int, name: str = "python.exe") -> MagicMock:
    """Build a MagicMock that quacks like a child psutil.Process."""
    c = MagicMock(spec=psutil.Process)
    c.pid = pid
    c.name.return_value = name
    return c


# ---------------------------------------------------------------------------
# Resolution: wrapper has exactly one python child → child PID returned
# ---------------------------------------------------------------------------

def test_resolve_returns_child_pid_when_one_python_child():
    """The canonical Windows venv case: wrapper spawns one child python."""
    from src.training.trainer import _resolve_tracked_pid

    child = _mock_child(pid=99999)
    wrapper = _mock_proc(children=[child])

    with patch("src.training.trainer.psutil.Process", return_value=wrapper):
        result = _resolve_tracked_pid(popen_pid=12345)
    assert result == 99999, (
        f"Expected child pid 99999 (wrapper's only python child); got {result}. "
        "The #118 mitigation must return the GPU-using child, not the wrapper."
    )


def test_resolve_returns_child_pid_only_when_name_starts_with_python():
    """The 'python' filter must be applied — child named 'cmd.exe' is not a trainer."""
    from src.training.trainer import _resolve_tracked_pid

    non_python = _mock_child(pid=88888, name="cmd.exe")
    wrapper = _mock_proc(children=[non_python])

    with patch("src.training.trainer.psutil.Process", return_value=wrapper):
        result = _resolve_tracked_pid(popen_pid=12345, settle_timeout_s=0.5)
    # After settle, the helper finds zero python children, falls back to popen_pid.
    assert result == 12345


def test_resolve_python3_named_child_recognized():
    """Linux-style 'python3.13' or 'python3' must also be recognized."""
    from src.training.trainer import _resolve_tracked_pid

    child = _mock_child(pid=77777, name="python3.13")
    wrapper = _mock_proc(children=[child])

    with patch("src.training.trainer.psutil.Process", return_value=wrapper):
        result = _resolve_tracked_pid(popen_pid=12345)
    assert result == 77777


# ---------------------------------------------------------------------------
# No-op fallback: zero python children → popen_pid returned (Linux/Mac/non-venv)
# ---------------------------------------------------------------------------

def test_resolve_falls_back_to_popen_pid_when_no_children():
    """Non-Windows-venv: Popen IS the trainer. Settle then fall back."""
    from src.training.trainer import _resolve_tracked_pid

    wrapper = _mock_proc(children=[])

    with patch("src.training.trainer.psutil.Process", return_value=wrapper):
        result = _resolve_tracked_pid(popen_pid=12345, settle_timeout_s=0.5)
    assert result == 12345


def test_resolve_settle_timeout_is_short():
    """When no children appear, the helper must give up quickly — don't block launch."""
    from src.training.trainer import _resolve_tracked_pid

    wrapper = _mock_proc(children=[])

    start = time.monotonic()
    with patch("src.training.trainer.psutil.Process", return_value=wrapper):
        _resolve_tracked_pid(popen_pid=12345, settle_timeout_s=0.4)
    elapsed = time.monotonic() - start
    assert elapsed < 1.5, (
        f"settle_timeout_s=0.4 but helper took {elapsed:.2f}s. "
        "Long settle delays the training launch."
    )


# ---------------------------------------------------------------------------
# Defensive fallback: multiple python children → popen_pid + warn loudly
# ---------------------------------------------------------------------------

def test_resolve_warns_and_falls_back_on_multiple_children(caplog):
    """Unexpected: wrapper has >1 python child. Fall back + warn so operator
    can investigate. Don't pick arbitrary child."""
    from src.training.trainer import _resolve_tracked_pid

    c1 = _mock_child(pid=10001)
    c2 = _mock_child(pid=10002)
    wrapper = _mock_proc(children=[c1, c2])

    with patch("src.training.trainer.psutil.Process", return_value=wrapper):
        with caplog.at_level("WARNING", logger="src.training.trainer"):
            result = _resolve_tracked_pid(popen_pid=12345)
    assert result == 12345
    assert any("#118 mitigation" in rec.message and "2 python children" in rec.message
               for rec in caplog.records), (
        f"Expected loud WARNING about multiple python children + #118 mitigation. "
        f"Got: {[r.message for r in caplog.records]}"
    )


# ---------------------------------------------------------------------------
# Graceful failure: process dead/inaccessible → popen_pid returned
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("exc_type", [
    psutil.NoSuchProcess,
    psutil.AccessDenied,
    psutil.ZombieProcess,
])
def test_resolve_falls_back_gracefully_on_psutil_errors(exc_type):
    """psutil raises if process dies, is denied, or zombies. Caller's stop-path
    handles those via _is_tracked_training_proc; we just hand back the popen_pid."""
    from src.training.trainer import _resolve_tracked_pid

    # psutil exception constructors require specific positional args
    if exc_type is psutil.NoSuchProcess:
        side_effect = exc_type(12345)
    elif exc_type is psutil.AccessDenied:
        side_effect = exc_type(pid=12345)
    else:  # ZombieProcess
        side_effect = exc_type(pid=12345)

    with patch("src.training.trainer.psutil.Process", side_effect=side_effect):
        result = _resolve_tracked_pid(popen_pid=12345, settle_timeout_s=0.5)
    assert result == 12345


# ---------------------------------------------------------------------------
# End-to-end on Windows: real subprocess, real wrapper, real child
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
    sys.platform != "win32",
    reason="Windows venv launcher wrapper pattern is the discovered #118 surface",
)
@pytest.mark.skipif(
    not os.path.exists(".venv/Scripts/python.exe"),
    reason="No venv python available — non-launcher python.exe may not exhibit the wrapper",
)
def test_resolve_real_windows_venv_subprocess_returns_child():
    """Smoke-level confirmation: spawn a real venv-python subprocess, verify
    _resolve_tracked_pid returns a different PID than Popen.pid (i.e., the
    actual child)."""
    from src.training.trainer import _resolve_tracked_pid

    env = os.environ.copy()
    env["CUDA_VISIBLE_DEVICES"] = "0"
    venv_python = os.path.abspath(".venv/Scripts/python.exe")
    p = subprocess.Popen(
        [venv_python, "-c", "import time; time.sleep(5)"],
        env=env,
    )
    try:
        # Match the production default (5.0s). Dual-QA reviewers (2026-05-24)
        # observed worst-case child-emergence latency up to 2.3s on this box
        # and ~20% of cold-spawn trials never had a python child appear at all
        # within 3s. Lower timeout was flaky without improving signal — the
        # production code uses 5.0s, so the integration test should too.
        resolved = _resolve_tracked_pid(p.pid, settle_timeout_s=5.0)
        # Discovery in gpu0_training_partition_smoke.py 2026-05-24: child PID
        # differs from Popen.pid on Windows venv (40-PID gap typical).
        assert resolved != p.pid, (
            f"resolved={resolved}, popen.pid={p.pid}. "
            "Expected the venv wrapper to spawn a python child; either the "
            "wrapper pattern has changed (good — #118 is naturally resolved), "
            "or psutil failed to enumerate children."
        )
        # And the resolved PID must be alive
        assert psutil.pid_exists(resolved)
    finally:
        try:
            p.terminate()
            p.wait(timeout=2)
        except subprocess.TimeoutExpired:
            p.kill()
