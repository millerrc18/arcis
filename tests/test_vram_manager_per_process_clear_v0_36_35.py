"""Regression-lock for v0.36.35 — per-process VRAM clear check (multi-GPU desktop topology).

Root cause
==========

`get_vram_used_mb()` reads only GPU[0]'s total memory (`vram_manager.py` —
`split("\\n")[0]`). On the operator's host GPU[0] is the **RTX 3090**, which
also drives the Windows desktop: dwm.exe, Chrome, VS Code, Docker, Steam, etc.
all hold VRAM there — an irreducible ~2.6 GB baseline that can't be freed
without closing the desktop.

The handoff clear-thresholds (1500 MB inference / 2500 MB training) were
written for the original **headless single RTX 3060** (vram_manager docstring).
Post-GPU-upgrade, the 3090's desktop baseline permanently exceeds both
thresholds, so `_wait_for_vram_clear()` could never pass — every handoff
escalated and FAILED even though Ollama unloaded fine. Net effect: overnight
training never ran (only 1 successful training handoff since the 2026-05-10
upgrade; failures 2026-05-18/19 evenings + 2026-05-19/20 mornings).

The fix
=======

Stop gating on total-GPU-VRAM-vs-threshold. Gate per-process instead: the
handoff is clear when the model process we're handing off FROM (Ollama by
name, or the training subprocess by PID) no longer appears in
`nvidia-smi --query-compute-apps`. Desktop apps are irrelevant to that check.

Mocks here mirror REAL nvidia-smi output — including `[N/A]` memory (WDDM
per-process accounting is absent for many Windows processes) and the same
desktop process names observed on the host — so the test can't pass against a
sanitized fiction the way the v0.36.24 mocks did (lens-11 mock-divergence).
"""
from __future__ import annotations

from unittest.mock import patch

import pytest


# Realistic compute-apps snapshots (name, used_mb) — used_mb=None models `[N/A]`.
_DESKTOP_PROCS = [
    {"pid": 2156, "name": "C:\\Windows\\System32\\dwm.exe", "used_mb": None},
    {"pid": 263060, "name": "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe", "used_mb": None},
    {"pid": 222456, "name": "B:\\Microsoft VS Code\\Code.exe", "used_mb": None},
    {"pid": 70096, "name": "C:\\Program Files\\Docker\\Docker\\Docker Desktop.exe", "used_mb": None},
]
_OLLAMA_PROCS = [
    {"pid": 2219228, "name": "C:\\Users\\mille\\AppData\\Local\\Programs\\Ollama\\ollama.exe", "used_mb": None},
    {"pid": 2213936, "name": "C:\\Users\\mille\\AppData\\Local\\Programs\\Ollama\\ollama_llama_server.exe", "used_mb": None},
]


def _vm_with_smi():
    from src.scheduler.vram_manager import VRAMManager
    with patch("src.scheduler.vram_manager._find_nvidia_smi", return_value="nvidia-smi"):
        return VRAMManager()


def test_model_release_true_when_ollama_absent_despite_desktop_vram():
    """THE root-cause lock: Ollama released, but the display GPU still shows
    desktop apps (dwm/chrome/vscode/docker). Per-process check must report
    CLEAR — the prior total-VRAM gate reported 'not clear' on this exact state."""
    vm = _vm_with_smi()
    with patch.object(vm, "_get_gpu_processes", return_value=list(_DESKTOP_PROCS)), \
         patch("time.sleep"):
        assert vm._wait_for_model_release(name_substr="ollama", timeout_seconds=10) is True


def test_model_release_false_while_ollama_holds():
    """Ollama still in compute-apps → must report NOT released (within timeout)."""
    vm = _vm_with_smi()
    times = [0.0]
    def fake_time():
        times[0] += 100.0
        return times[0]
    with patch.object(vm, "_get_gpu_processes", return_value=_DESKTOP_PROCS + _OLLAMA_PROCS), \
         patch("time.sleep"), patch("time.time", side_effect=fake_time):
        assert vm._wait_for_model_release(name_substr="ollama", timeout_seconds=10) is False


def test_model_release_by_pid_for_training():
    """Training handoff identifies the training subprocess by PID, not name."""
    vm = _vm_with_smi()
    training = [{"pid": 999001, "name": "C:\\...\\python.exe", "used_mb": None}]
    # Present first, then gone.
    seq = [_DESKTOP_PROCS + training, list(_DESKTOP_PROCS)]
    with patch.object(vm, "_get_gpu_processes", side_effect=lambda: seq.pop(0) if len(seq) > 1 else seq[0]), \
         patch("time.sleep"):
        assert vm._wait_for_model_release(pid=999001, timeout_seconds=10) is True


def test_model_release_no_nvidia_smi_assumes_clear():
    """Preserve the no-nvidia-smi shortcut (parity with _wait_for_vram_clear)."""
    from src.scheduler.vram_manager import VRAMManager
    with patch("src.scheduler.vram_manager._find_nvidia_smi", return_value=None):
        vm = VRAMManager()
    with patch("time.sleep"):
        assert vm._wait_for_model_release(name_substr="ollama", timeout_seconds=10) is True


def test_model_pids_on_gpu_matches_name_and_pid():
    vm = _vm_with_smi()
    with patch.object(vm, "_get_gpu_processes", return_value=_DESKTOP_PROCS + _OLLAMA_PROCS):
        assert set(vm._model_pids_on_gpu(name_substr="ollama")) == {2213936, 2219228}
        assert vm._model_pids_on_gpu(pid=70096) == [70096]
        assert set(vm._model_pids_on_gpu(name_substr="ollama", pid=2156)) == {2213936, 2219228, 2156}


def test_handoff_to_training_clears_despite_desktop_floor():
    """Integration regression: after Ollama unloads, the 3090 still reports a
    ~2611MB desktop floor. The OLD code failed here (2611 > 2500 threshold).
    The new per-process check sees no Ollama process and proceeds."""
    vm = _vm_with_smi()
    import requests
    ok = type("R", (), {"status_code": 200})()
    with patch.object(vm, "_unload_ollama", return_value=True), \
         patch.object(vm, "_get_gpu_processes", return_value=list(_DESKTOP_PROCS)), \
         patch.object(vm, "get_vram_used_mb", return_value=2611), \
         patch("requests.post", return_value=ok), \
         patch("time.sleep"):
        assert vm.handoff_to_training() is True


def test_handoff_to_inference_clears_despite_desktop_floor():
    """Integration regression: training killed, 3090 shows desktop floor (2611MB).
    OLD code failed (2611 > 1500); new per-process check sees training PID gone."""
    vm = _vm_with_smi()
    ok = type("R", (), {"status_code": 200})()
    with patch.object(vm, "_get_gpu_processes", return_value=list(_DESKTOP_PROCS)), \
         patch.object(vm, "get_vram_used_mb", return_value=2611), \
         patch.object(vm, "_reload_ollama", return_value=True), \
         patch("subprocess.Popen"), \
         patch("src.llm.client.is_llm_available", return_value=True), \
         patch("requests.post", return_value=ok), \
         patch("time.sleep"):
        assert vm.handoff_to_inference() is True
