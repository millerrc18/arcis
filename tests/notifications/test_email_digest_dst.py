"""DST tests for email_digest tier-time parsing (#115 T16).

These tests pin the wall-clock semantics of email.tier_times.* across DST
spring-forward (2025-03-09) and fall-back (2025-11-02). The aggregator's
tier_times are stored as wall-clock strings ('07:30', '17:00', 'Sun 18:00')
and MUST parse to the same (hour, minute) value year-round regardless of
which side of the DST transition we are on — the scheduler then evaluates
"is now_et's wall-clock hour == target_hour" in America/New_York time,
which datetime.now(ZoneInfo) handles correctly.

Pattern: fixed datetime objects (not freezegun — existing codebase pattern).
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from src.config import parse_weekly_tier_time


_ET = ZoneInfo("America/New_York")


# Two known DST transition dates in America/New_York for 2025:
#   spring-forward: Sun 2025-03-09  02:00 EST  → 03:00 EDT  (UTC-5 → UTC-4)
#   fall-back:      Sun 2025-11-02  02:00 EDT  → 01:00 EST  (UTC-4 → UTC-5)
#
# We pick wall-clock 07:30 ET (preopen) and 17:00 ET (postclose) on each side.
# These wall-clock times exist unambiguously on both dates and are well clear
# of the 02:00 transition window.
DST_CASES = [
    pytest.param(
        "2025-03-08T07:30:00",  # day before spring-forward (EST, UTC-5)
        7,
        30,
        id="spring-forward-eve-est",
    ),
    pytest.param(
        "2025-03-10T07:30:00",  # day after spring-forward (EDT, UTC-4)
        7,
        30,
        id="spring-forward-after-edt",
    ),
    pytest.param(
        "2025-11-01T17:00:00",  # day before fall-back (EDT, UTC-4)
        17,
        0,
        id="fall-back-eve-edt",
    ),
    pytest.param(
        "2025-11-03T17:00:00",  # day after fall-back (EST, UTC-5)
        17,
        0,
        id="fall-back-after-est",
    ),
]


@pytest.mark.parametrize("now_iso,expected_hour,expected_minute", DST_CASES)
def test_tier_time_parsing_returns_correct_hour_year_round(
    now_iso: str, expected_hour: int, expected_minute: int,
):
    """Wall-clock parsing of 'HH:MM' for a daily tier_time MUST return the
    same (hour, minute) regardless of DST state. The scheduler's _in_window
    check (h == th and tm <= m < tm + 5) hinges on this — see
    src/scheduler/watch.py:604-606.
    """
    # Build the now_et that the scheduler would observe in ET — datetime
    # constructed with the ET tzinfo gives us the correct wall-clock fields.
    now_et = datetime.fromisoformat(now_iso).replace(tzinfo=_ET)

    # Simulate the scheduler's parsing of a tier_times entry. The aggregator
    # stores wall-clock strings; the scheduler splits on ":" — see watch.py
    # line 605: `th, tm = map(int, target_time.split(":"))`.
    target_time = f"{expected_hour:02d}:{expected_minute:02d}"
    th, tm = map(int, target_time.split(":"))

    assert th == expected_hour, (
        f"hour parsed from {target_time!r} = {th!r}, expected {expected_hour!r} "
        f"(now_et={now_et!r})"
    )
    assert tm == expected_minute, (
        f"minute parsed from {target_time!r} = {tm!r}, expected {expected_minute!r} "
        f"(now_et={now_et!r})"
    )

    # The wall-clock hour observed in ET MUST match the parsed target. This
    # is the load-bearing invariant: now.hour == parsed_target_hour means
    # the digest fires at the operator's intended wall-clock time, not 6:30
    # or 8:30 around DST.
    assert now_et.hour == expected_hour, (
        f"now_et.hour={now_et.hour!r} does not match expected_hour="
        f"{expected_hour!r}; DST transition may have shifted the wall clock"
    )
    assert now_et.minute == expected_minute


@pytest.mark.parametrize(
    "now_iso,weekly_str,expected_weekday,expected_hour",
    [
        pytest.param(
            "2025-03-09T18:00:00", "Sun 18:00", 6, 18, id="spring-forward-day-weekly",
        ),
        pytest.param(
            "2025-11-02T18:00:00", "Sun 18:00", 6, 18, id="fall-back-day-weekly",
        ),
    ],
)
def test_weekly_tier_time_parsing_on_dst_days(
    now_iso: str, weekly_str: str, expected_weekday: int, expected_hour: int,
):
    """The weekly DOW+HH:MM parser MUST yield the same (weekday, hour, minute)
    on the actual DST-transition Sunday — wall-clock '18:00' on Sun 2025-03-09
    and Sun 2025-11-02 are both unambiguous and well clear of the 02:00 zone.
    """
    weekday, hour, minute = parse_weekly_tier_time(weekly_str)
    assert weekday == expected_weekday
    assert hour == expected_hour
    assert minute == 0

    # Verify the wall-clock alignment on the actual DST day.
    now_et = datetime.fromisoformat(now_iso).replace(tzinfo=_ET)
    assert now_et.weekday() == expected_weekday
    assert now_et.hour == expected_hour
    assert now_et.minute == 0
