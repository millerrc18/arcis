"""Unit tests for table_freshness_health (collector SYSTEM health proxy).

Verifies the four status transitions against a tmp SQLite, and that an
unconstructable/missing DB degrades to ``down`` WITHOUT raising (bare-env
tolerance). The helper lazy-imports ``src.config.DB_PATH`` and
``src.utils.db.connect_db`` inside the function, so we monkeypatch those
module attributes.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from src.data_collection._capability_health import table_freshness_health


def _make_db(tmp_path, rows=None):
    db_path = tmp_path / "freshness.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("CREATE TABLE widget (collected_at TEXT)")
    for ts in rows or []:
        conn.execute("INSERT INTO widget (collected_at) VALUES (?)", (ts,))
    conn.commit()
    conn.close()
    return db_path


@pytest.fixture
def point_at_sqlite(tmp_path, monkeypatch):
    """Return a callable that points the helper at a tmp SQLite db_path."""

    def _install(db_path):
        import src.config
        import src.utils.db as dbmod

        monkeypatch.setattr(src.config, "DB_PATH", str(db_path), raising=False)

        real_connect = dbmod.connect_db

        def _connect(_db_path=None, **kwargs):
            return real_connect(str(db_path), force_sqlite=True)

        monkeypatch.setattr(dbmod, "connect_db", _connect)

    return _install


def test_empty_table_is_degraded(tmp_path, point_at_sqlite):
    db_path = _make_db(tmp_path, rows=[])
    point_at_sqlite(db_path)
    result = table_freshness_health("widget", "collected_at", 1500, "daily")
    assert result["status"] == "degraded"
    assert "empty" in result["detail"]


def test_one_fresh_row_is_ok(tmp_path, point_at_sqlite):
    now_iso = datetime.now(timezone.utc).isoformat()
    db_path = _make_db(tmp_path, rows=[now_iso])
    point_at_sqlite(db_path)
    result = table_freshness_health("widget", "collected_at", 1500, "daily")
    assert result["status"] == "ok"
    assert result["last_updated_at"] == now_iso


def test_stale_row_is_degraded(tmp_path, point_at_sqlite):
    old_iso = (datetime.now(timezone.utc) - timedelta(minutes=3000)).isoformat()
    db_path = _make_db(tmp_path, rows=[old_iso])
    point_at_sqlite(db_path)
    result = table_freshness_health("widget", "collected_at", 1500, "daily")
    assert result["status"] == "degraded"
    assert "stale" in result["detail"]
    assert result["last_updated_at"] == old_iso


def test_missing_table_is_down(tmp_path, point_at_sqlite):
    db_path = _make_db(tmp_path, rows=[])
    point_at_sqlite(db_path)
    result = table_freshness_health("does_not_exist", "collected_at", 1500, "daily")
    assert result["status"] == "down"


def test_bad_db_path_is_down_without_raising(monkeypatch):
    """A fully-unconstructable DB connection degrades to down, never raises."""

    def _boom(*args, **kwargs):
        raise OSError("no database configured")

    # Patch the lazily-imported connect_db at its source module.
    import src.utils.db as dbmod
    monkeypatch.setattr(dbmod, "connect_db", _boom)

    result = table_freshness_health("widget", "collected_at", 1500, "daily")
    assert result["status"] == "down"
    assert "db unavailable" in result["detail"]
