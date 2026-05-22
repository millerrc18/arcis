"""Tests for training_control.py — bounded cooperative stop + tracked-PID predicate.

SAFETY-CRITICAL (dual-GPU re-cutover T4). This module runs as LocalSystem and a
wrong-target hard-kill on the live box is catastrophic. Every psutil/subprocess
interaction is MOCKED — no real PID is ever killed here.

Predicate coverage (`_is_tracked_training_proc`):
  - missing pidfile / unparseable pidfile  -> False
  - dead PID (pid_exists False)             -> False
  - ZOMBIE process                          -> False
  - cmdline lacks train-script/module marker (recycled PID) -> False
  - NoSuchProcess / AccessDenied            -> False
  - valid tracked proc (marker + alive + CVD=0) -> True

stop_training_bounded() no-op safety:
  (a) missing pidfile      -> terminate NOTHING
  (b) dead PID             -> no-op + stale pidfile cleared
  (c) recycled non-training PID (watch loop / arbitrary) -> terminate NOTHING
  (d) valid tracked PID    -> cooperative wait then terminate TRACKED only,
                              never /im, never an Ollama process
"""

from unittest.mock import MagicMock, patch

import psutil
import pytest

from src.training import training_control


# ── Helpers ──────────────────────────────────────────────────────────────


def _fake_proc(pid=4321, cmdline=None, status=psutil.STATUS_RUNNING,
               environ=None, alive_after=None):
    """Build a MagicMock that quacks like psutil.Process."""
    proc = MagicMock(spec=psutil.Process)
    proc.pid = pid
    proc.cmdline.return_value = cmdline if cmdline is not None else [
        "python", "training_data/train.py",
    ]
    proc.status.return_value = status
    proc.environ.return_value = environ if environ is not None else {
        "CUDA_VISIBLE_DEVICES": "0",
    }
    # is_running returns the queued sequence (cooperative wait), else True.
    if alive_after is not None:
        proc.is_running.side_effect = alive_after
    else:
        proc.is_running.return_value = True
    return proc


# ── _is_tracked_training_proc predicate ────────────────────────────────────


def test_predicate_false_when_pidfile_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(training_control, "TRAINING_PID_FILE",
                        str(tmp_path / "training.pid"))
    assert training_control._is_tracked_training_proc(4321) is False


def test_predicate_false_when_pidfile_unparseable(tmp_path, monkeypatch):
    pidfile = tmp_path / "training.pid"
    pidfile.write_text("not-an-int")
    monkeypatch.setattr(training_control, "TRAINING_PID_FILE", str(pidfile))
    assert training_control._is_tracked_training_proc(4321) is False


def test_predicate_false_when_pid_does_not_exist(tmp_path, monkeypatch):
    pidfile = tmp_path / "training.pid"
    pidfile.write_text("4321")
    monkeypatch.setattr(training_control, "TRAINING_PID_FILE", str(pidfile))
    with patch.object(training_control.psutil, "pid_exists", return_value=False) as pe:
        assert training_control._is_tracked_training_proc(4321) is False
        pe.assert_called_once_with(4321)


def test_predicate_false_when_process_is_zombie(tmp_path, monkeypatch):
    pidfile = tmp_path / "training.pid"
    pidfile.write_text("4321")
    monkeypatch.setattr(training_control, "TRAINING_PID_FILE", str(pidfile))
    zombie = _fake_proc(status=psutil.STATUS_ZOMBIE)
    with patch.object(training_control.psutil, "pid_exists", return_value=True), \
         patch.object(training_control.psutil, "Process", return_value=zombie):
        assert training_control._is_tracked_training_proc(4321) is False


def test_predicate_false_when_cmdline_lacks_marker(tmp_path, monkeypatch):
    """Recycled PID: process exists & alive but is NOT the training process."""
    pidfile = tmp_path / "training.pid"
    pidfile.write_text("4321")
    monkeypatch.setattr(training_control, "TRAINING_PID_FILE", str(pidfile))
    watchloop = _fake_proc(
        cmdline=["python", "-m", "src.main", "startup", "--overnight"],
        environ={},
    )
    with patch.object(training_control.psutil, "pid_exists", return_value=True), \
         patch.object(training_control.psutil, "Process", return_value=watchloop):
        assert training_control._is_tracked_training_proc(4321) is False


def test_predicate_false_on_no_such_process(tmp_path, monkeypatch):
    pidfile = tmp_path / "training.pid"
    pidfile.write_text("4321")
    monkeypatch.setattr(training_control, "TRAINING_PID_FILE", str(pidfile))
    with patch.object(training_control.psutil, "pid_exists", return_value=True), \
         patch.object(training_control.psutil, "Process",
                      side_effect=psutil.NoSuchProcess(4321)):
        assert training_control._is_tracked_training_proc(4321) is False


def test_predicate_false_on_access_denied(tmp_path, monkeypatch):
    pidfile = tmp_path / "training.pid"
    pidfile.write_text("4321")
    monkeypatch.setattr(training_control, "TRAINING_PID_FILE", str(pidfile))
    proc = _fake_proc()
    proc.cmdline.side_effect = psutil.AccessDenied(4321)
    with patch.object(training_control.psutil, "pid_exists", return_value=True), \
         patch.object(training_control.psutil, "Process", return_value=proc):
        assert training_control._is_tracked_training_proc(4321) is False


def test_predicate_true_for_script_path_marker(tmp_path, monkeypatch):
    pidfile = tmp_path / "training.pid"
    pidfile.write_text("4321")
    monkeypatch.setattr(training_control, "TRAINING_PID_FILE", str(pidfile))
    proc = _fake_proc(
        cmdline=["C:\\Python\\python.exe", "training_data/train.py"],
        environ={"CUDA_VISIBLE_DEVICES": "0"},
    )
    with patch.object(training_control.psutil, "pid_exists", return_value=True), \
         patch.object(training_control.psutil, "Process", return_value=proc):
        assert training_control._is_tracked_training_proc(4321) is True


def test_predicate_true_for_module_marker(tmp_path, monkeypatch):
    pidfile = tmp_path / "training.pid"
    pidfile.write_text("4321")
    monkeypatch.setattr(training_control, "TRAINING_PID_FILE", str(pidfile))
    proc = _fake_proc(
        cmdline=["python", "-m", "training", "--curriculum"],
        environ={"CUDA_VISIBLE_DEVICES": "0"},
    )
    with patch.object(training_control.psutil, "pid_exists", return_value=True), \
         patch.object(training_control.psutil, "Process", return_value=proc):
        assert training_control._is_tracked_training_proc(4321) is True


def test_predicate_pid_arg_mismatch_with_pidfile_is_false(tmp_path, monkeypatch):
    """If the queried pid disagrees with the pidfile's recorded pid -> False."""
    pidfile = tmp_path / "training.pid"
    pidfile.write_text("4321")
    monkeypatch.setattr(training_control, "TRAINING_PID_FILE", str(pidfile))
    proc = _fake_proc(cmdline=["python", "training_data/train.py"])
    with patch.object(training_control.psutil, "pid_exists", return_value=True), \
         patch.object(training_control.psutil, "Process", return_value=proc):
        assert training_control._is_tracked_training_proc(9999) is False


# ── stop_training_bounded — no-op safety ───────────────────────────────────


def test_stop_bounded_missing_pidfile_terminates_nothing(tmp_path, monkeypatch):
    """(a) Missing pidfile -> set/clear stop, terminate NOTHING."""
    monkeypatch.setattr(training_control, "TRAINING_PID_FILE",
                        str(tmp_path / "training.pid"))
    with patch.object(training_control, "set_stop") as set_stop, \
         patch.object(training_control, "clear_stop") as clear_stop, \
         patch.object(training_control.psutil, "Process") as proc_cls:
        training_control.stop_training_bounded(timeout_s=5)
        proc_cls.assert_not_called()
        set_stop.assert_called_once()
        clear_stop.assert_called_once()


def test_stop_bounded_dead_pid_noop_and_clears_stale_pidfile(tmp_path, monkeypatch):
    """(b) Dead PID -> no-op + stale pidfile cleared."""
    pidfile = tmp_path / "training.pid"
    pidfile.write_text("4321")
    monkeypatch.setattr(training_control, "TRAINING_PID_FILE", str(pidfile))
    with patch.object(training_control, "set_stop"), \
         patch.object(training_control, "clear_stop"), \
         patch.object(training_control.psutil, "pid_exists", return_value=False), \
         patch.object(training_control.psutil, "Process") as proc_cls:
        training_control.stop_training_bounded(timeout_s=5)
        proc_cls.assert_not_called()
    assert not pidfile.exists(), "stale pidfile should be cleared"


def test_stop_bounded_recycled_pid_terminates_nothing(tmp_path, monkeypatch):
    """(c) PID recycled to a NON-training process (watch loop / arbitrary).

    The predicate must return False and stop_training_bounded must terminate
    NOTHING — assert terminate AND kill are NEVER called.
    """
    pidfile = tmp_path / "training.pid"
    pidfile.write_text("4321")
    monkeypatch.setattr(training_control, "TRAINING_PID_FILE", str(pidfile))
    recycled = _fake_proc(
        cmdline=["python", "-m", "src.main", "startup"],  # watch loop, not training
        environ={},
    )
    with patch.object(training_control, "set_stop"), \
         patch.object(training_control, "clear_stop"), \
         patch.object(training_control.psutil, "pid_exists", return_value=True), \
         patch.object(training_control.psutil, "Process", return_value=recycled):
        training_control.stop_training_bounded(timeout_s=5)
    recycled.terminate.assert_not_called()
    recycled.kill.assert_not_called()


def test_stop_bounded_valid_pid_terminates_tracked_only(tmp_path, monkeypatch):
    """(d) Valid tracked PID that ignores the cooperative window -> hard
    terminate the TRACKED pid ONLY."""
    pidfile = tmp_path / "training.pid"
    pidfile.write_text("4321")
    monkeypatch.setattr(training_control, "TRAINING_PID_FILE", str(pidfile))
    # Stays alive through the cooperative poll so the hard-terminate path runs.
    proc = _fake_proc(
        pid=4321,
        cmdline=["python", "training_data/train.py"],
        environ={"CUDA_VISIBLE_DEVICES": "0"},
        alive_after=[True, True, True, True, True, True],
    )
    with patch.object(training_control, "set_stop") as set_stop, \
         patch.object(training_control, "clear_stop") as clear_stop, \
         patch.object(training_control.psutil, "pid_exists", return_value=True), \
         patch.object(training_control.psutil, "Process", return_value=proc), \
         patch.object(training_control.psutil, "wait_procs", return_value=([], [proc])), \
         patch.object(training_control.time, "sleep"), \
         patch.object(training_control.time, "monotonic", side_effect=[0.0, 0.1, 6.0, 6.0, 6.0]):
        training_control.stop_training_bounded(timeout_s=5)
    set_stop.assert_called_once()
    proc.terminate.assert_called_once()  # terminated the tracked proc
    clear_stop.assert_called_once()


def test_stop_bounded_valid_pid_cooperative_exit_no_hard_kill(tmp_path, monkeypatch):
    """Valid tracked PID that exits cooperatively within the window -> NO
    hard terminate/kill."""
    pidfile = tmp_path / "training.pid"
    pidfile.write_text("4321")
    monkeypatch.setattr(training_control, "TRAINING_PID_FILE", str(pidfile))
    # is_running flips to False on the second poll (cooperative exit).
    proc = _fake_proc(
        pid=4321,
        cmdline=["python", "training_data/train.py"],
        environ={"CUDA_VISIBLE_DEVICES": "0"},
        alive_after=[True, False, False],
    )
    with patch.object(training_control, "set_stop"), \
         patch.object(training_control, "clear_stop") as clear_stop, \
         patch.object(training_control.psutil, "pid_exists", return_value=True), \
         patch.object(training_control.psutil, "Process", return_value=proc), \
         patch.object(training_control.time, "sleep"), \
         patch.object(training_control.time, "monotonic", side_effect=[0.0, 0.1, 0.2, 0.3]):
        training_control.stop_training_bounded(timeout_s=30)
    proc.terminate.assert_not_called()
    proc.kill.assert_not_called()
    clear_stop.assert_called_once()
