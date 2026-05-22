"""Fast SQLite smoke entrypoint for the lifecycle simulator (Task 13).

``run_smoke()`` is the CI-per-PR tier. It bootstraps the safe env FIRST (the
package import below scrubs os.environ), installs the prod guard, then runs a
short ScenarioRunner scenario against a TEMPORARY SQLite database — explicitly
NOT the 5434 PG and with NO Docker / NO GPU. It exercises a few sim-days, the
core invariant subset, and a light fault set, then renders a Verdict report that
labels the integrity results "non-authoritative (SQLite)" via the smoke tier of
VerdictReporter.

WHY SQLite here even though bootstrap pins the 5434 PG: bootstrap closes the
prod-PG vector for the WHOLE simulator, but the smoke tier deliberately routes
to a throwaway SQLite file (``connect_db(force_sqlite=True)``) so a PR can run it
on a bare-metal box with no Docker. Because SQLite cannot enforce the same
constraints as the PG schema, its integrity verdict is wiring-only and the
report says so.

WHY a tiny placeholder-rewriting cursor: ScenarioRunner (read-only here) writes
its DB rows with psycopg2 ``%s`` placeholders. SQLite's DB-API uses ``?``, so a
thin connection wrapper rewrites ``%s`` -> ``?`` at the cursor boundary. It does
NOT touch the runner.

Called by: src.simulation.lifecycle.entrypoints (CI per-PR).
Calls: install_prod_guard, ScenarioRunner.run, VerdictReporter.render,
    src.schema.sqlite.create_all_tables, src.utils.db.connect_db.
Owns tables: writes to a temp SQLite file (deleted on exit). Config keys: none.
Tests: tests/simulation/lifecycle/test_entrypoints.py
"""

from __future__ import annotations

import src.simulation.lifecycle.bootstrap  # noqa: F401  — FIRST: pins safe env

import os
import tempfile
from dataclasses import dataclass, field
from datetime import datetime

from src.schema.sqlite import create_all_tables
from src.simulation.lifecycle.clock import ET
from src.simulation.lifecycle.faults.clock_faults import DstEdgeClockFault
from src.simulation.lifecycle.faults import FaultRegistry
from src.simulation.lifecycle.oracle import InvariantResult
from src.simulation.lifecycle.prod_guard import install_prod_guard
from src.simulation.lifecycle.scenario import ScenarioRunner
from src.simulation.lifecycle.verdict import Verdict, VerdictReporter, classify
from src.utils.db import connect_db

_SMOKE_DAYS = 2
_SMOKE_START = datetime(2026, 5, 22, 4, tzinfo=ET)


@dataclass
class SmokeResult:
    """The outcome of run_smoke(): verdict, invariant results, rendered report."""

    verdict: Verdict
    report: str
    results: list[InvariantResult] = field(default_factory=list)
    tier: str = "smoke"


class _SqliteCompatCursor:
    """Wraps a sqlite3 cursor, rewriting psycopg2 ``%s`` placeholders to ``?``."""

    def __init__(self, cursor) -> None:
        self._cursor = cursor

    def execute(self, sql, params=None):
        rewritten = sql.replace("%s", "?")
        if params is None:
            return self._cursor.execute(rewritten)
        return self._cursor.execute(rewritten, params)

    def __getattr__(self, name):
        return getattr(self._cursor, name)


class _SqliteCompatConn:
    """Wraps a sqlite3 connection so ScenarioRunner's ``%s`` writes work."""

    def __init__(self, conn) -> None:
        self._conn = conn

    def cursor(self):
        return _SqliteCompatCursor(self._conn.cursor())

    def __getattr__(self, name):
        return getattr(self._conn, name)


def run_smoke() -> SmokeResult:
    """Run the fast SQLite smoke scenario; return a NON-authoritative verdict."""
    install_prod_guard()
    fd, db_path = tempfile.mkstemp(suffix=".sqlite", prefix="hl-sim-smoke-")
    os.close(fd)
    try:
        create_all_tables(db_path)
        raw = connect_db(db_path, force_sqlite=True)
        conn = _SqliteCompatConn(raw)
        runner = ScenarioRunner(conn=conn, start=_SMOKE_START)
        runner.fault_registry = FaultRegistry([DstEdgeClockFault(runner.clock)])
        scenario = runner.run(days=_SMOKE_DAYS)
        raw.close()
    finally:
        try:
            os.remove(db_path)
        except OSError:
            pass
    results = list(scenario.final_results)
    report = VerdictReporter(tier="smoke").render(results)
    return SmokeResult(verdict=classify(results), report=report, results=results)


__all__ = ["run_smoke", "SmokeResult"]
