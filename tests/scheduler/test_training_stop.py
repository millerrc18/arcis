"""Tests for the cooperative training-stop signal (src/scheduler/training_stop.py).

Behavioral coverage for the dual-GPU separation stop mechanism (T1):
- STOP_FLAG is an ABSOLUTE path (no relative-cwd landmine under LocalSystem).
- request_training_stop() touches the flag (mkdir parent if missing).
- clear_training_stop() removes idempotently (missing_ok).
- is_stop_requested() honors ARCIS_STOP_FLAG env override, then an explicit
  flag_path arg, then the absolute STOP_FLAG default.
- A relative cwd does NOT change STOP_FLAG resolution.
"""

import os

from src.scheduler import training_stop


def test_stop_flag_is_absolute():
    assert os.path.isabs(training_stop.STOP_FLAG)


def test_stop_flag_basename_is_stop_overnight():
    assert os.path.basename(training_stop.STOP_FLAG) == "STOP_OVERNIGHT"


def test_request_then_is_stop_requested(tmp_path):
    flag = tmp_path / "subdir" / "STOP_OVERNIGHT"
    # parent subdir does not exist yet — request must mkdir it.
    assert not flag.parent.exists()
    training_stop.request_training_stop(str(flag))
    assert flag.exists()
    assert training_stop.is_stop_requested(str(flag)) is True


def test_clear_is_idempotent(tmp_path):
    flag = tmp_path / "STOP_OVERNIGHT"
    flag.write_text("x", encoding="utf-8")
    assert flag.exists()
    training_stop.clear_training_stop(str(flag))
    assert not flag.exists()
    # second call must not raise (missing_ok)
    training_stop.clear_training_stop(str(flag))
    assert not flag.exists()


def test_is_stop_requested_false_when_absent(tmp_path):
    flag = tmp_path / "STOP_OVERNIGHT"
    assert training_stop.is_stop_requested(str(flag)) is False


def test_env_override_takes_precedence(tmp_path, monkeypatch):
    env_flag = tmp_path / "env" / "STOP_OVERNIGHT"
    arg_flag = tmp_path / "arg" / "STOP_OVERNIGHT"
    env_flag.parent.mkdir(parents=True)
    env_flag.write_text("x", encoding="utf-8")
    # arg flag intentionally does not exist
    monkeypatch.setenv("ARCIS_STOP_FLAG", str(env_flag))
    # env flag exists -> True even though the passed arg_flag is absent
    assert training_stop.is_stop_requested(str(arg_flag)) is True


def test_default_flag_used_when_no_arg_no_env(tmp_path, monkeypatch):
    monkeypatch.delenv("ARCIS_STOP_FLAG", raising=False)
    # Point the module default at a temp flag we control.
    flag = tmp_path / "STOP_OVERNIGHT"
    monkeypatch.setattr(training_stop, "STOP_FLAG", str(flag))
    assert training_stop.is_stop_requested() is False
    flag.write_text("x", encoding="utf-8")
    assert training_stop.is_stop_requested() is True


def test_relative_cwd_does_not_change_resolution(tmp_path, monkeypatch):
    # Resolution must not depend on cwd — changing into a temp dir leaves
    # the absolute STOP_FLAG unchanged.
    before = training_stop.STOP_FLAG
    monkeypatch.chdir(tmp_path)
    assert training_stop.STOP_FLAG == before
    assert os.path.isabs(training_stop.STOP_FLAG)
