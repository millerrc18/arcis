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


def test_handoff_to_training_vram_not_clear():
    from src.scheduler.vram_manager import VRAMManager
    with patch("src.scheduler.vram_manager._find_nvidia_smi",
               return_value="nvidia-smi"):
        vm = VRAMManager()

    mock_resp = MagicMock()
    mock_resp.status_code = 200

    # nvidia-smi always reports high VRAM
    mock_smi = MagicMock()
    mock_smi.returncode = 0
    mock_smi.stdout = "8000\n"

    # Make time.time() return a monotonically increasing counter so
    # _wait_for_vram_clear's `while time.time() < deadline` loop exits
    # immediately (deadline = t + timeout where t is in the past by the
    # second call). Without this, the test waits the full real-time
    # 30s + 15s×3 = 75s, exceeding pytest-timeout=60s in CI.
    time_counter = [0]
    def fake_time():
        time_counter[0] += 1000  # jump forward 1000s per call
        return time_counter[0]

    with patch("requests.post", return_value=mock_resp), \
         patch("subprocess.run", return_value=mock_smi), \
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


def test_handoff_to_inference_escalates_when_vram_not_clear():
    """When VRAM stays high after training kill, should kill Ollama processes (#198)."""
    from src.scheduler.vram_manager import VRAMManager
    with patch("src.scheduler.vram_manager._find_nvidia_smi",
               return_value="nvidia-smi"):
        vm = VRAMManager()

    # Simulate training process that exits cleanly
    mock_proc = MagicMock()
    mock_proc.poll.return_value = None
    mock_proc.pid = 12345
    vm._training_process = mock_proc

    # nvidia-smi always reports high VRAM (above 1500MB threshold)
    mock_smi = MagicMock()
    mock_smi.returncode = 0
    mock_smi.stdout = "5000\n"

    mock_resp = MagicMock()
    mock_resp.status_code = 200

    # Patch time.time so _wait_for_vram_clear's deadline loop exits
    # immediately (see test_handoff_to_training_vram_not_clear rationale).
    time_counter = [0]
    def fake_time():
        time_counter[0] += 1000
        return time_counter[0]

    with patch("subprocess.run", return_value=mock_smi) as mock_run, \
         patch("subprocess.Popen"), \
         patch("requests.post", return_value=mock_resp), \
         patch("time.sleep"), \
         patch("time.time", side_effect=fake_time):
        result = vm.handoff_to_inference()

    # Should have attempted to kill Ollama processes (taskkill or pkill)
    kill_calls = [c for c in mock_run.call_args_list
                  if any("taskkill" in str(a) or "pkill" in str(a)
                         for a in c.args + tuple(c.kwargs.values()))]
    assert len(kill_calls) > 0, "Should have called taskkill/pkill to kill Ollama"


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
