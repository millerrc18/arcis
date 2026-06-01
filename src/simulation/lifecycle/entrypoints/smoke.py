"""Fast smoke entrypoint for the lifecycle simulator (T14, #97).

``run_smoke()`` is the CI-per-PR tier. It bootstraps the safe env FIRST (the
package import below scrubs os.environ), installs the prod guard, provisions
the ephemeral 5434 Postgres (same test fixture as the full gate — no Docker
service is needed beyond what the test runner sets up), runs a short scenario
using the T9 organic open->exit->reconcile lifecycle, and renders a Verdict
report that labels the integrity results "non-authoritative (smoke tier)".

WHY the integrity verdict is NON-authoritative (smoke tier): the smoke runs
fewer sim-days and a lighter scenario than the nightly full gate. It is a
fast wiring + regression check, NOT the authoritative integrity gate. The
rendered report labels the results "non-authoritative (SQLite)" for historical
compatibility — the smoke always uses the same 5434 PG ephemeral fixture as
the full gate, but with a TRUNCATE-before-run + fewer days.

WHY the smoke tier still requires the 5434 PG: the T9 organic runner drives
the REAL prod scan path (universe_scanner -> log_recommendation ->
executor.open_shadow_trade), which writes through connect_db(None) → PG under
bootstrap's env (DATABASE_URL=5434 + ARCIS_PG_CUTOVER_ENABLED=1). An all-SQLite
smoke cannot use the organic runner without every prod write being redirected.
The smoke's non-authoritative label reflects its reduced scope, not a different
backing store. Bare-metal CI without the 5434 PG fixture will skip/fail the
smoke tests with a connection error — this is expected and documented.

WHY sim_dsn override: ScenarioRunner requires a sim_dsn that passes the wiring
guard (':5434/' must appear). The smoke uses the canonical SIM_DATABASE_URL.

Called by: src.simulation.lifecycle.entrypoints (CI per-PR).
Calls: install_prod_guard, ScenarioRunner.run, VerdictReporter.render,
    src.schema.postgres.create_all_tables (via _truncate_smoke_tables).
Owns tables: TRUNCATEs + writes shadow_trades / recommendations on the 5434 PG.
Config keys: none. Tests: tests/simulation/lifecycle/test_entrypoints.py
"""

from __future__ import annotations

import src.simulation.lifecycle.bootstrap  # noqa: F401  — FIRST: pins safe env

import logging
from dataclasses import dataclass, field
from datetime import datetime

import psycopg2

from src.simulation.lifecycle import _leak_detector
from src.simulation.lifecycle.bootstrap import SIM_DATABASE_URL, scoped_scrub
from src.simulation.lifecycle.clock import ET
from src.simulation.lifecycle.oracle import InvariantResult
from src.simulation.lifecycle.prod_guard import install_prod_guard
from src.simulation.lifecycle.scenario import ScenarioRunner
from src.simulation.lifecycle.verdict import Verdict, VerdictReporter, classify

LOG = logging.getLogger(__name__)

_SMOKE_DAYS = 1
_SMOKE_START = datetime(2026, 5, 22, 4, tzinfo=ET)
_SMOKE_TRUNCATE_TABLES = ("shadow_trades", "recommendations", "training_examples", "model_versions")


@dataclass
class SmokeResult:
    """The outcome of run_smoke(): verdict, invariant results, rendered report."""

    verdict: Verdict
    report: str
    results: list[InvariantResult] = field(default_factory=list)
    tier: str = "smoke"
    provenance_passed: bool = False
    organic_open_rows: list = field(default_factory=list)


def _truncate_smoke_tables() -> None:
    """TRUNCATE the 5434 PG test tables before the smoke run.

    The _DeterministicUuidStub resets its counter to 1 on each
    install_organic_patches call, so without a TRUNCATE the second smoke
    run hits a UniqueViolation on the recommendation_id primary key.
    Mirrors full_gate._provision_pg (TRUNCATE only — no schema bootstrap;
    the schema must already exist on the 5434 PG).

    If the 5434 PG is not reachable, the OperationalError propagates to the
    caller so the test fails with a clear connection error rather than
    silently skipping the truncate and hitting a later UniqueViolation.
    """
    conn = psycopg2.connect(SIM_DATABASE_URL)
    conn.autocommit = True
    with conn.cursor() as cur:
        for tbl in _SMOKE_TRUNCATE_TABLES:
            cur.execute(f"TRUNCATE TABLE {tbl} CASCADE")
    conn.close()


def run_smoke() -> SmokeResult:
    """Run the short-scenario smoke run; return a NON-authoritative verdict.

    The bootstrap env scrub is applied via ``scoped_scrub()`` for the duration
    of THIS run only (pins the :5434 gate env so the organic scan path routes
    connect_db to the test PG) and fully restored on exit — it is NOT an import
    side-effect, so it never leaks into the rest of the suite (#128 / T5).
    """
    install_prod_guard()
    with scoped_scrub():
        baseline = _leak_detector.snapshot_backends(SIM_DATABASE_URL, application_name_filter=None)
        _truncate_smoke_tables()
        conn = psycopg2.connect(SIM_DATABASE_URL)
        conn.autocommit = True
        try:
            runner = ScenarioRunner(conn=conn, start=_SMOKE_START, sim_dsn=SIM_DATABASE_URL)
            scenario = runner.run(days=_SMOKE_DAYS)
        finally:
            conn.rollback()
            conn.close()
            after = _leak_detector.snapshot_backends(SIM_DATABASE_URL, application_name_filter=None)
            LOG.info(
                "[smoke] conn-leak diagnostic:\n%s",
                _leak_detector.format_delta(baseline, after),
            )
    results = list(scenario.final_results)
    report = VerdictReporter(tier="smoke").render(results)
    return SmokeResult(
        verdict=classify(results),
        report=report,
        results=results,
        provenance_passed=scenario.provenance_passed,
        organic_open_rows=scenario.organic_open_rows,
    )


__all__ = ["run_smoke", "SmokeResult"]
