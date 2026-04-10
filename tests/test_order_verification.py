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
