"""Tests for src/notifications/email_digest.py weekly-tier rendering (#115 T7).

Covers _collect_weekly_data and _render_weekly_html. The weekly tier subsumes
the deprecated Saturday training + CTO reports and adds research synthesis +
audit week-in-review. Spec sections 5.1 + 6.5 + DD-33.

Tests are isolated against in-memory sqlite — no production-PG side-effects.
Run with `DATABASE_URL= python -m pytest tests/notifications/test_email_digest_render_weekly.py -v`.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest


# ── Shared test scaffolding ────────────────────────────────────────────────

def _make_conn():
    """In-memory sqlite with all tables the weekly tier queries.

    Tables: notifications_digest_queue, shadow_trades, training_examples,
    canary_evaluations, api_costs, notifications_sent, notifications_dedup.
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
        CREATE TABLE training_examples (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT,
            quality_score_auto REAL,
            created_at TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE canary_evaluations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            model_name TEXT,
            status TEXT,
            created_at TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE api_costs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            provider TEXT,
            cost_dollars REAL,
            created_at TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE notifications_sent (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel TEXT,
            event_type TEXT,
            severity TEXT,
            payload_json TEXT,
            status TEXT,
            sent_at TEXT
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


def _add_closed_trade(conn, *, trade_id, ticker, pnl_dollars, pnl_pct, days_ago=1):
    """Insert a closed shadow_trade with actual_exit_time = N days ago."""
    exit_time = (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()
    conn.execute(
        "INSERT INTO shadow_trades "
        "(trade_id, ticker, status, exit_reason, actual_exit_time, "
        " entry_price, pnl_dollars, pnl_pct, source, created_at, quarantined) "
        "VALUES (?, ?, 'closed', 'tp_hit', ?, 100.0, ?, ?, 'paper', ?, 0)",
        (trade_id, ticker, exit_time, pnl_dollars, pnl_pct, exit_time),
    )
    conn.commit()


def _add_notification_sent(conn, *, event_type, severity, days_ago=1):
    sent_at = (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()
    conn.execute(
        "INSERT INTO notifications_sent (channel, event_type, severity, payload_json, status, sent_at) "
        "VALUES ('email', ?, ?, '{}', 'ok', ?)",
        (event_type, severity, sent_at),
    )
    conn.commit()


def _fake_config(*, weekly_send_when_empty=True):
    return {
        "email": {
            "tier_times": {
                "preopen": "07:30",
                "postclose": "17:00",
                "weekly": "Sun 18:00",
            },
            "tiers": {
                "preopen": {"enabled": True, "send_when_empty": False},
                "postclose": {"enabled": True, "send_when_empty": False},
                "weekly": {"enabled": True, "send_when_empty": weekly_send_when_empty},
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


# ── (a) All 5 sections present with seeded data ──────────────────────────

def test_weekly_includes_all_5_sections():
    """Weekly tier renders 5 sections: Performance, Training, CTO, Research, Audit.

    Spec Section 5.1: the weekly tier subsumes saturday_training_report and
    saturday_cto_report content and adds research synthesis + audit week-in-
    review. All 5 section headers must appear in the rendered HTML body.
    """
    from src.notifications.email_digest import render_digest

    conn = _make_conn()

    # Section 1: Weekly performance — 3 closed trades in past 7 days
    _add_closed_trade(conn, trade_id="t1", ticker="AAPL", pnl_dollars=150.0, pnl_pct=2.5, days_ago=1)
    _add_closed_trade(conn, trade_id="t2", ticker="MSFT", pnl_dollars=-50.0, pnl_pct=-1.0, days_ago=2)
    _add_closed_trade(conn, trade_id="t3", ticker="GOOG", pnl_dollars=80.0, pnl_pct=1.2, days_ago=3)

    # Section 2: Training pipeline status
    now = datetime.now(timezone.utc)
    for i in range(5):
        ts = (now - timedelta(days=i)).isoformat()
        conn.execute(
            "INSERT INTO training_examples (source, quality_score_auto, created_at) "
            "VALUES (?, ?, ?)",
            ("paper", 0.75, ts),
        )
    conn.execute(
        "INSERT INTO canary_evaluations (model_name, status, created_at) VALUES (?, ?, ?)",
        ("llama-3-8b", "STABLE", now.isoformat()),
    )
    conn.commit()

    # Section 3: CTO report highlights — api_costs in past 7 days
    for i in range(3):
        ts = (now - timedelta(days=i)).isoformat()
        conn.execute(
            "INSERT INTO api_costs (provider, cost_dollars, created_at) VALUES (?, ?, ?)",
            ("anthropic", 1.25, ts),
        )
    conn.commit()

    # Section 4: Research synthesis — queued research_synthesis_email row
    _enqueue(
        conn,
        event_type="research_synthesis_email",
        severity="normal",
        payload={"title": "Q2 vol regime synthesis", "summary": "vol falling"},
        source_tag="email:weekly",
    )

    # Section 5: Audit week-in-review — CRITICAL + ALERT notifications_sent in past 7 days
    _add_notification_sent(conn, event_type="audit_critical", severity="critical", days_ago=1)
    _add_notification_sent(conn, event_type="audit_alert", severity="alert", days_ago=2)

    rows = [{
        "id": 1,
        "event_type": "research_synthesis_email",
        "severity": "normal",
        "source_tag": "email:weekly",
        "flush_attempts": 0,
        "payload": {"title": "Q2 vol regime synthesis", "summary": "vol falling"},
    }]

    subject, plain, html, overflow_ids = render_digest(
        "weekly", rows=rows, conn=conn,
    )

    # All 5 section headers MUST appear.
    assert "Weekly performance" in html, "Section 1 missing"
    assert "Training pipeline" in html, "Section 2 missing"
    assert "CTO report" in html, "Section 3 missing"
    assert "Research synthesis" in html, "Section 4 missing"
    assert "Audit week-in-review" in html, "Section 5 missing"


# ── (b) Subject format pattern ──────────────────────────────────────────

def test_weekly_subject_format():
    """Subject: 'Arcis Weekly — {Mon DD-Sun DD} | {N} trades, P&L: ${X} | Audit: {status}'."""
    from src.notifications.email_digest import render_digest

    conn = _make_conn()
    _add_closed_trade(conn, trade_id="t1", ticker="AAPL", pnl_dollars=100.0, pnl_pct=2.0, days_ago=1)
    _add_closed_trade(conn, trade_id="t2", ticker="MSFT", pnl_dollars=50.0, pnl_pct=1.0, days_ago=2)

    subject, plain, html, overflow_ids = render_digest(
        "weekly", rows=[], conn=conn,
    )

    assert subject.startswith("Arcis Weekly"), f"Subject prefix wrong: {subject!r}"
    assert "trades" in subject, f"trade-count missing: {subject!r}"
    assert "P&L" in subject or "P&amp;L" in subject, f"P&L missing: {subject!r}"
    assert "Audit" in subject, f"audit-status missing: {subject!r}"


# ── (c) Truncation when 50 trades closed → top-10 + overflow ───────────

def test_weekly_truncation_when_50_trades_closed():
    """50 closed trades → top-10 rendered + 40 overflow row IDs (DA-CRIT-2).

    Weekly tier uses the same top-K-by-severity truncation as preopen/postclose.
    Even though most weekly content is queries (not queue rows), if many queue
    rows accumulate (e.g. 50 packets queued for weekly), only top-10 render.
    """
    from src.notifications.email_digest import render_digest

    conn = _make_conn()

    # Build 50 queue rows tagged email:weekly (research_synthesis_email events).
    rows = []
    for i in range(50):
        rows.append({
            "id": 200 + i,
            "event_type": "research_synthesis_email",
            "severity": "normal",
            "source_tag": "email:weekly",
            "flush_attempts": 0,
            "payload": {"title": f"synth {i}", "summary": f"row {i}"},
        })

    subject, plain, html, overflow_ids = render_digest(
        "weekly", rows=rows, conn=conn, top_k=10,
    )

    # 40 overflow IDs returned (NOT marked sent — DA-CRIT-2).
    assert len(overflow_ids) == 40, f"expected 40 overflow, got {len(overflow_ids)}"
    assert overflow_ids == [200 + i for i in range(10, 50)]


# ── (d) Research synthesis section gracefully omitted when no events ──

def test_weekly_with_no_research_omits_section_gracefully():
    """When no research_synthesis_email events queued, the Research section
    must STILL appear with an explicit "no synthesis this week" message —
    not error, not omit silently."""
    from src.notifications.email_digest import render_digest

    conn = _make_conn()
    # NO research_synthesis_email rows queued. Other content optional.
    subject, plain, html, overflow_ids = render_digest(
        "weekly", rows=[], conn=conn,
    )

    # Research synthesis section header still present
    assert "Research synthesis" in html
    # And it explicitly says "no" / "none" content (graceful empty handling)
    assert ("No research synthesis" in html
            or "no synthesis" in html.lower()
            or "no research" in html.lower())


# ── (e) DD-33: weekly always sends even with no events ─────────────────

def test_weekly_always_sends_even_with_no_events(monkeypatch):
    """DD-33: weekly tier defaults to send_when_empty=true → empty queue +
    no critical replays still produces an email with rolling P&L content.
    Suppression rule explicitly DOES NOT apply to weekly tier."""
    from src.notifications import email_digest

    conn = _make_conn()

    monkeypatch.setattr(email_digest, "load_config",
                        lambda: _fake_config(weekly_send_when_empty=True),
                        raising=False)
    sent = {"called": False, "subject": None}

    def _fake_send_email(subject, body, *args, **kwargs):
        sent["called"] = True
        sent["subject"] = subject
        return True

    monkeypatch.setattr(email_digest, "send_email", _fake_send_email, raising=False)

    email_digest.flush_tier("weekly", conn=conn)
    # DD-33: weekly always sends → send_email IS called.
    assert sent["called"] is True
    # Subject still follows weekly pattern.
    assert "Weekly" in (sent["subject"] or "")


# ── (f) DOW-time parser sanity (parser lives in src/config) ─────────────

def test_weekly_dow_time_parser():
    """Parser already lives in src/config — verify it works for 'Sun 18:00'
    and raises ValueError for invalid 'Mon 25:99' (DA-NIT-20)."""
    from src.config import parse_weekly_tier_time

    # Valid: 'Sun 18:00' → (6, 18, 0)
    wd, h, m = parse_weekly_tier_time("Sun 18:00")
    assert (wd, h, m) == (6, 18, 0)

    # Invalid: hour out of range
    with pytest.raises(ValueError):
        parse_weekly_tier_time("Mon 25:99")


# ── (g) Rolling 7-day P&L computed correctly ──────────────────────────

def test_weekly_pnl_aggregates_past_7_days_only():
    """Performance section sums only trades closed in past 7 days; trades
    closed 8+ days ago are excluded from the P&L total."""
    from src.notifications.email_digest import render_digest

    conn = _make_conn()
    # Inside window (past 7 days)
    _add_closed_trade(conn, trade_id="recent1", ticker="AAPL", pnl_dollars=100.0, pnl_pct=2.0, days_ago=1)
    _add_closed_trade(conn, trade_id="recent2", ticker="MSFT", pnl_dollars=50.0, pnl_pct=1.0, days_ago=6)
    # Outside window (8+ days ago)
    _add_closed_trade(conn, trade_id="old1", ticker="OLD", pnl_dollars=99999.0, pnl_pct=200.0, days_ago=10)

    subject, plain, html, overflow_ids = render_digest(
        "weekly", rows=[], conn=conn,
    )

    # Subject embeds P&L of $150 (100 + 50), NOT $100,049
    assert "$150" in subject or "150" in subject, f"Expected P&L=150 in subject, got: {subject!r}"
    # The stale 8-day-old trade's P&L must NOT appear in subject totals
    assert "99999" not in subject
    # AAPL + MSFT tickers should appear in body, but OLD ticker should not
    assert "AAPL" in html
    assert "MSFT" in html
    assert "OLD" not in html


# ── (h) Defensive payload access — missing fields don't crash ─────────

def test_weekly_handles_research_payload_with_missing_fields():
    """DA-MIN-17: research_synthesis_email rows with missing 'title'/'summary'
    must NOT crash render_digest. Defaults via .get() are required."""
    from src.notifications.email_digest import render_digest

    conn = _make_conn()
    # Payload missing 'title' and 'summary'.
    rows = [{
        "id": 1,
        "event_type": "research_synthesis_email",
        "severity": "normal",
        "source_tag": "email:weekly",
        "flush_attempts": 0,
        "payload": {},   # Missing fields
    }]
    # Must not raise
    subject, plain, html, overflow_ids = render_digest(
        "weekly", rows=rows, conn=conn,
    )
    assert "Research synthesis" in html
