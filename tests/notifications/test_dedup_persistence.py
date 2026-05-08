"""T15a — dedup persistence tests.

Validates that _DEDUP_CACHE has been migrated to notifications_dedup table
and that dedup state survives a simulated process restart.
"""
import sqlite3
import tempfile
import os
from datetime import datetime, timedelta, timezone
from unittest.mock import patch


def _make_db():
    """Create an in-memory SQLite DB with the notifications_dedup table."""
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE notifications_dedup ("
        "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "  event_type TEXT NOT NULL,"
        "  dedup_key TEXT NOT NULL,"
        "  sent_at TEXT NOT NULL,"
        "  UNIQUE(event_type, dedup_key)"
        ")"
    )
    conn.commit()
    return conn


def test_dedup_reads_from_table_not_memory():
    """_already_notified_recently reads notifications_dedup, not the in-memory dict."""
    from src.notifications.platform_events import _already_notified_recently_db

    conn = _make_db()
    # Pre-insert a dedup row as if a previous run fired
    now = datetime.now(timezone.utc)
    conn.execute(
        "INSERT INTO notifications_dedup (event_type, dedup_key, sent_at) VALUES (?, ?, ?)",
        ("platform_event", "some_key", now.isoformat()),
    )
    conn.commit()

    # Should detect the existing row and return True (already notified)
    result = _already_notified_recently_db("platform_event", "some_key", conn=conn)
    assert result is True


def test_dedup_not_notified_when_no_row():
    """Fresh key → False (no prior notification), and row is inserted."""
    from src.notifications.platform_events import _already_notified_recently_db

    conn = _make_db()
    result = _already_notified_recently_db("platform_event", "brand_new_key", conn=conn)
    assert result is False

    # Row should be inserted
    row = conn.execute(
        "SELECT * FROM notifications_dedup WHERE event_type=? AND dedup_key=?",
        ("platform_event", "brand_new_key"),
    ).fetchone()
    assert row is not None


def test_dedup_expired_row_allows_resend():
    """Row older than DEDUP_WINDOW_HOURS should be replaced, returning False."""
    from src.notifications.platform_events import _already_notified_recently_db

    conn = _make_db()
    old_time = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()
    conn.execute(
        "INSERT INTO notifications_dedup (event_type, dedup_key, sent_at) VALUES (?, ?, ?)",
        ("platform_event", "stale_key", old_time),
    )
    conn.commit()

    result = _already_notified_recently_db("platform_event", "stale_key", conn=conn)
    assert result is False


def test_nssm_restart_preserves_dedup_state():
    """Simulates NSSM restart: fresh module import but DB retains the dedup row."""
    import importlib
    import src.notifications.platform_events as pe_module

    with tempfile.NamedTemporaryFile(suffix=".sqlite3", delete=False) as f:
        db_path = f.name
    try:
        # Bootstrap the table in a temp file DB
        conn = sqlite3.connect(db_path)
        conn.execute(
            "CREATE TABLE notifications_dedup ("
            "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
            "  event_type TEXT NOT NULL,"
            "  dedup_key TEXT NOT NULL,"
            "  sent_at TEXT NOT NULL,"
            "  UNIQUE(event_type, dedup_key)"
            ")"
        )
        now = datetime.now(timezone.utc)
        conn.execute(
            "INSERT INTO notifications_dedup (event_type, dedup_key, sent_at) VALUES (?,?,?)",
            ("platform_event", "restart_key", now.isoformat()),
        )
        conn.commit()
        conn.close()

        # Simulate re-import (restart): the function reads from DB, not in-memory cache
        result = pe_module._already_notified_recently_db(
            "platform_event", "restart_key", db_path=db_path
        )
        assert result is True, "Restart-safe: DB row must suppress duplicate send"
    finally:
        os.unlink(db_path)


def test_heartbeat_row_written_to_notifications_sent():
    """Heartbeat sentinel writes a row with status='heartbeat'."""
    from src.notifications.platform_events import write_heartbeat

    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE notifications_sent ("
        "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "  event_type TEXT NOT NULL,"
        "  channel TEXT NOT NULL,"
        "  recipient TEXT,"
        "  sent_at TEXT NOT NULL,"
        "  status TEXT NOT NULL,"
        "  retry_count INTEGER NOT NULL DEFAULT 0,"
        "  error_msg TEXT"
        ")"
    )
    conn.commit()

    write_heartbeat(conn=conn)

    row = conn.execute(
        "SELECT status, event_type, channel FROM notifications_sent WHERE status='heartbeat'"
    ).fetchone()
    assert row is not None
    assert row[0] == "heartbeat"
    assert row[2] == "telegram"
