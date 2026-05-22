"""Run entrypoints for the lifecycle simulator (Task 13).

Two tiers share one ScenarioRunner + VerdictReporter but differ in their
backing store and rigor:

  * ``run_smoke`` — fast CI-per-PR tier on a TEMP SQLite DB (no Docker/GPU);
    its integrity results are wiring-only / NON-authoritative.
  * ``run_full_gate`` — authoritative nightly tier on the ephemeral 5434 PG;
    its verdict is the integrity-authoritative one.

Both bootstrap-first (the package __init__ scrubs the env on import) and install
the prod guard before any DB connection opens.

Called by: CI (smoke per-PR) + the nightly gate (full).
Calls: smoke.run_smoke, full_gate.run_full_gate.
Owns tables: none. Config keys: none.
Tests: tests/simulation/lifecycle/test_entrypoints.py
"""

from src.simulation.lifecycle.entrypoints.full_gate import run_full_gate
from src.simulation.lifecycle.entrypoints.smoke import run_smoke

__all__ = ["run_smoke", "run_full_gate"]
