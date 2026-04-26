"""Regression tests for Sprint 0 Wave 5c LIVE-VERIFY.

CLAUDE.md: "Verify orders after submission — call verify_order_accepted()
after submit_order(). Network errors don't mean Alpaca rejected the order."

Pre-Wave-5c, AlpacaLiveBroker submitted orders fire-and-forget against a
real-money account (place_market_order, place_exit, place_bracket_order,
cancel_order). On a live account, a missed acceptance verification means:

  - bracket parent silently rejected -> we record a "live trade" in the
    DB with no actual position on the broker (capital phantom row)
  - exit silently rejected -> we believe the position is closed but it
    isn't, leaving capital exposed past the operator's intended exit
  - cancel didn't actually cancel -> we believe the order is dead but
    it's still active and can fill against our intent

This module proves AlpacaLiveBroker now calls verify_live_order_accepted
on every submit-bearing path, that polling + raise semantics are correct,
and that terminal-reject statuses propagate as OrderNotAcceptedError.
"""
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# verify_live_order_accepted polling semantics
# ---------------------------------------------------------------------------
class TestVerifyLiveOrderAccepted:
    """Direct tests of the polling/retry/raise contract in alpaca_adapter."""

    def test_returns_immediately_on_accepted(self):
        from src.shadow_trading.alpaca_adapter import verify_live_order_accepted

        mock_order = MagicMock()
        mock_order.status = "accepted"
        mock_order.id = "ord-1"
        mock_order.symbol = "AAPL"
        mock_order.qty = 1
        mock_order.filled_qty = 0
        mock_order.filled_avg_price = None

        sleeps: list[float] = []
        with patch(
            "src.shadow_trading.alpaca_adapter._get_live_trading_client"
        ) as mock_client:
            mock_client.return_value.get_order_by_id.return_value = mock_order
            result = verify_live_order_accepted(
                "ord-1", sleep_fn=lambda s: sleeps.append(s),
            )

        assert result["verified"] is True
        assert result["status"] == "accepted"
        assert result["attempts"] == 1
        # First successful attempt: no backoff sleep
        assert sleeps == []

    def test_returns_on_filled(self):
        from src.shadow_trading.alpaca_adapter import verify_live_order_accepted

        mock_order = MagicMock()
        mock_order.status = "filled"
        mock_order.id = "ord-2"
        mock_order.symbol = "MSFT"
        mock_order.qty = 5
        mock_order.filled_qty = 5
        mock_order.filled_avg_price = 300.0

        with patch(
            "src.shadow_trading.alpaca_adapter._get_live_trading_client"
        ) as mock_client:
            mock_client.return_value.get_order_by_id.return_value = mock_order
            result = verify_live_order_accepted("ord-2", sleep_fn=lambda s: None)

        assert result["verified"] is True
        assert result["status"] == "filled"
        assert result["order"]["filled_avg_price"] == 300.0

    def test_returns_on_partially_filled(self):
        from src.shadow_trading.alpaca_adapter import verify_live_order_accepted

        mock_order = MagicMock()
        mock_order.status = "partially_filled"
        mock_order.id = "ord-3"
        mock_order.symbol = "NVDA"
        mock_order.qty = 10
        mock_order.filled_qty = 4
        mock_order.filled_avg_price = 950.0

        with patch(
            "src.shadow_trading.alpaca_adapter._get_live_trading_client"
        ) as mock_client:
            mock_client.return_value.get_order_by_id.return_value = mock_order
            result = verify_live_order_accepted("ord-3", sleep_fn=lambda s: None)

        assert result["verified"] is True
        assert result["status"] == "partially_filled"

    def test_raises_on_terminal_reject_rejected(self):
        from src.shadow_trading.alpaca_adapter import (
            verify_live_order_accepted, OrderNotAcceptedError,
        )

        mock_order = MagicMock()
        mock_order.status = "rejected"
        mock_order.id = "ord-rej"
        mock_order.symbol = "AAPL"
        mock_order.qty = 1
        mock_order.filled_qty = 0
        mock_order.filled_avg_price = None

        with patch(
            "src.shadow_trading.alpaca_adapter._get_live_trading_client"
        ) as mock_client:
            mock_client.return_value.get_order_by_id.return_value = mock_order
            with pytest.raises(OrderNotAcceptedError) as excinfo:
                verify_live_order_accepted("ord-rej", sleep_fn=lambda s: None)

        assert excinfo.value.status == "rejected"
        assert excinfo.value.order_id == "ord-rej"

    def test_raises_on_terminal_reject_canceled(self):
        from src.shadow_trading.alpaca_adapter import (
            verify_live_order_accepted, OrderNotAcceptedError,
        )

        mock_order = MagicMock()
        mock_order.status = "canceled"
        mock_order.id = "ord-can"
        mock_order.symbol = "TSLA"
        mock_order.qty = 1
        mock_order.filled_qty = 0
        mock_order.filled_avg_price = None

        with patch(
            "src.shadow_trading.alpaca_adapter._get_live_trading_client"
        ) as mock_client:
            mock_client.return_value.get_order_by_id.return_value = mock_order
            with pytest.raises(OrderNotAcceptedError) as excinfo:
                verify_live_order_accepted("ord-can", sleep_fn=lambda s: None)

        assert excinfo.value.status == "canceled"

    def test_polls_with_exponential_backoff(self):
        """Status returns 'unknown' on first 4 attempts, accepted on the 5th.

        Exponential backoff: 1s, 2s, 4s, 8s before attempts 2..5.
        """
        from src.shadow_trading.alpaca_adapter import verify_live_order_accepted

        # First 4 calls return an unrecognized status; 5th returns accepted.
        statuses = ["weird_status", "weird_status", "weird_status",
                    "weird_status", "accepted"]
        mock_orders = []
        for s in statuses:
            mo = MagicMock()
            mo.status = s
            mo.id = "ord-poll"
            mo.symbol = "AAPL"
            mo.qty = 1
            mo.filled_qty = 0
            mo.filled_avg_price = None
            mock_orders.append(mo)

        sleeps: list[float] = []
        with patch(
            "src.shadow_trading.alpaca_adapter._get_live_trading_client"
        ) as mock_client:
            mock_client.return_value.get_order_by_id.side_effect = mock_orders
            result = verify_live_order_accepted(
                "ord-poll",
                sleep_fn=lambda s: sleeps.append(s),
            )

        assert result["verified"] is True
        assert result["status"] == "accepted"
        assert result["attempts"] == 5
        # 4 sleeps fire BETWEEN the 5 attempts, with cap at max_delay=8.0
        assert sleeps == [1.0, 2.0, 4.0, 8.0]

    def test_raises_when_attempts_exhausted(self):
        from src.shadow_trading.alpaca_adapter import (
            verify_live_order_accepted, OrderNotAcceptedError,
        )

        mock_order = MagicMock()
        mock_order.status = "weird_status"
        mock_order.id = "ord-poll-exhaust"
        mock_order.symbol = "AAPL"
        mock_order.qty = 1
        mock_order.filled_qty = 0
        mock_order.filled_avg_price = None

        with patch(
            "src.shadow_trading.alpaca_adapter._get_live_trading_client"
        ) as mock_client:
            mock_client.return_value.get_order_by_id.return_value = mock_order
            with pytest.raises(OrderNotAcceptedError) as excinfo:
                verify_live_order_accepted(
                    "ord-poll-exhaust", sleep_fn=lambda s: None,
                )

        assert excinfo.value.attempts == 5
        assert excinfo.value.status == "weird_status"

    def test_retries_on_api_error_then_succeeds(self):
        """Transient API errors get retried; eventual success is observed."""
        from src.shadow_trading.alpaca_adapter import verify_live_order_accepted

        mock_ok = MagicMock()
        mock_ok.status = "accepted"
        mock_ok.id = "ord-r"
        mock_ok.symbol = "AAPL"
        mock_ok.qty = 1
        mock_ok.filled_qty = 0
        mock_ok.filled_avg_price = None

        side_effects = [
            ConnectionError("alpaca timeout"),
            ConnectionError("alpaca timeout"),
            mock_ok,
        ]
        sleeps: list[float] = []
        with patch(
            "src.shadow_trading.alpaca_adapter._get_live_trading_client"
        ) as mock_client:
            mock_client.return_value.get_order_by_id.side_effect = side_effects
            result = verify_live_order_accepted(
                "ord-r", sleep_fn=lambda s: sleeps.append(s),
            )

        assert result["verified"] is True
        assert result["attempts"] == 3
        assert sleeps == [1.0, 2.0]

    def test_raises_with_last_error_when_all_attempts_api_fail(self):
        from src.shadow_trading.alpaca_adapter import (
            verify_live_order_accepted, OrderNotAcceptedError,
        )

        with patch(
            "src.shadow_trading.alpaca_adapter._get_live_trading_client"
        ) as mock_client:
            mock_client.return_value.get_order_by_id.side_effect = (
                ConnectionError("alpaca down")
            )
            with pytest.raises(OrderNotAcceptedError) as excinfo:
                verify_live_order_accepted("ord-x", sleep_fn=lambda s: None)

        assert excinfo.value.attempts == 5
        assert excinfo.value.last_error == "alpaca down"


# ---------------------------------------------------------------------------
# AlpacaLiveBroker integration: verify is wired on every submit path
# ---------------------------------------------------------------------------
class TestAlpacaLiveBrokerCallsVerify:
    """Each submit-bearing method on AlpacaLiveBroker must invoke
    verify_live_order_accepted post-submit. Pre-Wave-5c they did not.
    """

    def test_alpaca_live_place_market_order_calls_verify(self):
        from src.trading.alpaca_broker import AlpacaLiveBroker

        fake_entry = {
            "order_id": "mkt-1", "status": "accepted",
            "filled_avg_price": 100.0, "qty": 5,
        }
        with patch(
            "src.shadow_trading.alpaca_adapter.place_live_entry",
            return_value=fake_entry,
        ), patch(
            "src.shadow_trading.alpaca_adapter.verify_live_order_accepted",
            return_value={"verified": True, "status": "accepted",
                          "attempts": 1, "order": {}},
        ) as mock_verify:
            broker = AlpacaLiveBroker()
            order = broker.place_market_order("AAPL", 5, side="buy")

        mock_verify.assert_called_once()
        # First positional arg is the order id from the live submit response
        assert mock_verify.call_args.args[0] == "mkt-1"
        assert order.order_id == "mkt-1"

    def test_alpaca_live_place_market_sell_calls_verify(self):
        from src.trading.alpaca_broker import AlpacaLiveBroker

        fake_exit = {
            "order_id": "mkt-sell-1", "status": "accepted",
            "filled_avg_price": 100.0, "qty": 5,
        }
        with patch(
            "src.shadow_trading.alpaca_adapter.place_live_exit",
            return_value=fake_exit,
        ), patch(
            "src.shadow_trading.alpaca_adapter.verify_live_order_accepted",
            return_value={"verified": True, "status": "accepted",
                          "attempts": 1, "order": {}},
        ) as mock_verify:
            broker = AlpacaLiveBroker()
            broker.place_market_order("AAPL", 5, side="sell")

        mock_verify.assert_called_once()
        assert mock_verify.call_args.args[0] == "mkt-sell-1"

    def test_alpaca_live_place_exit_calls_verify(self):
        from src.trading.alpaca_broker import AlpacaLiveBroker

        fake_exit = {
            "order_id": "exit-1", "status": "accepted",
            "filled_avg_price": 100.0, "qty": 5,
        }
        with patch(
            "src.shadow_trading.alpaca_adapter.place_live_exit",
            return_value=fake_exit,
        ), patch(
            "src.shadow_trading.alpaca_adapter.verify_live_order_accepted",
            return_value={"verified": True, "status": "accepted",
                          "attempts": 1, "order": {}},
        ) as mock_verify:
            broker = AlpacaLiveBroker()
            order = broker.place_exit("AAPL", quantity=5)

        mock_verify.assert_called_once()
        assert mock_verify.call_args.args[0] == "exit-1"
        assert order.side == "sell"

    def test_alpaca_live_place_exit_skips_verify_for_close_position_synth(self):
        """close_position returns a synthetic 'close_position' placeholder
        when the SDK doesn't expose a real id — there's nothing to poll."""
        from src.trading.alpaca_broker import AlpacaLiveBroker

        fake_close = {
            "order_id": "close_position", "status": "accepted",
            "filled_avg_price": None, "qty": 0,
        }
        with patch(
            "src.shadow_trading.alpaca_adapter.place_live_exit",
            return_value=fake_close,
        ), patch(
            "src.shadow_trading.alpaca_adapter.verify_live_order_accepted",
        ) as mock_verify:
            broker = AlpacaLiveBroker()
            broker.place_exit("AAPL", quantity=0)

        # Synthetic placeholder must NOT trigger the verify call (there's
        # no real order id to poll for).
        mock_verify.assert_not_called()

    def test_alpaca_live_place_bracket_calls_verify(self):
        from src.trading.alpaca_broker import AlpacaLiveBroker

        fake_bracket = {
            "order_id": "br-1", "status": "accepted",
            "filled_avg_price": None, "qty": 5, "legs": ["tp", "sl"],
        }
        with patch(
            "src.shadow_trading.alpaca_adapter.place_live_bracket",
            return_value=fake_bracket,
        ), patch(
            "src.shadow_trading.alpaca_adapter.verify_live_order_accepted",
            return_value={"verified": True, "status": "accepted",
                          "attempts": 1, "order": {}},
        ) as mock_verify:
            broker = AlpacaLiveBroker()
            order = broker.place_bracket_order(
                ticker="AAPL",
                quantity=5,
                take_profit_price=110.0,
                stop_loss_price=90.0,
                limit_price=100.0,
            )

        mock_verify.assert_called_once()
        assert mock_verify.call_args.args[0] == "br-1"
        assert order.order_type == "bracket"

    def test_alpaca_live_cancel_calls_verify(self):
        """cancel_order must verify the broker actually cancelled (not raced
        by a fill) by polling and treating canceled/expired as success."""
        from src.trading.alpaca_broker import AlpacaLiveBroker

        with patch(
            "src.shadow_trading.alpaca_adapter._get_live_trading_client"
        ) as mock_client, patch(
            "src.shadow_trading.alpaca_adapter.verify_live_order_accepted",
            return_value={"verified": True, "status": "canceled",
                          "attempts": 1, "order": {}},
        ) as mock_verify:
            mock_client.return_value.cancel_order_by_id.return_value = None
            broker = AlpacaLiveBroker()
            ok = broker.cancel_order("ord-cancel-1")

        mock_verify.assert_called_once()
        assert mock_verify.call_args.args[0] == "ord-cancel-1"
        assert ok is True

    def test_alpaca_live_cancel_returns_false_when_filled_raced_cancel(self):
        """If the broker reports 'filled' after our cancel (we lost the race),
        cancel_order returns False so the caller knows the position changed."""
        from src.trading.alpaca_broker import AlpacaLiveBroker

        with patch(
            "src.shadow_trading.alpaca_adapter._get_live_trading_client"
        ) as mock_client, patch(
            "src.shadow_trading.alpaca_adapter.verify_live_order_accepted",
            return_value={"verified": True, "status": "filled",
                          "attempts": 1, "order": {}},
        ) as mock_verify:
            mock_client.return_value.cancel_order_by_id.return_value = None
            broker = AlpacaLiveBroker()
            ok = broker.cancel_order("ord-raced")

        mock_verify.assert_called_once()
        assert ok is False

    def test_alpaca_live_cancel_treats_terminal_reject_as_success(self):
        """If verify raises OrderNotAcceptedError with status canceled/
        expired/rejected/suspended, cancel intent is satisfied (order is
        no longer active on the broker)."""
        from src.trading.alpaca_broker import AlpacaLiveBroker
        from src.shadow_trading.alpaca_adapter import OrderNotAcceptedError

        with patch(
            "src.shadow_trading.alpaca_adapter._get_live_trading_client"
        ) as mock_client, patch(
            "src.shadow_trading.alpaca_adapter.verify_live_order_accepted",
            side_effect=OrderNotAcceptedError(
                order_id="ord-x", status="expired", attempts=5,
            ),
        ):
            mock_client.return_value.cancel_order_by_id.return_value = None
            broker = AlpacaLiveBroker()
            ok = broker.cancel_order("ord-x")

        assert ok is True

    def test_alpaca_live_place_market_propagates_terminal_reject(self):
        """OrderNotAcceptedError on place_market_order propagates to the
        caller — capital paths must not silently absorb a broker reject."""
        from src.trading.alpaca_broker import AlpacaLiveBroker
        from src.shadow_trading.alpaca_adapter import OrderNotAcceptedError

        fake_entry = {"order_id": "mkt-bad", "status": "accepted",
                      "filled_avg_price": None, "qty": 1}
        with patch(
            "src.shadow_trading.alpaca_adapter.place_live_entry",
            return_value=fake_entry,
        ), patch(
            "src.shadow_trading.alpaca_adapter.verify_live_order_accepted",
            side_effect=OrderNotAcceptedError(
                order_id="mkt-bad", status="rejected", attempts=1,
            ),
        ):
            broker = AlpacaLiveBroker()
            with pytest.raises(OrderNotAcceptedError):
                broker.place_market_order("AAPL", 1, side="buy")

    def test_alpaca_live_place_bracket_propagates_terminal_reject(self):
        from src.trading.alpaca_broker import AlpacaLiveBroker
        from src.shadow_trading.alpaca_adapter import OrderNotAcceptedError

        fake_bracket = {"order_id": "br-bad", "status": "accepted",
                        "filled_avg_price": None, "qty": 1, "legs": []}
        with patch(
            "src.shadow_trading.alpaca_adapter.place_live_bracket",
            return_value=fake_bracket,
        ), patch(
            "src.shadow_trading.alpaca_adapter.verify_live_order_accepted",
            side_effect=OrderNotAcceptedError(
                order_id="br-bad", status="rejected", attempts=1,
            ),
        ):
            broker = AlpacaLiveBroker()
            with pytest.raises(OrderNotAcceptedError):
                broker.place_bracket_order(
                    ticker="AAPL", quantity=1,
                    take_profit_price=110.0, stop_loss_price=90.0,
                )
