"""Tests for StopOnFlagCallback (src/training/stop_callback.py).

The callback cooperatively stops a HuggingFace/TRL training run when the
STOP_OVERNIGHT flag is present. Drives a fake `control` object through
on_step_end / on_epoch_end with the flag set / unset.
"""

from src.training.stop_callback import StopOnFlagCallback


class _FakeControl:
    def __init__(self):
        self.should_training_stop = False


def test_on_step_end_sets_stop_when_flag_present(tmp_path):
    flag = tmp_path / "STOP_OVERNIGHT"
    flag.write_text("x", encoding="utf-8")
    cb = StopOnFlagCallback(flag_path=str(flag))
    control = _FakeControl()
    returned = cb.on_step_end(args=None, state=None, control=control)
    assert control.should_training_stop is True
    assert returned is control


def test_on_step_end_no_op_when_flag_absent(tmp_path):
    flag = tmp_path / "STOP_OVERNIGHT"
    cb = StopOnFlagCallback(flag_path=str(flag))
    control = _FakeControl()
    cb.on_step_end(args=None, state=None, control=control)
    assert control.should_training_stop is False


def test_on_epoch_end_sets_stop_when_flag_present(tmp_path):
    flag = tmp_path / "STOP_OVERNIGHT"
    flag.write_text("x", encoding="utf-8")
    cb = StopOnFlagCallback(flag_path=str(flag))
    control = _FakeControl()
    cb.on_epoch_end(args=None, state=None, control=control)
    assert control.should_training_stop is True


def test_on_epoch_end_no_op_when_flag_absent(tmp_path):
    flag = tmp_path / "STOP_OVERNIGHT"
    cb = StopOnFlagCallback(flag_path=str(flag))
    control = _FakeControl()
    cb.on_epoch_end(args=None, state=None, control=control)
    assert control.should_training_stop is False


def test_env_override_drives_stop(tmp_path, monkeypatch):
    # No flag_path passed -> resolves via is_stop_requested's own logic,
    # which checks ARCIS_STOP_FLAG first.
    env_flag = tmp_path / "STOP_OVERNIGHT"
    env_flag.write_text("x", encoding="utf-8")
    monkeypatch.setenv("ARCIS_STOP_FLAG", str(env_flag))
    cb = StopOnFlagCallback()
    control = _FakeControl()
    cb.on_step_end(args=None, state=None, control=control)
    assert control.should_training_stop is True
