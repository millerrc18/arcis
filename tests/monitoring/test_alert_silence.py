"""Tests for src.monitoring.alert_silence — T14 D5.

Covers:
1. Silence detected when no signal during market hours
2. No silence when recent send (notifications_sent within threshold)
3. No silence when recent enqueue only (notifications_digest_queue created_at within threshold)
4. Outside market hours returns None (no-op)
5. Emits safe_send + platform_events row on finding
"""
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
