"""Tests for src.commands.maintenance.expire_stale_commands.

Called by: pytest (Sprint 5 §J5/§J6 Phase 3-revised)
Calls: src.commands.maintenance, src.utils.db
Owns tables: pending_commands (test fixture creates + tears down)
Config keys: none (uses tmp SQLite path)
Tests: 4 round-trip + edge-case scenarios for the relocated function.

Replaces the 3 test_expire_stale_commands_* tests + the
test_run_sync_cycle_calls_expire_stale_commands test that lived in
tests/test_command_queue_reliability.py before SP5 §J5/§J6 Phase 3-revised.
The function moved from src/sync/render_sync.py (deleted) to
src/commands/maintenance.py and now uses connect_db() (engine-aware) instead
of direct psycopg2 calls. The run_sync_cycle function was deleted entirely
(render_sync.py is gone) so its test has no replacement target.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from src.commands.maintenance import expire_stale_commands


ET = ZoneInfo("America/New_York")


def _create_pending_commands_schema(conn: sqlite3.Connection) -> None:
    """Create a minimal pending_commands table for tests."""
    conn.execute(
        """
        CREATE TABLE pending_commands (
            command_id TEXT PRIMARY KEY,
            command_type TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TEXT NOT NULL,
            expires_at TEXT,
            payload TEXT
        )
        """
    )
    conn.commit()


def _insert_row(conn, command_id, status, expires_at):
    conn.execute(
        "INSERT INTO pending_commands (command_id, command_type, status, "
        "created_at, expires_at, payload) VALUES (?, 'test', ?, ?, ?, '{}')",
        (command_id, status, datetime.now(ET).isoformat(), expires_at),
    )
    conn.commit()


def test_expire_stale_commands_updates_rows_past_expiry(tmp_path, monkeypatch):
    """Rows where status='pending' AND expires_at < now should flip to 'expired'."""
    db_path = str(tmp_path / "test.sqlite3")
    # Force the SQLite path — gate stays off so connect_db() returns sqlite3.
    monkeypatch.delenv("ARCIS_PG_CUTOVER_ENABLED", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(
        "src.commands.maintenance.connect_db",
        lambda: sqlite3.connect(db_path, timeout=30.0),
    )

    conn = sqlite3.connect(db_path)
    _create_pending_commands_schema(conn)
    yesterday = (datetime.now(ET) - timedelta(days=1)).isoformat()
    tomorrow = (datetime.now(ET) + timedelta(days=1)).isoformat()
    _insert_row(conn, "stale-1", "pending", yesterday)
    _insert_row(conn, "stale-2", "pending", yesterday)
    _insert_row(conn, "fresh-1", "pending", tomorrow)
    _insert_row(conn, "done-1", "completed", yesterday)
    conn.close()

    count = expire_stale_commands()

    assert count == 2, f"expected 2 expired (stale-1, stale-2), got {count}"

    conn = sqlite3.connect(db_path)
    statuses = dict(conn.execute(
        "SELECT command_id, status FROM pending_commands ORDER BY command_id"
    ).fetchall())
    conn.close()
    assert statuses["stale-1"] == "expired"
    assert statuses["stale-2"] == "expired"
    assert statuses["fresh-1"] == "pending", "future-expiry should not flip"
    assert statuses["done-1"] == "completed", "already-completed should not flip"


def test_expire_stale_commands_returns_zero_when_no_stale_rows(tmp_path, monkeypatch):
    """If nothing matches the predicate, return 0 — no exception."""
    db_path = str(tmp_path / "test.sqlite3")
    monkeypatch.delenv("ARCIS_PG_CUTOVER_ENABLED", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(
        "src.commands.maintenance.connect_db",
        lambda: sqlite3.connect(db_path, timeout=30.0),
    )

    conn = sqlite3.connect(db_path)
    _create_pending_commands_schema(conn)
    tomorrow = (datetime.now(ET) + timedelta(days=1)).isoformat()
    _insert_row(conn, "fresh-1", "pending", tomorrow)
    conn.close()

    count = expire_stale_commands()

    assert count == 0


def test_expire_stale_commands_returns_zero_on_db_error(monkeypatch):
    """Connection failure logs error + returns 0 — never raises."""
    def _raise(*args, **kwargs):
        raise OSError("simulated DB unreachable")

    monkeypatch.setattr("src.commands.maintenance.connect_db", _raise)

    count = expire_stale_commands()
    assert count == 0


def test_expire_stale_commands_ignores_database_url_arg(tmp_path, monkeypatch):
    """The database_url arg is kept for API back-compat but ignored.

    The relocated function uses connect_db() (engine-aware) instead of
    direct psycopg2.connect(database_url). The argument is preserved in the
    signature so existing cloud_routes endpoint callers don't break, but
    the value is not consulted internally.
    """
    db_path = str(tmp_path / "test.sqlite3")
    monkeypatch.delenv("ARCIS_PG_CUTOVER_ENABLED", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(
        "src.commands.maintenance.connect_db",
        lambda: sqlite3.connect(db_path, timeout=30.0),
    )

    conn = sqlite3.connect(db_path)
    _create_pending_commands_schema(conn)
    yesterday = (datetime.now(ET) - timedelta(days=1)).isoformat()
    _insert_row(conn, "stale-1", "pending", yesterday)
    conn.close()

    count_no_arg = expire_stale_commands()
    # Reset for second call
    conn = sqlite3.connect(db_path)
    conn.execute("UPDATE pending_commands SET status='pending' WHERE command_id='stale-1'")
    conn.commit()
    conn.close()

    count_with_arg = expire_stale_commands(database_url="postgresql://ignored")

    assert count_no_arg == count_with_arg == 1, (
        "function behavior must be identical with or without database_url arg"
    )
