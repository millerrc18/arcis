"""Tests for IB production hardening features in src/trading/ib_broker.py.

Covers: exponential-backoff reconnect, bracket integrity verification,
IB_STATUS_MAP normalization, partial fill detection, outsideRth/ocaType
settings, IB error code classification, and permId tracking.

All tests mock ib_async — no IB Gateway required.
"""

import logging
import unittest
from unittest.mock import MagicMock, patch, call

from tests.conftest_ib import (
    mock_account_summary, mock_trade, mock_position,
    mock_bracket_orders, mock_ticker_data, mock_account_value,
)
from src.trading.ib_broker import IBBroker, IB_STATUS_MAP
from src.trading.broker_interface import BrokerOrder


class TestReconnection(unittest.TestCase):
    """Exponential-backoff reconnect logic in _ensure_connected."""

    @patch("time.sleep")
    @patch("ib_async.IB")
    def test_exponential_backoff_retries_three_times(self, MockIB, mock_sleep):
        """Connect fails 3 times -> ConnectionError after 3 attempts."""
        mock_instance = MockIB.return_value
        mock_instance.connect.side_effect = Exception("Gateway down")

        broker = IBBroker(port=4002)
        broker._ib = None

        with self.assertRaises(ConnectionError) as ctx:
            broker._ensure_connected()

        self.assertIn("3 attempts", str(ctx.exception))
        self.assertEqual(mock_instance.connect.call_count, 3)
        # Verify exponential backoff delays: 1s, 2s (no sleep after 3rd fail)
        mock_sleep.assert_has_calls([call(1), call(2)])
        self.assertEqual(mock_sleep.call_count, 2)

    @patch("time.sleep")
    @patch("ib_async.IB")
    def test_reconnect_succeeds_on_second_attempt(self, MockIB, mock_sleep):
        """First connect fails, second succeeds -> connected."""
        mock_instance = MockIB.return_value
        mock_instance.connect.side_effect = [Exception("Timeout"), None]

        broker = IBBroker(port=4002)
        broker._ib = None
        broker._ensure_connected()

        self.assertEqual(mock_instance.connect.call_count, 2)
        self.assertIsNotNone(broker._ib)
        # Only one sleep between attempt 1 and 2
        mock_sleep.assert_called_once_with(1)

    def test_no_reconnect_when_already_connected(self):
        """isConnected()=True -> connect() NOT called."""
        broker = IBBroker(port=4002)
        broker._ib = MagicMock()
        broker._ib.isConnected.return_value = True

        broker._ensure_connected()

        broker._ib.isConnected.assert_called_once()
        # Should NOT have replaced _ib with a new instance
        broker._ib.connect.assert_not_called()


class TestBracketVerification(unittest.TestCase):
    """_verify_bracket_integrity checks all positions have active stops."""

    @patch("src.trading.ib_broker.IBBroker._ensure_connected")
    def test_verify_bracket_integrity_all_protected(self, mock_connect):
        """2 positions with matching stop orders -> empty list."""
        broker = IBBroker(port=4002)
        broker._ib = MagicMock()

        # Two positions
        broker._ib.positions.return_value = [
            mock_position(ticker="AAPL", quantity=100),
            mock_position(ticker="MSFT", quantity=50),
        ]

        # Two active stop orders matching both positions
        stop_aapl = mock_trade(ticker="AAPL", order_type="STP", action="SELL",
                               status="PreSubmitted")
        stop_aapl.order.orderType = "STP"
        stop_aapl.order.action = "SELL"
        stop_aapl.orderStatus.status = "PreSubmitted"

        stop_msft = mock_trade(ticker="MSFT", order_type="STP", action="SELL",
                               status="Submitted")
        stop_msft.order.orderType = "STP"
        stop_msft.order.action = "SELL"
        stop_msft.orderStatus.status = "Submitted"

        broker._ib.openTrades.return_value = [stop_aapl, stop_msft]

        result = broker._verify_bracket_integrity()
        self.assertEqual(result, [])

    @patch("src.trading.ib_broker.IBBroker._ensure_connected")
    def test_verify_bracket_integrity_unprotected(self, mock_connect):
        """1 position with stop, 1 without -> returns ['MSFT']."""
        broker = IBBroker(port=4002)
        broker._ib = MagicMock()

        broker._ib.positions.return_value = [
            mock_position(ticker="AAPL", quantity=100),
            mock_position(ticker="MSFT", quantity=50),
        ]

        # Only AAPL has a stop order
        stop_aapl = mock_trade(ticker="AAPL", order_type="STP", action="SELL",
                               status="PreSubmitted")
        stop_aapl.order.orderType = "STP"
        stop_aapl.order.action = "SELL"
        stop_aapl.orderStatus.status = "PreSubmitted"

        broker._ib.openTrades.return_value = [stop_aapl]

        result = broker._verify_bracket_integrity()
        self.assertEqual(result, ["MSFT"])

    @patch("src.trading.ib_broker.IBBroker._ensure_connected")
    def test_verify_bracket_integrity_no_positions(self, mock_connect):
        """Empty positions -> empty list."""
        broker = IBBroker(port=4002)
        broker._ib = MagicMock()
        broker._ib.positions.return_value = []
        broker._ib.openTrades.return_value = []

        result = broker._verify_bracket_integrity()
        self.assertEqual(result, [])


class TestStatusMapping(unittest.TestCase):
    """IB_STATUS_MAP normalizes raw IB statuses to canonical set."""

    def test_status_map_presubmitted(self):
        """IB 'PreSubmitted' -> 'pending'."""
        self.assertEqual(IB_STATUS_MAP["presubmitted"], "pending")

    def test_status_map_filled(self):
        """IB 'Filled' -> 'filled'."""
        self.assertEqual(IB_STATUS_MAP["filled"], "filled")

    def test_status_map_inactive(self):
        """IB 'Inactive' -> 'rejected'."""
        self.assertEqual(IB_STATUS_MAP["inactive"], "rejected")


class TestPartialFills(unittest.TestCase):
    """Partial fill detection in place_bracket_order."""

    @patch("src.trading.ib_broker.IBBroker._ensure_connected")
    def test_partial_fill_logged_bracket(self, mock_connect, ):
        """place_bracket_order with filled=5, totalQuantity=10 -> warning logged."""
        broker = IBBroker(port=4002)
        broker._ib = MagicMock()

        bracket = mock_bracket_orders()
        broker._ib.bracketOrder.return_value = bracket

        # Parent trade with partial fill: 5 of 10
        parent_trade = MagicMock()
        parent_trade.order.orderId = 100
        parent_trade.order.permId = 999
        parent_trade.orderStatus.status = "Submitted"
        parent_trade.orderStatus.filled = 5
        parent_trade.orderStatus.avgFillPrice = 150.0

        child1_trade = MagicMock()
        child1_trade.order.orderId = 101
        child1_trade.order.permId = 1001

        child2_trade = MagicMock()
        child2_trade.order.orderId = 102
        child2_trade.order.permId = 1002

        broker._ib.placeOrder.side_effect = [parent_trade, child1_trade, child2_trade]
        broker._ib.qualifyContracts.return_value = None

        with self.assertLogs("src.trading.ib_broker", level="WARNING") as cm:
            result = broker.place_bracket_order(
                ticker="AAPL", quantity=10,
                take_profit_price=160.0, stop_loss_price=140.0,
                limit_price=150.0,
            )

        # Check that partial fill warning was logged
        partial_msgs = [m for m in cm.output if "Partial fill" in m]
        self.assertEqual(len(partial_msgs), 1)
        self.assertIn("5/10", partial_msgs[0])

    @patch("src.trading.ib_broker.IBBroker._ensure_connected")
    def test_full_fill_no_warning(self, mock_connect):
        """filled=10, totalQuantity=10 -> no partial fill warning."""
        broker = IBBroker(port=4002)
        broker._ib = MagicMock()

        bracket = mock_bracket_orders()
        broker._ib.bracketOrder.return_value = bracket

        parent_trade = MagicMock()
        parent_trade.order.orderId = 100
        parent_trade.order.permId = 888
        parent_trade.orderStatus.status = "Filled"
        parent_trade.orderStatus.filled = 10
        parent_trade.orderStatus.avgFillPrice = 150.0

        child1_trade = MagicMock()
        child1_trade.order.orderId = 101
        child1_trade.order.permId = 1001

        child2_trade = MagicMock()
        child2_trade.order.orderId = 102
        child2_trade.order.permId = 1002

        broker._ib.placeOrder.side_effect = [parent_trade, child1_trade, child2_trade]
        broker._ib.qualifyContracts.return_value = None

        # Enable logging to capture any warnings
        logger = logging.getLogger("src.trading.ib_broker")
        with self.assertNoLogs("src.trading.ib_broker", level="WARNING"):
            result = broker.place_bracket_order(
                ticker="AAPL", quantity=10,
                take_profit_price=160.0, stop_loss_price=140.0,
                limit_price=150.0,
            )

    @patch("src.trading.ib_broker.IBBroker._ensure_connected")
    def test_full_fill_returns_correct_filled_qty(self, mock_connect):
        """Verify filled_qty in returned BrokerOrder matches actual fill."""
        broker = IBBroker(port=4002)
        broker._ib = MagicMock()

        bracket = mock_bracket_orders()
        broker._ib.bracketOrder.return_value = bracket

        parent_trade = MagicMock()
        parent_trade.order.orderId = 100
        parent_trade.order.permId = 888
        parent_trade.orderStatus.status = "Filled"
        parent_trade.orderStatus.filled = 10
        parent_trade.orderStatus.avgFillPrice = 150.0

        child1_trade = MagicMock()
        child1_trade.order.orderId = 101
        child1_trade.order.permId = 1001

        child2_trade = MagicMock()
        child2_trade.order.orderId = 102
        child2_trade.order.permId = 1002

        broker._ib.placeOrder.side_effect = [parent_trade, child1_trade, child2_trade]
        broker._ib.qualifyContracts.return_value = None

        result = broker.place_bracket_order(
            ticker="AAPL", quantity=10,
            take_profit_price=160.0, stop_loss_price=140.0,
            limit_price=150.0,
        )

        self.assertEqual(result.filled_qty, 10)


class TestOutsideRthAndOcaType(unittest.TestCase):
    """outsideRth and ocaType settings on bracket orders."""

    @patch("src.trading.ib_broker.IBBroker._ensure_connected")
    def test_bracket_orders_have_outside_rth(self, mock_connect):
        """All 3 bracket orders have outsideRth=True."""
        broker = IBBroker(port=4002)
        broker._ib = MagicMock()

        bracket = mock_bracket_orders()
        broker._ib.bracketOrder.return_value = bracket

        parent_trade = MagicMock()
        parent_trade.order.orderId = 100
        parent_trade.order.permId = 777
        parent_trade.orderStatus.status = "Filled"
        parent_trade.orderStatus.filled = 10
        parent_trade.orderStatus.avgFillPrice = 150.0

        child1_trade = MagicMock()
        child1_trade.order.orderId = 101
        child1_trade.order.permId = 1001

        child2_trade = MagicMock()
        child2_trade.order.orderId = 102
        child2_trade.order.permId = 1002

        broker._ib.placeOrder.side_effect = [parent_trade, child1_trade, child2_trade]
        broker._ib.qualifyContracts.return_value = None

        broker.place_bracket_order(
            ticker="AAPL", quantity=10,
            take_profit_price=160.0, stop_loss_price=140.0,
            limit_price=150.0,
        )

        # Verify all 3 bracket orders got outsideRth=True
        for i, order in enumerate(bracket):
            self.assertTrue(order.outsideRth,
                            f"bracket[{i}] missing outsideRth=True")

    @patch("src.trading.ib_broker.IBBroker._ensure_connected")
    def test_bracket_children_have_oca_type_3(self, mock_connect):
        """bracket[1] and bracket[2] have ocaType=3."""
        broker = IBBroker(port=4002)
        broker._ib = MagicMock()

        bracket = mock_bracket_orders()
        broker._ib.bracketOrder.return_value = bracket

        parent_trade = MagicMock()
        parent_trade.order.orderId = 100
        parent_trade.order.permId = 666
        parent_trade.orderStatus.status = "Filled"
        parent_trade.orderStatus.filled = 10
        parent_trade.orderStatus.avgFillPrice = 150.0

        child1_trade = MagicMock()
        child1_trade.order.orderId = 101
        child1_trade.order.permId = 1001

        child2_trade = MagicMock()
        child2_trade.order.orderId = 102
        child2_trade.order.permId = 1002

        broker._ib.placeOrder.side_effect = [parent_trade, child1_trade, child2_trade]
        broker._ib.qualifyContracts.return_value = None

        broker.place_bracket_order(
            ticker="AAPL", quantity=10,
            take_profit_price=160.0, stop_loss_price=140.0,
            limit_price=150.0,
        )

        # Children (bracket[1] and bracket[2]) must have ocaType=3
        self.assertEqual(bracket[1].ocaType, 3)
        self.assertEqual(bracket[2].ocaType, 3)


class TestErrorCodes(unittest.TestCase):
    """_handle_ib_error classifies IB error codes."""

    @patch("src.trading.ib_broker.IBBroker._ensure_connected")
    def test_handle_ib_error_classifies_codes(self, mock_connect):
        """Codes 200, 201, 202 produce correct classification strings."""
        broker = IBBroker(port=4002)
        broker._ib = MagicMock()

        expected = {
            200: ("unknown_contract", "ERROR"),
            201: ("order_rejected", "ERROR"),
            202: ("order_cancelled", "WARNING"),
        }

        for code, (classification, level) in expected.items():
            with self.assertLogs("src.trading.ib_broker") as cm:
                broker._handle_ib_error(code, f"Test msg for {code}", ticker="AAPL")

            combined = " ".join(cm.output)
            self.assertIn(classification, combined,
                          f"Code {code} should log '{classification}'")


class TestPermId(unittest.TestCase):
    """permId cross-session tracking on bracket orders."""

    @patch("src.trading.ib_broker.IBBroker._ensure_connected")
    def test_bracket_order_returns_perm_id(self, mock_connect):
        """place_bracket_order returns BrokerOrder with perm_id from parent trade."""
        broker = IBBroker(port=4002)
        broker._ib = MagicMock()

        bracket = mock_bracket_orders()
        broker._ib.bracketOrder.return_value = bracket

        parent_trade = MagicMock()
        parent_trade.order.orderId = 100
        parent_trade.order.permId = 12345678
        parent_trade.orderStatus.status = "Filled"
        parent_trade.orderStatus.filled = 10
        parent_trade.orderStatus.avgFillPrice = 150.0

        child1_trade = MagicMock()
        child1_trade.order.orderId = 101
        child1_trade.order.permId = 1001

        child2_trade = MagicMock()
        child2_trade.order.orderId = 102
        child2_trade.order.permId = 1002

        broker._ib.placeOrder.side_effect = [parent_trade, child1_trade, child2_trade]
        broker._ib.qualifyContracts.return_value = None

        result = broker.place_bracket_order(
            ticker="AAPL", quantity=10,
            take_profit_price=160.0, stop_loss_price=140.0,
            limit_price=150.0,
        )

        self.assertIsInstance(result, BrokerOrder)
        self.assertEqual(result.perm_id, "12345678")
        self.assertEqual(result.order_id, "100")
        self.assertEqual(result.broker, "ib")


if __name__ == "__main__":
    unittest.main()
