"""Market-holiday skip tests for email_digest.flush_tier (#115 T17).

DD-23 (revised): ``email.holidays.skip_preopen_on_market_holidays`` and
``email.holidays.skip_postclose_on_market_holidays`` (both default True)
gate whether flush_tier should suppress dispatch on full NYSE closures.

The weekly tier ALWAYS fires on its scheduled Sunday — Sunday is never a
market trading day, so a "market holiday" on a weekday has no impact on
the weekly digest cadence (DD-23 — weekly is calendar-based, not
trading-calendar-based).

Defensive depth: holiday skip is also enforced at the scheduler layer
(`src/scheduler/watch.py::_check_digest_schedule`). flush_tier checks
again so the contract is preserved when called from any caller (CLI,
service, scheduler) — not just the watch loop.
"""

from __future__ import annotations

import sqlite3
from unittest.mock import patch

import pytest


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


def _config(tmp_path, *, skip_preopen=True, skip_postclose=True, mode="off"):
    """Config object load_config() returns. mode='off' so flush_tier calls
    real send_email path (the path we MUST suppress on holidays)."""
    return {
        "email": {
            "tier_times": {
                "preopen": "07:30", "postclose": "17:00", "weekly": "Sun 18:00",
            },
            "tiers": {
                "preopen": {"enabled": True, "send_when_empty": True},
                "postclose": {"enabled": True, "send_when_empty": True},
                "weekly": {"enabled": True, "send_when_empty": True},
            },
            "holidays": {
                "skip_preopen_on_market_holidays": skip_preopen,
                "skip_postclose_on_market_holidays": skip_postclose,
            },
            "dual_write_hold_over": {
                "enabled": True,
                "mode": mode,
                "shadow_output_dir": str(tmp_path),
            },
        }
    }


def _enqueue_row(conn, *, event_type, source_tag, severity="normal"):
    conn.execute(
        "INSERT INTO notifications_digest_queue (event_type, severity, "
        "payload_json, source_tag) VALUES (?, ?, ?, ?)",
        (event_type, severity, "{}", source_tag),
    )
    conn.commit()


# ── (1) preopen skipped on market holiday ─────────────────────────────────

def test_preopen_skipped_on_market_holiday(tmp_path, monkeypatch):
    """DD-23: with skip_preopen_on_market_holidays=True and a market
    holiday in effect, flush_tier('preopen') MUST return without invoking
    send_email AND MUST leave queued rows as flush_status='pending'."""
    from src.notifications import email_digest

    monkeypatch.setattr(
        email_digest, "load_config", lambda: _config(tmp_path),
        raising=False,
    )
    send_count = {"n": 0}
    monkeypatch.setattr(
        email_digest, "send_email",
        lambda *a, **kw: (send_count.__setitem__("n", send_count["n"] + 1) or True),
        raising=False,
    )

    conn = _make_conn()
    _enqueue_row(conn, event_type="morning_watchlist", source_tag="email:preopen")
    _enqueue_row(conn, event_type="audit_critical", source_tag="email:preopen")

    with patch(
        "src.scheduler.holidays.is_market_holiday", return_value=True,
    ):
        email_digest.flush_tier("preopen", conn=conn)

    assert send_count["n"] == 0, (
        f"flush_tier('preopen') called send_email {send_count['n']} time(s) "
        f"on a market holiday — DD-23 requires suppression"
    )

    pending = conn.execute(
        "SELECT COUNT(*) FROM notifications_digest_queue "
        "WHERE flush_status='pending'"
    ).fetchone()[0]
    assert pending == 2, (
        f"Expected 2 rows to remain pending after holiday skip, got {pending}"
    )


# ── (2) postclose skipped on market holiday ───────────────────────────────

def test_postclose_skipped_on_market_holiday(tmp_path, monkeypatch):
    """DD-23: with skip_postclose_on_market_holidays=True and a market
    holiday in effect, flush_tier('postclose') MUST return without invoking
    send_email."""
    from src.notifications import email_digest

    monkeypatch.setattr(
        email_digest, "load_config", lambda: _config(tmp_path),
        raising=False,
    )
    send_count = {"n": 0}
    monkeypatch.setattr(
        email_digest, "send_email",
        lambda *a, **kw: (send_count.__setitem__("n", send_count["n"] + 1) or True),
        raising=False,
    )

    conn = _make_conn()
    _enqueue_row(conn, event_type="action_packet", source_tag="email:postclose")

    with patch(
        "src.scheduler.holidays.is_market_holiday", return_value=True,
    ):
        email_digest.flush_tier("postclose", conn=conn)

    assert send_count["n"] == 0, (
        f"flush_tier('postclose') called send_email {send_count['n']} "
        f"time(s) on a market holiday — DD-23 requires suppression"
    )

    pending = conn.execute(
        "SELECT COUNT(*) FROM notifications_digest_queue "
        "WHERE flush_status='pending'"
    ).fetchone()[0]
    assert pending == 1


# ── (3) weekly fires regardless of holiday ────────────────────────────────

def test_weekly_fires_regardless_of_holiday(tmp_path, monkeypatch):
    """DD-23: the weekly tier (Sun 18:00 ET) MUST fire even if
    is_market_holiday returns True. The weekly is calendar-based, not
    trading-calendar-based. Sundays are never trading days anyway, so
    a 'market holiday' on a weekday has no bearing on the weekly cadence.
    """
    from src.notifications import email_digest

    monkeypatch.setattr(
        email_digest, "load_config", lambda: _config(tmp_path),
        raising=False,
    )
    send_count = {"n": 0}
    monkeypatch.setattr(
        email_digest, "send_email",
        lambda *a, **kw: (send_count.__setitem__("n", send_count["n"] + 1) or True),
        raising=False,
    )

    conn = _make_conn()
    _enqueue_row(
        conn,
        event_type="weekly_digest_content",
        source_tag="email:weekly",
    )

    with patch(
        "src.scheduler.holidays.is_market_holiday", return_value=True,
    ):
        email_digest.flush_tier("weekly", conn=conn)

    assert send_count["n"] == 1, (
        f"flush_tier('weekly') did NOT fire on a (fake) market holiday "
        f"day — DD-23 says weekly is independent of trading calendar. "
        f"send_email calls: {send_count['n']}"
    )


# ── (4) holiday-skip disabled in config → still fires ────────────────────

def test_holiday_skip_disabled_in_config_still_fires(tmp_path, monkeypatch):
    """DD-23 + config override: with skip_preopen_on_market_holidays=False
    in config, flush_tier('preopen') MUST fire even on a market holiday.
    The flag is an explicit operator opt-out for that specific behavior.
    """
    from src.notifications import email_digest

    monkeypatch.setattr(
        email_digest, "load_config",
        lambda: _config(tmp_path, skip_preopen=False, skip_postclose=False),
        raising=False,
    )
    send_count = {"n": 0}
    monkeypatch.setattr(
        email_digest, "send_email",
        lambda *a, **kw: (send_count.__setitem__("n", send_count["n"] + 1) or True),
        raising=False,
    )

    conn = _make_conn()
    _enqueue_row(conn, event_type="morning_watchlist", source_tag="email:preopen")

    with patch(
        "src.scheduler.holidays.is_market_holiday", return_value=True,
    ):
        email_digest.flush_tier("preopen", conn=conn)

    assert send_count["n"] == 1, (
        f"skip_preopen_on_market_holidays=False but flush_tier('preopen') "
        f"still suppressed dispatch on a holiday. send_email calls: "
        f"{send_count['n']}"
    )
