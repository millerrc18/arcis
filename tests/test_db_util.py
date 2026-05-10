"""Tests for src/utils/db.py — SQLite connection helper.

Covers: #160 (busy_timeout on all connections).
"""

import sqlite3
from unittest.mock import MagicMock, patch

import pytest


def test_connect_db_uses_sqlite_when_database_url_unset(monkeypatch):
    """connect_db with no args and no DATABASE_URL should return a sqlite3.Connection."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    from src.utils.db import connect_db
    conn = connect_db()
    assert type(conn) is sqlite3.Connection
    conn.close()


def test_connect_db_uses_postgres_when_database_url_postgres_scheme(monkeypatch):
    """connect_db with DATABASE_URL=postgresql://... should call psycopg2.connect and return a wrapper."""
    import psycopg2.extras
    pg_url = "postgresql://halcyon:pw@localhost:5433/halcyon"
    monkeypatch.setenv("DATABASE_URL", pg_url)
    sentinel_conn = MagicMock(name="pg_raw_conn")
    with patch("psycopg2.connect", return_value=sentinel_conn) as mock_pg:
        from src.utils.db import connect_db
        wrapper = connect_db()
        mock_pg.assert_called_once_with(pg_url, cursor_factory=psycopg2.extras.RealDictCursor)
    assert hasattr(wrapper, "cursor")
    assert hasattr(wrapper, "execute")
    assert hasattr(wrapper, "executemany")
    assert hasattr(wrapper, "commit")
    assert hasattr(wrapper, "rollback")
    assert hasattr(wrapper, "close")
    assert hasattr(wrapper, "row_factory")


def test_connect_db_explicit_db_path_forces_sqlite(tmp_path, monkeypatch):
    """connect_db with an explicit db_path should always use SQLite, even when DATABASE_URL is postgres."""
    monkeypatch.setenv("DATABASE_URL", "postgresql://halcyon:pw@localhost:5433/halcyon")
    db_path = str(tmp_path / "test.sqlite3")
    from src.utils.db import connect_db
    conn = connect_db(db_path=db_path)
    assert type(conn) is sqlite3.Connection
    conn.close()


def test_pg_wrapper_exposes_required_methods(monkeypatch):
    """The PG wrapper class must expose cursor, execute, executemany, commit, rollback, close, row_factory."""
    pg_url = "postgresql://halcyon:pw@localhost:5433/halcyon"
    monkeypatch.setenv("DATABASE_URL", pg_url)
    sentinel_conn = MagicMock(name="pg_raw_conn")
    with patch("psycopg2.connect", return_value=sentinel_conn):
        from src.utils.db import connect_db
        wrapper = connect_db()
    for method in ("cursor", "execute", "executemany", "commit", "rollback", "close"):
        assert callable(getattr(wrapper, method)), f"wrapper.{method} must be callable"
    assert hasattr(wrapper, "row_factory")


def test_connect_db_sets_busy_timeout(tmp_path):
    """connect_db should set PRAGMA busy_timeout=30000 (30s).

    Bumped from 5000 after 2026-04-19 incident: MS Access held the DB file
    lock while the operator inspected data, causing 118 'database is locked'
    errors. 30s rides through typical external-tool locks.
    """
    db_path = str(tmp_path / "test.sqlite3")
    from src.utils.db import BUSY_TIMEOUT_MS, connect_db
    conn = connect_db(db_path)
    result = conn.execute("PRAGMA busy_timeout").fetchone()
    assert result[0] == 30000
    assert BUSY_TIMEOUT_MS == 30000
    conn.close()


def test_connect_db_sets_row_factory(tmp_path):
    """connect_db should set row_factory to sqlite3.Row."""
    db_path = str(tmp_path / "test.sqlite3")
    from src.utils.db import connect_db
    conn = connect_db(db_path)
    assert conn.row_factory is sqlite3.Row
    conn.close()


def test_connect_db_default_path():
    """connect_db with no args should use default DB path."""
    from src.utils.db import connect_db, DEFAULT_DB
    conn = connect_db()
    assert conn is not None
    conn.close()
