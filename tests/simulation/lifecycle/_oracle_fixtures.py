"""Shared Oracle fixture builders for lifecycle regression tests.

Hoisted from tests/simulation/lifecycle/test_oracle.py so that
test_no_conn_leak.py can reuse the same clean-world and oracle-builder
patterns without duplicating them.

Called by: tests/simulation/lifecycle/test_oracle.py,
           tests/simulation/lifecycle/test_no_conn_leak.py
Calls: psycopg2, src.simulation.lifecycle.oracle builders
Owns tables: none (read/write via conn passed in by the caller)
Config keys: none
Tests: n/a (this is a helper module, not a test module)
"""

from __future__ import annotations

from datetime import datetime

import psycopg2

from src.simulation.lifecycle.clock import ET, VirtualClock
from src.simulation.lifecycle.fakes.trading_client import FakePosition, FakeTradingClient
from src.simulation.lifecycle.oracle import (
    CapitalLedger,
    Oracle,
    SwallowedErrorObserver,
)

SIM_DSN = "postgresql://test:test@127.0.0.1:5434/halcyon"

# Tables the oracle reads. Truncated between tests so each starts clean.
_ORACLE_TABLES = ("shadow_trades", "recommendations", "training_examples", "model_versions")


def ensure_schema() -> None:
    """Bootstrap the registry schema once against the ephemeral 5434 PG."""
    from src.schema.postgres import create_all_tables
    create_all_tables(SIM_DSN)


def truncate_oracle_tables() -> None:
    """TRUNCATE all oracle tables via a short-lived autocommit conn."""
    conn = psycopg2.connect(SIM_DSN)
    conn.autocommit = True
    cur = conn.cursor()
    for tbl in _ORACLE_TABLES:
        cur.execute(f"TRUNCATE TABLE {tbl} CASCADE")
    cur.close()
    conn.close()


def insert_recommendation(conn, rec_id, ticker="AAPL"):
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO recommendations (recommendation_id, created_at, ticker) "
        "VALUES (%s, %s, %s)",
        (rec_id, "2026-05-22T10:00:00", ticker),
    )
    conn.commit()


def insert_shadow_trade(conn, trade_id, *, recommendation_id, ticker, status,
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


def clean_world(conn):
    """Seed a clean, fully-attributed world: one rec, one open trade.

    Returns (ledger, fake_client, marks) wired so capital/position/honest-metric
    invariants all pass.
    """
    insert_recommendation(conn, "rec-1", ticker="AAPL")
    insert_shadow_trade(
        conn, "trade-1", recommendation_id="rec-1", ticker="AAPL",
        status="open", actual_shares=10.0, order_type="paper",
    )
    ledger = CapitalLedger(starting_capital=10_000.0)
    ledger.apply_fill(symbol="AAPL", side="buy", qty=10, price=100.0)
    fake = FakeTradingClient(clock=VirtualClock(datetime(2026, 5, 22, 10, tzinfo=ET)))
    fake._positions["AAPL"] = FakePosition(symbol="AAPL", qty=10.0, avg_entry_price=100.0)
    marks = {"AAPL": 100.0}
    return ledger, fake, marks


def build_oracle(conn, ledger, fake, observer, marks, *, pidfile=None,
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
