"""Tests for src/training/training_stop.py — order-independent, no importlib.reload."""

import os

import pytest

import src.config as cfg
import src.training.training_stop as ts


# ---------------------------------------------------------------------------
# Path-derivation tests — assert invariants on the real already-imported module
# No monkeypatching, no reload: fully order-independent.
# ---------------------------------------------------------------------------


def test_stop_flag_is_absolute():
    """STOP_FLAG must be an absolute path regardless of cwd."""
    assert os.path.isabs(ts.STOP_FLAG)


def test_stop_flag_anchored_at_dirname_db_path():
    """STOP_FLAG must live in dirname(DB_PATH)."""
    assert os.path.dirname(ts.STOP_FLAG) == os.path.dirname(cfg.DB_PATH)


def test_stop_flag_filename():
    """STOP_FLAG filename must be 'STOP_OVERNIGHT'."""
    assert os.path.basename(ts.STOP_FLAG) == "STOP_OVERNIGHT"


# ---------------------------------------------------------------------------
# Behavior tests — redirect flag to tmp_path via module-attr patch (no reload).
# Functions reference module-level STOP_FLAG, so patching the attribute
# redirects them; the real STOP_OVERNIGHT file is never touched.
# ---------------------------------------------------------------------------


def test_set_stop_creates_flag(tmp_path, monkeypatch):
    """set_stop() must create the flag file."""
    monkeypatch.setattr(ts, "STOP_FLAG", str(tmp_path / "STOP_OVERNIGHT"))
    assert not os.path.exists(ts.STOP_FLAG)
    ts.set_stop()
    assert os.path.exists(ts.STOP_FLAG)


def test_is_stop_requested_true_after_set(tmp_path, monkeypatch):
    """is_stop_requested() returns True after set_stop()."""
    monkeypatch.setattr(ts, "STOP_FLAG", str(tmp_path / "STOP_OVERNIGHT"))
    ts.set_stop()
    assert ts.is_stop_requested() is True


def test_clear_stop_removes_flag(tmp_path, monkeypatch):
    """clear_stop() removes the flag; is_stop_requested() returns False."""
    monkeypatch.setattr(ts, "STOP_FLAG", str(tmp_path / "STOP_OVERNIGHT"))
    ts.set_stop()
    assert ts.is_stop_requested() is True
    ts.clear_stop()
    assert ts.is_stop_requested() is False


def test_clear_stop_missing_flag_is_noop(tmp_path, monkeypatch):
    """clear_stop() on a non-existent flag must not raise."""
    monkeypatch.setattr(ts, "STOP_FLAG", str(tmp_path / "STOP_OVERNIGHT"))
    assert not os.path.exists(ts.STOP_FLAG)
    ts.clear_stop()  # must not raise


def test_is_stop_requested_false_initially(tmp_path, monkeypatch):
    """is_stop_requested() returns False when flag is absent."""
    monkeypatch.setattr(ts, "STOP_FLAG", str(tmp_path / "STOP_OVERNIGHT"))
    assert ts.is_stop_requested() is False
