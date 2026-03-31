"""Tests for live and paper trade reconciliation."""

import sqlite3
from unittest.mock import patch

import pytest

from src.journal.store import initialize_database, insert_shadow_trade
from src.shadow_trading.reconcile import reconcile_live_trades, reconcile_paper_trades


@pytest.fixture
def db_path(tmp_path):
    """Create a temporary DB with shadow_trades table."""
    path = str(tmp_path / "test.sqlite3")
    initialize_database(path)
    return path


MOCK_ALPACA_POSITIONS = [
    {
        "symbol": "AAPL",
        "qty": 0.30,
        "avg_entry_price": 253.69,
        "current_price": 255.00,
        "market_value": 76.50,
        "unrealized_pl": 0.39,
        "unrealized_plpc": 0.0051,
    },
]


@patch("src.shadow_trading.alpaca_adapter.get_live_positions", return_value=MOCK_ALPACA_POSITIONS)
def test_reconcile_dry_run_no_modifications(mock_positions, db_path):
    """Dry-run mode should report discrepancies but not modify DB."""
    result = reconcile_live_trades(db_path=db_path, dry_run=True)

    assert result["alpaca_positions"] == 1
    assert result["tracked_positions"] == 0
    assert result["orphaned"] == ["AAPL"]
    assert result["backfilled"] == []
    assert result["marked_closed"] == []

    # Verify no rows inserted
    with sqlite3.connect(db_path) as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM shadow_trades WHERE source = 'live'"
        ).fetchone()[0]
    assert count == 0


@patch("src.shadow_trading.alpaca_adapter.get_live_positions", return_value=MOCK_ALPACA_POSITIONS)
def test_reconcile_backfills_orphaned(mock_positions, db_path):
    """Orphaned Alpaca positions should be backfilled into shadow_trades."""
    result = reconcile_live_trades(db_path=db_path, dry_run=False)

    assert result["orphaned"] == ["AAPL"]
    assert result["backfilled"] == ["AAPL"]

    # Verify row inserted
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM shadow_trades WHERE source = 'live' AND ticker = 'AAPL'"
        ).fetchall()

    assert len(rows) == 1
    row = dict(rows[0])
    assert row["status"] == "open"
    assert row["source"] == "live"
    assert row["order_type"] == "reconciled"
    assert abs(row["actual_entry_price"] - 253.69) < 0.01
    assert abs(row["planned_shares"] - 0.30) < 0.01


@patch("src.shadow_trading.alpaca_adapter.get_live_positions", return_value=[])
def test_reconcile_marks_stale(mock_positions, db_path):
    """DB records with no Alpaca position should be marked closed."""
    # Insert a stale live trade
    insert_shadow_trade(
        {
            "ticker": "MSFT",
            "status": "open",
            "source": "live",
            "direction": "long",
            "entry_price": 400.0,
            "created_at": "2026-03-27T10:00:00",
            "updated_at": "2026-03-27T10:00:00",
        },
        db_path,
    )

    result = reconcile_live_trades(db_path=db_path, dry_run=False)

    assert result["stale"] == ["MSFT"]
    assert result["marked_closed"] == ["MSFT"]

    # Verify row updated
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT status, exit_reason FROM shadow_trades WHERE ticker = 'MSFT'"
        ).fetchone()

    assert row["status"] == "closed"
    assert row["exit_reason"] == "reconciled_stale"


@patch("src.shadow_trading.alpaca_adapter.get_live_positions", return_value=MOCK_ALPACA_POSITIONS)
def test_reconcile_no_discrepancies(mock_positions, db_path):
    """When everything matches, no changes should be made."""
    # Insert a matching live trade
    insert_shadow_trade(
        {
            "ticker": "AAPL",
            "status": "open",
            "source": "live",
            "direction": "long",
            "entry_price": 253.69,
            "created_at": "2026-03-27T10:00:00",
            "updated_at": "2026-03-27T10:00:00",
        },
        db_path,
    )

    result = reconcile_live_trades(db_path=db_path, dry_run=False)

    assert result["alpaca_positions"] == 1
    assert result["tracked_positions"] == 1
    assert result["orphaned"] == []
    assert result["stale"] == []
    assert result["backfilled"] == []
    assert result["marked_closed"] == []


@patch("src.shadow_trading.alpaca_adapter.get_live_positions", return_value=MOCK_ALPACA_POSITIONS)
def test_reconcile_ignores_paper_trades(mock_positions, db_path):
    """Paper trades should not count as tracked live positions."""
    # Insert a paper trade for AAPL — should NOT match
    insert_shadow_trade(
        {
            "ticker": "AAPL",
            "status": "open",
            "source": "paper",
            "direction": "long",
            "entry_price": 253.69,
            "created_at": "2026-03-27T10:00:00",
            "updated_at": "2026-03-27T10:00:00",
        },
        db_path,
    )

    result = reconcile_live_trades(db_path=db_path, dry_run=False)

    # AAPL should still be orphaned because only paper trade exists
    assert result["orphaned"] == ["AAPL"]
    assert result["backfilled"] == ["AAPL"]


# ── Paper trade reconciliation tests ──


MOCK_PAPER_POSITIONS = [
    {
        "symbol": "AAPL",
        "qty": 10.0,
        "avg_entry_price": 253.69,
        "current_price": 255.00,
        "market_value": 2550.00,
        "unrealized_pl": 13.10,
        "unrealized_plpc": 0.0051,
    },
]


@patch(
    "src.shadow_trading.alpaca_adapter.get_all_positions",
    return_value=MOCK_PAPER_POSITIONS,
)
def test_paper_reconcile_all_matched(mock_positions, db_path):
    """When Alpaca and local DB match, no discrepancies reported."""
    insert_shadow_trade(
        {
            "ticker": "AAPL",
            "status": "open",
            "source": "paper",
            "direction": "long",
            "entry_price": 253.69,
            "planned_shares": 10,
            "created_at": "2026-03-27T10:00:00",
            "updated_at": "2026-03-27T10:00:00",
        },
        db_path,
    )

    result = reconcile_paper_trades(db_path=db_path, dry_run=False)

    assert result["matched"] == 1
    assert result["orphaned"] == []
    assert result["stale"] == []
    assert result["discrepancies"] == []
    assert result["backfilled"] == []
    assert result["error"] is None


@patch(
    "src.shadow_trading.alpaca_adapter.get_all_positions",
    return_value=MOCK_PAPER_POSITIONS,
)
def test_paper_reconcile_backfills_orphaned(mock_positions, db_path):
    """Orphaned Alpaca paper positions should be backfilled."""
    result = reconcile_paper_trades(db_path=db_path, dry_run=False)

    assert len(result["orphaned"]) == 1
    assert result["orphaned"][0]["ticker"] == "AAPL"
    assert result["backfilled"] == ["AAPL"]

    # Verify row inserted with source='paper'
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM shadow_trades WHERE source = 'paper' AND ticker = 'AAPL'"
        ).fetchall()

    assert len(rows) == 1
    row = dict(rows[0])
    assert row["status"] == "open"
    assert row["source"] == "paper"
    assert row["order_type"] == "reconciled"
    assert abs(row["actual_entry_price"] - 253.69) < 0.01
    assert abs(row["planned_shares"] - 10.0) < 0.01


@patch(
    "src.shadow_trading.alpaca_adapter.get_all_positions",
    return_value=[],
)
def test_paper_reconcile_stale_not_auto_closed(mock_positions, db_path):
    """Stale paper trades should be flagged but NOT auto-closed."""
    insert_shadow_trade(
        {
            "ticker": "MSFT",
            "status": "open",
            "source": "paper",
            "direction": "long",
            "entry_price": 400.0,
            "planned_shares": 5,
            "created_at": "2026-03-27T10:00:00",
            "updated_at": "2026-03-27T10:00:00",
        },
        db_path,
    )

    result = reconcile_paper_trades(db_path=db_path, dry_run=False)

    assert len(result["stale"]) == 1
    assert result["stale"][0]["ticker"] == "MSFT"

    # Verify status is still 'open' — NOT auto-closed
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT status, exit_reason FROM shadow_trades WHERE ticker = 'MSFT'"
        ).fetchone()

    assert row["status"] == "open"
    assert row["exit_reason"] is None


@patch(
    "src.shadow_trading.alpaca_adapter.get_all_positions",
    return_value=[
        {
            "symbol": "AAPL",
            "qty": 5.0,
            "avg_entry_price": 253.69,
            "current_price": 255.00,
            "market_value": 1275.00,
            "unrealized_pl": 6.55,
            "unrealized_plpc": 0.0051,
        },
    ],
)
def test_paper_reconcile_qty_discrepancy(mock_positions, db_path):
    """Qty mismatch between local and Alpaca should be reported."""
    insert_shadow_trade(
        {
            "ticker": "AAPL",
            "status": "open",
            "source": "paper",
            "direction": "long",
            "entry_price": 253.69,
            "planned_shares": 10,
            "created_at": "2026-03-27T10:00:00",
            "updated_at": "2026-03-27T10:00:00",
        },
        db_path,
    )

    result = reconcile_paper_trades(db_path=db_path, dry_run=False)

    assert result["matched"] == 0
    assert len(result["discrepancies"]) == 1
    assert result["discrepancies"][0]["ticker"] == "AAPL"
    assert "qty mismatch" in result["discrepancies"][0]["issue"]
