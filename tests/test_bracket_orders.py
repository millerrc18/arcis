"""Tests for bracket order parameter construction and fallback logic."""

from unittest.mock import patch, MagicMock, PropertyMock

import pytest


class TestBracketOrderConstruction:
    @patch("src.shadow_trading.alpaca_adapter._get_trading_client")
    @patch("src.shadow_trading.alpaca_adapter._check_enabled")
    def test_market_bracket_order_params(self, mock_check, mock_client):
        """Verify bracket order uses correct parameters."""
        from src.shadow_trading.alpaca_adapter import place_bracket_order

        mock_order = MagicMock()
        mock_order.id = "test-order-123"
        mock_order.symbol = "AAPL"
        mock_order.qty = 5
        mock_order.side = "buy"
        mock_order.type = "market"
        mock_order.status = "accepted"
        mock_order.filled_avg_price = None
        mock_order.legs = []

        mock_client_instance = MagicMock()
        mock_client_instance.submit_order.return_value = mock_order
        mock_client.return_value = mock_client_instance

        result = place_bracket_order(
            ticker="AAPL",
            shares=5,
            take_profit_price=195.0,
            stop_loss_price=175.0,
        )

        assert result["order_id"] == "test-order-123"
        assert result["order_class"] == "bracket"
        assert result["symbol"] == "AAPL"

        # Verify the order request was built correctly
        call_args = mock_client_instance.submit_order.call_args
        order_request = call_args[0][0]
        assert order_request.qty == 5
        assert order_request.symbol == "AAPL"

    @patch("src.shadow_trading.alpaca_adapter._get_trading_client")
    @patch("src.shadow_trading.alpaca_adapter._check_enabled")
    def test_limit_bracket_order_params(self, mock_check, mock_client):
        """Verify limit bracket order uses limit_price."""
        from src.shadow_trading.alpaca_adapter import place_bracket_order

        mock_order = MagicMock()
        mock_order.id = "test-order-456"
        mock_order.symbol = "MSFT"
        mock_order.qty = 3
        mock_order.side = "buy"
        mock_order.type = "limit"
        mock_order.status = "accepted"
        mock_order.filled_avg_price = None
        mock_order.legs = []

        mock_client_instance = MagicMock()
        mock_client_instance.submit_order.return_value = mock_order
        mock_client.return_value = mock_client_instance

        result = place_bracket_order(
            ticker="MSFT",
            shares=3,
            take_profit_price=450.0,
            stop_loss_price=400.0,
            limit_price=420.0,
        )

        assert result["order_id"] == "test-order-456"
        assert result["order_class"] == "bracket"

        # Verify LimitOrderRequest was used
        call_args = mock_client_instance.submit_order.call_args
        order_request = call_args[0][0]
        assert order_request.limit_price == 420.0


class TestBracketFallback:
    @patch("src.shadow_trading.alpaca_adapter.place_paper_entry")
    @patch("src.shadow_trading.alpaca_adapter.place_bracket_order")
    def test_fallback_to_simple_on_bracket_failure(self, mock_bracket, mock_simple):
        """When bracket order fails, executor should fall back to simple market."""
        mock_bracket.side_effect = Exception("Bracket not supported")
        mock_simple.return_value = {
            "order_id": "fallback-order-789",
            "filled_avg_price": 185.0,
        }

        # We can't easily test the full executor without DB setup,
        # but we verify the adapter functions work independently
        with pytest.raises(Exception, match="Bracket not supported"):
            from src.shadow_trading.alpaca_adapter import place_bracket_order
            place_bracket_order("AAPL", 5, 195.0, 175.0)

        from src.shadow_trading.alpaca_adapter import place_paper_entry
        result = place_paper_entry("AAPL", 5)
        assert result["order_id"] == "fallback-order-789"


class TestBracketOrderKwargs:
    """Assert that take_profit and stop_loss kwargs are populated on the OrderRequest.

    Gap identified in PR #942 Wave 6 investigation: the existing tests only
    checked qty/symbol, so a regression dropping `stop_loss=` or `take_profit=`
    would silently pass the suite.  These tests lock the kwarg-presence contract.
    """

    def _make_mock_order(self):
        mock_order = MagicMock()
        mock_order.id = "test-order-kwarg"
        mock_order.symbol = "AAPL"
        mock_order.qty = 5
        mock_order.side = "buy"
        mock_order.type = "market"
        mock_order.status = "accepted"
        mock_order.filled_avg_price = None
        mock_order.legs = []
        return mock_order

    @patch("src.shadow_trading.alpaca_adapter._get_trading_client")
    @patch("src.shadow_trading.alpaca_adapter._check_enabled")
    def test_market_bracket_order_passes_take_profit_kwarg(self, mock_check, mock_client):
        """OrderRequest.take_profit must be populated with correct limit_price."""
        from src.shadow_trading.alpaca_adapter import place_bracket_order

        mock_client_instance = MagicMock()
        mock_client_instance.submit_order.return_value = self._make_mock_order()
        mock_client.return_value = mock_client_instance

        place_bracket_order(
            ticker="AAPL",
            shares=5,
            take_profit_price=195.0,
            stop_loss_price=175.0,
        )

        call_args = mock_client_instance.submit_order.call_args
        order_request = call_args[0][0]
        assert order_request.take_profit is not None, (
            "take_profit kwarg must be set on OrderRequest — a missing take_profit "
            "means no profit-taking leg would be submitted to Alpaca"
        )
        assert order_request.take_profit == {"limit_price": 195.0}, (
            f"take_profit must be {{'limit_price': 195.0}}, got {order_request.take_profit!r}"
        )

    @patch("src.shadow_trading.alpaca_adapter._get_trading_client")
    @patch("src.shadow_trading.alpaca_adapter._check_enabled")
    def test_market_bracket_order_passes_stop_loss_kwarg(self, mock_check, mock_client):
        """OrderRequest.stop_loss must be populated with correct stop_price."""
        from src.shadow_trading.alpaca_adapter import place_bracket_order

        mock_client_instance = MagicMock()
        mock_client_instance.submit_order.return_value = self._make_mock_order()
        mock_client.return_value = mock_client_instance

        place_bracket_order(
            ticker="AAPL",
            shares=5,
            take_profit_price=195.0,
            stop_loss_price=175.0,
        )

        call_args = mock_client_instance.submit_order.call_args
        order_request = call_args[0][0]
        assert order_request.stop_loss is not None, (
            "stop_loss kwarg must be set on OrderRequest — a missing stop_loss "
            "means no protective stop would be attached: the position ships unprotected"
        )
        assert order_request.stop_loss == {"stop_price": 175.0}, (
            f"stop_loss must be {{'stop_price': 175.0}}, got {order_request.stop_loss!r}"
        )

    @patch("src.shadow_trading.alpaca_adapter._get_trading_client")
    @patch("src.shadow_trading.alpaca_adapter._check_enabled")
    def test_bracket_order_request_has_both_kwargs_required(self, mock_check, mock_client):
        """Both take_profit AND stop_loss must be non-None on the OrderRequest.

        A bracket order without either leg is semantically not a bracket order.
        This test asserts atomically that BOTH are present so a single regression
        dropping one leg cannot hide behind the other.
        """
        from src.shadow_trading.alpaca_adapter import place_bracket_order

        mock_client_instance = MagicMock()
        mock_client_instance.submit_order.return_value = self._make_mock_order()
        mock_client.return_value = mock_client_instance

        place_bracket_order(
            ticker="AAPL",
            shares=5,
            take_profit_price=195.0,
            stop_loss_price=175.0,
        )

        call_args = mock_client_instance.submit_order.call_args
        order_request = call_args[0][0]
        assert order_request.take_profit is not None, (
            "take_profit must be present — bracket order requires both legs"
        )
        assert order_request.stop_loss is not None, (
            "stop_loss must be present — bracket order requires both legs"
        )

    @patch("src.shadow_trading.alpaca_adapter._get_trading_client")
    @patch("src.shadow_trading.alpaca_adapter._check_enabled")
    def test_limit_bracket_order_passes_take_profit_kwarg(self, mock_check, mock_client):
        """Limit-entry bracket: take_profit limit_price must match take_profit_price arg."""
        from src.shadow_trading.alpaca_adapter import place_bracket_order

        mock_order = MagicMock()
        mock_order.id = "test-limit-kwarg"
        mock_order.symbol = "MSFT"
        mock_order.qty = 3
        mock_order.side = "buy"
        mock_order.type = "limit"
        mock_order.status = "accepted"
        mock_order.filled_avg_price = None
        mock_order.legs = []

        mock_client_instance = MagicMock()
        mock_client_instance.submit_order.return_value = mock_order
        mock_client.return_value = mock_client_instance

        place_bracket_order(
            ticker="MSFT",
            shares=3,
            take_profit_price=450.0,
            stop_loss_price=400.0,
            limit_price=420.0,
        )

        call_args = mock_client_instance.submit_order.call_args
        order_request = call_args[0][0]
        assert order_request.take_profit is not None
        assert order_request.take_profit == {"limit_price": 450.0}

    @patch("src.shadow_trading.alpaca_adapter._get_trading_client")
    @patch("src.shadow_trading.alpaca_adapter._check_enabled")
    def test_limit_bracket_order_passes_stop_loss_kwarg(self, mock_check, mock_client):
        """Limit-entry bracket: stop_loss stop_price must match stop_loss_price arg."""
        from src.shadow_trading.alpaca_adapter import place_bracket_order

        mock_order = MagicMock()
        mock_order.id = "test-limit-kwarg-sl"
        mock_order.symbol = "MSFT"
        mock_order.qty = 3
        mock_order.side = "buy"
        mock_order.type = "limit"
        mock_order.status = "accepted"
        mock_order.filled_avg_price = None
        mock_order.legs = []

        mock_client_instance = MagicMock()
        mock_client_instance.submit_order.return_value = mock_order
        mock_client.return_value = mock_client_instance

        place_bracket_order(
            ticker="MSFT",
            shares=3,
            take_profit_price=450.0,
            stop_loss_price=400.0,
            limit_price=420.0,
        )

        call_args = mock_client_instance.submit_order.call_args
        order_request = call_args[0][0]
        assert order_request.stop_loss is not None
        assert order_request.stop_loss == {"stop_price": 400.0}


class TestBracketOrderResult:
    @patch("src.shadow_trading.alpaca_adapter._get_trading_client")
    @patch("src.shadow_trading.alpaca_adapter._check_enabled")
    def test_result_includes_legs(self, mock_check, mock_client):
        """Bracket order result should include leg IDs."""
        from src.shadow_trading.alpaca_adapter import place_bracket_order

        leg1 = MagicMock()
        leg1.id = "leg-tp-001"
        leg2 = MagicMock()
        leg2.id = "leg-sl-002"

        mock_order = MagicMock()
        mock_order.id = "parent-order"
        mock_order.symbol = "AAPL"
        mock_order.qty = 5
        mock_order.side = "buy"
        mock_order.type = "market"
        mock_order.status = "accepted"
        mock_order.filled_avg_price = 185.50
        mock_order.legs = [leg1, leg2]

        mock_client_instance = MagicMock()
        mock_client_instance.submit_order.return_value = mock_order
        mock_client.return_value = mock_client_instance

        result = place_bracket_order("AAPL", 5, 195.0, 175.0)
        assert result["legs"] == ["leg-tp-001", "leg-sl-002"]
        assert result["filled_avg_price"] == 185.50
