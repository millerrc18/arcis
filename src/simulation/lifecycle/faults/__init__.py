"""Composable fault-injection framework for the lifecycle simulator (Task 10).

The adversarial half of the simulator. Each fault class reproduces a fault that
caused a real Arcis data-integrity bug (partial fills, OCO-leg races, sticky
positions, phantom closes, PID recycling, DST-edge cadence, schema drift, …) by
configuring the FAKES' injectable seams + the harness — NEVER by editing prod
code and NEVER by faking the fakes themselves.

Two primitives live here:

  * ``FaultInjector`` — the arm()/disarm() lifecycle base. ``arm`` installs the
    fault (swapping a fake's seam, wrapping a method, …) and stashes whatever it
    replaced; ``disarm`` restores EXACTLY what was there before so a fault never
    leaks past its own scope. Double-arm / disarm-before-arm are programming
    errors and raise.

  * ``FaultRegistry`` — arms a SET of faults and guarantees clean teardown. Its
    ``armed()`` context manager arms in order and disarms in REVERSE order even
    when the body raises, so a second clean run on the same fakes sees no
    residual fault (the no-leakage guarantee the stress harness depends on).

Called by: the ScenarioRunner (Task 11) — NOT wired here.
Calls: the lifecycle fakes + clock (seams only). Owns tables: none.
Tests: tests/simulation/lifecycle/test_faults.py
"""

from __future__ import annotations

import contextlib
from typing import Iterator, Sequence


class FaultInjector:
    """Base class: an arm()/disarm() fault that restores exactly what it took.

    Subclasses implement ``_install`` (apply the fault, stash originals) and
    ``_restore`` (undo it). The base enforces the lifecycle: arm once, disarm
    once, no double-arm.
    """

    def __init__(self) -> None:
        self._armed = False

    @property
    def armed(self) -> bool:
        return self._armed

    def arm(self) -> "FaultInjector":
        """Install the fault. Raises if already armed."""
        if self._armed:
            raise RuntimeError(f"{type(self).__name__} is already armed.")
        self._install()
        self._armed = True
        return self

    def disarm(self) -> None:
        """Restore the pre-fault state. Idempotent after a successful arm."""
        if not self._armed:
            return
        try:
            self._restore()
        finally:
            self._armed = False

    def _install(self) -> None:
        """Apply the fault and stash whatever it replaced.

        Default is a no-op: faults whose effect is delivered through explicit
        helper methods (race(), phantom_close(), …) install nothing on arm.
        """
        return None

    def _restore(self) -> None:
        """Undo ``_install``. Default no-op for install-less faults."""
        return None


class FaultRegistry:
    """Arms a set of faults and guarantees clean, reverse-order teardown."""

    def __init__(self, faults: Sequence[FaultInjector]) -> None:
        self._faults = list(faults)

    def arm_all(self) -> None:
        for fault in self._faults:
            fault.arm()

    def disarm_all(self) -> None:
        for fault in reversed(self._faults):
            fault.disarm()

    @contextlib.contextmanager
    def armed(self) -> Iterator["FaultRegistry"]:
        """Arm every fault for the duration; disarm in reverse on exit/error."""
        armed_so_far: list[FaultInjector] = []
        try:
            for fault in self._faults:
                fault.arm()
                armed_so_far.append(fault)
            yield self
        finally:
            for fault in reversed(armed_so_far):
                fault.disarm()


__all__ = ["FaultInjector", "FaultRegistry"]
