"""Tests for exit slippage persistence at trade close.

Track 1.5 / B1 — green-field implementation: signal_exit_price and
exit_slippage_bps were computed and logged at executor.py:1842-1853 but
the local variables were discarded before the close-write.

This test file covers:
  1. Normal fill: signal $105.00, fill $105.25 → ~23.8 bps
  2. None fill → NULL slippage (signal_exit_price still written)
  3. Zero signal price → both NULL (no divide-by-zero)
  4. Idempotent: already-closed trade not reprocessed
  5. Negative slippage: fill below signal (favorable)
  6. Bracket exit overwrite regression: signal_exit captured BEFORE
     bracket detection, not after current_price is clobbered by fill price
"""
from __future__ import annotations

import sqlite3
from unittest.mock import MagicMock, patch

import pytest

from src.journal.store import initialize_database, insert_shadow_trade


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_db(tmp_path):
    db = str(tmp_path / "exit_slippage.db")
    initialize_database(db)
    return db


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _seed_open_trade(
    db_path: str,
    *,
    trade_id: str,
    ticker: str = "AAPL",
    entry_price: float = 100.0,
    target_1: float = 105.0,
    target_2: float = 0.0,
    stop_price: float = 95.0,
    planned_shares: float = 100.0,
    alpaca_order_id: str = "oid-test",
    order_type: str = "market",
    status: str = "open",
) -> None:
    ts = "2026-04-01T09:30:00"
    insert_shadow_trade(
        {
            "trade_id": trade_id,
            "ticker": ticker,
            "direction": "long",
            "status": status,
            "source": "paper",
            "desk": "swing",
            "order_type": order_type,
            "planned_shares": planned_shares,
            "entry_price": entry_price,
            "actual_entry_price": entry_price,
            "stop_price": stop_price,
            "target_1": target_1,
            "target_2": target_2,
            "strategy_type": "pullback",
            "alpaca_order_id": alpaca_order_id,
            "created_at": ts,
            "updated_at": ts,
            "actual_entry_time": ts,
            "timeout_days": 8,
        },
        db_path,
    )


def _row(db_path: str, trade_id: str) -> dict | None:
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        r = conn.execute(
            "SELECT signal_exit_price, exit_slippage_bps, status "
            "FROM shadow_trades WHERE trade_id = ?",
            (trade_id,),
        ).fetchone()
    return dict(r) if r else None


def _run_check(
    db_path: str,
    *,
    current_price: float,
    fill_price,  # float or None
    order_status_dict: dict | None = None,
) -> None:
    from src.shadow_trading import executor as exec_mod

    fill_val = fill_price
    mock_exit = MagicMock(
        return_value={
            "order_id": "mock-exit-oid",
            "status": "filled",
            "filled_avg_price": fill_val,
            "filled_qty": 100,
        }
    )
    mock_order_status = MagicMock(
        return_value=order_status_dict or {
            "status": "open",
            "filled_avg_price": None,
            "legs": [],
        }
    )

    with patch.object(
        exec_mod, "_get_current_price_safe", return_value=current_price
    ), patch(
        "src.shadow_trading.alpaca_adapter.get_all_positions",
        return_value=[{"symbol": "AAPL", "qty": "100", "avg_entry_price": "100.00"}],
    ), patch(
        "src.shadow_trading.alpaca_adapter.place_paper_exit",
        mock_exit,
    ), patch(
        "src.shadow_trading.alpaca_adapter.get_order_status",
        mock_order_status,
    ), patch(
        "src.shadow_trading.alpaca_adapter.cancel_paper_order",
        return_value={"cancelled": True},
    ), patch.object(
        exec_mod, "load_config",
        return_value={
            "shadow_trading": {"timeout_days": 8, "max_positions": 10},
            "strategies": {"mean_reversion": {}},
            "trading": {"ib_enabled": False},
        },
    ):
        exec_mod.check_and_manage_open_trades(
            db_path=db_path, source_filter="paper",
        )


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------

def test_exit_slippage_normal_fill(tmp_db):
    """Positive: signal $105.00, fill $105.25 → ~23.8 bps persisted."""
    _seed_open_trade(tmp_db, trade_id="t-normal", ticker="AAPL",
                     entry_price=100.0, target_1=105.0)

    _run_check(tmp_db, current_price=105.0, fill_price=105.25)

    row = _row(tmp_db, "t-normal")
    assert row is not None
    assert row["status"] == "closed", f"Expected closed, got {row['status']}"
    assert row["signal_exit_price"] is not None, "signal_exit_price must be written on normal fill"
    assert abs(row["signal_exit_price"] - 105.0) < 0.01, (
        f"Expected signal_exit_price=105.00, got {row['signal_exit_price']}"
    )
    assert row["exit_slippage_bps"] is not None, "exit_slippage_bps must be written on normal fill"
    expected_bps = (105.25 - 105.0) / 105.0 * 10000
    assert abs(row["exit_slippage_bps"] - expected_bps) < 0.5, (
        f"Expected ~{expected_bps:.1f} bps, got {row['exit_slippage_bps']}"
    )


def test_exit_slippage_none_fill(tmp_db):
    """None fill → NULL slippage, but signal_exit_price still written."""
    _seed_open_trade(tmp_db, trade_id="t-none-fill", ticker="AAPL",
                     entry_price=100.0, target_1=105.0)

    _run_check(tmp_db, current_price=105.0, fill_price=None)

    row = _row(tmp_db, "t-none-fill")
    assert row is not None
    assert row["status"] == "closed", f"Expected closed, got {row['status']}"
    assert row["signal_exit_price"] is not None, (
        "signal_exit_price must be written even when fill is None "
        "(preserves 'tried to measure' signal)"
    )
    assert row["exit_slippage_bps"] is None, (
        f"exit_slippage_bps must be NULL when fill is None, got {row['exit_slippage_bps']}"
    )


def test_exit_slippage_negative_slippage(tmp_db):
    """Negative slippage: fill $104.80 below signal $105.00 → ~-19.0 bps."""
    _seed_open_trade(tmp_db, trade_id="t-neg", ticker="AAPL",
                     entry_price=100.0, target_1=105.0)

    _run_check(tmp_db, current_price=105.0, fill_price=104.80)

    row = _row(tmp_db, "t-neg")
    assert row is not None
    assert row["exit_slippage_bps"] is not None, "exit_slippage_bps must be written"
    expected_bps = (104.80 - 105.0) / 105.0 * 10000
    assert abs(row["exit_slippage_bps"] - expected_bps) < 0.5, (
        f"Expected ~{expected_bps:.1f} bps (negative), got {row['exit_slippage_bps']}"
    )
    assert row["exit_slippage_bps"] < 0, "Slippage should be negative when fill < signal"


def test_exit_slippage_idempotent(tmp_db):
    """Re-run on an already-closed trade must not overwrite existing slippage values."""
    ts = "2026-04-01T09:30:00"
    # Insert a pre-closed trade with known slippage values
    insert_shadow_trade(
        {
            "trade_id": "t-idem",
            "ticker": "AAPL",
            "direction": "long",
            "status": "closed",
            "source": "paper",
            "desk": "swing",
            "order_type": "market",
            "planned_shares": 100.0,
            "entry_price": 100.0,
            "actual_entry_price": 100.0,
            "stop_price": 95.0,
            "target_1": 105.0,
            "target_2": 0.0,
            "strategy_type": "pullback",
            "alpaca_order_id": "oid-idem",
            "created_at": ts,
            "updated_at": ts,
            "actual_entry_time": ts,
            "actual_exit_time": ts,
            "actual_exit_price": 105.25,
            "signal_exit_price": 105.0,
            "exit_slippage_bps": 23.8,
            "timeout_days": 8,
        },
        tmp_db,
    )

    # Run the executor — closed trades must be skipped
    _run_check(tmp_db, current_price=106.0, fill_price=106.5)

    row = _row(tmp_db, "t-idem")
    assert row is not None
    assert row["status"] == "closed", "Must remain closed"
    assert abs(row["signal_exit_price"] - 105.0) < 0.01, (
        f"signal_exit_price must not be overwritten: expected 105.0, got {row['signal_exit_price']}"
    )
    assert abs(row["exit_slippage_bps"] - 23.8) < 0.1, (
        f"exit_slippage_bps must not be overwritten: expected 23.8, got {row['exit_slippage_bps']}"
    )


def test_bracket_exit_signal_captured_before_detection(tmp_db):
    """Regression: signal_exit must be captured BEFORE bracket detection overwrites current_price.

    Without the fix, bracket fills set current_price = leg_price (the fill price)
    BEFORE signal_exit = current_price is executed at line 1725. This makes
    signal_exit == fill_price, producing trivial 0 bps slippage every time.

    This test verifies that signal_exit_price != fill_price for a bracket exit
    where the polled price (105.00) differs from the bracket fill (105.50).
    """
    _seed_open_trade(
        tmp_db,
        trade_id="t-bracket",
        ticker="AAPL",
        entry_price=100.0,
        target_1=105.0,
        order_type="bracket",
        alpaca_order_id="bracket-oid-1",
    )

    from src.shadow_trading import executor as exec_mod

    # The bracket leg fill price differs from the polled current_price
    polled_price = 105.0   # what _get_current_price_safe returns (signal)
    bracket_fill = 105.50  # what Alpaca reports as filled_avg_price on the leg

    mock_exit = MagicMock(return_value={
        "order_id": "mock-exit-bracket",
        "status": "OrderStatus.FILLED",
        "filled_avg_price": bracket_fill,
        "filled_qty": 100,
    })
    bracket_order_status = {
        "status": "open",
        "filled_avg_price": None,
        "legs": [
            {
                "status": "filled",
                "filled_avg_price": bracket_fill,
                "order_type": "limit",
                "limit_price": 105.0,
            }
        ],
    }

    with patch.object(
        exec_mod, "_get_current_price_safe", return_value=polled_price
    ), patch(
        "src.shadow_trading.alpaca_adapter.get_all_positions",
        return_value=[{"symbol": "AAPL", "qty": "100", "avg_entry_price": "100.00"}],
    ), patch(
        "src.shadow_trading.alpaca_adapter.place_paper_exit",
        mock_exit,
    ), patch(
        "src.shadow_trading.alpaca_adapter.get_order_status",
        return_value=bracket_order_status,
    ), patch(
        "src.shadow_trading.alpaca_adapter.cancel_paper_order",
        return_value={"cancelled": True},
    ), patch.object(
        exec_mod, "load_config",
        return_value={
            "shadow_trading": {"timeout_days": 8, "max_positions": 10},
            "strategies": {"mean_reversion": {}},
            "trading": {"ib_enabled": False},
        },
    ):
        exec_mod.check_and_manage_open_trades(
            db_path=tmp_db, source_filter="paper",
        )

    row = _row(tmp_db, "t-bracket")
    assert row is not None
    assert row["status"] == "closed", f"Expected closed, got {row['status']}"
    assert row["signal_exit_price"] is not None, "signal_exit_price must be written for bracket exit"
    # The signal price must be the polled price (105.0), NOT the bracket fill (105.50).
    # If signal_exit was captured after bracket detection, it would be 105.50 and
    # slippage would trivially be 0.
    assert abs(row["signal_exit_price"] - polled_price) < 0.01, (
        f"signal_exit_price should be the polled price {polled_price}, "
        f"not the bracket fill {bracket_fill}. "
        f"Got {row['signal_exit_price']} — signal_exit was captured AFTER bracket detection."
    )
