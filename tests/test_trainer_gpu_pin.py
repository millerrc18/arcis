"""T9 — GPU0 pin + nvidia-smi identity preflight + stop-aware wait loop.

Verifies (all subprocess / nvidia-smi mocked — NEVER touches a real GPU):
- Training subprocess env carries CUDA_VISIBLE_DEVICES=0 + CUDA_DEVICE_ORDER=PCI_BUS_ID
- The PID is written to training_control.TRAINING_PID_FILE after Popen
- The stop-aware wait loop does NOT return while proc.poll() is None, and
  returns only after the subprocess exits (no early return)
- A STOP flag set mid-loop triggers training_control.stop_training_bounded
- The DPO subprocess inherits CUDA_VISIBLE_DEVICES=0
- The generated curriculum script wires device_map + StopOnFlagCallback
- MAJOR-5: a mocked nvidia-smi showing index0 == RTX 3060 aborts the launch (raise)
"""

import subprocess
from unittest.mock import MagicMock, patch

import pytest

from src.training import trainer
from src.training import trainer_checkpoint
from src.training import training_control


# ---------------------------------------------------------------------------
# Test 1 — Popen env carries the GPU0 pin
# ---------------------------------------------------------------------------

def test_training_subprocess_env_pins_gpu0():
    env = trainer._training_subprocess_env()
    assert env["CUDA_VISIBLE_DEVICES"] == "0"
    assert env["CUDA_DEVICE_ORDER"] == "PCI_BUS_ID"


# ---------------------------------------------------------------------------
# Test 2 — generated curriculum script wires device_map + StopOnFlagCallback
# ---------------------------------------------------------------------------

def test_curriculum_script_wires_device_map_and_stop_callback():
    script = trainer.CURRICULUM_TRAIN_SCRIPT
    # GPU0 placement: device_map pinned to cuda:0 (not "auto" which could pick GPU1)
    assert 'device_map={"": 0}' in script or 'device_map="cuda:0"' in script
    # Stop callback wired into the Trainer
    assert "StopOnFlagCallback" in script
    assert "callbacks=" in script


# ---------------------------------------------------------------------------
# nvidia-smi identity preflight helpers
# ---------------------------------------------------------------------------

def _fake_nvidia_smi(stdout: str, returncode: int = 0):
    """Build a fake subprocess.run that returns the given nvidia-smi CSV."""
    def _run(*args, **kwargs):
        res = MagicMock()
        res.returncode = returncode
        res.stdout = stdout
        res.stderr = ""
        return res
    return _run


_GPU0_3090 = "0, NVIDIA GeForce RTX 3090, GPU-1111\n1, NVIDIA GeForce RTX 3060, GPU-2222\n"
_GPU0_3060 = "0, NVIDIA GeForce RTX 3060, GPU-2222\n1, NVIDIA GeForce RTX 3090, GPU-1111\n"


def test_launch_preflight_passes_when_gpu0_is_3090():
    with patch("src.training.trainer_checkpoint.subprocess.run", _fake_nvidia_smi(_GPU0_3090)):
        # Should NOT raise
        trainer._assert_gpu0_identity()


def test_launch_preflight_aborts_when_gpu0_is_3060():
    # MAJOR-5 regression lock: index0 is the 12 GB 3060 ⇒ abort the launch loud.
    with patch("src.training.trainer_checkpoint.subprocess.run", _fake_nvidia_smi(_GPU0_3060)):
        with pytest.raises(RuntimeError, match="3090|IDENTITY|MAJOR-5"):
            trainer._assert_gpu0_identity()


# ---------------------------------------------------------------------------
# Stop-aware wait loop
# ---------------------------------------------------------------------------

def _proc_that_exits_after(n_polls: int, returncode: int = 0):
    """A fake Popen whose poll() returns None n_polls times, then returncode."""
    proc = MagicMock()
    proc.pid = 4321
    state = {"calls": 0}

    def _poll():
        state["calls"] += 1
        if state["calls"] <= n_polls:
            return None
        return returncode

    proc.poll.side_effect = _poll
    proc.returncode = returncode
    return proc, state


def test_wait_loop_does_not_return_until_subprocess_exits():
    proc, state = _proc_that_exits_after(n_polls=3, returncode=0)
    with patch("src.training.trainer_checkpoint.training_stop.is_stop_requested", return_value=False), \
         patch("src.training.trainer_checkpoint.time.sleep", return_value=None):
        rc = trainer._wait_for_training_proc(proc, timeout_s=7200, poll_interval=0.01)
    # poll() must have been called until it stopped returning None — proof of no early return
    assert state["calls"] >= 4
    assert rc == 0


def test_wait_loop_stop_flag_triggers_bounded_stop():
    proc, state = _proc_that_exits_after(n_polls=10, returncode=0)
    stop_states = iter([False, True])

    def _is_stop():
        try:
            return next(stop_states)
        except StopIteration:
            return True

    with patch("src.training.trainer_checkpoint.training_stop.is_stop_requested", side_effect=_is_stop), \
         patch("src.training.trainer_checkpoint.training_control.stop_training_bounded") as mock_stop, \
         patch("src.training.trainer_checkpoint.time.sleep", return_value=None):
        trainer._wait_for_training_proc(proc, timeout_s=7200, poll_interval=0.01)
    mock_stop.assert_called_once()


def test_wait_loop_enforces_7200_ceiling():
    # proc never exits; once the monotonic clock passes the ceiling the loop
    # must request a bounded stop and return rather than spin forever.
    proc = MagicMock()
    proc.pid = 4321
    proc.poll.return_value = None
    proc.returncode = None

    times = iter([0.0, 1.0, 2.0, 10_000.0, 10_001.0, 10_002.0])

    def _mono():
        try:
            return next(times)
        except StopIteration:
            return 99_999.0

    with patch("src.training.trainer_checkpoint.training_stop.is_stop_requested", return_value=False), \
         patch("src.training.trainer_checkpoint.training_control.stop_training_bounded") as mock_stop, \
         patch("src.training.trainer_checkpoint.time.monotonic", side_effect=_mono), \
         patch("src.training.trainer_checkpoint.time.sleep", return_value=None):
        trainer._wait_for_training_proc(proc, timeout_s=7200, poll_interval=0.01)
    mock_stop.assert_called_once()


# ---------------------------------------------------------------------------
# End-to-end run_fine_tune wiring (Popen + PID file + GPU pin)
# ---------------------------------------------------------------------------

def _patch_pipeline_around_popen(tmp_path, monkeypatch):
    """Patch run_fine_tune's surroundings so we only exercise the launch path.

    Returns nothing; raises a sentinel after the Popen+PID+preflight so the
    test can stop the pipeline immediately after launch without exercising
    Ollama/canary/holdout.
    """
    # Point TRAINING_PID_FILE at the tmp dir.
    pid_file = tmp_path / "training.pid"
    monkeypatch.setattr(training_control, "TRAINING_PID_FILE", str(pid_file))
    return pid_file


class _StopPipeline(Exception):
    pass


def test_run_fine_tune_uses_popen_and_writes_pid(tmp_path, monkeypatch):
    pid_file = _patch_pipeline_around_popen(tmp_path, monkeypatch)

    captured = {}

    def _fake_popen(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["env"] = kwargs.get("env")
        captured["creationflags"] = kwargs.get("creationflags")
        proc = MagicMock()
        proc.pid = 13579
        proc.poll.return_value = 0
        proc.returncode = 0
        return proc

    # export_training_data returns a viable split
    monkeypatch.setattr(trainer, "export_training_data",
                        lambda *a, **k: ({"training": 10, "holdout": 3}, 13))
    # stage1 file "exists" so curriculum path is taken; write the file
    (tmp_path / "td").mkdir()
    # T12: Popen/nvidia-smi/wait-loop now execute in trainer_checkpoint's
    # namespace (the launch helpers moved there); patch that module so the
    # mocks actually bind. run_fine_tune itself still lives in trainer.py.
    monkeypatch.setattr(trainer_checkpoint, "subprocess", subprocess)
    monkeypatch.setattr(trainer_checkpoint.subprocess, "Popen", _fake_popen)
    # nvidia-smi preflight passes
    monkeypatch.setattr(trainer_checkpoint.subprocess, "run", _fake_nvidia_smi(_GPU0_3090))
    monkeypatch.setattr(trainer_checkpoint.training_stop, "is_stop_requested", lambda: False)
    monkeypatch.setattr(trainer_checkpoint.time, "sleep", lambda *a, **k: None)

    # Make the script-writing target the tmp dir and force curriculum path.
    from pathlib import Path as _P
    orig_path = trainer.Path

    def _path(p):
        # redirect training_data root into tmp
        if str(p) == "training_data":
            return _P(tmp_path / "td")
        return orig_path(p)

    monkeypatch.setattr(trainer, "Path", _path)
    # create a non-empty stage1 file so curriculum branch fires
    (tmp_path / "td" / "stage1_structure.jsonl").write_text('{"x":1}\n', encoding="utf-8")

    # Capture the pidfile contents at the moment _launch_and_wait_training's
    # finally-block cleanup removes it (the file is cleared after the wait
    # returns, before _find_gguf runs).
    real_remove = trainer_checkpoint.os.remove

    def _spy_remove(path):
        if str(path) == str(pid_file) and pid_file.exists():
            captured["pid_contents"] = pid_file.read_text(encoding="utf-8").strip()
        return real_remove(path)

    monkeypatch.setattr(trainer_checkpoint.os, "remove", _spy_remove)

    # Stop the pipeline right after the wait loop returns by making the GGUF
    # lookup raise our sentinel.
    def _boom(*a, **k):
        raise _StopPipeline()

    monkeypatch.setattr(trainer, "_find_gguf", _boom)

    with pytest.raises(_StopPipeline):
        trainer.run_fine_tune(db_path=":memory:")

    # Popen was used with the GPU0-pinned env
    assert captured["env"]["CUDA_VISIBLE_DEVICES"] == "0"
    assert captured["env"]["CUDA_DEVICE_ORDER"] == "PCI_BUS_ID"
    # PID file written with the Popen pid (captured before cleanup removed it)
    assert captured.get("pid_contents") == "13579"
    # cmdline carries the generated train.py path so T4's predicate matches
    assert any("train.py" in str(part) for part in captured["cmd"])
