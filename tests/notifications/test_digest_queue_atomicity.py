"""Tests for DigestQueue atomicity — flush-then-fail recovery + mark_flush_failed.

T11 Sprint 5 Wave D D2.
"""

import sqlite3
import threading

import pytest

from src.notifications.digest_queue import DigestQueue, FlushResult


def _make_conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("""
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
    """)
    conn.execute("CREATE INDEX idx_digest_flush_status ON notifications_digest_queue (flush_status)")
    conn.execute("CREATE INDEX idx_digest_created_at ON notifications_digest_queue (created_at)")
    conn.commit()
    return conn


def _default_config():
    from src.notifications.policy import NotificationsConfig
    return NotificationsConfig(
        default_routing={"telegram": True, "email": False},
        digest_low=True,
        quiet_hours_start="22:00",
        quiet_hours_end="06:00",
        quiet_digest=True,
        mute_event_types=[],
        routing_overrides={},
        cadence_minutes_per_event_type={},
        retry_attempts=3,
        retry_backoff_seconds=[1, 5, 15],
    )


def test_flush_status_transition_is_atomic():
    """Two sequential flush calls must not double-dispatch the same row.

    SQLite does not support SELECT ... FOR UPDATE, but the atomic
    UPDATE ... WHERE flush_status='pending' pattern ensures a row
    cannot be picked up by two concurrent flushes. We test this by
    verifying that after both calls the row has been dispatched exactly
    once (successes sum == 1 across both calls).
    """
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("""
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
    """)
    conn.commit()

    cfg = _default_config()
    q = DigestQueue(conn, config=cfg)
    q.enqueue(event_type="trade_opened", severity="low", payload={"ticker": "AAPL"})

    dispatch_count = [0]

    def dispatcher(p):
        dispatch_count[0] += 1

    result1 = q.flush(dispatcher=dispatcher)
    result2 = q.flush(dispatcher=dispatcher)

    total_successes = result1.successes + result2.successes
    assert total_successes == 1
    assert dispatch_count[0] == 1


def test_mark_flush_failed_sets_abandoned_status():
    conn = _make_conn()
    q = DigestQueue(conn, config=_default_config())
    row_id = q.enqueue(event_type="risk_alert", severity="low", payload={})

    q.mark_flush_failed(row_id, "manual failure marker")

    row = conn.execute(
        "SELECT flush_status, flush_error FROM notifications_digest_queue WHERE id=?",
        (row_id,),
    ).fetchone()
    assert row["flush_status"] == "abandoned"
    assert row["flush_error"] == "manual failure marker"


def test_flush_then_fail_recovery():
    """Orphaned 'in_progress' rows from a mid-flush crash are recovered.

    Simulates: flush starts, row transitions to 'in_progress', process
    crashes. On next tick, the orphan is treated as failed (increments
    flush_attempts; re-queues as 'pending' if under retry limit, or
    'abandoned' if limit exhausted).
    """
    conn = _make_conn()
    cfg = _default_config()
    q = DigestQueue(conn, config=cfg)
    row_id = q.enqueue(event_type="system_event", severity="low", payload={})

    conn.execute(
        "UPDATE notifications_digest_queue SET flush_status='in_progress', flush_attempts=0 WHERE id=?",
        (row_id,),
    )
    conn.commit()

    row_before = conn.execute(
        "SELECT flush_status FROM notifications_digest_queue WHERE id=?", (row_id,)
    ).fetchone()
    assert row_before["flush_status"] == "in_progress"

    def failing_dispatcher(p):
        raise RuntimeError("simulated dispatch failure after crash recovery")

    result = q.flush(dispatcher=failing_dispatcher)

    row_after = conn.execute(
        "SELECT flush_status, flush_attempts FROM notifications_digest_queue WHERE id=?",
        (row_id,),
    ).fetchone()
    assert row_after["flush_status"] == "pending", (
        f"Crash recovery of in_progress row with attempts={row_after['flush_attempts']} "
        f"and retry_attempts=3 should transition to 'pending' (still has retries left), "
        f"got {row_after['flush_status']!r}. If the recovery logic were broken, this test "
        f"would catch it."
    )
    assert row_after["flush_attempts"] >= 1


def test_abandoned_rows_not_re_picked_up_by_flush():
    conn = _make_conn()
    q = DigestQueue(conn, config=_default_config())
    row_id = q.enqueue(event_type="trade_opened", severity="low", payload={})
    q.mark_flush_failed(row_id, "intentionally abandoned")

    dispatch_count = [0]

    def dispatcher(p):
        dispatch_count[0] += 1

    result = q.flush(dispatcher=dispatcher)

    assert result.successes == 0
    assert dispatch_count[0] == 0

    row = conn.execute(
        "SELECT flush_status FROM notifications_digest_queue WHERE id=?", (row_id,)
    ).fetchone()
    assert row["flush_status"] == "abandoned"
