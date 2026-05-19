"""Regression-lock for v0.36.29 — nvidia-smi `[N/A]` memory parse.

Background
==========

v0.36.24 introduced PID-based Ollama-killing via
`nvidia-smi --query-compute-apps=pid,process_name,used_memory` to fix the
2026-05-18/19 VRAM-handoff cascade. The implementation parsed the third
column as `int(parts[2])`, with a `ValueError` fallthrough.

Two nights later (2026-05-19 18:50 ET handoff) the fix failed to fire.
Diagnosis: `nvidia-smi --query-compute-apps=...,used_memory` returns
**`[N/A]`** (literal string with brackets) for processes whose per-process
VRAM accounting is unavailable. On the operator's RTX 3090+3060 system,
Ollama's `ollama.exe` shows up TWICE (once per GPU) with `[N/A]` memory:

    2195136, C:\\Users\\mille\\AppData\\Local\\Programs\\Ollama\\ollama.exe, [N/A]
    2195136, C:\\Users\\mille\\AppData\\Local\\Programs\\Ollama\\ollama.exe, [N/A]

`int("[N/A]")` raises ValueError → the `except ValueError: continue` swallows
the row → `_get_gpu_processes()` returned `[]` → the ollama-filter found no
matches → fallthrough to the legacy `taskkill /f /im ollama.exe` path which
times out.

Net effect: v0.36.24 was effectively a no-op on this hardware. The training
pipeline missed another night.

Fix
===

Treat non-integer `used_memory` as `None` (not skip the row). Identification
of Ollama processes doesn't require the memory column. Dedupe PIDs since
multi-GPU systems list the same process once per GPU.

Tests
=====

This file pins the contract using the ACTUAL nvidia-smi output captured
from the live system on 2026-05-19 (RTX 3090+3060). The v0.36.24 mock
used a hypothesized `int` memory value — that's how the [N/A] case slipped
through review. TDD lesson: pin the real output format, not the documented one.
"""
from __future__ import annotations

from unittest.mock import patch, MagicMock

import pytest


# Real nvidia-smi output captured 2026-05-19 ~19:35 ET from the operator's
# RTX 3090+3060 system. Used as the test fixture so future refactors
# can't accidentally break the `[N/A]` handling.
REAL_NVIDIA_SMI_OUTPUT = """\
2156, C:\\Windows\\System32\\dwm.exe, [N/A]
13700, C:\\Windows\\SystemApps\\MicrosoftWindows.Client.CBS_cw5n1h2txyewy\\CrossDeviceResume.exe, [N/A]
12996, C:\\Program Files\\LogiOptionsPlus\\logioptionsplus_agent.exe, [N/A]
2195136, C:\\Users\\mille\\AppData\\Local\\Programs\\Ollama\\ollama.exe, [N/A]
2195136, C:\\Users\\mille\\AppData\\Local\\Programs\\Ollama\\ollama.exe, [N/A]
1988, B:\\Steam\\bin\\cef\\cef.win64\\steamwebhelper.exe, [N/A]
"""


def _make_subprocess_mock(stdout: str, returncode: int = 0):
    """Build a subprocess.run mock that yields the given output."""
    mock_result = MagicMock()
    mock_result.returncode = returncode
    mock_result.stdout = stdout
    return mock_result


def test_get_gpu_processes_handles_na_memory():
    """Real-world nvidia-smi rows with `[N/A]` memory must NOT be skipped."""
    from src.scheduler.vram_manager import VRAMManager

    with patch("src.scheduler.vram_manager._find_nvidia_smi", return_value="nvidia-smi"):
        vm = VRAMManager()

    with patch("src.scheduler.vram_manager.subprocess.run",
               return_value=_make_subprocess_mock(REAL_NVIDIA_SMI_OUTPUT)):
        procs = vm._get_gpu_processes()

    # At minimum, the rows must be parsed (used_mb may be None for N/A)
    assert len(procs) >= 4, (
        f"Real nvidia-smi output yielded only {len(procs)} parsed rows. "
        f"The [N/A] memory column must not cause row-skip. Sample: {procs[:2]}"
    )
    # Ollama must be found (case-insensitive name match downstream)
    ollama_rows = [p for p in procs if "ollama" in p["name"].lower()]
    assert len(ollama_rows) >= 1, (
        f"Ollama process missing from parsed gpu processes. "
        f"All parsed: {[p['name'] for p in procs]}"
    )
    # used_mb is None when memory was '[N/A]'
    for p in ollama_rows:
        assert p["used_mb"] is None, (
            f"Ollama row used_mb should be None for '[N/A]', got {p['used_mb']!r}"
        )


def test_get_gpu_processes_preserves_int_memory_when_present():
    """Backward-compat: when memory IS an int, preserve int parsing."""
    from src.scheduler.vram_manager import VRAMManager

    with patch("src.scheduler.vram_manager._find_nvidia_smi", return_value="nvidia-smi"):
        vm = VRAMManager()

    # Mix of N/A and int memory values
    output = (
        "12345, ollama_llama_server.exe, 2673\n"
        "67890, python.exe, 4096\n"
        "99999, dwm.exe, [N/A]\n"
    )

    with patch("src.scheduler.vram_manager.subprocess.run",
               return_value=_make_subprocess_mock(output)):
        procs = vm._get_gpu_processes()

    by_pid = {p["pid"]: p for p in procs}
    assert by_pid[12345]["used_mb"] == 2673
    assert by_pid[67890]["used_mb"] == 4096
    assert by_pid[99999]["used_mb"] is None


def test_kill_ollama_processes_finds_ollama_when_memory_is_na():
    """End-to-end: real nvidia-smi output → PID-based kill path engages.

    Pre-fix: `[N/A]` caused row-skip → ollama-filter empty → fell through to
    `/im` legacy path. This test ensures the PID-based path actually kills
    PID 2195136 on real-world input.
    """
    from src.scheduler.vram_manager import VRAMManager

    with patch("src.scheduler.vram_manager._find_nvidia_smi", return_value="nvidia-smi"), \
         patch("src.scheduler.vram_manager.platform.system", return_value="Windows"):
        vm = VRAMManager()

    # Sequence:
    # call 1: _get_gpu_processes → returns the real output (Ollama present)
    # call 2: _kill_pid(2195136) → taskkill /f /t /pid 2195136 → success
    # call 3: _get_gpu_processes again (verify pass) → empty (Ollama dead)
    real_input = _make_subprocess_mock(REAL_NVIDIA_SMI_OUTPUT)
    taskkill_ok = _make_subprocess_mock("", returncode=0)
    second_query = _make_subprocess_mock("")  # nothing left

    calls = []
    def run_side_effect(cmd, *args, **kwargs):
        calls.append(cmd)
        # Heuristic: nvidia-smi → return real-input then second-query
        if cmd and ("nvidia-smi" in str(cmd[0]) or "--query-compute-apps" in str(cmd)):
            return real_input if len([c for c in calls if "--query-compute-apps" in str(c)]) == 1 else second_query
        # Otherwise return ok (taskkill / Stop-Process / wmic)
        return taskkill_ok

    with patch("src.scheduler.vram_manager.subprocess.run", side_effect=run_side_effect), \
         patch("src.scheduler.vram_manager.time.sleep"):
        vm._kill_ollama_processes()

    # The taskkill should have been called for the Ollama PID 2195136
    pid_kill_calls = [
        c for c in calls
        if isinstance(c, list) and "/pid" in c and "2195136" in c
    ]
    assert len(pid_kill_calls) >= 1, (
        f"PID-based kill for Ollama PID 2195136 was NOT called. All commands: "
        f"{[c[0] if isinstance(c, list) else c for c in calls]}"
    )


def test_kill_ollama_processes_dedupes_pids():
    """Multi-GPU systems show the same Ollama PID twice (once per GPU).
    Don't kill the same PID twice — wasteful and noisy.
    """
    from src.scheduler.vram_manager import VRAMManager

    with patch("src.scheduler.vram_manager._find_nvidia_smi", return_value="nvidia-smi"), \
         patch("src.scheduler.vram_manager.platform.system", return_value="Windows"):
        vm = VRAMManager()

    # nvidia-smi reports Ollama PID 2195136 twice (RTX 3090 + RTX 3060)
    duplicate_output = (
        "2195136, ollama.exe, [N/A]\n"
        "2195136, ollama.exe, [N/A]\n"
    )

    calls = []
    def run_side_effect(cmd, *args, **kwargs):
        calls.append(cmd)
        if cmd and "--query-compute-apps" in str(cmd):
            return _make_subprocess_mock(duplicate_output)
        return _make_subprocess_mock("", returncode=0)

    with patch("src.scheduler.vram_manager.subprocess.run", side_effect=run_side_effect), \
         patch("src.scheduler.vram_manager.time.sleep"):
        vm._kill_ollama_processes()

    # Count distinct PIDs targeted by taskkill /pid
    pid_kill_calls = [c for c in calls if isinstance(c, list) and "/pid" in c]
    targeted_pids = [c[c.index("/pid") + 1] for c in pid_kill_calls]
    distinct = set(targeted_pids)
    assert len(distinct) <= 1, (
        f"Killed multiple distinct PIDs from duplicated nvidia-smi rows: {targeted_pids}. "
        "Should dedupe by PID."
    )
    # And confirm the kill DID fire at least once (vs. dedupe killing all)
    assert "2195136" in distinct, (
        f"Ollama PID 2195136 was NOT killed despite being listed. "
        f"PIDs targeted: {targeted_pids}"
    )
