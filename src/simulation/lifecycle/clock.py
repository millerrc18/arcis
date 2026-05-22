"""VirtualClock + freezegun sync for the lifecycle simulator (Task 4).

The simulator drives a WatchLoop through a compressed trading day. The loop
reads time from many sources — `datetime.now()`, `time.time()`,
`time.monotonic()`, and `pandas.Timestamp.now()`. If any of those reflect the
real wall clock while others reflect the virtual clock, the loop observes
skew (spec §4.4 review finding). `freeze_at(clock)` pins ALL of them to
`clock.now()` for the duration of the context so the simulated code can never
tell it is not running in real time.

VirtualClock owns the simulated instant; freeze_at projects that instant onto
the process-global clock sources via freezegun.

Called by: the ScenarioRunner (later task) — NOT wired here.
Calls: freezegun.freeze_time (test-only dependency).
Owns tables: none. Config keys: none.
Tests: tests/simulation/lifecycle/test_clock.py (Task 4)
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Iterator, Union
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")


class VirtualClock:
    """A monotonic, tz-aware ET clock the simulator advances by hand."""

    def __init__(self, start: datetime) -> None:
        if start.tzinfo is None:
            raise ValueError("VirtualClock start must be tz-aware (ET).")
        self._now = start.astimezone(ET)

    def now(self) -> datetime:
        """Return the current virtual instant as a tz-aware ET datetime."""
        return self._now

    def advance(self, amount: Union[int, float, timedelta]) -> datetime:
        """Advance the clock by `amount` seconds (or a timedelta).

        Raises ValueError on a negative amount — the clock is monotonic
        non-decreasing.
        """
        delta = amount if isinstance(amount, timedelta) else timedelta(seconds=amount)
        if delta < timedelta(0):
            raise ValueError("VirtualClock cannot advance by a negative amount.")
        self._now = self._now + delta
        return self._now

    def tick_to(self, hour: int, minute: int) -> datetime:
        """Advance to the next occurrence of the given ET wall-clock time.

        If `hour:minute` is at or before the current instant, the clock rolls
        forward to that time on the following day. Always strictly advances.
        """
        candidate = self._now.replace(
            hour=hour, minute=minute, second=0, microsecond=0
        )
        if candidate <= self._now:
            candidate = candidate + timedelta(days=1)
        self._now = candidate
        return self._now


@contextmanager
def freeze_at(clock: VirtualClock) -> Iterator[None]:
    """Freeze every process clock source to `clock.now()`.

    Inside the context, `datetime.now(tz)`, `time.time()`, `time.monotonic()`,
    and `pandas.Timestamp.now()` all report the same absolute instant —
    `clock.now()` — so the simulated code can never observe skew between the
    virtual clock and a real wall clock (spec §4.4 clock-source pinning).

    Note: freegun freezes `datetime.now(tz)` and `time.time()`, but does NOT
    patch pandas' C-level `Timestamp.now()`. We patch it explicitly so a
    `pd.Timestamp.now()` call agrees with `datetime.now()` (same naive
    UTC-equivalent instant freezegun reports).
    """
    import pandas as pd
    from freezegun import freeze_time

    instant = clock.now()
    # Naive UTC-equivalent of the instant — matches what freezegun makes
    # datetime.now() (no tz) return, keeping pandas consistent with stdlib.
    naive_utc = instant.astimezone(timezone.utc).replace(tzinfo=None)

    def _frozen_pd_now(tz=None):
        if tz is None:
            return pd.Timestamp(naive_utc)
        return pd.Timestamp(instant).tz_convert(tz)

    original_pd_now = pd.Timestamp.now
    pd.Timestamp.now = _frozen_pd_now
    try:
        with freeze_time(instant):
            yield
    finally:
        pd.Timestamp.now = original_pd_now
