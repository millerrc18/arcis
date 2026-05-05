"""Wave 4 H4 — executor retry-exit path and quarantine_trade coerce tests.

Called by: pytest
Calls: src.shadow_trading.executor (quarantine_trade, check_and_manage_open_trades)
Owns tables: none
Config keys: none
Tests: Wave 4 H4 coerce_exit_reason bypass fix at executor.py:120, :1489, :1516
"""
from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock

from zoneinfo import ZoneInfo

import pytest

from src.shadow_trading.exit_reason import CONTROLLED_VOCAB

ET = ZoneInfo("America/New_York")


def _isoformat_days_ago(days: int) -> str:
    return (datetime.now(ET) - timedelta(days=days)).isoformat()


def _make_exit_failed_trade(ticker: str = "AAPL", exit_reason=None) -> dict:
    entry_ts = _isoformat_days_ago(1)
    return {
        "trade_id": f"tid-{ticker.lower()}",
        "ticker": ticker,
        "status": "exit_failed",
        "alpaca_order_id": "order-abc",
        "actual_entry_price": 150.0,
        "entry_price": 150.0,
        "stop_price": 140.0,
        "target_1": 160.0,
        "target_2": 170.0,
        "planned_shares": 10,
        "shares": 10,
        "actual_entry_time": entry_ts,
        "created_at": entry_ts,
        "exit_retry_count": 0,
        "timeout_days": 15,
        "exit_reason": exit_reason,
    }


# ---------------------------------------------------------------------------
# Test 1: retry success writes 'retry_exit' when trade.exit_reason is None
# ---------------------------------------------------------------------------

def test_retry_exit_success_writes_retry_exit_reason():
    """executor.py:1516 — when trade.exit_reason is None and retry fills, writes 'retry_exit'."""
    from src.shadow_trading import executor

    trade = _make_exit_failed_trade("AAPL", exit_reason=None)
    filled_result = {
        "status": "filled",
        "filled_avg_price": "155.0",
        "order_id": "ord-filled",
    }

    with (
        patch.object(executor, "get_open_shadow_trades", return_value=[trade]),
        patch.object(executor, "_get_current_price_safe", return_value=152.0),
        patch.object(executor, "update_shadow_trade"),
        patch.object(executor, "close_shadow_trade") as mock_close,
        patch.object(executor, "load_config", return_value={"shadow_trading": {"timeout_days": 15}}),
        patch.object(executor, "_submit_exit_order", return_value=filled_result),
        patch.object(executor, "_sync_exit_qty", return_value=(10, None)),
        patch("src.shadow_trading.alpaca_adapter.get_all_positions",
              return_value=[{"symbol": "AAPL", "qty": 10}]),
        patch("src.shadow_trading.alpaca_adapter.get_order_status",
              return_value={"status": "pending"}),
        patch("src.shadow_trading.alpaca_adapter.cancel_paper_order", return_value=None),
    ):
        executor.check_and_manage_open_trades(db_path=":memory:")

    assert mock_close.called, "close_shadow_trade must be called on retry success"
    call = mock_close.call_args
    er = call.kwargs.get("exit_reason")
    assert er == "retry_exit", f"expected 'retry_exit', got {er!r}"


# ---------------------------------------------------------------------------
# Test 2: retry success preserves existing vocab exit_reason from trade
# ---------------------------------------------------------------------------

def test_retry_exit_with_existing_exit_reason_uses_trade_value():
    """executor.py:1516 — when trade.exit_reason is 'target_1' (vocab), preserves it."""
    from src.shadow_trading import executor

    trade = _make_exit_failed_trade("MSFT", exit_reason="target_1")
    filled_result = {
        "status": "filled",
        "filled_avg_price": "160.0",
        "order_id": "ord-filled2",
    }

    with (
        patch.object(executor, "get_open_shadow_trades", return_value=[trade]),
        patch.object(executor, "_get_current_price_safe", return_value=158.0),
        patch.object(executor, "update_shadow_trade"),
        patch.object(executor, "close_shadow_trade") as mock_close,
        patch.object(executor, "load_config", return_value={"shadow_trading": {"timeout_days": 15}}),
        patch.object(executor, "_submit_exit_order", return_value=filled_result),
        patch.object(executor, "_sync_exit_qty", return_value=(10, None)),
        patch("src.shadow_trading.alpaca_adapter.get_all_positions",
              return_value=[{"symbol": "MSFT", "qty": 10}]),
        patch("src.shadow_trading.alpaca_adapter.get_order_status",
              return_value={"status": "pending"}),
        patch("src.shadow_trading.alpaca_adapter.cancel_paper_order", return_value=None),
    ):
        executor.check_and_manage_open_trades(db_path=":memory:")

    assert mock_close.called, "close_shadow_trade must be called on retry success"
    call = mock_close.call_args
    er = call.kwargs.get("exit_reason")
    assert er == "target_1", f"expected 'target_1' (vocab pass-through), got {er!r}"


# ---------------------------------------------------------------------------
# Test 3: quarantine_trade coerces unknown reason to 'unknown'
# ---------------------------------------------------------------------------

def test_quarantine_trade_coerces_unknown_reason():
    """executor.py:120 — quarantine_trade must write coerced exit_reason, not raw value."""
    from src.shadow_trading import executor

    conn = sqlite3.connect(":memory:")
    conn.execute("""
        CREATE TABLE shadow_trades (
            trade_id TEXT PRIMARY KEY,
            status TEXT,
            quarantined INTEGER,
            exit_reason TEXT,
            updated_at TEXT
        )
    """)
    conn.execute(
        "INSERT INTO shadow_trades VALUES (?, ?, ?, ?, ?)",
        ("tid-q1", "open", 0, None, None),
    )
    conn.commit()

    with patch("src.shadow_trading.executor.connect_db", return_value=conn):
        executor.quarantine_trade("tid-q1", "non_vocab_raw_value", ticker="AAPL", db_path=":memory:")

    row = conn.execute(
        "SELECT exit_reason FROM shadow_trades WHERE trade_id='tid-q1'"
    ).fetchone()
    assert row is not None
    assert row[0] == "unknown", (
        f"quarantine_trade wrote {row[0]!r} — non-vocab reason must coerce to 'unknown'"
    )
    conn.close()


# ---------------------------------------------------------------------------
# Test 4: quarantine_trade propagates ticker to coerce (M4 fidelity — caplog)
# ---------------------------------------------------------------------------

def test_quarantine_trade_propagates_ticker_to_coerce(caplog):
    """executor.py:120 — coerce_exit_reason WARNING must include ticker=AAPL (M4 fidelity)."""
    from src.shadow_trading import executor

    conn = sqlite3.connect(":memory:")
    conn.execute("""
        CREATE TABLE shadow_trades (
            trade_id TEXT PRIMARY KEY,
            status TEXT,
            quarantined INTEGER,
            exit_reason TEXT,
            updated_at TEXT
        )
    """)
    conn.execute(
        "INSERT INTO shadow_trades VALUES (?, ?, ?, ?, ?)",
        ("tid-q2", "open", 0, None, None),
    )
    conn.commit()

    with (
        patch("src.shadow_trading.executor.connect_db", return_value=conn),
        caplog.at_level(logging.WARNING, logger="src.shadow_trading.exit_reason"),
    ):
        executor.quarantine_trade("tid-q2", "non_vocab_bad_value", ticker="AAPL", db_path=":memory:")

    assert "AAPL" in caplog.text, (
        "Expected ticker=AAPL in WARNING log — coerce must propagate ticker kwarg"
    )
    conn.close()


# ---------------------------------------------------------------------------
# Test 5: skip_reason from _sync_exit_qty coerces at line 1489
# ---------------------------------------------------------------------------

def test_skip_reason_from_sync_exit_qty_coerces():
    """executor.py:1489 — non-vocab skip_reason must be coerced before UPDATE."""
    from src.shadow_trading import executor

    trade = _make_exit_failed_trade("GOOG", exit_reason=None)

    with (
        patch.object(executor, "get_open_shadow_trades", return_value=[trade]),
        patch.object(executor, "_get_current_price_safe", return_value=155.0),
        patch.object(executor, "update_shadow_trade") as mock_update,
        patch.object(executor, "load_config", return_value={"shadow_trading": {"timeout_days": 15}}),
        patch.object(executor, "_sync_exit_qty", return_value=(0, "non_vocab_skip_raw")),
        patch("src.shadow_trading.alpaca_adapter.get_all_positions", return_value=[]),
        patch("src.shadow_trading.alpaca_adapter.get_order_status",
              return_value={"status": "pending"}),
        patch("src.shadow_trading.alpaca_adapter.cancel_paper_order", return_value=None),
    ):
        executor.check_and_manage_open_trades(db_path=":memory:")

    exit_pending_writes = [
        call.args[1].get("exit_reason")
        for call in mock_update.call_args_list
        if len(call.args) >= 2
        and isinstance(call.args[1], dict)
        and call.args[1].get("status") == "exit_pending"
        and call.args[1].get("exit_reason") is not None
    ]
    assert exit_pending_writes, "expected at least one exit_pending write with exit_reason"
    for er in exit_pending_writes:
        assert er in CONTROLLED_VOCAB, (
            f"skip_reason {er!r} was not coerced — must be in CONTROLLED_VOCAB"
        )
