"""Authoritative ephemeral-PG full-gate entrypoint (Task 13).

``run_full_gate()`` is the NIGHTLY tier and the only integrity-AUTHORITATIVE
run. It bootstraps the safe env FIRST (the package import below scrubs
os.environ to the safe 5434 PG), installs the prod guard, provisions the
ephemeral test Postgres on 127.0.0.1:5434 (the docker-compose.test.yml service),
bootstraps the registry schema there via ``src.schema.postgres.create_all_tables``
(the same DDL the prod cutover runs), then runs the ScenarioRunner over many
sim-days and drives the 11 governor gates (ScenarioRunner marks all of
GOVERNOR_GATES during its training stage). It returns the authoritative Verdict.

WHY PG and not SQLite: only the PG schema enforces the FK / NOT NULL / type
constraints the data-integrity invariants assert against, so only this tier's
verdict is authoritative. The smoke tier (SQLite) is wiring-only.

The schema is bootstrapped against the SAME safe 5434 DSN the bootstrap module
pins; the prod guard rejects any prod-signature DSN before a connection opens, so
this entrypoint can NEVER reach production even if DATABASE_URL were tampered.

Called by: src.simulation.lifecycle.entrypoints (the nightly gate).
Calls: install_prod_guard, src.schema.postgres.create_all_tables,
    psycopg2.connect (safe 5434), ScenarioRunner.run, VerdictReporter.render.
Owns tables: TRUNCATEs + writes shadow_trades / recommendations on the 5434 PG.
Config keys: none. Tests: tests/simulation/lifecycle/test_entrypoints.py
"""

from __future__ import annotations

import src.simulation.lifecycle.bootstrap as _bootstrap  # FIRST: pins safe env

from dataclasses import dataclass, field
from datetime import datetime

import psycopg2

from src.schema.postgres import create_all_tables
from src.simulation.lifecycle.clock import ET
from src.simulation.lifecycle.oracle import InvariantResult
from src.simulation.lifecycle.prod_guard import install_prod_guard
from src.simulation.lifecycle.scenario import ScenarioRunner
from src.simulation.lifecycle.verdict import Verdict, VerdictReporter, classify

_FULL_GATE_DAYS = 5
_FULL_GATE_START = datetime(2026, 5, 22, 4, tzinfo=ET)
_TABLES = ("shadow_trades", "recommendations", "training_examples", "model_versions")


@dataclass
class FullGateResult:
    """The outcome of run_full_gate(): the AUTHORITATIVE verdict + report."""

    verdict: Verdict
    report: str
    results: list[InvariantResult] = field(default_factory=list)
    tier: str = "full"


def _provision_pg(dsn: str):
    """Bootstrap the registry schema on the ephemeral PG and return a fresh conn."""
    create_all_tables(dsn)
    conn = psycopg2.connect(dsn)
    conn.autocommit = True
    cur = conn.cursor()
    for tbl in _TABLES:
        cur.execute(f"TRUNCATE TABLE {tbl} CASCADE")
    cur.close()
    conn.autocommit = False
    return conn


def run_full_gate() -> FullGateResult:
    """Provision the 5434 PG, run the authoritative scenario, return its Verdict."""
    install_prod_guard()
    dsn = _bootstrap.SIM_DATABASE_URL
    conn = _provision_pg(dsn)
    try:
        runner = ScenarioRunner(conn=conn, start=_FULL_GATE_START)
        scenario = runner.run(days=_FULL_GATE_DAYS)
    finally:
        conn.rollback()
        conn.close()
    results = list(scenario.final_results)
    report = VerdictReporter(tier="full").render(results)
    return FullGateResult(verdict=classify(results), report=report, results=results)


__all__ = ["run_full_gate", "FullGateResult"]
