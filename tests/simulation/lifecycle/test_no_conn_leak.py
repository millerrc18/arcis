"""Regression tests for #100 sim connection-lifecycle leak fix.

TWO tests per spec 3.5 + 3.6:
  - test_assert_all_does_not_poison_subsequent_checks  (PRIMARY -- load-bearing)
  - test_no_conn_leak_smoke_accumulator                (BACKSTOP -- best-effort)

Both connect to the REAL 5434 PG. No mocks of psycopg2.connect or cursors.

Called by: pytest test suite
Calls: src.simulation.lifecycle.oracle.invariants.Oracle,
       src.simulation.lifecycle.entrypoints.smoke.run_smoke,
       src.simulation.lifecycle._leak_detector
Owns tables: reads shadow_trades / recommendations / training_examples /
             model_versions on the 5434 PG (via Oracle + run_smoke)
Config keys: SIM_LEAK_LOOP_ITERATIONS (opt-in stress mode, default=3)
Tests: this file IS the test module
"""

import src.simulation.lifecycle.bootstrap  # noqa: F401  -- FIRST: pins 5434 + hashseed

import os

import psycopg2
import pytest

from src.simulation.lifecycle import _leak_detector
from src.simulation.lifecycle.bootstrap import SIM_DATABASE_URL
from src.simulation.lifecycle.entrypoints.smoke import run_smoke
from src.simulation.lifecycle.oracle import SwallowedErrorObserver

from tests.simulation.lifecycle._oracle_fixtures import (
    clean_world,
    build_oracle,
    ensure_schema,
    truncate_oracle_tables,
)


# -- bootstrap schema once for this module ------------------------------------

@pytest.fixture(scope="module", autouse=True)
def _schema():
    """Bootstrap the registry schema once against the ephemeral 5434 PG."""
    ensure_schema()


# -- PRIMARY witness -- load-bearing for dual-Opus merge gate -----------------


def test_assert_all_does_not_poison_subsequent_checks():
    """PRIMARY witness for the bug mechanism per spec 1.3 + 3.2.

    Bug (spec 1.3): Oracle.assert_all() shares self.conn across 9 invariants
    WITHOUT rollback between them. If check N leaves self.conn in
    'idle in transaction (aborted)' state (due to a mid-execute raise), check
    N+1's first cur.execute() raises psycopg2.errors.InFailedSqlTransaction.

    Fix (spec 3.2): each invariant call is wrapped in try/finally with
    self.conn.rollback() in the finally block. The rollback runs even when the
    check raises, guaranteeing self.conn is in IDLE state on exit from
    assert_all(). This means: after assert_all() raises on a poisoned conn,
    the conn is usable again -- a second assert_all() call on the SAME conn
    returns all 9 InvariantResults.

    Verify-by-mutation procedure (RED+GREEN required by the dual-Opus merge gate):
      1. Stash invariants.py:
         git stash -- src/simulation/lifecycle/oracle/invariants.py
      2. Run this test -> EXPECT FAIL: psycopg2.errors.InFailedSqlTransaction
         raised inside oracle.assert_all() on the SECOND call -- because without
         T4's rollback, the first call leaves conn in aborted state and the
         second call also raises InFailedSqlTransaction.
      3. git stash pop
      4. Re-run same test -> EXPECT PASS: second assert_all() returns 9 results.

    autocommit=False is REQUIRED (spec 3.6): with autocommit=True each statement
    is its own txn and the aborted-txn state cannot persist across statements,
    masking the bug entirely.

    Two-call pattern rationale: the first call simulates assert_all() receiving
    a conn in aborted state (poisoned by a prior failing check). T4's try/finally
    rollback-in-finally ensures conn is IDLE after the first exception, so the
    second call succeeds. Without T4, the first call leaves conn dirty and the
    second call also raises InFailedSqlTransaction.
    """
    truncate_oracle_tables()

    conn = psycopg2.connect(SIM_DATABASE_URL, application_name="sim_leak_test")
    conn.autocommit = False  # MUST be False -- autocommit=True masks the bug
    try:
        # Seed a clean world so the DB checks have valid tables and rows.
        ledger, fake, marks = clean_world(conn)
        observer = SwallowedErrorObserver().install()
        try:
            oracle = build_oracle(conn, ledger, fake, observer, marks)

            # Induce 'idle in transaction (aborted)' state on oracle's conn.
            # This simulates what happens when an invariant check's cur.execute()
            # raises mid-flight: the conn is left in aborted state, which is the
            # poisoning condition the pre-T4 bug left behind. The UndefinedTable
            # error is the harness mechanism; the actual bug is the missing rollback.
            with pytest.raises(psycopg2.errors.UndefinedTable):
                with conn.cursor() as cur:
                    cur.execute("SELECT 1 FROM table_that_does_not_exist")
            # conn is now in 'idle in transaction (aborted)' state (txn_status=3).

            # CALL 1: assert_all() on the poisoned conn.
            # check_attribution is the first DB-touching check; it will raise
            # InFailedSqlTransaction because conn is aborted.
            # WITH T4: the try/finally rollback runs in finally, cleaning conn
            #   back to IDLE (txn_status=0) before the exception propagates.
            # WITHOUT T4 (stash mutation): no rollback -> conn stays aborted.
            with pytest.raises(psycopg2.errors.InFailedSqlTransaction):
                oracle.assert_all()

            # CALL 2: assert_all() again on the SAME conn.
            # WITH T4 fix: conn was cleaned by T4's rollback-in-finally on call 1.
            #   -> check_attribution succeeds, all 9 checks run, 9 results returned.
            # WITHOUT T4 fix (stash invariants.py mutation):
            #   conn is STILL in aborted state -> InFailedSqlTransaction AGAIN -> FAIL.
            results = oracle.assert_all()
        finally:
            observer.detach()
    finally:
        conn.close()

    assert len(results) == 9, f"expected 9 InvariantResults, got {len(results)}"
    # results[0] = attribution_1to1 (first DB-touching check).
    # results[1] = zero_orphans (second DB-touching check).
    assert results[0] is not None, "results[0] (attribution_1to1) must be non-None"
    assert results[1] is not None, "results[1] (zero_orphans) must be non-None"


# -- BACKSTOP -- defensive outer-loop accumulator ----------------------------


@pytest.mark.skip(reason="integration(authoritative-coverage:lifecycle-full-gate): runs the full organic-runner lifecycle scenario against the 5434 PG, exceeds the 60s per-PR pg-tests window; run_full_gate()/run_smoke() are authoritatively covered by the lifecycle-full-gate CI job")
def test_no_conn_leak_smoke_accumulator():
    """BACKSTOP: run smoke 3x back-to-back and assert zero net backend growth.

    Positioning (REV-2 per DA1): DEFENSIVE BACKSTOP. The PRIMARY witness for
    the bug is test_assert_all_does_not_poison_subsequent_checks above, which
    directly exercises the cross-check poisoning mechanism within ONE
    assert_all() call. This 3x outer-loop test catches the SECONDARY symptom --
    cross-run backend accumulation -- IF Python-side ref-keeping prevents full
    conn GC between iterations. Since that mechanism is GC-timing-fuzzy, this
    test's RED-when-mutated property is best-effort, not load-bearing.
    Treat as a regression smoke test for the broader leak surface.

    Threshold rationale: delta <= 0 (STRICT). Filtered by
    application_name='sim_leak_test' so concurrent psql sessions and parallel
    CI jobs do NOT confound the count (spec 2.5, DD-10).
    """
    os.environ["PGAPPNAME"] = "sim_leak_test"  # libpq honours on every connect()
    iterations = int(os.environ.get("SIM_LEAK_LOOP_ITERATIONS", "3"))

    baseline = _leak_detector.snapshot_backends(
        SIM_DATABASE_URL, application_name_filter="sim_leak_test"
    )
    for i in range(iterations):
        print(f"leak-test iteration {i + 1}/{iterations}")
        run_smoke()
    after = _leak_detector.snapshot_backends(
        SIM_DATABASE_URL, application_name_filter="sim_leak_test"
    )

    delta = after.total - baseline.total
    assert delta <= 0, (
        f"PG backend leak detected across {iterations} smoke runs:\n"
        + _leak_detector.format_delta(baseline, after)
    )
