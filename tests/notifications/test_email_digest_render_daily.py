"""Tests for src/notifications/email_digest.py daily-tier rendering (#115 T6).

Covers _collect_preopen_data, _collect_postclose_data, _render_preopen_html,
_render_postclose_html, and the DD-33 empty-suppression rule. Spec sections
5.1, 6.5 + decisions DD-05, DD-17, DD-33, DD-34, DA-CRIT-2, DA-MAJ-12,
DA-MIN-17.

Tests are isolated against in-memory sqlite — no production-PG side-effects.
Run with `DATABASE_URL= python -m pytest tests/notifications/test_email_digest_render_daily.py -v`.
"""

from __future__ import annotations

import json
import sqlite3
from unittest.mock import patch

import pytest


# ── Shared test scaffolding ────────────────────────────────────────────────

def _make_conn():
    """In-memory sqlite with notifications_digest_queue + activity_log +
    shadow_trades + notifications_dedup."""
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
    conn.execute("""
        CREATE TABLE activity_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type TEXT,
            detail TEXT,
            created_at TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE shadow_trades (
            trade_id TEXT PRIMARY KEY,
            ticker TEXT,
            status TEXT,
            exit_reason TEXT,
            actual_exit_time TEXT,
            actual_exit_price REAL,
            entry_price REAL,
            planned_shares INTEGER,
            pnl_dollars REAL,
            pnl_pct REAL,
            source TEXT,
            created_at TEXT,
            quarantined INTEGER DEFAULT 0
        )
    """)
    conn.execute("""
        CREATE TABLE notifications_dedup (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type TEXT NOT NULL,
            dedup_key TEXT NOT NULL,
            sent_at TEXT NOT NULL,
            UNIQUE(event_type, dedup_key)
        )
    """)
    conn.commit()
    return conn


def _enqueue(conn, *, event_type, severity, payload, source_tag, status="pending"):
    cur = conn.execute(
        "INSERT INTO notifications_digest_queue "
        "(event_type, severity, payload_json, source_tag, flush_status) "
        "VALUES (?, ?, ?, ?, ?)",
        (event_type, severity, json.dumps(payload), source_tag, status),
    )
    conn.commit()
    return cur.lastrowid


def _fake_config(*, preopen_send_when_empty=False, postclose_send_when_empty=False):
    return {
        "email": {
            "tier_times": {
                "preopen": "07:30",
                "postclose": "17:00",
                "weekly": "Sun 18:00",
            },
            "tiers": {
                "preopen": {"enabled": True, "send_when_empty": preopen_send_when_empty},
                "postclose": {"enabled": True, "send_when_empty": postclose_send_when_empty},
                "weekly": {"enabled": True, "send_when_empty": True},
            },
            "dual_write_hold_over": {
                "enabled": False,
                "mode": "off",
                "shadow_output_dir": "tmp/digest-shadow",
            },
            "holidays": {
                "skip_preopen_on_market_holidays": False,
                "skip_postclose_on_market_holidays": False,
            },
            "digest_truncation": {
                "top_k_per_section": 10,
                "overflow_strategy": "defer_to_next_tier",
                "overflow_attach_format": "plain",
            },
        }
    }


# ── (a) DD-34: Critical replay from queue row appears in preopen ─────────

def test_preopen_includes_critical_replay_from_queue_row():
    """DD-17 revised + DD-34: queue rows tagged 'email:preopen:critical-overflow'
    with flush_status='pending' MUST appear in the rendered pre-open body
    under a 'Critical audit alerts fired since last digest' section."""
    from src.notifications.email_digest import render_digest

    conn = _make_conn()
    _enqueue(
        conn,
        event_type="audit_critical",
        severity="critical",
        payload={
            "category": "stop_loss_breach",
            "description": "AAPL stop @ 145 hit before market open",
            "recommendation": "review next-day plan",
            "fired_immediately_at": "2026-05-26T03:15:00+00:00",
            "subject": "[CRITICAL] AAPL stop breach",
            "body": "AAPL stop hit overnight",
        },
        source_tag="email:preopen:critical-overflow",
    )

    subject, plain, html, overflow_ids = render_digest(
        "preopen", rows=[], conn=conn,
    )
    assert "Critical audit alerts fired since last digest" in html
    assert "stop_loss_breach" in html
    assert overflow_ids == []


# ── (b) DD-34: throttle-suppressed CRITICAL still appears ─────────────────

def test_preopen_critical_replay_throttled_immediate_still_appears():
    """DD-34: queue rows are canonical. Even when notifications_sent has no row
    (throttle-suppressed), the queue row drives the digest body."""
    from src.notifications.email_digest import render_digest

    conn = _make_conn()
    _enqueue(
        conn,
        event_type="audit_critical",
        severity="critical",
        payload={
            "category": "risk",
            "description": "throttled but queued",
        },
        source_tag="email:preopen:critical-overflow",
    )
    # Deliberately NO notifications_sent table writes; queue row alone drives.

    subject, plain, html, overflow_ids = render_digest(
        "preopen", rows=[], conn=conn,
    )
    assert "throttled but queued" in html


# ── (c) Post-close aggregates action packets ─────────────────────────────

def test_postclose_aggregates_action_packets():
    """Multiple queued 'action_packet' rows render as one section, not 5."""
    from src.notifications.email_digest import render_digest

    rows = []
    for i in range(5):
        rows.append({
            "id": i + 1,
            "event_type": "action_packet",
            "severity": "normal",
            "source_tag": "email:postclose",
            "flush_attempts": 0,
            "payload": {"ticker": f"TKR{i}", "summary": f"packet {i}"},
        })

    subject, plain, html, overflow_ids = render_digest(
        "postclose", rows=rows,
    )
    # One section header for action_packet, not five.
    assert html.count("Action packets summarized") == 1
    # All five tickers represented.
    for i in range(5):
        assert f"TKR{i}" in html
    assert overflow_ids == []


# ── (d) DD-05 truncation: top-K=10 with overflow IDs returned ────────────

def test_truncation_top_10_with_overflow_ids_returned():
    """25 action_packet rows → 10 rendered + 15 overflow IDs (DA-CRIT-2)."""
    from src.notifications.email_digest import render_digest

    rows = []
    for i in range(25):
        rows.append({
            "id": 100 + i,
            "event_type": "action_packet",
            "severity": "normal",
            "source_tag": "email:postclose",
            "flush_attempts": 0,
            "payload": {"ticker": f"T{i}", "summary": f"p{i}"},
        })

    subject, plain, html, overflow_ids = render_digest(
        "postclose", rows=rows, top_k=10,
    )
    # 15 overflow IDs returned for DA-CRIT-2 — must equal IDs of NOT-rendered rows.
    assert len(overflow_ids) == 15
    assert overflow_ids == [100 + i for i in range(10, 25)]


# ── (e) DA-CRIT-2: overflow NOT marked sent on SMTP failure ──────────────

def test_postclose_overflow_not_marked_sent_on_smtp_failure(monkeypatch):
    """DA-CRIT-2: if send_email returns False, overflow rows MUST remain pending.
    Included rows ALSO not marked sent (SMTP failure = nothing delivered)."""
    from src.notifications import email_digest

    conn = _make_conn()
    # 12 rows → 10 included, 2 overflow with top_k=10.
    ids = []
    for i in range(12):
        ids.append(_enqueue(
            conn,
            event_type="action_packet",
            severity="normal",
            payload={"ticker": f"X{i}", "summary": f"row{i}"},
            source_tag="email:postclose",
        ))

    monkeypatch.setattr(email_digest, "load_config",
                        lambda: _fake_config(), raising=False)
    monkeypatch.setattr(email_digest, "send_email",
                        lambda *a, **kw: False, raising=False)

    email_digest.flush_tier("postclose", conn=conn)

    statuses = {
        r["id"]: r["flush_status"]
        for r in conn.execute(
            "SELECT id, flush_status FROM notifications_digest_queue"
        ).fetchall()
    }
    # ALL rows remain pending — neither included nor overflow marked sent.
    for rid in ids:
        assert statuses[rid] == "pending", (
            f"row {rid} should stay pending on SMTP failure, got {statuses[rid]}"
        )


# ── (f) Plain and HTML bodies have the same section headers ──────────────

def test_plain_and_html_bodies_contain_same_sections():
    """Both bodies should describe the same sections; HTML is just marked up."""
    from src.notifications.email_digest import render_digest

    rows = [
        {
            "id": 1,
            "event_type": "action_packet",
            "severity": "normal",
            "source_tag": "email:postclose",
            "flush_attempts": 0,
            "payload": {"ticker": "AAPL", "summary": "buy 100"},
        },
    ]
    subject, plain, html, overflow_ids = render_digest("postclose", rows=rows)
    # Section header should appear in both bodies (with or without HTML tags).
    assert "Action packets summarized" in plain
    assert "Action packets summarized" in html
    # Ticker should appear in both.
    assert "AAPL" in plain
    assert "AAPL" in html


# ── (g) DD-33: empty pre-open with no replays → suppressed (no email) ────

def test_empty_preopen_with_zero_events_and_zero_replays_suppressed(monkeypatch):
    """DD-33: zero events + zero critical replays + send_when_empty=False →
    NO send_email; dedup-suppressed row written."""
    from src.notifications import email_digest

    conn = _make_conn()
    monkeypatch.setattr(email_digest, "load_config",
                        lambda: _fake_config(preopen_send_when_empty=False),
                        raising=False)
    sent = {"called": False}
    monkeypatch.setattr(
        email_digest, "send_email",
        lambda *a, **kw: (sent.__setitem__("called", True) or True),
        raising=False,
    )

    email_digest.flush_tier("preopen", conn=conn)
    assert sent["called"] is False
    # Dedup-suppressed marker row exists (event_type='digest_suppressed_empty').
    rows = conn.execute(
        "SELECT * FROM notifications_dedup "
        "WHERE event_type='digest_suppressed_empty'"
    ).fetchall()
    assert len(rows) == 1


# ── (h) DD-33 inverse: send_when_empty=True still sends ──────────────────

def test_empty_postclose_with_send_when_empty_true_still_sends(monkeypatch):
    """DD-33 inverse: send_when_empty=True allows the empty digest to ship."""
    from src.notifications import email_digest

    conn = _make_conn()
    monkeypatch.setattr(email_digest, "load_config",
                        lambda: _fake_config(postclose_send_when_empty=True),
                        raising=False)
    sent = {"called": False}
    monkeypatch.setattr(
        email_digest, "send_email",
        lambda *a, **kw: (sent.__setitem__("called", True) or True),
        raising=False,
    )

    email_digest.flush_tier("postclose", conn=conn)
    assert sent["called"] is True


# ── (i) DA-MAJ-12: subject uses 'Pre-Open', never 'Pre-Market' ───────────

def test_preopen_subject_uses_pre_open_not_pre_market():
    """DA-MAJ-12 terminology lock: subjects + logs use 'Pre-Open' exclusively."""
    from src.notifications.email_digest import render_digest

    conn = _make_conn()
    _enqueue(
        conn,
        event_type="morning_watchlist",
        severity="normal",
        payload={"tickers": ["AAPL", "MSFT"]},
        source_tag="email:preopen",
    )

    rows = [{
        "id": 1,
        "event_type": "morning_watchlist",
        "severity": "normal",
        "source_tag": "email:preopen",
        "flush_attempts": 0,
        "payload": {"tickers": ["AAPL", "MSFT"]},
    }]
    subject, plain, html, overflow_ids = render_digest(
        "preopen", rows=rows, conn=conn,
    )
    assert "Pre-Open" in subject
    assert "Pre-Market" not in subject
    # And body too — terminology lock includes the rendered body.
    assert "Pre-Market" not in html


# ── (j) DA-MIN-17: concurrent enqueue during flush doesn't corrupt ───────

def test_concurrent_enqueue_during_flush_does_not_corrupt(monkeypatch, tmp_path):
    """DA-MIN-17: a 07:25 ET CRITICAL enqueue racing 07:30 ET flush should
    either land in this flush OR stay pending — never corrupt the digest.

    Simulated here via a sequential timeline (the actual isolation_level lock
    is a single-process concern; the contract is: render result is deterministic
    regardless of whether the row was already in the queue when render started).
    """
    from src.notifications.email_digest import render_digest

    conn = _make_conn()
    # Pre-existing row (already in queue when flush "starts")
    _enqueue(
        conn,
        event_type="audit_critical",
        severity="critical",
        payload={"category": "risk_A", "description": "first row"},
        source_tag="email:preopen:critical-overflow",
    )

    # First render: should see ONE critical
    subject1, plain1, html1, _ = render_digest("preopen", rows=[], conn=conn)
    assert "risk_A" in html1

    # Simulate concurrent enqueue mid-flush — a new row lands after first read.
    _enqueue(
        conn,
        event_type="audit_critical",
        severity="critical",
        payload={"category": "risk_B", "description": "racy row"},
        source_tag="email:preopen:critical-overflow",
    )

    # Next render reads both deterministically — no corruption.
    subject2, plain2, html2, _ = render_digest("preopen", rows=[], conn=conn)
    assert "risk_A" in html2
    assert "risk_B" in html2
