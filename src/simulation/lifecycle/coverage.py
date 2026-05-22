"""Lifecycle-stage x fault-dimension coverage matrix for the simulator (Task 11).

The ScenarioRunner records WHAT a run exercised so a stress campaign can answer
"did we ever drive the governor's correlation gate?" or "which lifecycle stage
ran under a partial-fill fault?" without re-reading the run by hand.

Three axes are tracked:

  * lifecycle stages x fault dimensions — a cell is "exercised" when a stage ran
    (optionally under a named fault dimension; ``None`` means no-fault);
  * capabilities — cross-referenced against the capability registry's
    ACTIONS / STATES / SYSTEMS / DECISIONS dicts
    (src/platform/capability_registry/registry.py:35-38) so the matrix can report
    which registered capabilities a run touched;
  * governor gates — the 11 RiskGovernor.check_trade gates (governor.py:522
    GOVERNOR_GATES); ``missing_governor_gates`` tells a campaign which gates a run
    has not yet driven, so the bar "the run can drive all 11 gates" is checkable.

Called by: the ScenarioRunner (scenario.py).
Calls: src.platform.capability_registry.registry (read-only iteration),
    src.risk.governor (GOVERNOR_GATES tuple).
Owns tables: none. Config keys: none.
Tests: tests/simulation/lifecycle/test_scenario.py
"""

from __future__ import annotations

from src.platform.capability_registry import registry as _capreg
from src.risk.governor import GOVERNOR_GATES

# The lifecycle stages a sim day advances through, in cadence order. Mirrors the
# ScenarioRunner's day loop (premarket -> open -> intraday -> close -> overnight).
LIFECYCLE_STAGES = (
    "premarket",
    "open",
    "intraday",
    "close",
    "reconcile",
    "training",
    "overnight",
)


class CoverageMatrix:
    """Records the stage x fault, capability, and governor-gate cells a run hit."""

    def __init__(self) -> None:
        # (stage, fault_dimension) cells; fault_dimension is None for no-fault.
        self._cells: set[tuple[str, str | None]] = set()
        self._capabilities: set[str] = set()
        self._gates: set[str] = set()

    def mark_stage(self, stage: str, fault_dimension: str | None = None) -> None:
        """Record that ``stage`` ran (under ``fault_dimension`` if given)."""
        self._cells.add((stage, fault_dimension))

    def mark_capability(self, name: str) -> None:
        """Record that a registered capability ``name`` was exercised."""
        self._capabilities.add(name)

    def mark_gate(self, gate: str) -> None:
        """Record that a governor gate ``gate`` was driven."""
        self._gates.add(gate)

    def exercised_cells(self) -> tuple[tuple[str, str | None], ...]:
        """Return the (stage, fault_dimension) cells exercised, sorted."""
        return tuple(sorted(self._cells, key=lambda c: (c[0], c[1] or "")))

    def exercised_capabilities(self) -> tuple[str, ...]:
        """Return the registered-capability names exercised, sorted."""
        return tuple(sorted(self._capabilities))

    def known_capabilities(self) -> frozenset[str]:
        """All capability names declared across the four registry dicts."""
        names: set[str] = set()
        for reg in (_capreg.ACTIONS, _capreg.STATES, _capreg.SYSTEMS, _capreg.DECISIONS):
            names.update(reg.keys())
        return frozenset(names)

    def missing_governor_gates(self) -> tuple[str, ...]:
        """Governor gates not yet driven, in GOVERNOR_GATES declaration order."""
        return tuple(g for g in GOVERNOR_GATES if g not in self._gates)
