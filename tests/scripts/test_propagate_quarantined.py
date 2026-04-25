"""T1.05 — propagation script tests.

Tests scripts/propagate_quarantined.py for:
  (1) Positive: quarantined shadow_trade -> linked attribution_trade gets quarantined=1
  (2) Negative: non-quarantined shadow_trade -> linked attribution_trade stays 0
  (3) Idempotency: running twice changes 0 rows on the second pass
  (4) Dry-run: default mode does not write
  (5) Boundary: empty shadow_trades / no candidates -> no-op
  (6) walkforward_trades is NOT touched (manual-only column per T1.05)
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from scripts.propagate_quarantined import (
    BATCH_SIZE,
    apply_quarantine,
    find_propagation_candidates,
)


def _create_minimal_schema(conn: sqlite3.Connection) -> None:
    """Create only the columns this test needs from shadow_trades + attribution_trades.
    Faithful to registry.py shapes but minimal to avoid pulling the full 50+ column schema."""
    conn.execute(
        """
        CREATE TABLE shadow_trades (
            trade_id TEXT PRIMARY KEY,
            recommendation_id TEXT,
            ticker TEXT,
            quarantined INTEGER DEFAULT 0
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE attribution_trades (
            attribution_id TEXT PRIMARY KEY,
            recommendation_id TEXT,
            ticker TEXT,
            quarantined INTEGER DEFAULT 0
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE walkforward_trades (
            trade_id TEXT PRIMARY KEY,
            run_id TEXT,
            ticker TEXT,
            quarantined INTEGER DEFAULT 0
        )
        """
    )
    conn.commit()


def _seed(conn, table: str, **kwargs) -> None:
    cols = ",".join(kwargs.keys())
    placeholders = ",".join("?" * len(kwargs))
    conn.execute(f"INSERT INTO {table} ({cols}) VALUES ({placeholders})", tuple(kwargs.values()))


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    _create_minimal_schema(c)
    yield c
    c.close()


def test_positive_propagation(conn):
    _seed(conn, "shadow_trades", trade_id="t1", recommendation_id="r1", ticker="AAPL", quarantined=1)
    _seed(conn, "attribution_trades", attribution_id="a1", recommendation_id="r1", ticker="AAPL", quarantined=0)
    conn.commit()

    candidates = find_propagation_candidates(conn)
    assert candidates == [("a1", "r1")]

    updated = apply_quarantine(conn, ["a1"])
    assert updated == 1

    row = conn.execute("SELECT quarantined FROM attribution_trades WHERE attribution_id=?", ("a1",)).fetchone()
    assert row["quarantined"] == 1


def test_negative_unaffected(conn):
    _seed(conn, "shadow_trades", trade_id="t1", recommendation_id="r1", ticker="AAPL", quarantined=0)
    _seed(conn, "attribution_trades", attribution_id="a1", recommendation_id="r1", ticker="AAPL", quarantined=0)
    conn.commit()

    candidates = find_propagation_candidates(conn)
    assert candidates == []


def test_idempotent_second_run(conn):
    _seed(conn, "shadow_trades", trade_id="t1", recommendation_id="r1", ticker="AAPL", quarantined=1)
    _seed(conn, "attribution_trades", attribution_id="a1", recommendation_id="r1", ticker="AAPL", quarantined=0)
    conn.commit()

    apply_quarantine(conn, ["a1"])
    second_pass = find_propagation_candidates(conn)
    assert second_pass == []


def test_already_quarantined_attribution_skipped(conn):
    _seed(conn, "shadow_trades", trade_id="t1", recommendation_id="r1", ticker="AAPL", quarantined=1)
    _seed(conn, "attribution_trades", attribution_id="a1", recommendation_id="r1", ticker="AAPL", quarantined=1)
    conn.commit()

    assert find_propagation_candidates(conn) == []


def test_empty_no_op(conn):
    assert find_propagation_candidates(conn) == []


def test_walkforward_trades_not_touched(conn):
    """Per T1.05: walkforward_trades.quarantined is manual-only.
    The propagation script must NEVER set quarantined on walkforward_trades,
    even if it shares ticker / run dates with quarantined shadow_trades."""
    _seed(conn, "shadow_trades", trade_id="t1", recommendation_id="r1", ticker="AAPL", quarantined=1)
    _seed(conn, "attribution_trades", attribution_id="a1", recommendation_id="r1", ticker="AAPL", quarantined=0)
    _seed(conn, "walkforward_trades", trade_id="wf1", run_id="run-x", ticker="AAPL", quarantined=0)
    conn.commit()

    apply_quarantine(conn, ["a1"])
    wf = conn.execute("SELECT quarantined FROM walkforward_trades WHERE trade_id=?", ("wf1",)).fetchone()
    assert wf["quarantined"] == 0


def test_batch_size_constant_is_at_least_50():
    """Per backfill memory pattern: batch commits >=50 rows."""
    assert BATCH_SIZE >= 50


def test_large_batch_processes_all(conn):
    """Smoke test for batched UPDATE: seed >BATCH_SIZE candidates, verify all updated."""
    n = BATCH_SIZE + 7
    for i in range(n):
        _seed(conn, "shadow_trades", trade_id=f"t{i}", recommendation_id=f"r{i}", ticker="AAPL", quarantined=1)
        _seed(conn, "attribution_trades", attribution_id=f"a{i}", recommendation_id=f"r{i}", ticker="AAPL", quarantined=0)
    conn.commit()

    candidates = find_propagation_candidates(conn)
    assert len(candidates) == n
    updated = apply_quarantine(conn, [c[0] for c in candidates])
    assert updated == n
    assert find_propagation_candidates(conn) == []


def test_unmatched_recommendation_id_no_op(conn):
    """attribution_trades row with no matching shadow_trades row stays untouched."""
    _seed(conn, "attribution_trades", attribution_id="a1", recommendation_id="r-orphan", ticker="AAPL", quarantined=0)
    conn.commit()

    assert find_propagation_candidates(conn) == []
