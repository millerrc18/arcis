"""Tests for the lifecycle simulator's VirtualClock + freeze_at sync (Task 4).

Covers spec §4.4 clock-source pinning: inside freeze_at(clock), every clock
source Python code might read (datetime.now, time.time, time.monotonic,
pandas.Timestamp.now) must agree with clock.now() so the simulated WatchLoop
cannot observe skew between the virtual clock and a real wall clock.
"""

import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pandas as pd

from src.simulation.lifecycle.clock import VirtualClock, freeze_at

ET = ZoneInfo("America/New_York")


def _start() -> datetime:
    return datetime(2026, 5, 22, 9, 30, 0, tzinfo=ET)


def test_now_returns_tzaware_et():
    clock = VirtualClock(_start())
    now = clock.now()
    assert now == _start()
    assert now.tzinfo is not None
    assert now.utcoffset() == _start().utcoffset()


def test_advance_seconds_is_monotonic_nondecreasing():
    clock = VirtualClock(_start())
    seen = [clock.now()]
    for _ in range(5):
        clock.advance(30)
        seen.append(clock.now())
    for earlier, later in zip(seen, seen[1:]):
        assert later >= earlier
    assert clock.now() == _start() + timedelta(seconds=150)


def test_advance_accepts_timedelta():
    clock = VirtualClock(_start())
    clock.advance(timedelta(minutes=2))
    assert clock.now() == _start() + timedelta(minutes=2)


def test_advance_rejects_negative():
    clock = VirtualClock(_start())
    try:
        clock.advance(-1)
    except ValueError:
        pass
    else:
        raise AssertionError("advance(-1) must raise ValueError (monotonic)")


def test_tick_to_lands_on_wall_clock_instant():
    clock = VirtualClock(_start())  # 09:30
    clock.tick_to(16, 0)
    now = clock.now()
    assert now.hour == 16 and now.minute == 0
    assert now.date() == _start().date()
    assert now.tzinfo is not None


def test_tick_to_rolls_to_next_day_when_time_already_passed():
    clock = VirtualClock(_start())  # 09:30
    clock.tick_to(9, 0)  # 09:00 already passed today -> next day
    now = clock.now()
    assert now.hour == 9 and now.minute == 0
    assert now.date() == _start().date() + timedelta(days=1)


def test_tick_to_same_minute_advances_one_day():
    clock = VirtualClock(_start())  # 09:30
    clock.tick_to(9, 30)
    assert clock.now() == _start() + timedelta(days=1)


def test_tick_to_is_monotonic():
    clock = VirtualClock(_start())
    before = clock.now()
    clock.tick_to(16, 0)
    assert clock.now() >= before


def test_freeze_at_pins_all_clock_sources_consistently():
    clock = VirtualClock(datetime(2026, 5, 22, 14, 15, 30, tzinfo=ET))
    target = clock.now()
    naive_utc = target.astimezone(timezone.utc).replace(tzinfo=None)
    with freeze_at(clock):
        naive = datetime.now()
        aware = datetime.now(ET)
        py_time = time.time()
        pd_now = pd.Timestamp.now()

        # The tz-aware ET read is exactly clock.now() (the WatchLoop seam).
        assert aware == target
        # All sources agree on a single absolute instant: naive datetime.now(),
        # time.time(), and pandas.Timestamp.now() are the UTC-equivalent of it.
        assert naive == naive_utc
        assert py_time == target.timestamp()
        assert pd.Timestamp(pd_now) == pd.Timestamp(naive_utc)
        # Cross-source equality: pandas now == stdlib naive now.
        assert pd.Timestamp(pd_now) == pd.Timestamp(naive)


def test_freeze_at_pins_monotonic():
    clock = VirtualClock(_start())
    with freeze_at(clock):
        m1 = time.monotonic()
        m2 = time.monotonic()
        assert m1 == m2


def test_freeze_at_tracks_clock_after_advance_in_new_block():
    clock = VirtualClock(_start())
    clock.advance(60)
    with freeze_at(clock):
        assert datetime.now(ET) == clock.now()
        assert datetime.now(ET) == _start() + timedelta(seconds=60)
