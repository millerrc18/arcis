"""T8 — scheduler integration for email digest tiers (#115).

Per spec Section 9.1 + DD-07 (per-tier enabled), DD-20 revised (dual-write
hold-over modes: shadow / time_aligned / off), DD-21 (holiday skip for daily
tiers, NOT weekly).

Verifies the rewritten `_check_digest_schedule` and the new Sunday-18:00-ET
weekly branch in the main loop:

  (a) preopen fires at 07:30 ET on weekdays
  (b) preopen skipped on market holidays
  (c) postclose fires at 17:00 ET on weekdays
  (d) weekly fires Sunday 18:00 ET
  (e) done-flag prevents same-day re-fire
  (f) per-tier `enabled: false` skips flush
  (g) holdover mode='shadow': OLD path still emails (new path writes
      shadow only inside flush_tier — verified by flush_tier being called
      AND old send_email continuing to fire)
  (h) holdover mode='time_aligned': OLD midday + evening SUPPRESSED
  (i) holdover mode='off': OLD branches FULLY suppressed
"""

from collections import deque
from datetime import datetime, date
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")


# ---------------------------------------------------------------------------
# Test scaffolding — bare WatchLoop without heavy __init__ side-effects
# ---------------------------------------------------------------------------


def _make_watch_loop(
    email_mode: str = "digest",
    *,
    tier_times: dict | None = None,
    tiers: dict | None = None,
    holidays: dict | None = None,
    holdover: dict | None = None,
):
    """Construct a bare WatchLoop with the state _check_digest_schedule reads."""
    from src.scheduler.watch import WatchLoop

    wl = WatchLoop.__new__(WatchLoop)
    wl._backoff = {}
    wl._consecutive_errors = 0
    wl._error_timestamps = deque(maxlen=20)
    wl._hourly_alert_sent = False
    wl.email_mode = email_mode

    wl.config = {
        "email": {
            "tier_times": tier_times or {
                "preopen": "07:30",
                "postclose": "17:00",
                "weekly": "Sun 18:00",
            },
            "tiers": tiers or {
                "preopen": {"enabled": True, "send_when_empty": False},
                "postclose": {"enabled": True, "send_when_empty": False},
                "weekly": {"enabled": True, "send_when_empty": True},
            },
            "holidays": holidays or {
                "skip_preopen_on_market_holidays": True,
                "skip_postclose_on_market_holidays": True,
            },
            "dual_write_hold_over": holdover or {
                "enabled": True,
                "mode": "shadow",
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

    # Done-flags the new + old paths consult.
    wl._digest_preopen_done = False
    wl._digest_postclose_done = False
    wl._digest_weekly_done = False
    wl._digest_premarket_done = False
    wl._digest_midday_done = False
    wl._digest_eod_done = False
    wl._digest_evening_done = False

    # Injectable clock seam (so the new code uses self._clock())
    wl._clock = lambda: datetime.now(ET)

    return wl


# ---------------------------------------------------------------------------
# (a) preopen fires at 07:30 weekday
# ---------------------------------------------------------------------------


def test_preopen_fires_at_0730_weekday():
    """At 07:30 ET on a non-holiday weekday with mode='shadow', flush_tier
    is called with tier='preopen' and the done-flag is set."""
    wl = _make_watch_loop()
    # Tuesday 2026-05-26 (not a holiday)
    now = datetime(2026, 5, 26, 7, 32, tzinfo=ET)
    wl._clock = lambda: now

    with patch("src.notifications.email_digest.flush_tier") as mock_flush, \
         patch("src.scheduler.holidays.is_market_holiday", return_value=False):
        wl._check_digest_schedule()

    flush_tier_calls = [c for c in mock_flush.call_args_list
                        if c.kwargs.get("tier") == "preopen"
                        or (c.args and c.args[0] == "preopen")]
    assert flush_tier_calls, (
        f"flush_tier('preopen') was not called. Calls: {mock_flush.call_args_list}"
    )
    assert wl._digest_preopen_done is True


# ---------------------------------------------------------------------------
# (b) preopen skipped on market holiday
# ---------------------------------------------------------------------------


def test_preopen_skipped_on_market_holiday():
    """DD-21: when today is a market holiday and
    skip_preopen_on_market_holidays=True, flush_tier(preopen) is NOT called
    and the done-flag stays False."""
    wl = _make_watch_loop()
    now = datetime(2026, 5, 26, 7, 32, tzinfo=ET)
    wl._clock = lambda: now

    with patch("src.notifications.email_digest.flush_tier") as mock_flush, \
         patch("src.scheduler.holidays.is_market_holiday", return_value=True):
        wl._check_digest_schedule()

    preopen_calls = [
        c for c in mock_flush.call_args_list
        if (c.args and c.args[0] == "preopen")
        or c.kwargs.get("tier") == "preopen"
    ]
    assert not preopen_calls, (
        "flush_tier('preopen') fired on a market holiday — DD-21 violated."
    )
    assert wl._digest_preopen_done is False


# ---------------------------------------------------------------------------
# (c) postclose fires at 17:00 weekday
# ---------------------------------------------------------------------------


def test_postclose_fires_at_1700_weekday():
    """At 17:00 ET on a non-holiday weekday, flush_tier(postclose) fires."""
    wl = _make_watch_loop()
    now = datetime(2026, 5, 26, 17, 3, tzinfo=ET)
    wl._clock = lambda: now

    with patch("src.notifications.email_digest.flush_tier") as mock_flush, \
         patch("src.scheduler.holidays.is_market_holiday", return_value=False):
        wl._check_digest_schedule()

    postclose_calls = [
        c for c in mock_flush.call_args_list
        if (c.args and c.args[0] == "postclose")
        or c.kwargs.get("tier") == "postclose"
    ]
    assert postclose_calls, (
        f"flush_tier('postclose') was not called. Calls: {mock_flush.call_args_list}"
    )
    assert wl._digest_postclose_done is True


# ---------------------------------------------------------------------------
# (d) weekly fires Sunday 18:00 ET
# ---------------------------------------------------------------------------


def test_weekly_fires_sun_1800():
    """DD-21: weekly does NOT honor holiday skip (Sundays are non-trading
    anyway). At Sun 18:00 ET, flush_tier(weekly) fires.

    The weekly branch lives in the main loop (after research_synthesis).
    The branch delegates to `_maybe_flush_email_weekly_tier` which this
    test exercises directly with the same Sunday-18:00 fixture the
    main-loop gate uses."""
    wl = _make_watch_loop()
    # Sunday 2026-05-24 18:02
    now = datetime(2026, 5, 24, 18, 2, tzinfo=ET)
    assert now.weekday() == 6, "test fixture must be a Sunday"
    wl._clock = lambda: now

    with patch("src.notifications.email_digest.flush_tier") as mock_flush:
        wl._maybe_flush_email_weekly_tier(now)

    weekly_calls = [
        c for c in mock_flush.call_args_list
        if (c.args and c.args[0] == "weekly")
        or c.kwargs.get("tier") == "weekly"
    ]
    assert weekly_calls, (
        f"flush_tier('weekly') was not called at Sun 18:00. "
        f"Calls: {mock_flush.call_args_list}"
    )
    assert wl._digest_weekly_done is True


# ---------------------------------------------------------------------------
# (e) done-flag prevents same-day re-fire
# ---------------------------------------------------------------------------


def test_done_flag_prevents_refire_same_day():
    """Once _digest_preopen_done = True, subsequent calls inside the 5-min
    window MUST NOT re-invoke flush_tier."""
    wl = _make_watch_loop()
    now = datetime(2026, 5, 26, 7, 32, tzinfo=ET)
    wl._clock = lambda: now
    wl._digest_preopen_done = True  # already fired earlier

    with patch("src.notifications.email_digest.flush_tier") as mock_flush, \
         patch("src.scheduler.holidays.is_market_holiday", return_value=False):
        wl._check_digest_schedule()

    preopen_calls = [
        c for c in mock_flush.call_args_list
        if (c.args and c.args[0] == "preopen")
        or c.kwargs.get("tier") == "preopen"
    ]
    assert not preopen_calls, (
        "Re-fired flush_tier('preopen') despite done-flag being True."
    )


# ---------------------------------------------------------------------------
# (f) tier-disabled skips flush
# ---------------------------------------------------------------------------


def test_tier_disabled_skips_flush():
    """DD-07: when email.tiers.preopen.enabled=false, flush_tier(preopen)
    MUST NOT be called even at the canonical time."""
    wl = _make_watch_loop(
        tiers={
            "preopen": {"enabled": False, "send_when_empty": False},
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
    assert not preopen_calls, (
        "flush_tier('preopen') fired despite tiers.preopen.enabled=false."
    )
    assert wl._digest_preopen_done is False


# ---------------------------------------------------------------------------
# (g) DA-CRIT-1: holdover mode='shadow' → OLD path STILL emails
# ---------------------------------------------------------------------------


def test_holdover_shadow_mode_old_path_still_emails():
    """DA-CRIT-1: in mode='shadow', flush_tier writes shadow files (verified
    by being called) AND the old digest_builder send_email path also fires
    at its canonical legacy times. Operator inbox volume UNCHANGED.

    Legacy premarket time = 07:30 → matches preopen — both paths run.
    """
    wl = _make_watch_loop()  # default holdover mode = "shadow"
    now = datetime(2026, 5, 26, 7, 32, tzinfo=ET)
    wl._clock = lambda: now

    with patch("src.notifications.email_digest.flush_tier") as mock_flush, \
         patch("src.email.notifier.send_email") as mock_send, \
         patch("src.email.digest_builder.build_premarket_digest",
               return_value=("subj", "body")), \
         patch("src.scheduler.holidays.is_market_holiday", return_value=False):
        wl._check_digest_schedule()

    # New aggregator fired
    preopen_calls = [
        c for c in mock_flush.call_args_list
        if (c.args and c.args[0] == "preopen")
        or c.kwargs.get("tier") == "preopen"
    ]
    assert preopen_calls, "flush_tier('preopen') was not called in shadow mode."

    # OLD path STILL emails — operator inbox UNCHANGED in shadow mode
    assert mock_send.called, (
        "In mode='shadow' the OLD digest_builder send_email MUST still fire "
        "(operator inbox unchanged per DD-20 revised / DA-CRIT-1)."
    )


# ---------------------------------------------------------------------------
# (h) holdover mode='time_aligned' → OLD midday + evening SUPPRESSED
# ---------------------------------------------------------------------------


def test_holdover_time_aligned_mode_suppresses_midday_evening():
    """DD-20 revised: in mode='time_aligned', OLD midday (12:00) and
    OLD evening (20:00) branches are SUPPRESSED. Preopen + EOD still
    fire from the old path. New flush_tier sends real email at canonical
    tier times."""
    wl = _make_watch_loop(
        holdover={
            "enabled": True,
            "mode": "time_aligned",
            "shadow_output_dir": "tmp/digest-shadow",
        },
    )
    now = datetime(2026, 5, 26, 12, 1, tzinfo=ET)  # legacy midday window
    wl._clock = lambda: now

    with patch("src.notifications.email_digest.flush_tier") as mock_flush, \
         patch("src.email.notifier.send_email") as mock_send, \
         patch("src.email.digest_builder.build_midday_digest",
               return_value=("subj", "body")), \
         patch("src.scheduler.holidays.is_market_holiday", return_value=False):
        wl._check_digest_schedule()

    # OLD midday branch suppressed: send_email MUST NOT have been called
    assert not mock_send.called, (
        "OLD midday send_email fired despite mode='time_aligned' "
        "(DD-20 revised: midday + evening must be suppressed)."
    )


# ---------------------------------------------------------------------------
# (i) holdover mode='off' → OLD branches FULLY suppressed
# ---------------------------------------------------------------------------


def test_holdover_off_mode_only_new_aggregator_fires():
    """DD-20 revised: in mode='off', OLD digest_builder branches fully
    suppressed. Only the new flush_tier path fires (and inside flush_tier,
    it does a real send_email — not the legacy digest_builder send)."""
    wl = _make_watch_loop(
        holdover={
            "enabled": True,
            "mode": "off",
            "shadow_output_dir": "tmp/digest-shadow",
        },
    )
    now = datetime(2026, 5, 26, 7, 32, tzinfo=ET)  # legacy premarket window
    wl._clock = lambda: now

    with patch("src.notifications.email_digest.flush_tier") as mock_flush, \
         patch("src.email.notifier.send_email") as mock_send, \
         patch("src.email.digest_builder.build_premarket_digest",
               return_value=("subj", "body")), \
         patch("src.scheduler.holidays.is_market_holiday", return_value=False):
        wl._check_digest_schedule()

    # New aggregator fired
    preopen_calls = [
        c for c in mock_flush.call_args_list
        if (c.args and c.args[0] == "preopen")
        or c.kwargs.get("tier") == "preopen"
    ]
    assert preopen_calls, "flush_tier('preopen') was not called in mode='off'."

    # OLD digest_builder send_email branch suppressed
    assert not mock_send.called, (
        "OLD digest_builder send_email fired despite mode='off' "
        "(DD-20 revised: OLD paths fully retired in 'off' mode)."
    )
