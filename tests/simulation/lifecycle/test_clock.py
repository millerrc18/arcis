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


# ---------------------------------------------------------------------------
# REGRESSION-LOCK: freezegun covers both scheduler namespaces (T4, #97 §2.3/§4.4)
# ---------------------------------------------------------------------------
# freezegun's freeze_time rebinds module-level `from datetime import datetime`
# symbols in every already-imported module.  This test asserts that:
#   (a) src.scheduler.watch.datetime   and
#   (b) src.scheduler.universe_scanner.datetime
# are both frozen to clock.now() inside freeze_at(clock) WITHOUT any shim.
#
# If a future refactor removes the freezegun dep or introduces a shim that
# inadvertently breaks the module-rebind, this test will turn red.
# ---------------------------------------------------------------------------


import src.scheduler.watch as _watch_mod
import src.scheduler.universe_scanner as _scanner_mod


def test_freeze_at_regression_lock_watch_and_scanner_namespaces():
    """freezegun rebinds both scheduler module datetime symbols to clock.now()."""
    import datetime as _real_datetime_mod
    _real_dt_class = _real_datetime_mod.datetime

    clock = VirtualClock(datetime(2026, 5, 22, 14, 30, 0, tzinfo=ET))
    target = clock.now()

    # ── Inside the context: both namespaces read clock.now() ──────────────
    with freeze_at(clock):
        watch_now = _watch_mod.datetime.now(ET)
        scanner_now = _scanner_mod.datetime.now(ET)

        assert watch_now == target, (
            f"src.scheduler.watch.datetime.now(ET) = {watch_now!r}, "
            f"expected clock.now() = {target!r}"
        )
        assert scanner_now == target, (
            f"src.scheduler.universe_scanner.datetime.now(ET) = {scanner_now!r}, "
            f"expected clock.now() = {target!r}"
        )

        # Both symbols inside the context are freezegun's FakeDatetime, not the
        # original class — confirming the rebind is live.  _watch_mod.datetime
        # IS the FakeDatetime class, so check __name__ directly (not type()).
        assert _watch_mod.datetime.__name__ == "FakeDatetime", (
            "watch.datetime should be FakeDatetime inside freeze_at"
        )
        assert _scanner_mod.datetime.__name__ == "FakeDatetime", (
            "universe_scanner.datetime should be FakeDatetime inside freeze_at"
        )

    # ── After the context exits: originals are restored ───────────────────
    assert _watch_mod.datetime is _real_dt_class, (
        "watch.datetime was not restored to the original datetime class after freeze_at"
    )
    assert _scanner_mod.datetime is _real_dt_class, (
        "universe_scanner.datetime was not restored after freeze_at"
    )


def test_freeze_at_regression_lock_no_shim_needed(monkeypatch):
    """Prove freezegun alone suffices — no FrozenDatetime shim required.

    clock.py contains no shim.  We verify this property explicitly:
    even if we remove any hypothetical shim hook from the module namespace,
    freeze_at still freezes both scheduler namespaces via freezegun's own
    module-level rebind.  This guards against a future refactor that adds
    a shim and accidentally becomes the only thing keeping the namespaces
    frozen.
    """
    import src.simulation.lifecycle.clock as _clock_mod

    # Verify no shim attribute exists (clock.py should be shim-free).
    assert not hasattr(_clock_mod, "FrozenDatetime"), (
        "clock.py must not contain a FrozenDatetime shim — it is redundant "
        "with freezegun's module-level rebind (spec §2.3)"
    )

    clock = VirtualClock(datetime(2026, 5, 22, 10, 0, 0, tzinfo=ET))
    target = clock.now()

    with freeze_at(clock):
        watch_now = _watch_mod.datetime.now(ET)
        scanner_now = _scanner_mod.datetime.now(ET)

        assert watch_now == target, (
            f"Without shim: watch_now={watch_now!r} != clock.now()={target!r}"
        )
        assert scanner_now == target, (
            f"Without shim: scanner_now={scanner_now!r} != clock.now()={target!r}"
        )

