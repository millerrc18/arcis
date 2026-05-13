"""Tests for DigestQueue — enqueue/flush happy paths + boundary conditions.

T11 Sprint 5 Wave D D2.
"""

import json
import sqlite3
from datetime import datetime, timezone

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


def test_enqueue_inserts_row_with_pending_status():
    conn = _make_conn()
    q = DigestQueue(conn, config=_default_config())
    row_id = q.enqueue(
        event_type="trade_opened",
        severity="low",
        payload={"ticker": "AAPL"},
    )
    row = conn.execute(
        "SELECT * FROM notifications_digest_queue WHERE id=?", (row_id,)
    ).fetchone()
    assert row is not None
    assert row["flush_status"] == "pending"
    assert row["flush_attempts"] == 0
    assert row["flushed_at"] is None


def test_enqueue_unknown_event_type_raises_value_error():
    conn = _make_conn()
    q = DigestQueue(conn, config=_default_config())
    with pytest.raises(ValueError, match="not_in_allowlist"):
        q.enqueue(
            event_type="not_in_allowlist",
            severity="low",
            payload={"msg": "test"},
        )


def test_enqueue_returns_row_id():
    conn = _make_conn()
    q = DigestQueue(conn, config=_default_config())
    row_id = q.enqueue(
        event_type="risk_alert",
        severity="medium",
        payload={"detail": "test"},
    )
    assert isinstance(row_id, int)
    assert row_id >= 1


def test_flush_drains_pending_rows():
    conn = _make_conn()
    q = DigestQueue(conn, config=_default_config())
    for _ in range(3):
        q.enqueue(event_type="trade_closed", severity="low", payload={"ticker": "TSLA"})

    dispatched = []
    result = q.flush(dispatcher=lambda p: dispatched.append(p))

    assert isinstance(result, FlushResult)
    assert result.successes == 3
    assert result.failures == 0
    assert result.abandoned == 0
    assert len(dispatched) == 3

    rows = conn.execute(
        "SELECT flush_status, flush_attempts, flushed_at FROM notifications_digest_queue"
    ).fetchall()
    for row in rows:
        assert row["flush_status"] == "sent"
        assert row["flush_attempts"] == 1
        assert row["flushed_at"] is not None


def test_flush_respects_max_rows():
    conn = _make_conn()
    q = DigestQueue(conn, config=_default_config())
    for _ in range(10):
        q.enqueue(event_type="scan_result", severity="low", payload={})

    result = q.flush(max_rows=3, dispatcher=lambda p: None)

    assert result.successes == 3
    pending = conn.execute(
        "SELECT COUNT(*) FROM notifications_digest_queue WHERE flush_status='pending'"
    ).fetchone()[0]
    assert pending == 7


def test_flush_on_dispatcher_exception_increments_attempts():
    conn = _make_conn()
    q = DigestQueue(conn, config=_default_config())
    row_id = q.enqueue(event_type="system_event", severity="low", payload={})

    def raising_dispatcher(p):
        raise RuntimeError("dispatch failed")

    result = q.flush(dispatcher=raising_dispatcher)
    assert result.failures == 1
    assert result.successes == 0

    row = conn.execute(
        "SELECT flush_status, flush_attempts FROM notifications_digest_queue WHERE id=?",
        (row_id,),
    ).fetchone()
    assert row["flush_attempts"] == 1
    assert row["flush_status"] == "pending"


def test_flush_marks_abandoned_after_max_retries():
    conn = _make_conn()
    cfg = _default_config()
    q = DigestQueue(conn, config=cfg)
    row_id = q.enqueue(event_type="system_event", severity="low", payload={})

    def raising_dispatcher(p):
        raise RuntimeError("always fails")

    for _ in range(cfg.retry_attempts):
        q.flush(dispatcher=raising_dispatcher)

    row = conn.execute(
        "SELECT flush_status, flush_attempts, flush_error FROM notifications_digest_queue WHERE id=?",
        (row_id,),
    ).fetchone()
    assert row["flush_status"] == "abandoned"
    assert row["flush_attempts"] == cfg.retry_attempts
    assert row["flush_error"] is not None and "always fails" in row["flush_error"]


def test_pending_count_returns_correct_count():
    conn = _make_conn()
    q = DigestQueue(conn, config=_default_config())
    for _ in range(5):
        q.enqueue(event_type="trade_opened", severity="low", payload={})

    dispatched_count = 0

    def counting_dispatcher(p):
        nonlocal dispatched_count
        dispatched_count += 1
        if dispatched_count > 2:
            raise RuntimeError("fail after 2")

    q.flush(max_rows=2, dispatcher=lambda p: None)
    assert q.pending_count() == 3


def test_abandoned_count_returns_correct_count():
    conn = _make_conn()
    cfg = _default_config()
    q = DigestQueue(conn, config=cfg)

    for _ in range(2):
        q.enqueue(event_type="risk_alert", severity="low", payload={})
    q.enqueue(event_type="trade_opened", severity="low", payload={})

    all_ids = [r["id"] for r in conn.execute("SELECT id FROM notifications_digest_queue").fetchall()]
    for row_id in all_ids[:2]:
        q.mark_flush_failed(row_id, "test abandonment")

    assert q.abandoned_count() == 2


def test_source_tag_persists_through_enqueue_flush_cycle():
    conn = _make_conn()
    q = DigestQueue(conn, config=_default_config())
    row_id = q.enqueue(
        event_type="trade_opened",
        severity="low",
        payload={"ticker": "NVDA"},
        source_tag="pytest:T11",
    )

    q.flush(dispatcher=lambda p: None)

    row = conn.execute(
        "SELECT source_tag, flush_status FROM notifications_digest_queue WHERE id=?",
        (row_id,),
    ).fetchone()
    assert row["source_tag"] == "pytest:T11"
    assert row["flush_status"] == "sent"


def _make_queue():
    conn = _make_conn()
    from src.notifications.policy import NotificationsConfig
    config = NotificationsConfig(
        default_routing={"telegram": True, "email": False},
        digest_low=True,
        quiet_hours_start="22:00",
        quiet_hours_end="06:00",
        quiet_digest=True,
        mute_event_types=[],
        routing_overrides={},
        cadence_minutes_per_event_type={},
        retry_attempts=1,
        retry_backoff_seconds=[1],
    )
    return DigestQueue(conn, config=config), config


def test_flush_error_redacts_bot_token_in_exception_string():
    """Regression-lock: flush_error must apply _redact_token to exception strings.

    Security review of T11 (Sprint 5 D2) flagged that the digest queue persists
    raw str(exc) to a column that syncs to Postgres. When T12 wires the real
    Telegram dispatcher, HTTP exceptions carry URLs like
    /bot<TOKEN>/sendMessage -- without redaction, the token lands in the queue
    table and downstream sync targets.

    This test fails loudly if the redaction is removed from _dispatch_one_row.
    """
    queue, _config = _make_queue()
    row_id = queue.enqueue(event_type="manual_intervention_drift", severity="high",
                           payload={"ticker": "AAPL"}, source_tag="pytest:T11-fixup")

    fake_token = "1234567890:AAAA-fake-bot-token-do-not-leak-this"

    def raising_dispatcher(payload):
        raise RuntimeError(
            f"Connection failed: GET https://api.telegram.org/bot{fake_token}/sendMessage 502"
        )

    queue.flush(max_rows=10, dispatcher=raising_dispatcher)

    conn = queue._conn
    cur = conn.execute("SELECT flush_error FROM notifications_digest_queue WHERE id=?", (row_id,))
    flush_error = cur.fetchone()[0]
    assert flush_error is not None, "flush_error should be populated after dispatcher exception"
    assert fake_token not in flush_error, (
        f"Bot token leaked into flush_error: {flush_error!r}. "
        f"Apply _redact_token in _dispatch_one_row's exception handler."
    )
    assert "<redacted" in flush_error.lower() or "REDACTED" in flush_error or "bot***" in flush_error.lower(), (
        f"flush_error doesn't show redaction marker -- verify _redact_token output: {flush_error!r}"
    )
