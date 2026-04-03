"""Tests for shadow trading executor and adapter (#196)."""

from unittest.mock import patch, MagicMock

import pytest


def test_module_imports():
    """Verify module imports without error."""
    import src.shadow_trading.executor  # noqa: F401


# ── Cancel order adapter (#196) ──────────────────────────────────────


class TestCancelPaperOrder:
    """Test the cancel_paper_order adapter function."""

    def test_cancel_success(self):
        from src.shadow_trading.alpaca_adapter import cancel_paper_order
        mock_client = MagicMock()
        with patch("src.shadow_trading.alpaca_adapter._get_trading_client",
                   return_value=mock_client):
            result = cancel_paper_order("order-123")

        assert result is True
        mock_client.cancel_order_by_id.assert_called_once_with("order-123")

    def test_cancel_already_filled(self):
        from src.shadow_trading.alpaca_adapter import cancel_paper_order
        mock_client = MagicMock()
        mock_client.cancel_order_by_id.side_effect = Exception("order already filled")
        with patch("src.shadow_trading.alpaca_adapter._get_trading_client",
                   return_value=mock_client):
            result = cancel_paper_order("order-123")

        assert result is False

    def test_cancel_no_client(self):
        from src.shadow_trading.alpaca_adapter import cancel_paper_order
        with patch("src.shadow_trading.alpaca_adapter._get_trading_client",
                   side_effect=Exception("No API key")):
            result = cancel_paper_order("order-123")

        assert result is False
