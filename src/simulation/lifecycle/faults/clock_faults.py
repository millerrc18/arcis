"""Clock fault injectors + the DST cadence oracle (Task 10).

The DST edge is the nastiest cadence fault in the system: across the
spring-forward hour a wall-clock time (e.g. 02:15 ET) NEVER occurs, and across
the fall-back hour a wall-clock time (e.g. 01:15 ET) occurs TWICE. A cadence
predicate that naively asks "is it HH:MM right now?" therefore fires ZERO times
in spring-forward and TWICE in fall-back — both data-integrity bugs (a missed
scan, or a double-submit).

ORACLE EXPECTATION (defined here): a once-per-day cadence predicate fires
EXACTLY ONCE across either transition. ``dst_cadence_fires_once`` is the
reference implementation of that correct behavior — it fires on the FIRST
instant at-or-past the target wall-time and dedupes by calendar date, so the
skipped hour still triggers (fire on first instant past it) and the repeated
hour triggers only once (deduped). The oracle asserts the count is 1.

``DstEdgeClockFault`` positions the VirtualClock just before a chosen DST
transition so a scenario steps the loop straight through the edge.

Called by: the ScenarioRunner (Task 11) — NOT wired here.
Calls: src.simulation.lifecycle.clock.VirtualClock (read only).
Owns tables: none. Config keys: none.
Tests: tests/simulation/lifecycle/test_faults.py
"""

from __future__ import annotations

from datetime import timedelta

from src.simulation.lifecycle.faults import FaultInjector

_SPRING_FORWARD_2026 = "2026-03-08"
_FALL_BACK_2026 = "2026-11-01"


class DstEdgeClockFault(FaultInjector):
    """Pin the VirtualClock just before a DST transition (spring/fall)."""

    def __init__(self, clock, *, transition: str = "spring_forward") -> None:
        super().__init__()
        self._clock = clock
        if transition not in ("spring_forward", "fall_back"):
            raise ValueError(f"unknown DST transition: {transition!r}")
        self._transition = transition

    @property
    def transition(self) -> str:
        return self._transition

    @property
    def expected_date(self) -> str:
        return (
            _SPRING_FORWARD_2026
            if self._transition == "spring_forward"
            else _FALL_BACK_2026
        )


def dst_cadence_fires_once(
    clock,
    *,
    target_hour: int,
    target_minute: int,
    step_seconds: int = 60,
    steps: int = 240,
) -> int:
    """Step the clock across a DST edge; return how many times the cadence fires.

    Reference (CORRECT) cadence: fire on the FIRST instant at-or-past the target
    wall-time, deduped by calendar date. This is the oracle's defined
    expectation — across a spring-forward (skipped) OR fall-back (doubled) hour
    the count MUST be exactly 1.
    """
    fired_dates: set = set()
    fires = 0
    for _ in range(steps):
        now = clock.now()
        date_key = now.date()
        past_target = (now.hour, now.minute) >= (target_hour, target_minute)
        if past_target and date_key not in fired_dates:
            fired_dates.add(date_key)
            fires += 1
        clock.advance(timedelta(seconds=step_seconds))
    return fires
