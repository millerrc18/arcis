"""Regression-lock for PID-based Ollama kill in VRAM handoff (v0.36.24).

Background
----------

Pre-v0.36.24, `_kill_ollama_processes` in `src/scheduler/vram_manager.py`
used `taskkill /f /im ollama_llama_server.exe` with a 10s timeout. This
fails when an Ollama runner is hung in a CUDA syscall — the process is
unresponsive to /im-based signals, the kill command times out, the
function returns, and VRAM stays held.

Observed failures:
- 2026-05-18 18:50 ET: evening handoff to training failed (taskkill timed out)
- 2026-05-19 05:18 ET: morning handoff to inference failed (same root cause)

Both blocked the training pipeline (model arcis:v1.0.0 stalled at 2026-05-15
weights). The morning failure self-recovered via the `_reload_ollama` fallback
in `overnight.py:987`, but the evening failure had no equivalent — training
just didn't run.

Fix (v0.36.24)
--------------

`_kill_ollama_processes` now:
1. Queries `nvidia-smi --query-compute-apps=pid,process_name,used_memory`
   to find the actual VRAM-holding PIDs.
2. Filters for processes whose name contains "ollama".
3. For each, calls `_kill_pid(pid)` which escalates through:
   a. `taskkill /f /t /pid <PID>`  (kills process tree)
   b. PowerShell `Stop-Process -Id <PID> -Force`
   c. `wmic process where ProcessId=<PID> delete`
4. Falls back to the legacy `/im`-based kill if no GPU-holding Ollama
   PIDs are found (e.g. nvidia-smi unavailable, or ollama crashed without
   freeing VRAM and a different process now holds it).
"""
from __future__ import annotations

import subprocess
from unittest.mock import MagicMock, patch, call

import pytest


# ── _get_gpu_processes ───────────────────────────────────────────────────


def test_get_gpu_processes_parses_csv():
    """nvidia-smi --query-compute-apps CSV output → list of dicts."""
    from src.scheduler.vram_manager import VRAMManager

    csv_output = (
        "12345, ollama_llama_server.exe, 2673\n"
        "67890, python.exe, 4096\n"
    )
    with patch("src.scheduler.vram_manager._find_nvidia_smi", return_value="nvidia-smi"):
        vm = VRAMManager()

    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = csv_output
    with patch("src.scheduler.vram_manager.subprocess.run", return_value=mock_result):
        procs = vm._get_gpu_processes()

    assert len(procs) == 2
    assert procs[0] == {"pid": 12345, "name": "ollama_llama_server.exe", "used_mb": 2673}
    assert procs[1] == {"pid": 67890, "name": "python.exe", "used_mb": 4096}


def test_get_gpu_processes_empty():
    """No processes holding GPU memory → empty list."""
    from src.scheduler.vram_manager import VRAMManager

    with patch("src.scheduler.vram_manager._find_nvidia_smi", return_value="nvidia-smi"):
        vm = VRAMManager()

    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = ""
    with patch("src.scheduler.vram_manager.subprocess.run", return_value=mock_result):
        procs = vm._get_gpu_processes()

    assert procs == []


def test_get_gpu_processes_no_nvidia_smi():
    """nvidia-smi unavailable → empty list, no crash."""
    from src.scheduler.vram_manager import VRAMManager

    with patch("src.scheduler.vram_manager._find_nvidia_smi", return_value=None):
        vm = VRAMManager()

    procs = vm._get_gpu_processes()
    assert procs == []


def test_get_gpu_processes_timeout():
    """nvidia-smi hung → empty list, no crash."""
    from src.scheduler.vram_manager import VRAMManager

    with patch("src.scheduler.vram_manager._find_nvidia_smi", return_value="nvidia-smi"):
        vm = VRAMManager()

    with patch(
        "src.scheduler.vram_manager.subprocess.run",
        side_effect=subprocess.TimeoutExpired(cmd="nvidia-smi", timeout=10),
    ):
        procs = vm._get_gpu_processes()

    assert procs == []


# ── _kill_pid ────────────────────────────────────────────────────────────


def _make_run_outcomes(*outcomes):
    """Helper: build a subprocess.run side_effect that yields the given outcomes in order."""
    iterator = iter(outcomes)

    def _side_effect(*args, **kwargs):
        outcome = next(iterator)
        if isinstance(outcome, Exception):
            raise outcome
        result = MagicMock()
        result.returncode = outcome
        return result

    return _side_effect


def test_kill_pid_taskkill_succeeds():
    """taskkill /f /t /pid returns 0 → success, no escalation."""
    from src.scheduler.vram_manager import VRAMManager

    with patch("src.scheduler.vram_manager._find_nvidia_smi", return_value="nvidia-smi"), \
         patch("src.scheduler.vram_manager.platform.system", return_value="Windows"):
        vm = VRAMManager()

        with patch(
            "src.scheduler.vram_manager.subprocess.run",
            side_effect=_make_run_outcomes(0),
        ) as mock_run:
            ok = vm._kill_pid(12345)

    assert ok is True
    assert mock_run.call_count == 1
    cmd = mock_run.call_args_list[0].args[0]
    assert cmd[:4] == ["taskkill", "/f", "/t", "/pid"]
    assert cmd[4] == "12345"


def test_kill_pid_taskkill_timeout_powershell_succeeds():
    """taskkill times out → PowerShell Stop-Process succeeds."""
    from src.scheduler.vram_manager import VRAMManager

    with patch("src.scheduler.vram_manager._find_nvidia_smi", return_value="nvidia-smi"), \
         patch("src.scheduler.vram_manager.platform.system", return_value="Windows"):
        vm = VRAMManager()

        with patch(
            "src.scheduler.vram_manager.subprocess.run",
            side_effect=_make_run_outcomes(
                subprocess.TimeoutExpired(cmd="taskkill", timeout=10),
                0,  # PowerShell succeeds
            ),
        ) as mock_run:
            ok = vm._kill_pid(12345)

    assert ok is True
    assert mock_run.call_count == 2
    second_cmd = mock_run.call_args_list[1].args[0]
    assert "powershell" in second_cmd[0].lower()
    assert "Stop-Process" in " ".join(second_cmd)


def test_kill_pid_powershell_fails_wmic_succeeds():
    """taskkill + Stop-Process both fail → wmic succeeds."""
    from src.scheduler.vram_manager import VRAMManager

    with patch("src.scheduler.vram_manager._find_nvidia_smi", return_value="nvidia-smi"), \
         patch("src.scheduler.vram_manager.platform.system", return_value="Windows"):
        vm = VRAMManager()

        with patch(
            "src.scheduler.vram_manager.subprocess.run",
            side_effect=_make_run_outcomes(1, 1, 0),  # taskkill fail, PS fail, wmic OK
        ) as mock_run:
            ok = vm._kill_pid(12345)

    assert ok is True
    assert mock_run.call_count == 3
    third_cmd = mock_run.call_args_list[2].args[0]
    assert third_cmd[0] == "wmic"


def test_kill_pid_all_methods_fail():
    """All three Windows methods fail → returns False."""
    from src.scheduler.vram_manager import VRAMManager

    with patch("src.scheduler.vram_manager._find_nvidia_smi", return_value="nvidia-smi"), \
         patch("src.scheduler.vram_manager.platform.system", return_value="Windows"):
        vm = VRAMManager()

        with patch(
            "src.scheduler.vram_manager.subprocess.run",
            side_effect=_make_run_outcomes(1, 1, 1),
        ):
            ok = vm._kill_pid(12345)

    assert ok is False


# ── _kill_ollama_processes (the real entry point) ────────────────────────


def test_kill_ollama_processes_uses_pid_when_gpu_apps_present():
    """If nvidia-smi shows an Ollama PID, kill it by PID (not /im)."""
    from src.scheduler.vram_manager import VRAMManager

    with patch("src.scheduler.vram_manager._find_nvidia_smi", return_value="nvidia-smi"), \
         patch("src.scheduler.vram_manager.platform.system", return_value="Windows"):
        vm = VRAMManager()

        # 1st _get_gpu_processes call: returns the hung Ollama PID
        # _kill_pid taskkill: succeeds
        # 2nd _get_gpu_processes call (verification): empty (kill worked)
        gpu_first = MagicMock(returncode=0, stdout="55555, ollama_llama_server.exe, 2673\n")
        gpu_second = MagicMock(returncode=0, stdout="")
        taskkill_ok = MagicMock(returncode=0)

        with patch(
            "src.scheduler.vram_manager.subprocess.run",
            side_effect=[gpu_first, taskkill_ok, gpu_second],
        ) as mock_run, patch("src.scheduler.vram_manager.time.sleep"):
            vm._kill_ollama_processes()

    # Confirm taskkill was called with /pid 55555 (PID-based) not /im (name-based)
    taskkill_call = mock_run.call_args_list[1].args[0]
    assert "/pid" in taskkill_call
    assert "55555" in taskkill_call
    assert "/im" not in taskkill_call


def test_kill_ollama_processes_falls_back_to_im_when_no_gpu_apps():
    """If nvidia-smi shows no Ollama PIDs, fall back to legacy /im kill."""
    from src.scheduler.vram_manager import VRAMManager

    with patch("src.scheduler.vram_manager._find_nvidia_smi", return_value="nvidia-smi"), \
         patch("src.scheduler.vram_manager.platform.system", return_value="Windows"):
        vm = VRAMManager()

        gpu_empty = MagicMock(returncode=0, stdout="")
        taskkill_ok = MagicMock(returncode=0)

        with patch(
            "src.scheduler.vram_manager.subprocess.run",
            side_effect=[gpu_empty, taskkill_ok, taskkill_ok],
        ) as mock_run, patch("src.scheduler.vram_manager.time.sleep"):
            vm._kill_ollama_processes()

    # Confirm fallback to /im for both ollama.exe and ollama_llama_server.exe
    calls_after_query = mock_run.call_args_list[1:]
    im_args = [c.args[0] for c in calls_after_query]
    assert any("/im" in args and "ollama.exe" in args for args in im_args)
    assert any("/im" in args and "ollama_llama_server.exe" in args for args in im_args)


def test_kill_ollama_processes_ignores_non_ollama_gpu_procs():
    """nvidia-smi shows a Python process holding GPU memory — do NOT kill it."""
    from src.scheduler.vram_manager import VRAMManager

    with patch("src.scheduler.vram_manager._find_nvidia_smi", return_value="nvidia-smi"), \
         patch("src.scheduler.vram_manager.platform.system", return_value="Windows"):
        vm = VRAMManager()

        # nvidia-smi reports python.exe holding 4096 MB (e.g. training subprocess)
        gpu_python = MagicMock(returncode=0, stdout="99999, python.exe, 4096\n")
        # Fall back to /im kills (taskkill ollama.exe + ollama_llama_server.exe)
        taskkill_ok = MagicMock(returncode=0)

        with patch(
            "src.scheduler.vram_manager.subprocess.run",
            side_effect=[gpu_python, taskkill_ok, taskkill_ok],
        ) as mock_run, patch("src.scheduler.vram_manager.time.sleep"):
            vm._kill_ollama_processes()

    # Confirm: NO call with /pid 99999 (we did not kill the Python process)
    for c in mock_run.call_args_list:
        args = c.args[0]
        if "/pid" in args and "99999" in args:
            pytest.fail(
                "Killed a python.exe PID — must only kill ollama-named processes "
                "to avoid taking down the watch loop or training subprocess."
            )


# ── v0.36.44: skip /im on the CUDA-wedge path ────────────────────────────


def test_kill_ollama_processes_skips_im_when_wedged_after_pid_kill():
    """v0.36.44: PID found + killed, but VRAM is STILL held (Ollama runner wedged
    in a CUDA syscall) → must NOT fall back to the legacy /im kill. /im can't
    terminate a wedged process and just blocks for its full timeout (observed
    2026-05-20 18:54). The method returns so the caller's retry+empty_cache loop
    waits for the driver to reclaim VRAM."""
    from src.scheduler.vram_manager import VRAMManager

    with patch("src.scheduler.vram_manager._find_nvidia_smi", return_value="nvidia-smi"), \
         patch("src.scheduler.vram_manager.platform.system", return_value="Windows"):
        vm = VRAMManager()

        gpu_first = MagicMock(returncode=0, stdout="55555, ollama_llama_server.exe, 2673\n")
        taskkill_ok = MagicMock(returncode=0)          # _kill_pid taskkill /pid succeeds
        gpu_still = MagicMock(returncode=0, stdout="55555, ollama_llama_server.exe, 2673\n")  # still held

        with patch(
            "src.scheduler.vram_manager.subprocess.run",
            side_effect=[gpu_first, taskkill_ok, gpu_still],
        ) as mock_run, patch("src.scheduler.vram_manager.time.sleep"):
            vm._kill_ollama_processes()

    # The wedge path must NOT invoke any /im kill.
    for c in mock_run.call_args_list:
        args = c.args[0]
        assert "/im" not in args, f"must not fall back to /im on the wedge path: {args}"
    # And it must have attempted the PID kill (taskkill /pid 55555).
    assert any("/pid" in c.args[0] and "55555" in c.args[0] for c in mock_run.call_args_list)
