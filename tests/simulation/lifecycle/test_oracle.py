"""Tests for the lifecycle Oracle — the 9 data-integrity invariants (Task 9).

Importing ``src.simulation.lifecycle.bootstrap`` FIRST pins DATABASE_URL at the
ephemeral test PG on 127.0.0.1:5434 + ARCIS_PG_CUTOVER_ENABLED=1 + PYTHONHASHSEED=0
before anything else touches the DB. The schema is bootstrapped against that PG in
``pg_conn`` (src.schema.postgres.create_all_tables — same registry tables the
prod cutover creates).

Each invariant is exercised twice: it PASSES on clean seeded state and FAILS on
a single seeded violation (orphan row, reconciled_stale close, position mismatch,
governor [RISK] log via the observer, empty holdout, stale/recycled pidfile). The
reproducibility hash is stable across two identical snapshots and differs on a
real data change.
"""

import src.simulation.lifecycle.bootstrap  # noqa: F401  — FIRST: pins 5434 + hashseed
import logging
from datetime import datetime

import psycopg2
import pytest

from src.schema.postgres import create_all_tables
from src.simulation.lifecycle.clock import ET, VirtualClock
from src.simulation.lifecycle.fakes.trading_client import FakePosition, FakeTradingClient
from src.simulation.lifecycle.fakes.trainer import FakeTrainerPidfile
from src.simulation.lifecycle.oracle import (
    CapitalLedger,
    Oracle,
    SwallowedErrorObserver,
)
from src.simulation.lifecycle.oracle.invariants import InvariantResult

SIM_DSN = "postgresql://test:test@127.0.0.1:5434/halcyon"

# Tables the oracle reads. Truncated between tests so each starts clean.
_ORACLE_TABLES = ("shadow_trades", "recommendations", "training_examples", "model_versions")


@pytest.fixture(scope="module")
def _schema():
    """Bootstrap the registry schema once against the ephemeral 5434 PG."""
    create_all_tables(SIM_DSN)


@pytest.fixture
def pg_conn(_schema):
    """A clean connection to the 5434 PG; truncates oracle tables per test."""
    conn = psycopg2.connect(SIM_DSN)
    conn.autocommit = True
    cur = conn.cursor()
    for tbl in _ORACLE_TABLES:
        cur.execute(f"TRUNCATE TABLE {tbl} CASCADE")
    cur.close()
    conn.autocommit = False
    try:
        yield conn
    finally:
        conn.rollback()
        conn.close()


def _insert_recommendation(conn, rec_id, ticker="AAPL"):
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO recommendations (recommendation_id, created_at, ticker) "
        "VALUES (%s, %s, %s)",
        (rec_id, "2026-05-22T10:00:00", ticker),
    )
    conn.commit()


def _insert_shadow_trade(conn, trade_id, *, recommendation_id, ticker, status,
                         actual_shares=None, order_type="paper", exit_reason=None,
                         pnl_dollars=None):
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO shadow_trades "
        "(trade_id, recommendation_id, ticker, status, actual_shares, order_type, "
        " exit_reason, pnl_dollars, created_at, updated_at) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (trade_id, recommendation_id, ticker, status, actual_shares, order_type,
         exit_reason, pnl_dollars, "2026-05-22T10:00:00", "2026-05-22T10:00:00"),
    )
    conn.commit()


def _insert_training_example(conn, example_id, *, source, quarantined=0):
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO training_examples "
        "(example_id, created_at, source, instruction, input_text, output_text, quarantined) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s)",
        (example_id, "2026-05-22T10:00:00", source, "i", "in", "out", quarantined),
    )
    conn.commit()


def _clean_world(conn):
    """Seed a clean, fully-attributed world: one rec, one open trade.

    Returns (ledger, fake_client, marks) wired so capital/position/honest-metric
    invariants all pass.
    """
    _insert_recommendation(conn, "rec-1", ticker="AAPL")
    _insert_shadow_trade(
        conn, "trade-1", recommendation_id="rec-1", ticker="AAPL",
        status="open", actual_shares=10.0, order_type="paper",
    )
    ledger = CapitalLedger(starting_capital=10_000.0)
    ledger.apply_fill(symbol="AAPL", side="buy", qty=10, price=100.0)
    fake = FakeTradingClient(clock=VirtualClock(datetime(2026, 5, 22, 10, tzinfo=ET)))
    fake._positions["AAPL"] = FakePosition(symbol="AAPL", qty=10.0, avg_entry_price=100.0)
    marks = {"AAPL": 100.0}
    return ledger, fake, marks


def _build_oracle(conn, ledger, fake, observer, marks, *, pidfile=None,
                  pidfile_identity="sim-trainer", clock=None):
    return Oracle(
        conn=conn,
        capital_ledger=ledger,
        fake_trading_client=fake,
        observer=observer,
        marks=marks,
        db_reported_pnl=ledger.realized_pnl(),
        governor_drawdown_pct=ledger.drawdown(marks) * 100.0,
        pidfile=pidfile,
        pidfile_identity=pidfile_identity,
        clock=clock,
    )


def _result(results, name):
    return next(r for r in results if r.name == name)


# ── clean world: every invariant passes ───────────────────────────────────────


def test_clean_world_all_invariants_pass(pg_conn):
    ledger, fake, marks = _clean_world(pg_conn)
    observer = SwallowedErrorObserver().install()
    try:
        results = _build_oracle(pg_conn, ledger, fake, observer, marks).assert_all()
    finally:
        observer.detach()
    assert all(isinstance(r, InvariantResult) for r in results)
    assert len(results) == 9
    failed = [r.name for r in results if not r.passed]
    assert failed == [], f"expected all pass, failed: {failed}"


# ── invariant 2: zero orphans ──────────────────────────────────────────────────


def test_invariant_2_flags_null_recommendation_orphan(pg_conn):
    ledger, fake, marks = _clean_world(pg_conn)
    _insert_shadow_trade(
        pg_conn, "trade-orphan", recommendation_id=None, ticker="MSFT",
        status="open", actual_shares=5.0, order_type="paper",
    )
    observer = SwallowedErrorObserver().install()
    try:
        results = _build_oracle(pg_conn, ledger, fake, observer, marks).assert_all()
    finally:
        observer.detach()
    assert not _result(results, "zero_orphans").passed


def test_invariant_2_flags_reconciled_order_type(pg_conn):
    ledger, fake, marks = _clean_world(pg_conn)
    _insert_shadow_trade(
        pg_conn, "trade-recon", recommendation_id="rec-1", ticker="AAPL",
        status="open", actual_shares=10.0, order_type="reconciled",
    )
    observer = SwallowedErrorObserver().install()
    try:
        results = _build_oracle(pg_conn, ledger, fake, observer, marks).assert_all()
    finally:
        observer.detach()
    assert not _result(results, "zero_orphans").passed


# ── invariant 3: zero synthetic / reconciled_stale closes ──────────────────────


def test_invariant_3_flags_reconciled_stale_close(pg_conn):
    ledger, fake, marks = _clean_world(pg_conn)
    _insert_shadow_trade(
        pg_conn, "trade-stale", recommendation_id="rec-1", ticker="AAPL",
        status="closed", actual_shares=10.0, order_type="paper",
        exit_reason="reconciled_stale",
    )
    observer = SwallowedErrorObserver().install()
    try:
        results = _build_oracle(pg_conn, ledger, fake, observer, marks).assert_all()
    finally:
        observer.detach()
    assert not _result(results, "zero_synthetic_closes").passed


# ── invariant 4: DB-open == FakeBroker positions ───────────────────────────────


def test_invariant_4_flags_position_mismatch(pg_conn):
    ledger, fake, marks = _clean_world(pg_conn)
    # Broker now reports a position the DB doesn't have open.
    fake._positions["TSLA"] = FakePosition(symbol="TSLA", qty=3.0, avg_entry_price=200.0)
    observer = SwallowedErrorObserver().install()
    try:
        results = _build_oracle(pg_conn, ledger, fake, observer, marks).assert_all()
    finally:
        observer.detach()
    assert not _result(results, "db_open_equals_broker").passed


# ── invariant 5: capital conservation (phantom P&L) ────────────────────────────


def test_invariant_5_flags_phantom_pnl(pg_conn):
    ledger, fake, marks = _clean_world(pg_conn)
    oracle = Oracle(
        conn=pg_conn,
        capital_ledger=ledger,
        fake_trading_client=fake,
        observer=SwallowedErrorObserver().install(),
        marks=marks,
        db_reported_pnl=999.0,  # no fill behind this — phantom
        governor_drawdown_pct=0.0,
    )
    try:
        results = oracle.assert_all()
    finally:
        oracle.observer.detach()
    assert not _result(results, "capital_conservation").passed


# ── invariant 6: honest metrics — degraded-correctly vs error-swallowed ────────


def test_invariant_6_error_swallowed_on_governor_risk_log(pg_conn):
    ledger, fake, marks = _clean_world(pg_conn)
    observer = SwallowedErrorObserver().install()
    # Emit the EXACT governor fail-conservative log the observer keys on.
    logging.getLogger("src.risk.governor").error(
        "[RISK] Drawdown computation failed: %s — using CONSERVATIVE estimate (15%%)",
        "boom",
    )
    try:
        results = _build_oracle(pg_conn, ledger, fake, observer, marks).assert_all()
    finally:
        observer.detach()
    res = _result(results, "honest_metrics")
    assert res.error_swallowed is True
    assert res.passed is False


def test_invariant_6_degraded_correctly_when_no_risk_log(pg_conn):
    ledger, fake, marks = _clean_world(pg_conn)
    observer = SwallowedErrorObserver().install()
    try:
        results = _build_oracle(pg_conn, ledger, fake, observer, marks).assert_all()
    finally:
        observer.detach()
    res = _result(results, "honest_metrics")
    assert res.error_swallowed is False
    assert res.passed is True


# ── invariant 7: corpus integrity (empty-holdout blocks promotion) ─────────────


def test_invariant_7_passes_when_no_model_registered_on_empty_holdout(pg_conn):
    ledger, fake, marks = _clean_world(pg_conn)
    # Only quarantined / synthetic examples => holdout of measured trades is empty.
    _insert_training_example(pg_conn, "ex-q", source="synthetic", quarantined=0)
    observer = SwallowedErrorObserver().install()
    try:
        results = _build_oracle(pg_conn, ledger, fake, observer, marks).assert_all()
    finally:
        observer.detach()
    # No model_versions row registered => promotion correctly blocked => pass.
    assert _result(results, "corpus_integrity").passed


def test_invariant_7_flags_promotion_on_empty_holdout(pg_conn):
    ledger, fake, marks = _clean_world(pg_conn)
    # Empty measured-trade corpus but a model got registered anyway => violation.
    cur = pg_conn.cursor()
    cur.execute(
        "INSERT INTO model_versions (version_id, version_name, created_at, status) "
        "VALUES (%s, %s, %s, %s)",
        ("v1", "halcyon-v1", "2026-05-22T10:00:00", "active"),
    )
    pg_conn.commit()
    observer = SwallowedErrorObserver().install()
    try:
        results = _build_oracle(pg_conn, ledger, fake, observer, marks).assert_all()
    finally:
        observer.detach()
    assert not _result(results, "corpus_integrity").passed


# ── invariant 8: no wedged processes (stale / recycled pidfile) ────────────────


def test_invariant_8_passes_on_fresh_live_pidfile(pg_conn, tmp_path):
    ledger, fake, marks = _clean_world(pg_conn)
    clock = VirtualClock(datetime(2026, 5, 22, 10, tzinfo=ET))
    pidfile = FakeTrainerPidfile(tmp_path / "trainer.pid", pid=4242, alive=True,
                                 identity="sim-trainer")
    pidfile.acquire()
    observer = SwallowedErrorObserver().install()
    try:
        results = _build_oracle(pg_conn, ledger, fake, observer, marks,
                                pidfile=pidfile, pidfile_identity="sim-trainer",
                                clock=clock).assert_all()
    finally:
        observer.detach()
    assert _result(results, "no_wedged_processes").passed


def test_invariant_8_flags_stale_pidfile(pg_conn, tmp_path):
    ledger, fake, marks = _clean_world(pg_conn)
    clock = VirtualClock(datetime(2026, 5, 22, 10, tzinfo=ET))
    pidfile = FakeTrainerPidfile(tmp_path / "trainer.pid", pid=4242, alive=False,
                                 identity="sim-trainer")
    pidfile.acquire()
    observer = SwallowedErrorObserver().install()
    try:
        results = _build_oracle(pg_conn, ledger, fake, observer, marks,
                                pidfile=pidfile, pidfile_identity="sim-trainer",
                                clock=clock).assert_all()
    finally:
        observer.detach()
    assert not _result(results, "no_wedged_processes").passed


def test_invariant_8_flags_recycled_pidfile(pg_conn, tmp_path):
    ledger, fake, marks = _clean_world(pg_conn)
    clock = VirtualClock(datetime(2026, 5, 22, 10, tzinfo=ET))
    pidfile = FakeTrainerPidfile(tmp_path / "trainer.pid", pid=4242, alive=True,
                                 identity="sim-trainer")
    pidfile.acquire()
    observer = SwallowedErrorObserver().install()
    try:
        results = _build_oracle(pg_conn, ledger, fake, observer, marks,
                                pidfile=pidfile, pidfile_identity="some-other-proc",
                                clock=clock).assert_all()
    finally:
        observer.detach()
    assert not _result(results, "no_wedged_processes").passed


# ── invariant 9: deterministic reproducibility ─────────────────────────────────


def test_invariant_9_hash_stable_across_identical_snapshots(pg_conn):
    ledger, fake, marks = _clean_world(pg_conn)
    observer = SwallowedErrorObserver().install()
    try:
        r1 = _build_oracle(pg_conn, ledger, fake, observer, marks).assert_all()
        r2 = _build_oracle(pg_conn, ledger, fake, observer, marks).assert_all()
    finally:
        observer.detach()
    h1 = _result(r1, "deterministic_reproducibility").detail
    h2 = _result(r2, "deterministic_reproducibility").detail
    assert h1 == h2
    assert _result(r1, "deterministic_reproducibility").passed


def test_invariant_9_hash_differs_on_real_data_change(pg_conn):
    ledger, fake, marks = _clean_world(pg_conn)
    observer = SwallowedErrorObserver().install()
    try:
        baseline = _result(
            _build_oracle(pg_conn, ledger, fake, observer, marks).assert_all(),
            "deterministic_reproducibility",
        ).detail
        # A real business-data change: add an attributed trade.
        _insert_shadow_trade(
            pg_conn, "trade-2", recommendation_id="rec-1", ticker="AAPL",
            status="open", actual_shares=4.0, order_type="paper",
        )
        changed = _result(
            _build_oracle(pg_conn, ledger, fake, observer, marks).assert_all(),
            "deterministic_reproducibility",
        ).detail
    finally:
        observer.detach()
    assert baseline != changed
