"""Opt-out tests for email tier scheduling (#115 T16, DD-07).

The per-tier ``email.tiers.<tier>.enabled`` flag MUST gate the scheduler's
flush_tier dispatch. When a tier is disabled:

  - The scheduler MUST NOT call flush_tier for that tier (even at the canonical
    time, even on a weekday, even off a holiday).
  - The aggregator's ``enqueue_for_email_digest`` API MUST still accept new
    events — they remain queued as 'pending' so that re-enabling the tier
    drains the backlog on the next flush tick.

Fixture pattern mirrors tests/scheduler/test_watch_email_digest_schedule.py
``_make_watch_loop`` (existing T8 pattern), plus _make_conn() from
tests/notifications/test_digest_queue.py:15-51 for backlog assertions.
"""

from __future__ import annotations

import sqlite3
from collections import deque
from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest


ET = ZoneInfo("America/New_York")


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
    conn.commit()
    return conn


def _default_notifications_config():
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


def _make_watch_loop(
    email_mode: str = "digest",
    *,
    tiers: dict | None = None,
):
    """Bare WatchLoop with the state _check_digest_schedule reads.

    Mirrors tests/scheduler/test_watch_email_digest_schedule.py::_make_watch_loop.
    """
    from src.scheduler.watch import WatchLoop

    wl = WatchLoop.__new__(WatchLoop)
    wl._backoff = {}
    wl._consecutive_errors = 0
    wl._error_timestamps = deque(maxlen=20)
    wl._hourly_alert_sent = False
    wl.email_mode = email_mode

    wl.config = {
        "email": {
            "tier_times": {
                "preopen": "07:30",
                "postclose": "17:00",
                "weekly": "Sun 18:00",
            },
            "tiers": tiers or {
                "preopen": {"enabled": True, "send_when_empty": False},
                "postclose": {"enabled": True, "send_when_empty": False},
                "weekly": {"enabled": True, "send_when_empty": True},
            },
            "holidays": {
                "skip_preopen_on_market_holidays": True,
                "skip_postclose_on_market_holidays": True,
            },
            "dual_write_hold_over": {
                "enabled": True,
                "mode": "off",  # use 'off' so only the new path is in scope
                "shadow_output_dir": "tmp/digest-shadow",
            },
            "digest_times": {
                "premarket": "07:30",
                "midday": "12:00",
                "eod": "16:15",
                "evening": "20:00",
            },
        },
    }

    # Done-flags both paths consult.
    wl._digest_preopen_done = False
    wl._digest_postclose_done = False
    wl._digest_weekly_done = False
    wl._digest_premarket_done = False
    wl._digest_midday_done = False
    wl._digest_eod_done = False
    wl._digest_evening_done = False

    wl._clock = lambda: datetime.now(ET)
    return wl


# ── (1) preopen disabled skips flush but enqueues ────────────────────────

def test_preopen_disabled_skips_flush_but_enqueues():
    """DD-07: When tiers.preopen.enabled=False, the scheduler MUST NOT call
    flush_tier('preopen') at 07:30 ET. The aggregator's enqueue path MUST
    still accept new events so they queue up for the next enabled flush.
    """
    from src.notifications.email_digest import enqueue_for_email_digest

    wl = _make_watch_loop(
        tiers={
            "preopen": {"enabled": False, "send_when_empty": False},
            "postclose": {"enabled": True, "send_when_empty": False},
            "weekly": {"enabled": True, "send_when_empty": True},
        },
    )
    now = datetime(2026, 5, 26, 7, 32, tzinfo=ET)  # 07:32 = within 07:30 window
    wl._clock = lambda: now

    with patch("src.notifications.email_digest.flush_tier") as mock_flush, \
         patch("src.scheduler.holidays.is_market_holiday", return_value=False):
        wl._check_digest_schedule()

    preopen_calls = [
        c for c in mock_flush.call_args_list
        if (c.args and c.args[0] == "preopen")
        or c.kwargs.get("tier") == "preopen"
    ]
    assert not preopen_calls, (
        "flush_tier('preopen') fired despite tiers.preopen.enabled=False."
    )

    # Enqueue still works — the aggregator's API does NOT gate on enabled.
    conn = _make_conn()
    config = _default_notifications_config()
    row_id = enqueue_for_email_digest(
        "morning_watchlist",
        severity="normal",
        payload={"tickers": ["AAPL"]},
        conn=conn,
        config=config,
    )
    assert row_id is not None, (
        "enqueue_for_email_digest returned None — backlog-while-disabled broken"
    )
    row = conn.execute(
        "SELECT flush_status, source_tag FROM notifications_digest_queue WHERE id=?",
        (row_id,),
    ).fetchone()
    assert row["flush_status"] == "pending"
    assert row["source_tag"] == "email:preopen"


# ── (2) all tiers disabled → no email sent ───────────────────────────────

def test_all_tiers_disabled_no_email_sent():
    """When all three tiers (preopen, postclose, weekly) are disabled, the
    scheduler MUST NOT invoke flush_tier for any tier across a full
    weekday + Sunday sweep. This is the operator's escape hatch when they
    want to silence all digest emails without uninstalling the watch loop.
    """
    tiers_all_off = {
        "preopen": {"enabled": False, "send_when_empty": False},
        "postclose": {"enabled": False, "send_when_empty": False},
        "weekly": {"enabled": False, "send_when_empty": True},
    }
    wl = _make_watch_loop(tiers=tiers_all_off)

    # Weekday 07:30 (preopen window)
    wl._clock = lambda: datetime(2026, 5, 26, 7, 32, tzinfo=ET)
    with patch("src.notifications.email_digest.flush_tier") as mock_flush, \
         patch("src.scheduler.holidays.is_market_holiday", return_value=False):
        wl._check_digest_schedule()
    assert mock_flush.call_count == 0, (
        f"flush_tier fired at 07:32 despite all tiers disabled; calls: "
        f"{mock_flush.call_args_list}"
    )

    # Weekday 17:00 (postclose window) — fresh WatchLoop so done-flags clean.
    wl2 = _make_watch_loop(tiers=tiers_all_off)
    wl2._clock = lambda: datetime(2026, 5, 26, 17, 3, tzinfo=ET)
    with patch("src.notifications.email_digest.flush_tier") as mock_flush, \
         patch("src.scheduler.holidays.is_market_holiday", return_value=False):
        wl2._check_digest_schedule()
    assert mock_flush.call_count == 0, (
        f"flush_tier fired at 17:03 despite all tiers disabled; calls: "
        f"{mock_flush.call_args_list}"
    )

    # Sunday 18:02 (weekly window).
    wl3 = _make_watch_loop(tiers=tiers_all_off)
    sunday = datetime(2026, 5, 24, 18, 2, tzinfo=ET)
    assert sunday.weekday() == 6
    wl3._clock = lambda: sunday
    with patch("src.notifications.email_digest.flush_tier") as mock_flush:
        wl3._maybe_flush_email_weekly_tier(sunday)
    assert mock_flush.call_count == 0, (
        f"flush_tier('weekly') fired despite all tiers disabled; calls: "
        f"{mock_flush.call_args_list}"
    )


# ── (3) tier re-enabled drains backlog ───────────────────────────────────

def test_tier_re_enabled_drains_backlog():
    """When preopen is disabled, events still queue. On re-enable, the next
    scheduler tick at 07:30 calls flush_tier('preopen') which (per DD-27 +
    DD-34) reads the canonical queue rows and dispatches them as a digest.
    This test pins the wire-up: flush_tier is called when the tier flips
    from disabled → enabled.
    """
    from src.notifications.email_digest import enqueue_for_email_digest

    # Phase 1: tier disabled — accumulate a backlog of queued rows.
    conn = _make_conn()
    config = _default_notifications_config()
    for ticker in ("AAPL", "MSFT", "GOOG"):
        enqueue_for_email_digest(
            "morning_watchlist",
            severity="normal",
            payload={"tickers": [ticker]},
            conn=conn,
            config=config,
        )
    backlog_before = conn.execute(
        "SELECT COUNT(*) AS c FROM notifications_digest_queue "
        "WHERE flush_status='pending' AND source_tag='email:preopen'"
    ).fetchone()["c"]
    assert backlog_before == 3, (
        f"setup precondition: expected 3 queued rows, got {backlog_before}"
    )

    # Phase 2: tier re-enabled — scheduler tick MUST call flush_tier(preopen).
    wl = _make_watch_loop(
        tiers={
            "preopen": {"enabled": True, "send_when_empty": False},  # re-enabled
            "postclose": {"enabled": True, "send_when_empty": False},
            "weekly": {"enabled": True, "send_when_empty": True},
        },
    )
    now = datetime(2026, 5, 26, 7, 32, tzinfo=ET)
    wl._clock = lambda: now

    with patch("src.notifications.email_digest.flush_tier") as mock_flush, \
         patch("src.scheduler.holidays.is_market_holiday", return_value=False):
        wl._check_digest_schedule()

    preopen_calls = [
        c for c in mock_flush.call_args_list
        if (c.args and c.args[0] == "preopen")
        or c.kwargs.get("tier") == "preopen"
    ]
    assert preopen_calls, (
        f"flush_tier('preopen') did NOT fire on re-enable. Calls: "
        f"{mock_flush.call_args_list}"
    )
    assert wl._digest_preopen_done is True
