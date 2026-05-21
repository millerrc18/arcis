"""Tests for stop_training_bounded (src/scheduler/training_control.py).

The bounded-escalation stop is the critical fix for the dual-GPU separation:
request cooperative stop -> wait up to timeout for clean self-exit -> if still
alive, HARD-TERMINATE THE TRACKED TRAINING PID ONLY (terminate -> kill, or
PID-escalation from logs/training.pid when the handle is lost).

ABSOLUTE INVARIANT under test: NEVER an `/im` name-kill, NEVER Ollama, NEVER a
kill by process name. Only the specific tracked training PID.
"""

from src.scheduler import training_control


class _FakeProc:
    """Popen-like fake. Exits (poll() != None) after `exit_after` poll calls."""

    def __init__(self, exit_after=None):
        self.pid = 4242
        self._exit_after = exit_after
        self._polls = 0
        self.terminate_called = False
        self.kill_called = False
        self._returncode = None

    def poll(self):
        self._polls += 1
        if self._exit_after is not None and self._polls >= self._exit_after:
            self._returncode = 0
        return self._returncode

    def terminate(self):
        self.terminate_called = True

    def kill(self):
        self.kill_called = True
        self._returncode = -9

    def wait(self, timeout=None):
        self._returncode = self._returncode if self._returncode is not None else 0
        return self._returncode


def test_cooperative_exit(tmp_path, monkeypatch):
    # Redirect the stop flag to a temp path so we don't touch the real one.
    flag = tmp_path / "STOP_OVERNIGHT"
    monkeypatch.setattr(training_control, "STOP_FLAG", str(flag))
    proc = _FakeProc(exit_after=2)
    result = training_control.stop_training_bounded(proc, timeout=5)
    assert result["stopped_via"] == "cooperative"
    assert proc.terminate_called is False
    assert proc.kill_called is False
    # flag cleared at the end
    assert not flag.exists()


def test_already_exited(tmp_path, monkeypatch):
    flag = tmp_path / "STOP_OVERNIGHT"
    monkeypatch.setattr(training_control, "STOP_FLAG", str(flag))
    proc = _FakeProc(exit_after=1)  # poll() returns done on first call
    result = training_control.stop_training_bounded(proc, timeout=5)
    assert result["stopped_via"] in ("already_exited", "cooperative")
    assert proc.terminate_called is False


def test_hard_terminate_when_flag_ignored(tmp_path, monkeypatch):
    flag = tmp_path / "STOP_OVERNIGHT"
    monkeypatch.setattr(training_control, "STOP_FLAG", str(flag))
    proc = _FakeProc(exit_after=None)  # never exits cooperatively
    result = training_control.stop_training_bounded(proc, timeout=0)
    assert result["stopped_via"] == "hard_terminate"
    assert proc.terminate_called is True
    assert proc.kill_called is True
    assert not flag.exists()


def test_no_ollama_or_name_kill_ever(tmp_path, monkeypatch):
    """Spy on subprocess.run/Popen — assert no call references '/im' or 'ollama'."""
    flag = tmp_path / "STOP_OVERNIGHT"
    monkeypatch.setattr(training_control, "STOP_FLAG", str(flag))

    captured_calls = []

    def _spy_run(args, *a, **k):
        captured_calls.append(args)

        class _R:
            returncode = 0

        return _R()

    def _spy_popen(args, *a, **k):
        captured_calls.append(args)

        class _P:
            pass

        return _P()

    monkeypatch.setattr(training_control.subprocess, "run", _spy_run)
    monkeypatch.setattr(training_control.subprocess, "Popen", _spy_popen, raising=False)

    proc = _FakeProc(exit_after=None)
    training_control.stop_training_bounded(proc, timeout=0)

    flat = " ".join(str(c).lower() for c in captured_calls)
    assert "/im" not in flat
    assert "ollama" not in flat


def test_lost_handle_pid_escalation(tmp_path, monkeypatch):
    """proc=None + logs/training.pid -> PID-escalation against THAT pid only."""
    flag = tmp_path / "STOP_OVERNIGHT"
    monkeypatch.setattr(training_control, "STOP_FLAG", str(flag))

    pidfile = tmp_path / "training.pid"
    pidfile.write_text("31337", encoding="utf-8")
    monkeypatch.setattr(training_control, "TRAINING_PID_FILE", str(pidfile))

    captured_calls = []

    def _spy_run(args, *a, **k):
        captured_calls.append(args)

        class _R:
            returncode = 0

        return _R()

    monkeypatch.setattr(training_control.subprocess, "run", _spy_run)

    result = training_control.stop_training_bounded(None, timeout=0)
    assert result["stopped_via"] == "hard_terminate"

    flat = " ".join(str(c).lower() for c in captured_calls)
    # The tracked PID must appear; no name-kill.
    assert "31337" in flat
    assert "/im" not in flat
    assert "ollama" not in flat
    assert not flag.exists()


def test_morning_stop_timeout_constant():
    assert training_control.MORNING_STOP_TIMEOUT == 300
