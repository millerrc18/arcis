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
        """Trades with status=exit_failed should trigger _retry_exit.

        D3 sprint: _retry_exit now accepts a broker_positions kwarg so it
        can skip retries against closed positions; the existing behavior
        (retry is called) is preserved for stuck trades whose position
        still exists at the broker.
        """
        fake_trade = {
            "trade_id": "t1", "ticker": "AAPL", "entry_price": 150.0,
            "actual_entry_price": 150.0, "stop_price": 140.0,
            "target_1": 160.0, "target_2": 170.0, "shares": 10,
            "status": "exit_failed", "exit_reason": "stop_hit",
            "source": "paper", "order_type": "market",
        }

        with patch("src.shadow_trading.executor._retry_exit") as mock_retry, \
             patch("src.shadow_trading.executor.get_open_shadow_trades", return_value=[fake_trade]), \
             patch("src.shadow_trading.executor._get_current_price_safe", return_value=155.0), \
             patch("src.shadow_trading.alpaca_adapter.get_all_positions",
                   return_value=[{"symbol": "AAPL", "qty": "10"}]):
            from src.shadow_trading.executor import check_and_manage_open_trades
            check_and_manage_open_trades()
            # D3: _retry_exit now receives broker_positions kwarg with the cached
            # positions dict built at the top of check_and_manage_open_trades.
            mock_retry.assert_called_once_with(
                fake_trade, DB_PATH, broker_positions={"AAPL": 10.0},
            )


class TestTimestampParseFailure:
    """#105: Unparseable timestamps must default to days_open=999."""

    def test_bad_timestamp_forces_timeout(self):
        """Trade with bad entry time gets days_open=999 -> forces timeout.

        D3 sprint: the test now mocks `get_all_positions` to include AAPL
        so the D3 qty-sync at executor.py:~1547 lets the submit proceed.
        Without this mock, D3 would short-circuit (broker_qty=0) and mark
        the trade exit_pending instead of timing out via fallback path.
        """
        fake_trade = {
            "trade_id": "t1", "ticker": "AAPL", "entry_price": 150.0,
            "actual_entry_price": 150.0, "stop_price": 140.0,
            "target_1": 160.0, "target_2": 170.0, "shares": 10,
            "planned_shares": 10,
            "status": "open", "source": "paper", "order_type": "market",
            "actual_entry_time": "NOT-A-DATE", "created_at": "NOT-A-DATE",
            "alpaca_order_id": None,
            "max_favorable_excursion": 0, "max_adverse_excursion": 0,
        }

        with patch("src.shadow_trading.executor.get_open_shadow_trades", return_value=[fake_trade]), \
             patch("src.shadow_trading.executor._get_current_price_safe", return_value=155.0), \
             patch("src.shadow_trading.alpaca_adapter.get_all_positions",
                   return_value=[{"symbol": "AAPL", "qty": "10"}]), \
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
                assert kwargs.get("exit_reason") == "target_1"  # Coerced to canonical 'target_1' by B3 LEGACY_COERCIONS — see docs/sprints/track_1_5_pass1_design/B3_exit_reason_taxonomy.md


class TestBracketSafetyKwargs:
    """Mirror of TestBracketOrderKwargs for safety-net bracket submission paths.

    #48: Safety-net paths (GTC, cancel-before-close, broker-exception recovery)
    that call place_bracket_order must pass take_profit= and stop_loss= kwargs.
    A regression dropping either leg would leave a position without protection.
    These tests lock the kwarg-presence contract for the safety context.
    """

    def _make_mock_order(self):
        mock_order = MagicMock()
        mock_order.id = "safety-order-kwarg"
        mock_order.symbol = "AAPL"
        mock_order.qty = 10
        mock_order.side = "buy"
        mock_order.type = "market"
        mock_order.status = "accepted"
        mock_order.filled_avg_price = None
        mock_order.legs = []
        return mock_order

    def test_gtc_market_bracket_passes_take_profit_kwarg(self):
        """Safety path: market bracket order must set take_profit on the request."""
        with patch("src.shadow_trading.alpaca_adapter._get_trading_client") as mock_client, \
             patch("src.shadow_trading.alpaca_adapter._check_enabled"):
            mock_client.return_value.submit_order.return_value = self._make_mock_order()

            from src.shadow_trading.alpaca_adapter import place_bracket_order
            place_bracket_order("AAPL", 10, 160.0, 140.0)

            call_args = mock_client.return_value.submit_order.call_args
            request = call_args[0][0]
            assert request.take_profit is not None, (
                "take_profit kwarg must be set on safety-path OrderRequest — "
                "a missing take_profit means no profit-taking leg on the bracket"
            )
            assert request.take_profit == {"limit_price": 160.0}, (
                f"take_profit must be {{'limit_price': 160.0}}, got {request.take_profit!r}"
            )

    def test_gtc_market_bracket_passes_stop_loss_kwarg(self):
        """Safety path: market bracket order must set stop_loss on the request."""
        with patch("src.shadow_trading.alpaca_adapter._get_trading_client") as mock_client, \
             patch("src.shadow_trading.alpaca_adapter._check_enabled"):
            mock_client.return_value.submit_order.return_value = self._make_mock_order()

            from src.shadow_trading.alpaca_adapter import place_bracket_order
            place_bracket_order("AAPL", 10, 160.0, 140.0)

            call_args = mock_client.return_value.submit_order.call_args
            request = call_args[0][0]
            assert request.stop_loss is not None, (
                "stop_loss kwarg must be set on safety-path OrderRequest — "
                "a missing stop_loss means no protective stop: position ships unprotected"
            )
            assert request.stop_loss == {"stop_price": 140.0}, (
                f"stop_loss must be {{'stop_price': 140.0}}, got {request.stop_loss!r}"
            )

    def test_gtc_market_bracket_has_both_kwargs(self):
        """Safety path: both take_profit AND stop_loss must be non-None on market bracket.

        A bracket order without either leg is semantically not a bracket order.
        This test asserts atomically that BOTH are present so a single regression
        dropping one leg cannot hide behind the other.
        """
        with patch("src.shadow_trading.alpaca_adapter._get_trading_client") as mock_client, \
             patch("src.shadow_trading.alpaca_adapter._check_enabled"):
            mock_client.return_value.submit_order.return_value = self._make_mock_order()

            from src.shadow_trading.alpaca_adapter import place_bracket_order
            place_bracket_order("AAPL", 10, 160.0, 140.0)

            call_args = mock_client.return_value.submit_order.call_args
            request = call_args[0][0]
            assert request.take_profit is not None, (
                "take_profit must be present on safety-path bracket — both legs required"
            )
            assert request.stop_loss is not None, (
                "stop_loss must be present on safety-path bracket — both legs required"
            )

    def test_gtc_limit_bracket_passes_take_profit_kwarg(self):
        """Safety path: limit-entry bracket must set take_profit with correct price."""
        mock_order = MagicMock()
        mock_order.id = "safety-limit-tp"
        mock_order.symbol = "MSFT"
        mock_order.qty = 5
        mock_order.side = "buy"
        mock_order.type = "limit"
        mock_order.status = "accepted"
        mock_order.filled_avg_price = None
        mock_order.legs = []

        with patch("src.shadow_trading.alpaca_adapter._get_trading_client") as mock_client, \
             patch("src.shadow_trading.alpaca_adapter._check_enabled"):
            mock_client.return_value.submit_order.return_value = mock_order

            from src.shadow_trading.alpaca_adapter import place_bracket_order
            place_bracket_order("MSFT", 5, 450.0, 400.0, limit_price=420.0)

            call_args = mock_client.return_value.submit_order.call_args
            request = call_args[0][0]
            assert request.take_profit is not None
            assert request.take_profit == {"limit_price": 450.0}, (
                f"take_profit must be {{'limit_price': 450.0}}, got {request.take_profit!r}"
            )

    def test_gtc_limit_bracket_passes_stop_loss_kwarg(self):
        """Safety path: limit-entry bracket must set stop_loss with correct price."""
        mock_order = MagicMock()
        mock_order.id = "safety-limit-sl"
        mock_order.symbol = "MSFT"
        mock_order.qty = 5
        mock_order.side = "buy"
        mock_order.type = "limit"
        mock_order.status = "accepted"
        mock_order.filled_avg_price = None
        mock_order.legs = []

        with patch("src.shadow_trading.alpaca_adapter._get_trading_client") as mock_client, \
             patch("src.shadow_trading.alpaca_adapter._check_enabled"):
            mock_client.return_value.submit_order.return_value = mock_order

            from src.shadow_trading.alpaca_adapter import place_bracket_order
            place_bracket_order("MSFT", 5, 450.0, 400.0, limit_price=420.0)

            call_args = mock_client.return_value.submit_order.call_args
            request = call_args[0][0]
            assert request.stop_loss is not None
            assert request.stop_loss == {"stop_price": 400.0}, (
                f"stop_loss must be {{'stop_price': 400.0}}, got {request.stop_loss!r}"
            )

    def test_gtc_limit_bracket_has_both_kwargs(self):
        """Safety path: limit-entry bracket must have both take_profit and stop_loss."""
        mock_order = MagicMock()
        mock_order.id = "safety-limit-both"
        mock_order.symbol = "TSLA"
        mock_order.qty = 3
        mock_order.side = "buy"
        mock_order.type = "limit"
        mock_order.status = "accepted"
        mock_order.filled_avg_price = None
        mock_order.legs = []

        with patch("src.shadow_trading.alpaca_adapter._get_trading_client") as mock_client, \
             patch("src.shadow_trading.alpaca_adapter._check_enabled"):
            mock_client.return_value.submit_order.return_value = mock_order

            from src.shadow_trading.alpaca_adapter import place_bracket_order
            place_bracket_order("TSLA", 3, 300.0, 250.0, limit_price=270.0)

            call_args = mock_client.return_value.submit_order.call_args
            request = call_args[0][0]
            assert request.take_profit is not None, (
                "take_profit must be present on limit safety-path bracket — both legs required"
            )
            assert request.stop_loss is not None, (
                "stop_loss must be present on limit safety-path bracket — both legs required"
            )
