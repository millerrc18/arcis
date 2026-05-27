"""Crash-recovery tests for email_digest / DigestQueue (#115 T16).

These tests exercise the persistence-layer recovery contract:
  - in_progress rows from a crash are recovered on the next flush tick
  - the dedup key prevents double-send on restart
  - partial batch failures increment flush_attempts
  - retry_attempts exhaustion marks a row as abandoned

The DigestQueue class is the canonical persistence layer for the
notifications_digest_queue table (DD-34). Crash recovery semantics live in
``_recover_orphaned_in_progress`` which is invoked at the top of
``DigestQueue.flush()`` — see src/notifications/digest_queue.py:143.

Fixture pattern mirrors tests/notifications/test_digest_queue.py:15-51.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

import pytest

from src.notifications.digest_queue import DigestQueue


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
    conn.execute(
        "CREATE INDEX idx_digest_flush_status "
        "ON notifications_digest_queue (flush_status)"
    )
    conn.execute(
        "CREATE INDEX idx_digest_created_at "
        "ON notifications_digest_queue (created_at)"
    )
    conn.execute("""
        CREATE TABLE notifications_dedup (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type TEXT NOT NULL,
            dedup_key TEXT NOT NULL,
            sent_at TEXT NOT NULL
        )
    """)
    conn.execute(
        "CREATE UNIQUE INDEX idx_notifications_dedup_unique "
        "ON notifications_dedup (event_type, dedup_key)"
    )
    conn.commit()
    return conn


def _default_config(retry_attempts: int = 3):
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
        retry_attempts=retry_attempts,
        retry_backoff_seconds=[1, 5, 15],
    )


# ── (1) in_progress row recovered on next flush ──────────────────────────

def test_in_progress_row_recovered_on_next_flush():
    """An in_progress row from a crash MUST be re-queued as pending and then
    dispatched on the next flush tick. This is the load-bearing recovery
    contract: a process crash mid-dispatch leaves the row in 'in_progress'
    and the next flush must NOT leave it stranded.
    """
    conn = _make_conn()
    cfg = _default_config(retry_attempts=3)
    q = DigestQueue(conn, config=cfg)

    # Manually insert a row in 'in_progress' state — simulating a crash AFTER
    # the flush() call claimed the row but BEFORE the dispatcher finished.
    conn.execute(
        "INSERT INTO notifications_digest_queue "
        "(event_type, severity, payload_json, source_tag, flush_status, flush_attempts) "
        "VALUES (?, ?, ?, ?, 'in_progress', 0)",
        ("trade_opened", "low", '{"ticker": "AAPL"}', "email:postclose"),
    )
    conn.commit()

    dispatched: list[dict] = []

    def _dispatcher(payload):
        dispatched.append(payload)

    result = q.flush(dispatcher=_dispatcher)

    # The orphan row was recovered (re-queued as pending) and then
    # dispatched in the same flush call.
    assert result.successes == 1, (
        f"expected 1 success after orphan recovery + dispatch, got {result!r}"
    )
    assert len(dispatched) == 1
    assert dispatched[0]["event_type"] == "trade_opened"

    # The row is now marked sent — no orphans remain.
    rows = conn.execute(
        "SELECT flush_status FROM notifications_digest_queue"
    ).fetchall()
    assert all(r["flush_status"] == "sent" for r in rows), (
        f"expected all rows sent post-recovery, got {[dict(r) for r in rows]!r}"
    )


# ── (2) dedup_key prevents double-send on restart ────────────────────────

def test_dedup_key_prevents_double_send_on_restart():
    """The UNIQUE(event_type, dedup_key) index on notifications_dedup MUST
    prevent a second INSERT after a crash-then-restart simulation. Re-inserting
    the same dedup_key is a no-op (INSERT OR IGNORE) — the second attempt
    silently does nothing instead of double-sending.
    """
    conn = _make_conn()
    now = datetime.now(timezone.utc).isoformat()

    # First send: insert the dedup row.
    conn.execute(
        "INSERT OR IGNORE INTO notifications_dedup "
        "(event_type, dedup_key, sent_at) VALUES (?, ?, ?)",
        ("digest_suppressed_empty", "email:preopen:2026-05-26:suppressed-empty", now),
    )
    conn.commit()

    initial_count = conn.execute(
        "SELECT COUNT(*) AS c FROM notifications_dedup"
    ).fetchone()["c"]
    assert initial_count == 1

    # Simulate restart: re-attempt the INSERT — must NOT duplicate.
    conn.execute(
        "INSERT OR IGNORE INTO notifications_dedup "
        "(event_type, dedup_key, sent_at) VALUES (?, ?, ?)",
        (
            "digest_suppressed_empty",
            "email:preopen:2026-05-26:suppressed-empty",
            datetime.now(timezone.utc).isoformat(),
        ),
    )
    conn.commit()

    final_count = conn.execute(
        "SELECT COUNT(*) AS c FROM notifications_dedup"
    ).fetchone()["c"]
    assert final_count == 1, (
        f"expected 1 dedup row after re-insert (UNIQUE constraint), "
        f"got {final_count}"
    )


# ── (3) partial batch failure increments flush_attempts ─────────────────

def test_partial_batch_failure_increments_attempts():
    """When the dispatcher raises for a row, flush_attempts MUST be
    incremented and the row must be re-queued as 'pending' (not abandoned)
    as long as attempts < retry_attempts.
    """
    conn = _make_conn()
    cfg = _default_config(retry_attempts=3)
    q = DigestQueue(conn, config=cfg)
    row_id = q.enqueue(
        event_type="trade_opened",
        severity="low",
        payload={"ticker": "AAPL"},
        source_tag="email:postclose",
    )

    def _failing_dispatcher(payload):
        raise RuntimeError("simulated downstream failure")

    result = q.flush(dispatcher=_failing_dispatcher)

    # The dispatch failed; one failure recorded (not abandoned yet).
    assert result.failures == 1, f"expected 1 failure, got {result!r}"
    assert result.abandoned == 0, f"expected no abandons on attempt 1, got {result!r}"

    row = conn.execute(
        "SELECT flush_status, flush_attempts FROM notifications_digest_queue WHERE id=?",
        (row_id,),
    ).fetchone()
    assert row["flush_status"] == "pending", (
        f"expected re-queued as pending after retriable failure, "
        f"got {row['flush_status']!r}"
    )
    assert row["flush_attempts"] == 1, (
        f"expected flush_attempts incremented to 1, got {row['flush_attempts']!r}"
    )


# ── (4) max_attempts marks row as abandoned ─────────────────────────────

def test_max_attempts_marks_abandoned():
    """When flush_attempts reaches retry_attempts, the row MUST be marked
    'abandoned' (not retried indefinitely). With retry_attempts=2, the
    second failed dispatch should abandon the row.
    """
    conn = _make_conn()
    cfg = _default_config(retry_attempts=2)
    q = DigestQueue(conn, config=cfg)
    row_id = q.enqueue(
        event_type="trade_opened",
        severity="low",
        payload={"ticker": "AAPL"},
        source_tag="email:postclose",
    )

    def _failing_dispatcher(payload):
        raise RuntimeError("permanent downstream failure")

    # Attempt 1: flush_attempts goes 0 → 1, status='pending'.
    result1 = q.flush(dispatcher=_failing_dispatcher)
    assert result1.failures == 1
    row = conn.execute(
        "SELECT flush_status, flush_attempts FROM notifications_digest_queue WHERE id=?",
        (row_id,),
    ).fetchone()
    assert row["flush_attempts"] == 1
    assert row["flush_status"] == "pending"

    # Attempt 2: flush_attempts goes 1 → 2, status='abandoned' (== retry_attempts).
    result2 = q.flush(dispatcher=_failing_dispatcher)
    assert result2.abandoned == 1, (
        f"expected row abandoned on attempt 2 (retry_attempts=2), got {result2!r}"
    )
    row = conn.execute(
        "SELECT flush_status, flush_attempts, flush_error "
        "FROM notifications_digest_queue WHERE id=?",
        (row_id,),
    ).fetchone()
    assert row["flush_status"] == "abandoned", (
        f"expected status=abandoned after retry_attempts exhausted, "
        f"got {row['flush_status']!r}"
    )
    assert row["flush_attempts"] == 2
    assert row["flush_error"], "expected flush_error to be populated on abandon"
