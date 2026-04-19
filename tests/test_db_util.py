"""Tests for src/utils/db.py — SQLite connection helper.

Covers: #160 (busy_timeout on all connections).
"""

import sqlite3

import pytest


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
