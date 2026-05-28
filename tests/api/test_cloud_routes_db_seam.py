"""DB-seam boundary-touch tests — cloud_routes kpis SQL/schema contract.

Standards: docs/standards/boundary-touch-tests.md
Discipline: §1 "drives both sides of the seam with real artifacts"

Seam: journal.store.get_closed_shadow_trades() issues a REAL SQL query against
a SQLite DB. The contract is that the returned row shape matches what the kpis
orchestrator expects (pnl_pct, spy_return_over_hold, direction, actual_entry_time)
and that the quarantine filter and row-count behaviour are correct.

This test drives a real temp SQLite DB (no mocks at the seam) and asserts on
the actual returned rows.

Non-vacuity proved by:
  1. Replaced `COALESCE(quarantined, 0) = 0` with `1=1` in get_closed_shadow_trades:
     test_quarantined_trade_excluded FAILED (quarantined trade appeared in results).
  2. Changed `return [dict(row) for row in rows]` to `return []`:
     test_fetch_closed_trades_returns_real_rows FAILED (assert 0 == 1).
  3. Swapped `pnl_pct` column in INSERT to 0.0 but asserted 2.5:
     test_closed_trade_row_has_kpi_fields FAILED (approx assertion on pnl_pct).
All src/ mutations reverted with `git checkout` before committing.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest


def _insert_trade(conn, trade_id, ticker, status, closed_time, pnl_pct=2.5, quarantined=0):
    """Insert a shadow_trades row with the required NOT NULL fields."""
    conn.execute(
        """
        INSERT INTO shadow_trades
          (trade_id, strategy_id, ticker, status, pnl_pct,
           direction, actual_exit_time, actual_entry_time, entry_price,
           source, created_at, updated_at, quarantined)
        VALUES
          (?, 'strat-a', ?, ?, ?,
           'long', ?, ?, 100.0, 'test', ?, ?, ?)
        """,
        (trade_id, ticker, status, pnl_pct,
         closed_time, closed_time, closed_time, closed_time, quarantined),
    )


def _make_test_db(tmp_path: Path) -> str:
    """Create a minimal SQLite DB with the shadow_trades table and return its path."""
    db_path = str(tmp_path / "test_journal.sqlite3")
    from src.journal.store import initialize_database
    initialize_database(db_path)
    return db_path


def test_fetch_closed_trades_returns_real_rows(tmp_path):
    """get_closed_shadow_trades against a real temp DB returns the inserted closed trade.

    Non-vacuity: changing `return [dict(row) for row in rows]` to `return []`
    causes this test to FAIL with AssertionError: assert 0 == 1.
    """
    from src.journal.store import get_closed_shadow_trades

    db_path = _make_test_db(tmp_path)
    closed_time = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()

    with sqlite3.connect(db_path) as conn:
        _insert_trade(conn, "trade-closed-001", "AAPL", "closed", closed_time, pnl_pct=2.5)
        conn.commit()

    rows = get_closed_shadow_trades(days=3650, db_path=db_path)

    assert len(rows) == 1, f"expected 1 closed trade, got {len(rows)}"
    assert rows[0]["trade_id"] == "trade-closed-001"
    assert rows[0]["status"] == "closed"
    assert float(rows[0]["pnl_pct"]) == pytest.approx(2.5)


def test_quarantined_trade_excluded(tmp_path):
    """Quarantined trades (quarantined=1) are excluded from closed-trade results.

    Non-vacuity: replacing `COALESCE(quarantined, 0) = 0` with `1=1` causes
    the quarantined trade to appear in results; this test FAILS with
    AssertionError: len == 2 instead of 1.
    """
    from src.journal.store import get_closed_shadow_trades

    db_path = _make_test_db(tmp_path)
    closed_time = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()

    with sqlite3.connect(db_path) as conn:
        _insert_trade(conn, "trade-ok", "AAPL", "closed", closed_time, quarantined=0)
        _insert_trade(conn, "trade-quar", "MSFT", "closed", closed_time, quarantined=1)
        conn.commit()

    rows = get_closed_shadow_trades(days=3650, db_path=db_path)
    tickers = [r["ticker"] for r in rows]

    assert "AAPL" in tickers, "non-quarantined AAPL trade must appear"
    assert "MSFT" not in tickers, "quarantined MSFT trade must be excluded"
    assert len(rows) == 1, f"expected 1 row, got {len(rows)}"


def test_closed_trade_row_has_kpi_fields(tmp_path):
    """Closed trade row exposes all fields the kpis orchestrator reads.

    Non-vacuity: setting pnl_pct=0.0 in the INSERT but asserting 2.5 causes
    this test to FAIL with ApproxDecimal assertion failure.
    """
    from src.journal.store import get_closed_shadow_trades

    db_path = _make_test_db(tmp_path)
    closed_time = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()

    with sqlite3.connect(db_path) as conn:
        _insert_trade(conn, "trade-field-check", "AAPL", "closed", closed_time, pnl_pct=2.5)
        conn.commit()

    rows = get_closed_shadow_trades(days=3650, db_path=db_path)
    assert rows, "need at least one row to check field shape"
    row = rows[0]

    # Fields kpis.get_kpis() reads on each trade row
    for field_name in ("pnl_pct", "spy_return_over_hold", "direction", "actual_entry_time"):
        assert field_name in row, f"row missing field {field_name!r} needed by kpis orchestrator"
    assert float(row["pnl_pct"]) == pytest.approx(2.5)
