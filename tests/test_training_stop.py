"""Tests for src/training/training_stop.py — TDD: written BEFORE implementation."""

import importlib
import os

import pytest


def _reload_with_db(monkeypatch, fake_db_path):
    """Helper: patch src.config.DB_PATH and reload training_stop."""
    import src.config as cfg
    monkeypatch.setattr(cfg, "DB_PATH", fake_db_path)
    import src.training.training_stop as ts
    importlib.reload(ts)
    return ts


def test_stop_flag_is_absolute(tmp_path, monkeypatch):
    """STOP_FLAG must be an absolute path regardless of cwd."""
    fake_db = str(tmp_path / "subdir" / "test.sqlite3")
    ts = _reload_with_db(monkeypatch, fake_db)
    assert os.path.isabs(ts.STOP_FLAG)


def test_stop_flag_anchored_at_dirname_db_path(tmp_path, monkeypatch):
    """STOP_FLAG must live in dirname(DB_PATH), not relative to cwd."""
    subdir = tmp_path / "dbdir"
    subdir.mkdir()
    fake_db = str(subdir / "test.sqlite3")
    ts = _reload_with_db(monkeypatch, fake_db)
    assert os.path.dirname(ts.STOP_FLAG) == str(subdir)


def test_stop_flag_filename(tmp_path, monkeypatch):
    """STOP_FLAG filename must be 'STOP_OVERNIGHT'."""
    subdir = tmp_path / "dbdir"
    subdir.mkdir()
    fake_db = str(subdir / "test.sqlite3")
    ts = _reload_with_db(monkeypatch, fake_db)
    assert os.path.basename(ts.STOP_FLAG) == "STOP_OVERNIGHT"


def test_set_stop_creates_flag(tmp_path, monkeypatch):
    """set_stop() must create the flag file."""
    subdir = tmp_path / "dbdir"
    subdir.mkdir()
    fake_db = str(subdir / "test.sqlite3")
    ts = _reload_with_db(monkeypatch, fake_db)
    assert not os.path.exists(ts.STOP_FLAG)
    ts.set_stop()
    assert os.path.exists(ts.STOP_FLAG)


def test_is_stop_requested_true_after_set(tmp_path, monkeypatch):
    """is_stop_requested() returns True after set_stop()."""
    subdir = tmp_path / "dbdir"
    subdir.mkdir()
    fake_db = str(subdir / "test.sqlite3")
    ts = _reload_with_db(monkeypatch, fake_db)
    ts.set_stop()
    assert ts.is_stop_requested() is True


def test_clear_stop_removes_flag(tmp_path, monkeypatch):
    """clear_stop() removes the flag; is_stop_requested() returns False."""
    subdir = tmp_path / "dbdir"
    subdir.mkdir()
    fake_db = str(subdir / "test.sqlite3")
    ts = _reload_with_db(monkeypatch, fake_db)
    ts.set_stop()
    assert ts.is_stop_requested() is True
    ts.clear_stop()
    assert ts.is_stop_requested() is False


def test_clear_stop_missing_flag_is_noop(tmp_path, monkeypatch):
    """clear_stop() on a non-existent flag must not raise."""
    subdir = tmp_path / "dbdir"
    subdir.mkdir()
    fake_db = str(subdir / "test.sqlite3")
    ts = _reload_with_db(monkeypatch, fake_db)
    assert not os.path.exists(ts.STOP_FLAG)
    ts.clear_stop()  # must not raise


def test_is_stop_requested_false_initially(tmp_path, monkeypatch):
    """is_stop_requested() returns False when flag is absent."""
    subdir = tmp_path / "dbdir"
    subdir.mkdir()
    fake_db = str(subdir / "test.sqlite3")
    ts = _reload_with_db(monkeypatch, fake_db)
    assert ts.is_stop_requested() is False
