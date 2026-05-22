"""Tests for the lifecycle ScenarioRunner — the end-to-end integration (Task 11).

Importing ``src.simulation.lifecycle.bootstrap`` FIRST pins DATABASE_URL at the
ephemeral test PG on 127.0.0.1:5434 + ARCIS_PG_CUTOVER_ENABLED=1 +
PYTHONHASHSEED=0 before anything else touches the DB. The schema is bootstrapped
against that PG in ``_schema`` (src.schema.postgres.create_all_tables — the same
registry tables the prod cutover creates).

The headline test is a 2-sim-day NO-FAULT run: the ScenarioRunner builds the
REAL WatchLoop with the injected virtual clock + noop sleep + installed fakes,
advances through the daily cadence, runs Oracle checkpoints, and reaches run-end
with ALL integrity invariants passing. Teardown asserts no residual broker
singleton and no observer handler is left attached (determinism / no-leakage).
"""

import src.simulation.lifecycle.bootstrap  # noqa: F401  — FIRST: pins 5434 + hashseed
import logging
from datetime import datetime

import psycopg2
import pytest

import src.trading.broker_factory as broker_factory
import src.config as config_module
from src.risk.governor import GOVERNOR_GATES
from src.schema.postgres import create_all_tables
from src.scheduler.watch import WatchLoop
from src.simulation.lifecycle.clock import ET, VirtualClock
from src.simulation.lifecycle.oracle import SwallowedErrorObserver
from src.simulation.lifecycle.oracle.invariants import InvariantResult
from src.simulation.lifecycle.scenario import ScenarioRunner, ScenarioResult
from src.simulation.lifecycle.coverage import CoverageMatrix

SIM_DSN = "postgresql://test:test@127.0.0.1:5434/halcyon"

_TABLES = ("shadow_trades", "recommendations", "training_examples", "model_versions")


@pytest.fixture(scope="module")
def _schema():
    create_all_tables(SIM_DSN)


@pytest.fixture
def pg_conn(_schema):
    conn = psycopg2.connect(SIM_DSN)
    conn.autocommit = True
    cur = conn.cursor()
    for tbl in _TABLES:
        cur.execute(f"TRUNCATE TABLE {tbl} CASCADE")
    cur.close()
    conn.autocommit = False
    try:
        yield conn
    finally:
        conn.rollback()
        conn.close()


# ── headline: a clean 2-sim-day run, every integrity invariant passes ──────────


def test_two_day_no_fault_run_all_invariants_pass(pg_conn):
    runner = ScenarioRunner(conn=pg_conn, start=datetime(2026, 5, 22, 4, tzinfo=ET))
    result = runner.run(days=2)

    assert isinstance(result, ScenarioResult)
    # Run reached the end and produced checkpoint results.
    assert result.completed is True
    assert len(result.checkpoints) >= 2

    final = result.final_results
    assert all(isinstance(r, InvariantResult) for r in final)
    assert len(final) == 9
    failed = [r.name for r in final if not r.passed]
    assert failed == [], f"expected all invariants to pass, failed: {failed}"


def test_run_uses_injected_clock_and_noop_sleep(pg_conn):
    """The WatchLoop is built with the virtual clock + a noop sleep seam."""
    runner = ScenarioRunner(conn=pg_conn, start=datetime(2026, 5, 22, 4, tzinfo=ET))
    runner.run(days=1)
    loop = runner.watch_loop
    assert isinstance(loop, WatchLoop)
    # clock seam reads the virtual clock, NOT real wall time: the loop's clock
    # returns the same instant the VirtualClock reports.
    assert loop._clock() == runner.clock.now()
    # sleep seam is a noop (does not call real time.sleep).
    import time as _time
    assert loop._sleep is not _time.sleep


def test_clock_advances_through_two_full_days(pg_conn):
    runner = ScenarioRunner(conn=pg_conn, start=datetime(2026, 5, 22, 4, tzinfo=ET))
    start = runner.clock.now()
    runner.run(days=2)
    elapsed = runner.clock.now() - start
    # Two full sim days advanced (premarket -> overnight, twice).
    assert elapsed.days >= 1


# ── coverage matrix records exercised cells + can drive all governor gates ─────


def test_coverage_matrix_records_exercised_cells(pg_conn):
    runner = ScenarioRunner(conn=pg_conn, start=datetime(2026, 5, 22, 4, tzinfo=ET))
    result = runner.run(days=2)
    matrix = result.coverage
    assert isinstance(matrix, CoverageMatrix)
    exercised = matrix.exercised_cells()
    assert len(exercised) > 0


def test_coverage_can_drive_all_governor_gates():
    matrix = CoverageMatrix()
    for gate in GOVERNOR_GATES:
        matrix.mark_gate(gate)
    missing = matrix.missing_governor_gates()
    assert missing == (), f"all 11 gates must be drivable, missing: {missing}"
    assert len(GOVERNOR_GATES) == 11


def test_coverage_reports_missing_gates_when_not_all_driven():
    matrix = CoverageMatrix()
    matrix.mark_gate("traffic_light")
    missing = matrix.missing_governor_gates()
    assert "traffic_light" not in missing
    assert "duplicate" in missing


# ── teardown: no leakage (broker singletons cleared, observer detached) ────────


def test_teardown_clears_broker_singletons(pg_conn):
    broker_factory._brokers["alpaca"] = object()  # simulate a residual singleton
    runner = ScenarioRunner(conn=pg_conn, start=datetime(2026, 5, 22, 4, tzinfo=ET))
    runner.run(days=1)
    assert broker_factory._brokers == {}, "teardown must reset_brokers()"


def test_teardown_detaches_observer(pg_conn):
    runner = ScenarioRunner(conn=pg_conn, start=datetime(2026, 5, 22, 4, tzinfo=ET))
    runner.run(days=1)
    observer = runner.observer
    governor_logger = logging.getLogger("src.risk.governor")
    assert observer not in governor_logger.handlers, "observer must be detached"


def test_teardown_clears_config_cache(pg_conn):
    config_module._config_cache = {"stale": True}
    runner = ScenarioRunner(conn=pg_conn, start=datetime(2026, 5, 22, 4, tzinfo=ET))
    runner.run(days=1)
    assert config_module._config_cache is None, "teardown must clear config cache"


# ── determinism: two clean runs see no residual fault / state ──────────────────


def test_two_sequential_runs_no_residual_state(pg_conn):
    runner1 = ScenarioRunner(conn=pg_conn, start=datetime(2026, 5, 22, 4, tzinfo=ET))
    r1 = runner1.run(days=1)
    # Second run on the same conn must also pass cleanly (no residual leakage).
    cur = pg_conn.cursor()
    for tbl in _TABLES:
        cur.execute(f"TRUNCATE TABLE {tbl} CASCADE")
    pg_conn.commit()
    cur.close()
    runner2 = ScenarioRunner(conn=pg_conn, start=datetime(2026, 5, 22, 4, tzinfo=ET))
    r2 = runner2.run(days=1)
    assert [r.name for r in r1.final_results if not r.passed] == []
    assert [r.name for r in r2.final_results if not r.passed] == []
