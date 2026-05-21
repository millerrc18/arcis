"""Tests for the dual-GPU pin + cooperative-stop wiring in trainer.py (T2).

Covers:
  - _training_subprocess_env() pins CUDA_VISIBLE_DEVICES=0, PCI_BUS_ID ordering,
    sets an absolute ARCIS_STOP_FLAG, and preserves PYTHONUTF8 + inherited env.
  - The generated CURRICULUM_TRAIN_SCRIPT bakes an absolute stop-flag literal
    (never a bare relative "data/STOP_OVERNIGHT"), embeds a StopOnFlagCallback
    that mirrors stop_callback semantics, wires it via callbacks=[...], polls
    the flag in non-step phases, and pins the model to GPU0 (device_map).
  - The pidfile helper writes/cleans an absolute logs/training.pid.
"""

import os

import pytest

from src.scheduler.training_stop import STOP_FLAG
from src.training import trainer as trainer_mod


def test_subprocess_env_pins_gpu0_and_stop_flag():
    env = trainer_mod._training_subprocess_env()
    assert env["CUDA_VISIBLE_DEVICES"] == "0"
    assert env["CUDA_DEVICE_ORDER"] == "PCI_BUS_ID"
    # ARCIS_STOP_FLAG must be the absolute STOP_FLAG, not a bare relative path.
    assert env["ARCIS_STOP_FLAG"] == STOP_FLAG
    assert os.path.isabs(env["ARCIS_STOP_FLAG"])


def test_subprocess_env_preserves_utf8_and_inherited():
    os.environ["ARCIS_GPU_PIN_PROBE"] = "sentinel"
    try:
        env = trainer_mod._training_subprocess_env()
    finally:
        os.environ.pop("ARCIS_GPU_PIN_PROBE", None)
    assert env["PYTHONUTF8"] == "1"
    assert env["PYTHONIOENCODING"] == "utf-8"
    # Inherited os.environ keys survive the copy.
    assert env["ARCIS_GPU_PIN_PROBE"] == "sentinel"


def test_curriculum_script_bakes_absolute_stop_flag():
    script = trainer_mod._build_curriculum_train_script()
    # The resolved absolute flag literal must be present.
    assert STOP_FLAG in script
    # And never the relative landmine.
    assert '"data/STOP_OVERNIGHT"' not in script
    assert "'data/STOP_OVERNIGHT'" not in script
    # Also honors the env override.
    assert "ARCIS_STOP_FLAG" in script


def test_curriculum_script_has_stop_callback_wired():
    script = trainer_mod._build_curriculum_train_script()
    assert "class StopOnFlagCallback" in script
    assert "should_training_stop" in script
    assert "callbacks=[" in script


def test_curriculum_script_polls_non_step_phases():
    script = trainer_mod._build_curriculum_train_script()
    # A cooperative poll helper that exits cleanly when the flag is set.
    assert "sys.exit(0)" in script
    # Pinning the model to GPU0 defensively.
    assert 'device_map={"": 0}' in script
    assert 'device_map="auto"' not in script


def test_pidfile_path_is_absolute_under_logs():
    path = trainer_mod._training_pidfile_path()
    assert os.path.isabs(path)
    assert path.replace("\\", "/").endswith("logs/training.pid")


def test_pidfile_write_and_clear(tmp_path, monkeypatch):
    pidfile = tmp_path / "training.pid"
    monkeypatch.setattr(trainer_mod, "_training_pidfile_path", lambda: str(pidfile))
    trainer_mod._write_training_pidfile(4242)
    assert pidfile.read_text(encoding="utf-8").strip() == "4242"
    trainer_mod._clear_training_pidfile()
    assert not pidfile.exists()
    # Idempotent clear.
    trainer_mod._clear_training_pidfile()
