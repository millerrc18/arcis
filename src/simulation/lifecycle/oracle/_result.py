"""The InvariantResult value object shared by every oracle check (Task 9).

Called by: src.simulation.lifecycle.oracle._checks_db, ._checks_signal, .invariants
Calls: none (stdlib dataclass only)
Owns tables: none
Config keys: none
Tests: tests/simulation/lifecycle/test_oracle.py

Lives in its own module so both ``_checks_db`` and ``_checks_signal`` can import
it without importing ``invariants`` (which imports them) — no circular import.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class InvariantResult:
    """The outcome of one of the 9 data-integrity invariants.

    ``degraded_correctly`` and ``error_swallowed`` are the anti-masking axis:
    a fail-conservative branch that LOGGED its degradation is "degraded
    correctly"; one that silently masked an error is "error swallowed" (a FAIL
    even if the surface number looks plausible).
    """

    name: str
    passed: bool
    detail: str
    degraded_correctly: bool
    error_swallowed: bool
