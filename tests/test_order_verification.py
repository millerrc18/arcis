"""Tests for order submission verification."""
from unittest.mock import patch, MagicMock


def test_verify_order_accepted_returns_true_for_accepted():
    mock_order = MagicMock()
    mock_order.status = "accepted"
    with patch("src.shadow_trading.alpaca_adapter._get_trading_client") as mock_client:
        mock_client.return_value.get_order_by_id.return_value = mock_order
        from src.shadow_trading.alpaca_adapter import verify_order_accepted
        result = verify_order_accepted("order-123")
        assert result["verified"] is True
        assert result["status"] == "accepted"


def test_verify_order_accepted_returns_true_for_filled():
    mock_order = MagicMock()
    mock_order.status = "filled"
    with patch("src.shadow_trading.alpaca_adapter._get_trading_client") as mock_client:
        mock_client.return_value.get_order_by_id.return_value = mock_order
        from src.shadow_trading.alpaca_adapter import verify_order_accepted
        result = verify_order_accepted("order-123")
        assert result["verified"] is True
        assert result["status"] == "filled"


def test_verify_order_accepted_returns_false_for_rejected():
    mock_order = MagicMock()
    mock_order.status = "rejected"
    with patch("src.shadow_trading.alpaca_adapter._get_trading_client") as mock_client:
        mock_client.return_value.get_order_by_id.return_value = mock_order
        from src.shadow_trading.alpaca_adapter import verify_order_accepted
        result = verify_order_accepted("order-123")
        assert result["verified"] is False
        assert result["status"] == "rejected"


def test_verify_order_accepted_handles_api_error():
    with patch("src.shadow_trading.alpaca_adapter._get_trading_client") as mock_client:
        mock_client.return_value.get_order_by_id.side_effect = Exception("API down")
        from src.shadow_trading.alpaca_adapter import verify_order_accepted
        result = verify_order_accepted("order-123")
        assert result["verified"] is None
        assert "error" in result


def test_cancel_orders_for_ticker():
    """Fix #356: cancel_orders_for_ticker should cancel all open orders for a symbol."""
    mock_order_1 = MagicMock()
    mock_order_1.id = "order-1"
    mock_order_2 = MagicMock()
    mock_order_2.id = "order-2"
    with patch("src.shadow_trading.alpaca_adapter._get_trading_client") as mock_client:
        mock_client.return_value.get_orders.return_value = [mock_order_1, mock_order_2]
        from src.shadow_trading.alpaca_adapter import cancel_orders_for_ticker
        cancelled = cancel_orders_for_ticker("TEST")
        assert cancelled == 2
        assert mock_client.return_value.cancel_order_by_id.call_count == 2


def test_cancel_orders_for_ticker_no_orders():
    """Fix #356: no-op when no orders exist for the ticker."""
    with patch("src.shadow_trading.alpaca_adapter._get_trading_client") as mock_client:
        mock_client.return_value.get_orders.return_value = []
        from src.shadow_trading.alpaca_adapter import cancel_orders_for_ticker
        cancelled = cancel_orders_for_ticker("TEST")
        assert cancelled == 0
