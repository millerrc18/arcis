"""Tests for VRAM transition management."""

import subprocess
from unittest.mock import patch, MagicMock

import pytest


# ── nvidia-smi discovery ─────────────────────────────────────────────


def test_find_nvidia_smi_not_found():
    from src.scheduler.vram_manager import _find_nvidia_smi
    with patch("subprocess.run", side_effect=FileNotFoundError):
        result = _find_nvidia_smi()
        assert result is None


def test_find_nvidia_smi_found():
    from src.scheduler.vram_manager import _find_nvidia_smi
    mock_result = MagicMock()
    mock_result.returncode = 0
    with patch("subprocess.run", return_value=mock_result):
        result = _find_nvidia_smi()
        assert result is not None


# ── VRAMManager ──────────────────────────────────────────────────────


def test_get_active_model_from_config():
    from src.scheduler.vram_manager import VRAMManager
    with patch("src.scheduler.vram_manager._find_nvidia_smi", return_value=None):
        vm = VRAMManager()
    with patch("src.training.versioning.get_active_model_name", return_value="base"):
        model = vm.get_active_model()
    # Should fall back to config default
    assert isinstance(model, str)
    assert len(model) > 0


def test_get_active_model_trained_override():
    from src.scheduler.vram_manager import VRAMManager
    with patch("src.scheduler.vram_manager._find_nvidia_smi", return_value=None):
        vm = VRAMManager()
    with patch("src.training.versioning.get_active_model_name",
               return_value="halcyon-v3"):
        model = vm.get_active_model()
    assert model == "halcyon-v3"


def test_get_vram_used_mb_no_nvidia_smi():
    from src.scheduler.vram_manager import VRAMManager
    with patch("src.scheduler.vram_manager._find_nvidia_smi", return_value=None):
        vm = VRAMManager()
    assert vm.get_vram_used_mb() == -1


def test_get_vram_used_mb_success():
    from src.scheduler.vram_manager import VRAMManager
    with patch("src.scheduler.vram_manager._find_nvidia_smi",
               return_value="nvidia-smi"):
        vm = VRAMManager()

    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = "2048\n"
    with patch("subprocess.run", return_value=mock_result):
        used = vm.get_vram_used_mb()
    assert used == 2048


def test_get_vram_used_mb_multi_gpu():
    from src.scheduler.vram_manager import VRAMManager
    with patch("src.scheduler.vram_manager._find_nvidia_smi",
               return_value="nvidia-smi"):
        vm = VRAMManager()

    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = "2048\n4096\n"
    with patch("subprocess.run", return_value=mock_result):
        used = vm.get_vram_used_mb()
    assert used == 2048  # Takes first GPU


# ── Handoff to training ──────────────────────────────────────────────


def test_handoff_to_training_success():
    from src.scheduler.vram_manager import VRAMManager
    with patch("src.scheduler.vram_manager._find_nvidia_smi", return_value=None):
        vm = VRAMManager()

    mock_resp = MagicMock()
    mock_resp.status_code = 200

    with patch("requests.post", return_value=mock_resp), \
         patch("time.sleep"):
        result = vm.handoff_to_training()
    assert result is True


def test_handoff_to_training_unload_fails():
    from src.scheduler.vram_manager import VRAMManager
    with patch("src.scheduler.vram_manager._find_nvidia_smi", return_value=None):
        vm = VRAMManager()

    # _unload_ollama tries `ollama stop <model>` via subprocess before
    # falling back to the HTTP API. On a dev box that actually has ollama
    # installed, the subprocess succeeds and the requests.post mock is
    # never reached. Force subprocess to fail so the test exercises the
    # HTTP-fallback branch it was written for.
    subp_fail = MagicMock()
    subp_fail.returncode = 1
    with patch("subprocess.run", return_value=subp_fail), \
         patch("requests.post", side_effect=Exception("Connection refused")), \
         patch("time.sleep"):
        result = vm.handoff_to_training()
    assert result is False


def test_handoff_to_training_fails_when_ollama_wont_release():
    """v0.36.35: the training handoff fails only when Ollama keeps holding the
    GPU after unload + kill — NOT merely because total GPU VRAM is high. The
    prior `_wait_for_vram_clear(2500)` gate failed on the display GPU's ~2.6GB
    desktop floor even when Ollama had released; the per-process gate doesn't."""
    from src.scheduler.vram_manager import VRAMManager
    with patch("src.scheduler.vram_manager._find_nvidia_smi",
               return_value="nvidia-smi"):
        vm = VRAMManager()

    # Ollama persistently present in compute-apps — it never releases the GPU.
    ollama_proc = [{"pid": 4242, "name": "ollama_llama_server.exe", "used_mb": None}]

    # Monotonic time so the wait loops exit immediately (else 30s+15s×3 real wait).
    time_counter = [0]
    def fake_time():
        time_counter[0] += 1000
        return time_counter[0]

    with patch.object(vm, "_unload_ollama", return_value=True), \
         patch.object(vm, "_get_gpu_processes", return_value=ollama_proc), \
         patch.object(vm, "_kill_ollama_processes"), \
         patch.object(vm, "_reload_ollama", return_value=True), \
         patch("subprocess.Popen"), \
         patch("time.sleep"), \
         patch("time.time", side_effect=fake_time):
        result = vm.handoff_to_training()
    assert result is False


# ── Handoff to inference ─────────────────────────────────────────────


def test_handoff_to_inference_success():
    from src.scheduler.vram_manager import VRAMManager
    with patch("src.scheduler.vram_manager._find_nvidia_smi", return_value=None):
        vm = VRAMManager()

    mock_resp = MagicMock()
    mock_resp.status_code = 200

    with patch("requests.post", return_value=mock_resp), \
         patch("src.llm.client.is_llm_available", return_value=True), \
         patch("time.sleep"):
        result = vm.handoff_to_inference()
    assert result is True


def test_handoff_to_inference_kills_training():
    from src.scheduler.vram_manager import VRAMManager
    with patch("src.scheduler.vram_manager._find_nvidia_smi", return_value=None):
        vm = VRAMManager()

    # Simulate running training process
    mock_proc = MagicMock()
    mock_proc.poll.return_value = None  # Still running
    mock_proc.pid = 12345
    vm._training_process = mock_proc

    mock_resp = MagicMock()
    mock_resp.status_code = 200

    with patch("requests.post", return_value=mock_resp), \
         patch("src.llm.client.is_llm_available", return_value=True), \
         patch("time.sleep"):
        result = vm.handoff_to_inference()

    assert result is True
    mock_proc.terminate.assert_called_once()


def test_handoff_to_inference_force_kill():
    from src.scheduler.vram_manager import VRAMManager
    with patch("src.scheduler.vram_manager._find_nvidia_smi", return_value=None):
        vm = VRAMManager()

    mock_proc = MagicMock()
    mock_proc.poll.return_value = None
    mock_proc.pid = 12345
    mock_proc.wait.side_effect = [subprocess.TimeoutExpired("cmd", 30), None]
    vm._training_process = mock_proc

    mock_resp = MagicMock()
    mock_resp.status_code = 200

    with patch("requests.post", return_value=mock_resp), \
         patch("src.llm.client.is_llm_available", return_value=True), \
         patch("time.sleep"):
        result = vm.handoff_to_inference()

    assert result is True
    mock_proc.kill.assert_called_once()


def test_handoff_to_inference_reload_fails():
    from src.scheduler.vram_manager import VRAMManager
    with patch("src.scheduler.vram_manager._find_nvidia_smi", return_value=None):
        vm = VRAMManager()

    with patch("requests.post", side_effect=Exception("Connection refused")), \
         patch("time.sleep"):
        result = vm.handoff_to_inference()
    assert result is False


# ── Launch training subprocess ───────────────────────────────────────


def test_launch_training_subprocess():
    from src.scheduler.vram_manager import VRAMManager
    with patch("src.scheduler.vram_manager._find_nvidia_smi", return_value=None):
        vm = VRAMManager()

    mock_proc = MagicMock()
    with patch("subprocess.Popen", return_value=mock_proc):
        proc = vm.launch_training_subprocess("test_task", ["-m", "test"])

    assert proc is mock_proc
    assert vm._training_process is mock_proc


# ── Training running property ────────────────────────────────────────


def test_training_running_no_process():
    from src.scheduler.vram_manager import VRAMManager
    with patch("src.scheduler.vram_manager._find_nvidia_smi", return_value=None):
        vm = VRAMManager()
    assert vm.training_running is False


def test_training_running_active():
    from src.scheduler.vram_manager import VRAMManager
    with patch("src.scheduler.vram_manager._find_nvidia_smi", return_value=None):
        vm = VRAMManager()
    mock_proc = MagicMock()
    mock_proc.poll.return_value = None
    vm._training_process = mock_proc
    assert vm.training_running is True


def test_training_running_finished():
    from src.scheduler.vram_manager import VRAMManager
    with patch("src.scheduler.vram_manager._find_nvidia_smi", return_value=None):
        vm = VRAMManager()
    mock_proc = MagicMock()
    mock_proc.poll.return_value = 0
    vm._training_process = mock_proc
    assert vm.training_running is False


# ── VRAM inference handoff escalation (#198) ────────────────────────


def test_handoff_to_inference_escalates_by_killing_training():
    """v0.36.35: when the training process won't release the GPU, the inference
    handoff escalates by FORCE-KILLING the training PID — not Ollama, which it
    is about to load. The prior code killed Ollama here, a no-op against the
    real VRAM holder (and counterproductive to the goal of loading Ollama)."""
    from src.scheduler.vram_manager import VRAMManager
    with patch("src.scheduler.vram_manager._find_nvidia_smi",
               return_value="nvidia-smi"):
        vm = VRAMManager()

    mock_proc = MagicMock()
    mock_proc.poll.return_value = None
    mock_proc.pid = 12345
    vm._training_process = mock_proc

    # Training PID persistently holds the GPU (never releases) — desktop apps
    # would also be present on a real host but are irrelevant to the per-process gate.
    training_on_gpu = [{"pid": 12345, "name": "python.exe", "used_mb": None}]

    mock_run_result = MagicMock()
    mock_run_result.returncode = 0
    mock_run_result.stdout = ""

    time_counter = [0]
    def fake_time():
        time_counter[0] += 1000
        return time_counter[0]

    with patch.object(vm, "_get_gpu_processes", return_value=training_on_gpu), \
         patch("subprocess.run", return_value=mock_run_result) as mock_run, \
         patch("subprocess.Popen"), \
         patch("time.sleep"), \
         patch("time.time", side_effect=fake_time):
        result = vm.handoff_to_inference()

    # Escalation must force-kill the lingering TRAINING pid (12345), not Ollama.
    killed_training = [c for c in mock_run.call_args_list
                       if "taskkill" in str(c) and "12345" in str(c)]
    assert killed_training, "escalation should force-kill the lingering training PID 12345"
    assert result is False  # training never releases → handoff correctly fails


def test_handoff_to_inference_returns_false_after_escalation_failure():
    """When aggressive cleanup also fails, should return False (#198)."""
    from src.scheduler.vram_manager import VRAMManager
    with patch("src.scheduler.vram_manager._find_nvidia_smi",
               return_value="nvidia-smi"):
        vm = VRAMManager()

    # nvidia-smi always reports high VRAM
    mock_smi = MagicMock()
    mock_smi.returncode = 0
    mock_smi.stdout = "5000\n"

    # Patch time.time so wait loop exits immediately
    time_counter = [0]
    def fake_time():
        time_counter[0] += 1000
        return time_counter[0]

    with patch("subprocess.run", return_value=mock_smi), \
         patch("subprocess.Popen"), \
         patch("requests.post", side_effect=Exception("Connection refused")), \
         patch("time.sleep"), \
         patch("time.time", side_effect=fake_time):
        result = vm.handoff_to_inference()

    assert result is False


def test_handoff_to_inference_no_escalation_on_clean_vram():
    """When VRAM clears normally, should NOT kill Ollama processes (#198)."""
    from src.scheduler.vram_manager import VRAMManager
    with patch("src.scheduler.vram_manager._find_nvidia_smi", return_value=None):
        vm = VRAMManager()

    mock_resp = MagicMock()
    mock_resp.status_code = 200

    with patch("requests.post", return_value=mock_resp), \
         patch("src.llm.client.is_llm_available", return_value=True), \
         patch("subprocess.run") as mock_run, \
         patch("time.sleep"):
        result = vm.handoff_to_inference()

    assert result is True
    # Should NOT have called taskkill/pkill
    kill_calls = [c for c in mock_run.call_args_list
                  if any("taskkill" in str(a) or "pkill" in str(a)
                         for a in c.args + tuple(c.kwargs.values()))]
    assert len(kill_calls) == 0
