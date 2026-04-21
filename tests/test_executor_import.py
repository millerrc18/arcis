"""Tests for shadow trading executor and adapter (#196, #310)."""

from unittest.mock import patch, MagicMock, call
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest


def test_module_imports():
    """Verify module imports without error."""
    import src.shadow_trading.executor  # noqa: F401


# ── Cancel order adapter (#196) ──────────────────────────────────────


class TestCancelPaperOrder:
    """Test the cancel_paper_order adapter function.

    Returns a dict: {cancelled: bool, terminal_state: str|None, error: str|None}.
    terminal_state is set when the exception signals the order ALREADY reached
    a terminal broker state — e.g. 'filled' when Alpaca returns code 42210000
    ('order is already in "filled" state'). Callers use this signal to detect
    background fills that raced the cancel (2026-04-14 NVDA/GOOGL incident).
    """

    def test_cancel_success(self):
        from src.shadow_trading.alpaca_adapter import cancel_paper_order
        mock_client = MagicMock()
        with patch("src.shadow_trading.alpaca_adapter._get_trading_client",
                   return_value=mock_client):
            result = cancel_paper_order("order-123")

        assert result == {"cancelled": True, "terminal_state": None, "error": None}
        mock_client.cancel_order_by_id.assert_called_once_with("order-123")

    def test_cancel_already_filled_reports_terminal_state(self):
        """Alpaca APIError code 42210000 means the order filled before the
        cancel reached the broker. Caller must detect this to avoid
        submitting a duplicate exit SELL (2026-04-14 feedback loop)."""
        from src.shadow_trading.alpaca_adapter import cancel_paper_order
        from alpaca.common.exceptions import APIError
        mock_client = MagicMock()
        # Simulate the exact shape from production logs
        err = APIError({"code": 42210000, "message": 'order is already in "filled" state'})
        mock_client.cancel_order_by_id.side_effect = err
        with patch("src.shadow_trading.alpaca_adapter._get_trading_client",
                   return_value=mock_client):
            result = cancel_paper_order("order-123")

        assert result["cancelled"] is False
        assert result["terminal_state"] == "filled"

    def test_cancel_already_canceled_reports_terminal_state(self):
        """Similar race: order cancelled externally; cancel_paper_order should
        distinguish this from a generic failure so callers don't retry."""
        from src.shadow_trading.alpaca_adapter import cancel_paper_order
        from alpaca.common.exceptions import APIError
        mock_client = MagicMock()
        err = APIError({"code": 42210000, "message": 'order is already in "canceled" state'})
        mock_client.cancel_order_by_id.side_effect = err
        with patch("src.shadow_trading.alpaca_adapter._get_trading_client",
                   return_value=mock_client):
            result = cancel_paper_order("order-123")

        assert result["cancelled"] is False
        assert result["terminal_state"] == "canceled"

    def test_cancel_generic_failure_no_terminal_state(self):
        """Non-terminal failures (network, auth) return terminal_state=None."""
        from src.shadow_trading.alpaca_adapter import cancel_paper_order
        mock_client = MagicMock()
        mock_client.cancel_order_by_id.side_effect = ConnectionError("network")
        with patch("src.shadow_trading.alpaca_adapter._get_trading_client",
                   return_value=mock_client):
            result = cancel_paper_order("order-123")

        assert result["cancelled"] is False
        assert result["terminal_state"] is None
        assert "network" in result["error"]

    def test_cancel_no_client(self):
        from src.shadow_trading.alpaca_adapter import cancel_paper_order
        with patch("src.shadow_trading.alpaca_adapter._get_trading_client",
                   side_effect=Exception("No API key")):
            result = cancel_paper_order("order-123")

        assert result["cancelled"] is False
        assert result["terminal_state"] is None


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


class TestRetryExitDetectsBackgroundFill:
    """Regression guard for 2026-04-14 NVDA/GOOGL feedback loop.

    Before retrying an exit, _retry_exit must check whether the prior exit
    order already filled at the broker in the background. If it did:
      - Close the trade from the broker's fill data
      - Do NOT cancel (the cancel would be redundant)
      - Do NOT resubmit (would create a duplicate SELL)

    Two detection paths — both must work:
      1. Pre-check: get_order_status before cancel shows status=filled
      2. Cancel-race: cancel_paper_order returns terminal_state='filled'
         (order raced the cancel and filled at the broker)
    """

    def test_retry_closes_trade_when_prior_order_already_filled(self):
        """Path 1: pre-check detects the fill before we even try to cancel."""
        from src.shadow_trading.executor import _retry_exit

        trade = {
            "trade_id": "t-nvda-stuck",
            "ticker": "NVDA",
            "shares": 49,
            "actual_entry_price": 150.0,
            "entry_price": 150.0,
            "planned_shares": 49,
            "exit_order_id": "raced-order-id",
            "exit_reason": "stop_hit",
            "exit_retry_count": 1,
        }

        filled_order = {
            "order_id": "raced-order-id",
            "status": "filled",
            "filled_qty": "49",
            "filled_avg_price": 147.50,
            "filled_at": "2026-04-14T15:13:30-04:00",
        }

        with patch("src.shadow_trading.alpaca_adapter.get_order_status",
                   return_value=filled_order) as mock_status, \
             patch("src.shadow_trading.alpaca_adapter.cancel_paper_order") as mock_cancel, \
             patch("src.shadow_trading.executor._submit_exit_order") as mock_submit, \
             patch("src.shadow_trading.executor.close_shadow_trade") as mock_close, \
             patch("src.shadow_trading.executor.update_shadow_trade"), \
             patch("time.sleep"):
            _retry_exit(trade)

        mock_status.assert_called_once_with("raced-order-id")
        mock_cancel.assert_not_called()
        mock_submit.assert_not_called()
        mock_close.assert_called_once()
        close_kwargs = mock_close.call_args.kwargs or {}
        close_args_dict = {**{f"arg{i}": a for i, a in enumerate(mock_close.call_args.args)},
                           **close_kwargs}
        # Exit price should come from the broker fill, not re-submitted
        called_values = list(mock_close.call_args.args) + list(close_kwargs.values())
        assert 147.50 in called_values, \
            f"close_shadow_trade should use broker fill price 147.50; got {called_values}"

    def test_retry_closes_trade_when_cancel_reveals_background_fill(self):
        """Path 2: cancel race — status=pending_new at pre-check, but fill
        happened between pre-check and cancel, so cancel returns terminal_state=filled."""
        from src.shadow_trading.executor import _retry_exit

        trade = {
            "trade_id": "t-googl-stuck",
            "ticker": "GOOGL",
            "shares": 13,
            "actual_entry_price": 180.0,
            "entry_price": 180.0,
            "planned_shares": 13,
            "exit_order_id": "race-order-id",
            "exit_reason": "stop_hit",
            "exit_retry_count": 1,
        }

        # Pre-check says pending; cancel reveals it filled in the interim
        pending_order = {"order_id": "race-order-id", "status": "pending_new",
                         "filled_qty": "0", "filled_avg_price": None,
                         "filled_at": None}
        cancel_result = {"cancelled": False, "terminal_state": "filled",
                         "error": 'order is already in "filled" state'}
        # After the cancel fails with filled, re-fetch status shows filled
        filled_order = {"order_id": "race-order-id", "status": "filled",
                        "filled_qty": "13", "filled_avg_price": 178.25,
                        "filled_at": "2026-04-14T15:30:40-04:00"}

        with patch("src.shadow_trading.alpaca_adapter.get_order_status",
                   side_effect=[pending_order, filled_order]), \
             patch("src.shadow_trading.alpaca_adapter.cancel_paper_order",
                   return_value=cancel_result), \
             patch("src.shadow_trading.executor._submit_exit_order") as mock_submit, \
             patch("src.shadow_trading.executor.close_shadow_trade") as mock_close, \
             patch("src.shadow_trading.executor.update_shadow_trade"), \
             patch("time.sleep"):
            _retry_exit(trade)

        mock_submit.assert_not_called()  # NO duplicate SELL
        mock_close.assert_called_once()
        called_values = list(mock_close.call_args.args) + list(
            (mock_close.call_args.kwargs or {}).values())
        assert 178.25 in called_values, \
            f"Close price must come from broker fill; got {called_values}"


# ── Exit exception handling (#310) ─────────────────────────────────


class TestCancelAllOrders:
    """Test cancel_all_orders adapter function (#310)."""

    def test_cancel_all_returns_count(self):
        from src.shadow_trading.alpaca_adapter import cancel_all_orders
        mock_client = MagicMock()
        mock_client.cancel_orders.return_value = [MagicMock(), MagicMock()]
        with patch("src.shadow_trading.alpaca_adapter._get_trading_client",
                   return_value=mock_client):
            result = cancel_all_orders()
        assert result["cancelled"] == 2

    def test_cancel_all_handles_error(self):
        from src.shadow_trading.alpaca_adapter import cancel_all_orders
        with patch("src.shadow_trading.alpaca_adapter._get_trading_client",
                   side_effect=Exception("no key")):
            result = cancel_all_orders()
        assert result["cancelled"] == 0


class TestExitExceptionMarksFailure:
    """Regression #310: exception in _submit_exit_order must mark exit_failed."""

    def test_exception_marks_exit_failed_not_open(self):
        """Trade must NOT remain 'open' after broker exception."""
        from src.shadow_trading.executor import check_and_manage_open_trades

        et = ZoneInfo("America/New_York")
        entry_time = (datetime.now(et) - timedelta(days=20)).isoformat()

        mock_trade = {
            "trade_id": "t-stuck",
            "ticker": "TGT",
            "status": "open",
            "actual_entry_price": "125.0",
            "entry_price": "125.0",
            "stop_price": "120.0",
            "target_1": "130.0",
            "target_2": "135.0",
            "planned_shares": "166",
            "created_at": entry_time,
            "actual_entry_time": entry_time,
            "max_favorable_excursion": "0",
            "max_adverse_excursion": "0",
            "source": "paper",
        }

        # D3 sprint: mock get_all_positions to include TGT so the D3 sync
        # does not short-circuit with `position_already_closed`. The test's
        # intent is to verify exception handling in _submit_exit_order;
        # D3's pre-submit skip is a separate (and valid) code path.
        with patch("src.shadow_trading.executor.get_open_shadow_trades",
                   return_value=[mock_trade]), \
             patch("src.shadow_trading.executor._get_current_price_safe",
                   return_value=115.0), \
             patch("src.shadow_trading.alpaca_adapter.get_all_positions",
                   return_value=[{"symbol": "TGT", "qty": "166"}]), \
             patch("src.shadow_trading.executor._submit_exit_order",
                   side_effect=Exception("insufficient qty")), \
             patch("src.shadow_trading.executor.update_shadow_trade") as mock_update, \
             patch("src.shadow_trading.executor.load_config",
                   return_value={"shadow_trading": {"timeout_days": 15}}), \
             patch("time.sleep"):
            check_and_manage_open_trades()

        # Verify update_shadow_trade was called with exit_failed status
        exit_failed_calls = [
            c for c in mock_update.call_args_list
            if len(c[0]) >= 2 and isinstance(c[0][1], dict)
            and c[0][1].get("status") == "exit_failed"
        ]
        assert len(exit_failed_calls) > 0, (
            "Trade should be marked exit_failed on exception, not left as open"
        )
