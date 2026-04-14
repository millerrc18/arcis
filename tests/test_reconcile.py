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
    """DB records with no Alpaca position should be marked closed with actual_exit_time."""
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

    # Verify row updated with actual_exit_time set
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT status, exit_reason, actual_exit_time FROM shadow_trades WHERE ticker = 'MSFT'"
        ).fetchone()

    assert row["status"] == "closed"
    assert row["exit_reason"] == "reconciled_stale"
    assert row["actual_exit_time"] is not None


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
def test_paper_reconcile_stale_auto_closed(mock_positions, db_path):
    """Stale paper trades older than 1 hour should be auto-closed."""
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
    assert result["marked_closed"] == ["MSFT"]

    # Verify trade is closed with actual_exit_time set
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT status, exit_reason, actual_exit_time FROM shadow_trades WHERE ticker = 'MSFT'"
        ).fetchone()

    assert row["status"] == "closed"
    assert row["exit_reason"] == "reconciled_stale"
    assert row["actual_exit_time"] is not None


@patch(
    "src.shadow_trading.alpaca_adapter.get_all_positions",
    return_value=[],
)
def test_paper_reconcile_skips_recent_trade(mock_positions, db_path):
    """Stale paper trades less than 1 hour old should NOT be auto-closed (safety guard)."""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    # Create a trade with a very recent created_at (now)
    now_str = datetime.now(ZoneInfo("America/New_York")).isoformat()
    insert_shadow_trade(
        {
            "ticker": "NVDA",
            "status": "open",
            "source": "paper",
            "direction": "long",
            "entry_price": 800.0,
            "planned_shares": 2,
            "created_at": now_str,
            "updated_at": now_str,
        },
        db_path,
    )

    result = reconcile_paper_trades(db_path=db_path, dry_run=False)

    assert len(result["stale"]) == 1
    assert result["stale"][0]["ticker"] == "NVDA"
    assert result["marked_closed"] == []  # NOT closed — too recent

    # Verify status is still 'open'
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT status, exit_reason FROM shadow_trades WHERE ticker = 'NVDA'"
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


@patch("src.shadow_trading.alpaca_adapter.get_live_positions", return_value=[])
def test_reconcile_stale_without_yfinance(mock_positions, db_path):
    """Stale trades should be closed even when yfinance price lookup fails."""
    insert_shadow_trade(
        {
            "ticker": "FAKE",
            "status": "open",
            "source": "live",
            "direction": "long",
            "entry_price": 100.0,
            "actual_entry_price": 100.0,
            "planned_shares": 10,
            "created_at": "2026-03-27T10:00:00",
            "updated_at": "2026-03-27T10:00:00",
        },
        db_path,
    )

    result = reconcile_live_trades(db_path=db_path, dry_run=False)

    assert result["marked_closed"] == ["FAKE"]

    # Verify trade is closed with defaults (pnl=0, exit_price=0) and actual_exit_time set
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT status, exit_reason, actual_exit_time, pnl_dollars, actual_exit_price "
            "FROM shadow_trades WHERE ticker = 'FAKE'"
        ).fetchone()

    assert row["status"] == "closed"
    assert row["exit_reason"] == "reconciled_stale"
    assert row["actual_exit_time"] is not None
    # P&L defaults to 0.0 when yfinance fails (better than invisible trade)
    assert row["pnl_dollars"] == 0.0
    assert row["actual_exit_price"] == 0.0


# ── Fix #356: Cancel-before-close tests ──


@patch(
    "src.shadow_trading.alpaca_adapter.cancel_orders_for_ticker",
    return_value=2,
)
@patch(
    "src.shadow_trading.alpaca_adapter.get_all_positions",
    return_value=[],
)
def test_paper_reconcile_cancels_orders_before_close(mock_positions, mock_cancel, db_path):
    """Stale paper trades should trigger cancel_orders_for_ticker before closing (#356)."""
    insert_shadow_trade(
        {
            "ticker": "TSLA",
            "status": "open",
            "source": "paper",
            "direction": "long",
            "entry_price": 200.0,
            "planned_shares": 3,
            "created_at": "2026-03-27T10:00:00",
            "updated_at": "2026-03-27T10:00:00",
        },
        db_path,
    )

    result = reconcile_paper_trades(db_path=db_path, dry_run=False)

    assert result["marked_closed"] == ["TSLA"]
    mock_cancel.assert_called_once_with("TSLA")

    # Trade must be fully closed
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT status, exit_reason FROM shadow_trades WHERE ticker = 'TSLA'"
        ).fetchone()
    assert row["status"] == "closed"
    assert row["exit_reason"] == "reconciled_stale"


@patch(
    "src.shadow_trading.alpaca_adapter.cancel_orders_for_ticker",
    side_effect=Exception("Alpaca timeout"),
)
@patch(
    "src.shadow_trading.alpaca_adapter.get_all_positions",
    return_value=[],
)
def test_paper_reconcile_cancel_failure_does_not_block_close(mock_positions, mock_cancel, db_path):
    """A cancel_orders_for_ticker failure must not prevent the stale trade from closing (#356)."""
    insert_shadow_trade(
        {
            "ticker": "GOOG",
            "status": "open",
            "source": "paper",
            "direction": "long",
            "entry_price": 150.0,
            "planned_shares": 1,
            "created_at": "2026-03-27T10:00:00",
            "updated_at": "2026-03-27T10:00:00",
        },
        db_path,
    )

    result = reconcile_paper_trades(db_path=db_path, dry_run=False)

    # Cancel raised but close must still proceed
    assert result["marked_closed"] == ["GOOG"]

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT status FROM shadow_trades WHERE ticker = 'GOOG'"
        ).fetchone()
    assert row["status"] == "closed"


# ── Task 14: submission_uncertain reconciliation tests (#352, #353) ──


@patch(
    "src.shadow_trading.alpaca_adapter.get_all_positions",
    return_value=[
        {
            "symbol": "AMZN",
            "qty": 5.0,
            "avg_entry_price": 180.0,
            "current_price": 182.0,
            "market_value": 910.0,
            "unrealized_pl": 10.0,
            "unrealized_plpc": 0.011,
        },
    ],
)
def test_uncertain_trade_promoted_when_alpaca_has_position(mock_positions, db_path):
    """submission_uncertain trade should be promoted to open when Alpaca has the position."""
    insert_shadow_trade(
        {
            "ticker": "AMZN",
            "status": "submission_uncertain",
            "source": "paper",
            "direction": "long",
            "entry_price": 180.0,
            "planned_shares": 5,
            "created_at": "2026-03-27T10:00:00",
            "updated_at": "2026-03-27T10:00:00",
        },
        db_path,
    )

    reconcile_paper_trades(db_path=db_path, dry_run=False)

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT status FROM shadow_trades WHERE ticker = 'AMZN'"
        ).fetchone()
    assert row["status"] == "open"


@patch(
    "src.shadow_trading.alpaca_adapter.get_all_positions",
    return_value=[],
)
def test_uncertain_trade_marked_failed_when_alpaca_has_no_position(mock_positions, db_path):
    """submission_uncertain trade should be set to failed when Alpaca has no position."""
    insert_shadow_trade(
        {
            "ticker": "META",
            "status": "submission_uncertain",
            "source": "paper",
            "direction": "long",
            "entry_price": 500.0,
            "planned_shares": 2,
            "created_at": "2026-03-27T10:00:00",
            "updated_at": "2026-03-27T10:00:00",
        },
        db_path,
    )

    reconcile_paper_trades(db_path=db_path, dry_run=False)

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT status FROM shadow_trades WHERE ticker = 'META'"
        ).fetchone()
    assert row["status"] == "failed"


# ── Phase 2.4: exit-overshoot detection (2026-04-14 regression) ──────

_SHORT_NVDA = [
    {
        "symbol": "NVDA",
        "qty": -147.0,  # SHORT — long-only exit over-shot 3x (49 × 3)
        "avg_entry_price": 150.0,
        "current_price": 148.0,
        "market_value": -21756.0,
        "unrealized_pl": 294.0,
        "unrealized_plpc": 0.0135,
    },
]

_LONG_NVDA = [
    {
        "symbol": "NVDA",
        "qty": 49.0,
        "avg_entry_price": 150.0,
        "current_price": 148.0,
        "market_value": 7252.0,
        "unrealized_pl": -98.0,
        "unrealized_plpc": -0.0133,
    },
]


@patch(
    "src.shadow_trading.alpaca_adapter.get_all_positions",
    return_value=_SHORT_NVDA,
)
def test_stuck_exit_with_short_position_needs_manual_review(mock_positions, db_path):
    """2026-04-14 regression guard.

    A stuck exit_failed trade whose Alpaca position is SHORT (qty < 0) means
    the exit over-shot — each cycle's SELL filled in the background while
    the reconciler flipped the trade back to 'open', so the scanner kept
    re-submitting SELLs and extending the short. Reconcile must detect the
    negative qty and halt the trade (needs_manual_review) instead of
    reverting to open.
    """
    insert_shadow_trade(
        {
            "ticker": "NVDA",
            "status": "exit_failed",
            "source": "paper",
            "direction": "long",
            "entry_price": 150.0,
            "planned_shares": 49,
            "exit_reason": "stop_hit",
            "created_at": "2026-04-14T09:30:00",
            "updated_at": "2026-04-14T15:13:00",
        },
        db_path,
    )

    reconcile_paper_trades(db_path=db_path, dry_run=False)

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT status, exit_reason FROM shadow_trades WHERE ticker = 'NVDA'"
        ).fetchone()
    assert row["status"] == "needs_manual_review", (
        f"Expected needs_manual_review; got {row['status']} — "
        f"reconciler reverted to open despite short position"
    )
    assert "overshoot" in (row["exit_reason"] or "").lower()


@patch(
    "src.shadow_trading.alpaca_adapter.get_all_positions",
    return_value=_LONG_NVDA,
)
def test_stuck_exit_with_long_position_still_reverts_to_open(mock_positions, db_path):
    """Preservation test: legitimate reverts (long qty > 0) must still work.

    If the position is still long at the expected size, the exit genuinely
    did not happen and the reconciler should revert to open so the scanner
    can retry.
    """
    insert_shadow_trade(
        {
            "ticker": "NVDA",
            "status": "exit_failed",
            "source": "paper",
            "direction": "long",
            "entry_price": 150.0,
            "planned_shares": 49,
            "exit_reason": "stop_hit",
            "created_at": "2026-04-14T09:30:00",
            "updated_at": "2026-04-14T15:13:00",
        },
        db_path,
    )

    reconcile_paper_trades(db_path=db_path, dry_run=False)

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT status FROM shadow_trades WHERE ticker = 'NVDA'"
        ).fetchone()
    assert row["status"] == "open"


@patch(
    "src.shadow_trading.alpaca_adapter.get_all_positions",
    return_value=[],
)
def test_uncertain_trade_not_resolved_in_dry_run(mock_positions, db_path):
    """submission_uncertain trades must not be modified when dry_run=True."""
    insert_shadow_trade(
        {
            "ticker": "NFLX",
            "status": "submission_uncertain",
            "source": "paper",
            "direction": "long",
            "entry_price": 600.0,
            "planned_shares": 1,
            "created_at": "2026-03-27T10:00:00",
            "updated_at": "2026-03-27T10:00:00",
        },
        db_path,
    )

    reconcile_paper_trades(db_path=db_path, dry_run=True)

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT status FROM shadow_trades WHERE ticker = 'NFLX'"
        ).fetchone()
    assert row["status"] == "submission_uncertain"

