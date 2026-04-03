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


# ── Exit retry with cancel (#196) ───────────────────────────────────


class TestRetryExitWithCancel:
    """Test that exit retry cancels pending orders before resubmitting (#196)."""

    def test_retry_cancels_pending_order_before_resubmit(self):
        from src.shadow_trading.executor import _retry_exit

        trade = {
            "trade_id": "t1",
            "ticker": "PFE",
            "shares": 7,
            "actual_entry_price": 28.0,
            "exit_order_id": "old-order-123",
            "exit_reason": "timeout",
            "exit_retry_count": 0,
        }

        mock_exit_result = {"status": "filled", "filled_avg_price": "29.0"}

        with patch("src.shadow_trading.alpaca_adapter.cancel_paper_order") as mock_cancel, \
             patch("src.shadow_trading.executor._submit_exit_order",
                   return_value=mock_exit_result), \
             patch("src.shadow_trading.executor.close_shadow_trade"), \
             patch("src.shadow_trading.executor.update_shadow_trade"), \
             patch("time.sleep"):
            _retry_exit(trade)

        mock_cancel.assert_called_once_with("old-order-123")

    def test_retry_skips_cancel_when_no_pending_order(self):
        from src.shadow_trading.executor import _retry_exit

        trade = {
            "trade_id": "t1",
            "ticker": "PFE",
            "shares": 7,
            "actual_entry_price": 28.0,
            "exit_order_id": None,
            "exit_reason": "timeout",
            "exit_retry_count": 0,
        }

        mock_exit_result = {"status": "filled", "filled_avg_price": "29.0"}

        with patch("src.shadow_trading.alpaca_adapter.cancel_paper_order") as mock_cancel, \
             patch("src.shadow_trading.executor._submit_exit_order",
                   return_value=mock_exit_result), \
             patch("src.shadow_trading.executor.close_shadow_trade"), \
             patch("src.shadow_trading.executor.update_shadow_trade"), \
             patch("time.sleep"):
            _retry_exit(trade)

        mock_cancel.assert_not_called()

    def test_retry_stops_after_max_retries(self):
        from src.shadow_trading.executor import _retry_exit

        trade = {
            "trade_id": "t1",
            "ticker": "PFE",
            "shares": 7,
            "actual_entry_price": 28.0,
            "exit_order_id": "old-order-123",
            "exit_reason": "timeout",
            "exit_retry_count": 3,  # Already at max
        }

        with patch("src.shadow_trading.alpaca_adapter.cancel_paper_order") as mock_cancel, \
             patch("src.shadow_trading.executor._submit_exit_order") as mock_submit, \
             patch("src.shadow_trading.executor.update_shadow_trade") as mock_update, \
             patch("time.sleep"):
            _retry_exit(trade)

        # Should NOT attempt cancel or submit — just mark as abandoned
        mock_cancel.assert_not_called()
        mock_submit.assert_not_called()
        # Should update status to exit_abandoned
        mock_update.assert_called_once()
        update_args = mock_update.call_args
        assert update_args[0][1].get("status") == "exit_abandoned"
