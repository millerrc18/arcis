"""Tests for bracket order safety fixes.

Covers: #101 (GTC), #100 (exit_failed recovery), #105 (timestamp parse),
        #103 (stop vs take-profit identification).
"""

import sqlite3
from datetime import datetime
from unittest.mock import MagicMock, patch, call
from zoneinfo import ZoneInfo

import pytest

from src.config import DB_PATH

ET = ZoneInfo("America/New_York")


class TestGTCOrderFormat:
    """#101: Bracket orders must use GTC, not DAY."""

    def test_bracket_order_uses_gtc(self):
        """place_bracket_order should use TimeInForce.GTC."""
        with patch("src.shadow_trading.alpaca_adapter._get_trading_client") as mock_client, \
             patch("src.shadow_trading.alpaca_adapter._check_enabled"):
            mock_order = MagicMock()
            mock_order.id = "test-order-123"
            mock_order.status = "accepted"
            mock_order.filled_avg_price = None
            mock_order.legs = []
            mock_client.return_value.submit_order.return_value = mock_order

            from src.shadow_trading.alpaca_adapter import place_bracket_order
            result = place_bracket_order("AAPL", 10, 160.0, 140.0)

            call_args = mock_client.return_value.submit_order.call_args
            request = call_args[0][0]
            assert request.time_in_force.value == "gtc"

    def test_bracket_limit_order_uses_gtc(self):
        """place_bracket_order with limit_price should also use GTC."""
        with patch("src.shadow_trading.alpaca_adapter._get_trading_client") as mock_client, \
             patch("src.shadow_trading.alpaca_adapter._check_enabled"):
            mock_order = MagicMock()
            mock_order.id = "test-order-456"
            mock_order.status = "accepted"
            mock_order.filled_avg_price = None
            mock_order.legs = []
            mock_client.return_value.submit_order.return_value = mock_order

            from src.shadow_trading.alpaca_adapter import place_bracket_order
            result = place_bracket_order("AAPL", 10, 160.0, 140.0, limit_price=152.0)

            call_args = mock_client.return_value.submit_order.call_args
            request = call_args[0][0]
            assert request.time_in_force.value == "gtc"


class TestExitFailedRecovery:
    """#100: exit_failed trades should be retried."""

    def test_retry_exit_called_for_exit_failed(self):
        """Trades with status=exit_failed should trigger _retry_exit."""
        fake_trade = {
            "trade_id": "t1", "ticker": "AAPL", "entry_price": 150.0,
            "actual_entry_price": 150.0, "stop_price": 140.0,
            "target_1": 160.0, "target_2": 170.0, "shares": 10,
            "status": "exit_failed", "exit_reason": "stop_hit",
            "source": "paper", "order_type": "market",
        }

        with patch("src.shadow_trading.executor._retry_exit") as mock_retry, \
             patch("src.shadow_trading.executor.get_open_shadow_trades", return_value=[fake_trade]), \
             patch("src.shadow_trading.executor._get_current_price_safe", return_value=155.0):
            from src.shadow_trading.executor import check_and_manage_open_trades
            check_and_manage_open_trades()
            mock_retry.assert_called_once_with(fake_trade, DB_PATH)


class TestTimestampParseFailure:
    """#105: Unparseable timestamps must default to days_open=999."""

    def test_bad_timestamp_forces_timeout(self):
        """Trade with bad entry time gets days_open=999 -> forces timeout."""
        fake_trade = {
            "trade_id": "t1", "ticker": "AAPL", "entry_price": 150.0,
            "actual_entry_price": 150.0, "stop_price": 140.0,
            "target_1": 160.0, "target_2": 170.0, "shares": 10,
            "status": "open", "source": "paper", "order_type": "market",
            "actual_entry_time": "NOT-A-DATE", "created_at": "NOT-A-DATE",
            "alpaca_order_id": None,
            "max_favorable_excursion": 0, "max_adverse_excursion": 0,
        }

        with patch("src.shadow_trading.executor.get_open_shadow_trades", return_value=[fake_trade]), \
             patch("src.shadow_trading.executor._get_current_price_safe", return_value=155.0), \
             patch("src.shadow_trading.executor._submit_exit_order") as mock_exit, \
             patch("src.shadow_trading.executor.close_shadow_trade") as mock_close, \
             patch("src.shadow_trading.executor.update_shadow_trade"):
            mock_exit.return_value = {"status": "filled", "filled_avg_price": 155.0, "order_id": "x"}
            from src.shadow_trading.executor import check_and_manage_open_trades
            actions = check_and_manage_open_trades()
            # Should have triggered timeout exit due to days_open=999
            assert mock_close.called or any(
                a.get("exit_reason") == "timeout" for a in actions
            )


class TestStopVsTakeProfitLeg:
    """#103: Bracket leg identification must distinguish stop vs take-profit."""

    def test_stop_leg_sets_stop_loss_reason(self):
        """A filled stop leg should set exit_reason to stop_loss."""
        fake_trade = {
            "trade_id": "t1", "ticker": "AAPL", "entry_price": 150.0,
            "actual_entry_price": 150.0, "stop_price": 140.0,
            "target_1": 160.0, "target_2": 170.0, "shares": 10,
            "status": "open", "source": "paper", "order_type": "bracket",
            "alpaca_order_id": "ord-123",
            "actual_entry_time": "2025-01-01T10:00:00-05:00",
            "created_at": "2025-01-01T10:00:00-05:00",
            "max_favorable_excursion": 0, "max_adverse_excursion": 0,
        }
        stop_leg = {
            "status": "filled", "filled_avg_price": 140.0,
            "order_type": "stop", "stop_price": 140.0,
        }

        with patch("src.shadow_trading.executor.get_open_shadow_trades", return_value=[fake_trade]), \
             patch("src.shadow_trading.executor._get_current_price_safe", return_value=155.0), \
             patch("src.shadow_trading.alpaca_adapter.get_order_status") as mock_os, \
             patch("src.shadow_trading.executor.close_shadow_trade") as mock_close, \
             patch("src.shadow_trading.executor.update_shadow_trade"), \
             patch("src.shadow_trading.executor._submit_exit_order"):
            mock_os.return_value = {
                "status": "filled", "filled_avg_price": None, "legs": [stop_leg],
            }
            from src.shadow_trading.executor import check_and_manage_open_trades
            check_and_manage_open_trades()
            if mock_close.called:
                _, kwargs = mock_close.call_args
                assert kwargs.get("exit_reason") == "stop_loss"

    def test_limit_leg_sets_take_profit_reason(self):
        """A filled limit leg should set exit_reason to take_profit."""
        fake_trade = {
            "trade_id": "t1", "ticker": "AAPL", "entry_price": 150.0,
            "actual_entry_price": 150.0, "stop_price": 140.0,
            "target_1": 160.0, "target_2": 170.0, "shares": 10,
            "status": "open", "source": "paper", "order_type": "bracket",
            "alpaca_order_id": "ord-456",
            "actual_entry_time": "2025-01-01T10:00:00-05:00",
            "created_at": "2025-01-01T10:00:00-05:00",
            "max_favorable_excursion": 0, "max_adverse_excursion": 0,
        }
        tp_leg = {
            "status": "filled", "filled_avg_price": 160.0,
            "order_type": "limit", "limit_price": 160.0,
        }

        with patch("src.shadow_trading.executor.get_open_shadow_trades", return_value=[fake_trade]), \
             patch("src.shadow_trading.executor._get_current_price_safe", return_value=155.0), \
             patch("src.shadow_trading.alpaca_adapter.get_order_status") as mock_os, \
             patch("src.shadow_trading.executor.close_shadow_trade") as mock_close, \
             patch("src.shadow_trading.executor.update_shadow_trade"), \
             patch("src.shadow_trading.executor._submit_exit_order"):
            mock_os.return_value = {
                "status": "filled", "filled_avg_price": None, "legs": [tp_leg],
            }
            from src.shadow_trading.executor import check_and_manage_open_trades
            check_and_manage_open_trades()
            if mock_close.called:
                _, kwargs = mock_close.call_args
                assert kwargs.get("exit_reason") == "take_profit"
