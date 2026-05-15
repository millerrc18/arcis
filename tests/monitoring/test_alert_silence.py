"""Tests for src.monitoring.alert_silence — T14 D5.

Covers:
1. Silence detected when no signal during market hours
2. No silence when recent send (notifications_sent within threshold)
3. No silence when recent enqueue only (notifications_digest_queue created_at within threshold)
4. Outside market hours returns None (no-op)
5. Emits safe_send + platform_events row on finding
6. _query_max_signal returns (None, "none") when all sources empty (LIMIT 1 empty union)
7. PG-mode regression: SQL must run against PostgreSQL without GroupingError (skipped unless
   DATABASE_URL=postgres://... is set in env)

PG-mode test instructions (operator):
    docker-compose -f docker-compose.test.yml up -d
    DATABASE_URL=postgresql://test:test@localhost:5433/halcyon \
    ARCIS_PG_CUTOVER_ENABLED=1 \
    python -m pytest tests/monitoring/test_alert_silence.py::test_query_max_signal_works_on_pg -v
"""
import os
import sqlite3
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock
from zoneinfo import ZoneInfo

import pytest

ET = ZoneInfo("America/New_York")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_conn() -> sqlite3.Connection:
    """Return an in-memory SQLite connection with required tables."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE notifications_sent (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type TEXT NOT NULL,
            channel TEXT NOT NULL,
            recipient TEXT,
            sent_at TEXT NOT NULL,
            status TEXT NOT NULL,
            retry_count INTEGER NOT NULL DEFAULT 0,
            error_msg TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE notifications_digest_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type TEXT NOT NULL,
            severity TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            source_tag TEXT NOT NULL DEFAULT 'unknown',
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            flushed_at TIMESTAMP,
            flush_status TEXT NOT NULL DEFAULT 'pending',
            flush_attempts INTEGER NOT NULL DEFAULT 0,
            flush_error TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE platform_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type TEXT NOT NULL,
            severity TEXT NOT NULL,
            payload_json TEXT,
            source TEXT NOT NULL,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.commit()
    return conn


def _market_open_time() -> datetime:
    """Return a Tuesday at 11:00 ET — unambiguously during market hours."""
    return datetime(2026, 3, 10, 11, 0, tzinfo=ET)


def _saturday_time() -> datetime:
    """Return a Saturday — outside market hours."""
    return datetime(2026, 3, 7, 11, 0, tzinfo=ET)


# ---------------------------------------------------------------------------
# Test 1 — silence detected when no signal during market hours
# ---------------------------------------------------------------------------

def test_silence_detected_when_no_signal_during_market_hours():
    """Empty tables + market-open time → returns AlertSilenceFinding."""
    from src.monitoring.alert_silence import check_alert_silence, AlertSilenceFinding

    conn = _make_conn()
    now = _market_open_time()

    with patch("src.monitoring.alert_silence.safe_send"):
        result = check_alert_silence(now_et=now, threshold_minutes=60, conn=conn)

    assert result is not None
    assert isinstance(result, AlertSilenceFinding)
    assert result.minutes_silent >= 60
    assert result.source == "none"
    assert result.last_notification_ts is None


# ---------------------------------------------------------------------------
# Test 2 — no silence when recent send
# ---------------------------------------------------------------------------

def test_no_silence_when_recent_send():
    """notifications_sent has a row within threshold → None."""
    from datetime import timezone as _tz
    from src.monitoring.alert_silence import check_alert_silence

    conn = _make_conn()
    now = _market_open_time()
    # Store as UTC ISO (matching production _write_notification_sent format)
    recent_ts = (now - timedelta(minutes=10)).astimezone(_tz.utc).isoformat()
    conn.execute(
        "INSERT INTO notifications_sent (event_type, channel, sent_at, status) VALUES (?, ?, ?, ?)",
        ("scan_complete", "telegram", recent_ts, "ok"),
    )
    conn.commit()

    with patch("src.monitoring.alert_silence.safe_send"):
        result = check_alert_silence(now_et=now, threshold_minutes=60, conn=conn)

    assert result is None


# ---------------------------------------------------------------------------
# Test 3 — no silence when recent enqueue only (proves loop is alive)
# ---------------------------------------------------------------------------

def test_no_silence_when_recent_enqueue():
    """Only created_at activity in digest_queue (no sends) → None.

    This proves the enqueued_at/created_at UNION term is honoured:
    the watch loop is alive even if nothing has been explicitly sent.
    """
    from datetime import timezone as _tz
    from src.monitoring.alert_silence import check_alert_silence

    conn = _make_conn()
    now = _market_open_time()
    recent_ts = (now - timedelta(minutes=10)).astimezone(_tz.utc).isoformat()
    conn.execute(
        """INSERT INTO notifications_digest_queue
           (event_type, severity, payload_json, source_tag, created_at)
           VALUES (?, ?, ?, ?, ?)""",
        ("scan_complete", "normal", "{}", "test", recent_ts),
    )
    conn.commit()

    with patch("src.monitoring.alert_silence.safe_send"):
        result = check_alert_silence(now_et=now, threshold_minutes=60, conn=conn)

    assert result is None


# ---------------------------------------------------------------------------
# Test 4 — outside market hours returns None (no-op)
# ---------------------------------------------------------------------------

def test_outside_market_hours_returns_none_no_op():
    """Saturday → None even with empty tables — no side effects."""
    from src.monitoring.alert_silence import check_alert_silence

    conn = _make_conn()
    now = _saturday_time()

    mock_safe_send = MagicMock()
    with patch("src.monitoring.alert_silence.safe_send", mock_safe_send):
        result = check_alert_silence(now_et=now, threshold_minutes=60, conn=conn)

    assert result is None
    mock_safe_send.assert_not_called()


# ---------------------------------------------------------------------------
# Test 5 — emits safe_send AND platform_events row on finding
# ---------------------------------------------------------------------------

def test_emits_safe_send_and_platform_events_on_finding():
    """When silence is detected, assert safe_send called with event_type='alert_silence'
    AND a platform_events row is written."""
    from src.monitoring.alert_silence import check_alert_silence

    conn = _make_conn()
    now = _market_open_time()

    mock_safe_send = MagicMock(return_value=True)
    with patch("src.monitoring.alert_silence.safe_send", mock_safe_send):
        result = check_alert_silence(now_et=now, threshold_minutes=60, conn=conn)

    assert result is not None

    # safe_send must have been called with event_type='alert_silence'
    assert mock_safe_send.called
    call_kwargs = mock_safe_send.call_args
    assert call_kwargs[0][0] == "alert_silence" or call_kwargs.kwargs.get("event_type") == "alert_silence"

    # platform_events row must be written
    row = conn.execute(
        "SELECT * FROM platform_events WHERE source='alert_silence'"
    ).fetchone()
    assert row is not None
    assert row["severity"] == "high"
    assert row["event_type"] == "alert_silence"


# ---------------------------------------------------------------------------
# Test 6 — _query_max_signal returns (None, "none") when all sources empty
# ---------------------------------------------------------------------------

def test_query_max_signal_empty_tables_returns_none_source_none():
    """When all 3 UNION arms are empty, _query_max_signal must return (None, 'none').

    Regression-lock for the ORDER BY DESC LIMIT 1 form: when the union produces
    zero rows, fetchone() returns None (not a row with None columns). The function
    must handle that case explicitly.

    With the old broken MAX(ts)+source form on SQLite: returns one row (None, None).
    With the new ORDER BY DESC LIMIT 1 form: returns zero rows (fetchone() -> None).
    Both paths must produce (None, 'none').
    """
    from src.monitoring.alert_silence import _query_max_signal

    conn = _make_conn()
    ts, source = _query_max_signal(conn)
    assert ts is None
    assert source == "none"


def test_query_max_signal_returns_most_recent_ts_and_source():
    """When multiple sources have rows, _query_max_signal returns the most recent."""
    from datetime import timezone as _tz
    from src.monitoring.alert_silence import _query_max_signal

    conn = _make_conn()
    now = _market_open_time()
    older_ts = (now - timedelta(minutes=30)).astimezone(_tz.utc).isoformat()
    newer_ts = (now - timedelta(minutes=5)).astimezone(_tz.utc).isoformat()

    # Insert an older notifications_sent row and a newer digest enqueue row
    conn.execute(
        "INSERT INTO notifications_sent (event_type, channel, sent_at, status) VALUES (?, ?, ?, ?)",
        ("scan_complete", "telegram", older_ts, "ok"),
    )
    conn.execute(
        """INSERT INTO notifications_digest_queue
           (event_type, severity, payload_json, source_tag, created_at)
           VALUES (?, ?, ?, ?, ?)""",
        ("scan_complete", "normal", "{}", "test", newer_ts),
    )
    conn.commit()

    ts, source = _query_max_signal(conn)
    assert ts is not None
    assert source == "digest_enqueued"


# ---------------------------------------------------------------------------
# Test 7 — PG-mode regression: SQL portability against PostgreSQL
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
    not os.environ.get("DATABASE_URL", "").startswith("postgres"),
    reason=(
        "PG-mode test requires DATABASE_URL=postgres://... and "
        "ARCIS_PG_CUTOVER_ENABLED=1 in env. "
        "Run: DATABASE_URL=postgresql://test:test@localhost:5433/halcyon "
        "ARCIS_PG_CUTOVER_ENABLED=1 "
        "python -m pytest tests/monitoring/test_alert_silence.py::test_query_max_signal_works_on_pg"
    ),
)
def test_query_max_signal_works_on_pg():
    """Regression-lock: the SQL in _query_max_signal must run against PostgreSQL
    without raising psycopg2.errors.GroupingError.

    The old broken form 'SELECT MAX(ts), source FROM (...)' is rejected by PG
    because 'source' is a non-aggregate column in an aggregate SELECT without
    GROUP BY. The fixed form 'SELECT ts, source FROM (...) ORDER BY ts DESC
    NULLS LAST LIMIT 1' is engine-agnostic and accepted by both SQLite and PG.

    This test runs only when DATABASE_URL starts with 'postgres' AND
    ARCIS_PG_CUTOVER_ENABLED=1 — set both to exercise the PG code path via
    connect_db().

    The test seeds one row in notifications_sent, calls _query_max_signal via
    the PG-backed connection, and asserts the result is (ts, 'notifications_sent').
    """
    import os
    os.environ["ARCIS_PG_CUTOVER_ENABLED"] = "1"

    from src.utils.db import connect_db, PostgresConnectionWrapper
    conn = connect_db()
    assert isinstance(conn, PostgresConnectionWrapper), (
        "Expected PG connection — check DATABASE_URL and ARCIS_PG_CUTOVER_ENABLED"
    )

    try:
        # Create minimal tables for the test (drop first to avoid conflicts)
        conn.execute("DROP TABLE IF EXISTS notifications_sent")
        conn.execute("DROP TABLE IF EXISTS notifications_digest_queue")
        conn.execute(
            """
            CREATE TABLE notifications_sent (
                id SERIAL PRIMARY KEY,
                event_type TEXT NOT NULL,
                channel TEXT NOT NULL,
                recipient TEXT,
                sent_at TEXT NOT NULL,
                status TEXT NOT NULL,
                retry_count INTEGER NOT NULL DEFAULT 0,
                error_msg TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE notifications_digest_queue (
                id SERIAL PRIMARY KEY,
                event_type TEXT NOT NULL,
                severity TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                source_tag TEXT NOT NULL DEFAULT 'unknown',
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                flushed_at TIMESTAMP,
                flush_status TEXT NOT NULL DEFAULT 'pending',
                flush_attempts INTEGER NOT NULL DEFAULT 0,
                flush_error TEXT
            )
            """
        )
        conn.execute(
            "INSERT INTO notifications_sent (event_type, channel, sent_at, status) "
            "VALUES (?, ?, ?, ?)",
            ("scan_complete", "telegram", "2026-03-10T15:00:00+00:00", "ok"),
        )
        conn.commit()

        from src.monitoring.alert_silence import _query_max_signal
        ts, source = _query_max_signal(conn)
        assert ts is not None, "Expected a timestamp from notifications_sent row"
        assert source == "notifications_sent"
    finally:
        try:
            conn.execute("DROP TABLE IF EXISTS notifications_sent")
            conn.execute("DROP TABLE IF EXISTS notifications_digest_queue")
            conn.commit()
        except Exception:
            pass
        conn.close()


# ---------------------------------------------------------------------------
# Test 8 — regression-lock for the v0.36.6 text/timestamp UNION fix
# ---------------------------------------------------------------------------


def test_query_max_signal_does_not_union_mixed_types():
    """Regression-lock for the 2026-05-15 text/timestamp UNION crash.

    `notifications_sent.sent_at` is `text` (SQLite-shaped column type per
    the schema audit); `notifications_digest_queue.flushed_at` and
    `.created_at` are `TIMESTAMP WITHOUT TIME ZONE`. PG refuses to UNION
    text + timestamp with
        `UNION types text and timestamp without time zone cannot be matched`.

    Initial attempt to fix via `CAST(sent_at AS TIMESTAMP)` in SQL broke
    SQLite: `CAST('2026-05-15T...' AS TIMESTAMP)` produces the int 2026
    (TIMESTAMP coerces to NUMERIC affinity in SQLite, which truncates the
    string at the first non-digit char). The correct fix is to query each
    source separately and merge in Python via `_parse_ts`.

    This test asserts the implementation does NOT contain a UNION across
    the three sources (which would re-introduce the engine-divergent
    cast problem). Any future "let's collapse this back to one UNION
    query" PR will be caught by this guard.
    """
    import inspect
    from src.monitoring.alert_silence import _query_max_signal

    src = inspect.getsource(_query_max_signal)
    # The buggy form had `UNION ALL` joining notifications_sent with
    # notifications_digest_queue. Reject any re-introduction of that join.
    has_union = "UNION ALL" in src.upper() or "UNION\n" in src.upper()
    assert not has_union, (
        "_query_max_signal must NOT UNION text-typed `notifications_sent.sent_at` "
        "with timestamp-typed digest_queue columns — PG raises\n"
        "  'UNION types text and timestamp without time zone cannot be matched'\n"
        "(2026-05-15 incident). Use three separate ORDER BY ... LIMIT 1 queries "
        "and merge in Python via _parse_ts."
    )
