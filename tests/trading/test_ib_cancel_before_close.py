"""Regression tests for Sprint 0 Wave 5c IB-CANCEL-BEFORE-CLOSE.

CLAUDE.md: "Cancel before close — before closing a position via reconciliation,
call cancel_orders_for_ticker() to release held_for_orders locks."

The Alpaca side mirrors the cancel-before-close pattern (reconcile.py:591,645).
On the IB side, before this fix, IBBroker.place_exit submitted a market SELL
without first cancelling the bracket children (take-profit + stop-loss legs
in the OCA group). Three SELL orders could then race:

  - the new market exit (place_exit)
  - the take-profit LMT (bracket child)
  - the stop-loss STP / STP LMT (bracket child)

Best case: ocaType=3 atomicity holds and only one fills. Worst case: the OCA
loses atomicity across reconnects (it's broker-side, not always atomic) and
two SELLs fill — which on a long position oversells into a short.

This module verifies place_exit cancels bracket children FIRST and waits for
broker acknowledgement of every cancel before submitting the market exit.

All ib_async objects are mocked. No live IB Gateway connection required.
"""
import sys
import types
import unittest
from unittest.mock import MagicMock, patch

from src.trading.ib_broker import IBBroker
from src.trading.broker_interface import BrokerOrder
from tests.conftest_ib import mock_trade, mock_position


def _install_mock_ib_async():
    """Inject a mock ib_async module so deferred imports resolve."""
    mock_mod = types.ModuleType("ib_async")
    mock_mod.Stock = MagicMock(name="Stock")
    mock_mod.MarketOrder = MagicMock(name="MarketOrder")
    mock_mod.IB = MagicMock(name="IB")
    sys.modules["ib_async"] = mock_mod
    return mock_mod


def _remove_mock_ib_async():
    sys.modules.pop("ib_async", None)
    import src.trading.ib_broker as mod
    for attr in ("Stock", "MarketOrder", "IB"):
        if hasattr(mod, attr):
            delattr(mod, attr)


def _make_bracket_child_trade(order_id, ticker, order_type, status="Submitted"):
    """A bracket child SELL trade — TP (LMT SELL) or SL (STP SELL)."""
    trade = mock_trade(
        order_id=order_id, ticker=ticker, status=status,
        action="SELL", order_type=order_type, quantity=10, filled=0,
    )
    return trade


# ---------------------------------------------------------------------------
# TestIBPlaceExitCancelsBracketChildrenFirst
# ---------------------------------------------------------------------------
class TestIBPlaceExitCancelsBracketChildrenFirst(unittest.TestCase):
    """place_exit must cancel active bracket-child SELL orders BEFORE
    submitting the market exit, not concurrently or after."""

    def setUp(self):
        self._mock_ib_async = _install_mock_ib_async()

    def tearDown(self):
        _remove_mock_ib_async()

    @patch("src.trading.ib_broker.IBBroker._ensure_connected")
    def test_ib_place_exit_cancels_bracket_children_first(self, mock_connect):
        """When AAPL has bracket children TP(101) + SL(102) sitting on the
        broker, place_exit must call cancelOrder on BOTH before placeOrder
        is called for the new market SELL exit."""
        broker = IBBroker(port=4002)
        broker._ib = MagicMock()

        # Position so quantity=0 resolves to 10 shares.
        broker._ib.positions.return_value = [
            mock_position("AAPL", 10.0, 150.0, 50.0),
        ]

        # Two bracket children: take-profit (LMT SELL) + stop-loss (STP SELL).
        tp_child = _make_bracket_child_trade(101, "AAPL", "LMT")
        sl_child = _make_bracket_child_trade(102, "AAPL", "STP")
        # Other ticker should NOT be cancelled.
        unrelated = _make_bracket_child_trade(999, "MSFT", "STP")

        # First call (during cancel scan) returns all 3 trades.
        # After cancel, second/third calls (during ack-wait poll) return
        # an empty list to signal the cancellations took effect.
        broker._ib.openTrades.side_effect = [
            [tp_child, sl_child, unrelated],  # cancel-scan
            [unrelated],                        # ack-wait tick 1
            [unrelated],                        # extras
        ]

        call_log = []

        def cancelOrder_side_effect(order):
            call_log.append(("cancelOrder", order.orderId))

        def placeOrder_side_effect(contract, order):
            call_log.append(("placeOrder", "exit"))
            trade = mock_trade(
                order_id=500, action="SELL", status="Filled",
                avg_price=149.0, filled=10, quantity=10,
            )
            return trade

        broker._ib.cancelOrder.side_effect = cancelOrder_side_effect
        broker._ib.placeOrder.side_effect = placeOrder_side_effect

        # Mock MarketOrder so the 'from ib_async import MarketOrder' inside
        # place_market_order resolves to a MagicMock instance.
        self._mock_ib_async.MarketOrder.return_value = MagicMock()

        result = broker.place_exit("AAPL", quantity=0)

        # All cancels MUST appear before the placeOrder for the exit
        cancel_indices = [
            i for i, (op, _) in enumerate(call_log) if op == "cancelOrder"
        ]
        place_indices = [
            i for i, (op, _) in enumerate(call_log) if op == "placeOrder"
        ]
        self.assertEqual(len(cancel_indices), 2,
                         f"Expected 2 cancels, got {call_log!r}")
        self.assertEqual(len(place_indices), 1,
                         f"Expected 1 placeOrder, got {call_log!r}")
        self.assertLess(max(cancel_indices), place_indices[0],
                        "cancelOrder calls MUST precede the exit placeOrder; "
                        f"got order: {call_log!r}")

        # Cancelled IDs are exactly the AAPL bracket children (not the
        # MSFT unrelated SELL).
        cancelled_ids = {oid for op, oid in call_log if op == "cancelOrder"}
        self.assertEqual(cancelled_ids, {101, 102})

        # Result reflects the exit market SELL
        self.assertIsInstance(result, BrokerOrder)
        self.assertEqual(result.side, "sell")
        self.assertEqual(result.quantity, 10)

    @patch("src.trading.ib_broker.IBBroker._ensure_connected")
    def test_ib_place_exit_no_children_no_cancels(self, mock_connect):
        """If no bracket children exist for the ticker, place_exit submits
        the exit immediately — no spurious cancelOrder calls."""
        broker = IBBroker(port=4002)
        broker._ib = MagicMock()

        broker._ib.positions.return_value = [
            mock_position("AAPL", 10.0, 150.0, 50.0),
        ]
        broker._ib.openTrades.return_value = []  # no children

        self._mock_ib_async.MarketOrder.return_value = MagicMock()
        broker._ib.placeOrder.return_value = mock_trade(
            order_id=600, action="SELL", status="Filled",
            avg_price=149.0, filled=10, quantity=10,
        )

        broker.place_exit("AAPL", quantity=0)

        broker._ib.cancelOrder.assert_not_called()
        broker._ib.placeOrder.assert_called_once()

    @patch("src.trading.ib_broker.IBBroker._ensure_connected")
    def test_ib_place_exit_only_cancels_sells_for_target_ticker(self, mock_connect):
        """A BUY child (e.g. an unfilled bracket parent) must NOT be cancelled
        — that's not a protective leg, and cancelling it would abort an
        in-flight entry. Only SELL trades for the target ticker are cancelled."""
        broker = IBBroker(port=4002)
        broker._ib = MagicMock()

        broker._ib.positions.return_value = [
            mock_position("AAPL", 10.0, 150.0, 50.0),
        ]

        sell_child = _make_bracket_child_trade(101, "AAPL", "STP")
        buy_child = mock_trade(
            order_id=200, ticker="AAPL", status="Submitted",
            action="BUY", order_type="LMT", quantity=10, filled=0,
        )

        broker._ib.openTrades.side_effect = [
            [sell_child, buy_child],
            [buy_child],
        ]
        self._mock_ib_async.MarketOrder.return_value = MagicMock()
        broker._ib.placeOrder.return_value = mock_trade(
            order_id=700, action="SELL", status="Filled",
            avg_price=149.0, filled=10, quantity=10,
        )

        broker.place_exit("AAPL", quantity=0)

        # Only the sell_child (orderId=101) is cancelled.
        cancelled_args = [
            c.args[0] for c in broker._ib.cancelOrder.call_args_list
        ]
        self.assertEqual(len(cancelled_args), 1)
        self.assertEqual(cancelled_args[0].orderId, 101)


# ---------------------------------------------------------------------------
# TestIBPlaceExitWaitsForCancelAck
# ---------------------------------------------------------------------------
class TestIBPlaceExitWaitsForCancelAck(unittest.TestCase):
    """place_exit must wait for broker ACK on each cancel — submission alone
    is insufficient. The exit MUST not fire until each cancelled child's
    status reads terminal (Cancelled/ApiCancelled/Inactive/Filled) or the
    child has dropped out of openTrades()."""

    def setUp(self):
        self._mock_ib_async = _install_mock_ib_async()

    def tearDown(self):
        _remove_mock_ib_async()

    @patch("src.trading.ib_broker.IBBroker._ensure_connected")
    def test_ib_place_exit_waits_for_cancel_ack(self, mock_connect):
        """The cancel ack-wait loop must spin until openTrades() reflects
        terminal status for every cancelled child. While the child still
        shows status='Submitted', the exit market SELL is NOT submitted."""
        broker = IBBroker(port=4002)
        broker._ib = MagicMock()

        broker._ib.positions.return_value = [
            mock_position("AAPL", 10.0, 150.0, 50.0),
        ]

        # The same child trade object: status starts as Submitted and
        # mutates to ApiCancelled across openTrades() polls.
        child = _make_bracket_child_trade(101, "AAPL", "STP",
                                          status="Submitted")
        # Pre-cancel scan
        scan_result = [child]
        # Ack-wait poll #1: still Submitted -> not terminal
        ack_t1_child = _make_bracket_child_trade(101, "AAPL", "STP",
                                                  status="Submitted")
        ack_t1 = [ack_t1_child]
        # Ack-wait poll #2: status now ApiCancelled -> terminal -> stop
        ack_t2_child = _make_bracket_child_trade(101, "AAPL", "STP",
                                                  status="ApiCancelled")
        ack_t2 = [ack_t2_child]

        broker._ib.openTrades.side_effect = [scan_result, ack_t1, ack_t2]

        # Track the order of operations: sleeps between cancel-submit and
        # exit placeOrder must include at least one ack-wait sleep.
        op_log = []

        def cancelOrder_side_effect(order):
            op_log.append(("cancelOrder", order.orderId))

        def sleep_side_effect(secs):
            op_log.append(("sleep", secs))

        def placeOrder_side_effect(contract, order):
            op_log.append(("placeOrder", "exit"))
            return mock_trade(
                order_id=500, action="SELL", status="Filled",
                avg_price=149.0, filled=10, quantity=10,
            )

        broker._ib.cancelOrder.side_effect = cancelOrder_side_effect
        broker._ib.sleep.side_effect = sleep_side_effect
        broker._ib.placeOrder.side_effect = placeOrder_side_effect
        self._mock_ib_async.MarketOrder.return_value = MagicMock()

        broker.place_exit("AAPL", quantity=0)

        # Sequence MUST be: cancelOrder(101) -> sleep(s) -> placeOrder(exit)
        # We assert at least one sleep call sits between cancelOrder and the
        # placeOrder for the exit. (The market_order place_order also calls
        # _ib.sleep(2) AFTER the exit — that's not the cancel-ack sleep.)
        cancel_idx = next(
            i for i, (op, _) in enumerate(op_log) if op == "cancelOrder"
        )
        place_idx = next(
            i for i, (op, _) in enumerate(op_log) if op == "placeOrder"
        )
        ack_sleeps_between = [
            (op, val) for op, val in op_log[cancel_idx + 1:place_idx]
            if op == "sleep"
        ]
        self.assertGreaterEqual(
            len(ack_sleeps_between), 1,
            f"Expected at least one ack-wait sleep between cancel and "
            f"exit; got log: {op_log!r}",
        )

    @patch("src.trading.ib_broker.IBBroker._ensure_connected")
    def test_ib_place_exit_raises_when_cancel_ack_times_out(self, mock_connect):
        """If the broker never acks the cancel within the deadline, place_exit
        MUST raise — submitting the exit anyway would race the still-open
        bracket child (the bug we're fixing)."""
        broker = IBBroker(port=4002)
        broker._ib = MagicMock()

        broker._ib.positions.return_value = [
            mock_position("AAPL", 10.0, 150.0, 50.0),
        ]

        child = _make_bracket_child_trade(101, "AAPL", "STP",
                                          status="Submitted")
        # openTrades always returns the still-Submitted child; cancel
        # ACK never arrives -> ConnectionError.
        broker._ib.openTrades.return_value = [child]
        self._mock_ib_async.MarketOrder.return_value = MagicMock()

        with self.assertRaises(ConnectionError) as cm:
            broker._cancel_bracket_children_for_ticker(
                "AAPL", ack_timeout=1.0,
            )
        self.assertIn("cancel-before-close timeout", str(cm.exception))

        # The market exit MUST NOT fire when the cancel ack fails.
        broker._ib.placeOrder.assert_not_called()

    @patch("src.trading.ib_broker.IBBroker._ensure_connected")
    def test_ib_place_exit_aborts_when_cancel_times_out(self, mock_connect):
        """End-to-end: place_exit propagates the cancel-ack-timeout from
        _cancel_bracket_children_for_ticker — exit is NOT placed."""
        broker = IBBroker(port=4002)
        broker._ib = MagicMock()

        broker._ib.positions.return_value = [
            mock_position("AAPL", 10.0, 150.0, 50.0),
        ]
        # Child stays Submitted forever
        child = _make_bracket_child_trade(101, "AAPL", "STP",
                                          status="Submitted")
        broker._ib.openTrades.return_value = [child]
        self._mock_ib_async.MarketOrder.return_value = MagicMock()

        # Patch the timeout via monkey-patching the helper invocation:
        # easiest is to call the helper directly (covered above) — the
        # full place_exit path uses the default 5s timeout and would
        # hang the test for 5s. Instead, patch the helper to raise
        # directly so we exercise the place_exit propagation.
        with patch.object(
            broker, "_cancel_bracket_children_for_ticker",
            side_effect=ConnectionError("simulated ack timeout"),
        ):
            with self.assertRaises(ConnectionError):
                broker.place_exit("AAPL", quantity=0)

        broker._ib.placeOrder.assert_not_called()


# ---------------------------------------------------------------------------
# TestIBCancelHelperIsolation — _cancel_bracket_children_for_ticker behavior
# ---------------------------------------------------------------------------
class TestIBCancelHelperIsolation(unittest.TestCase):
    """Direct tests of _cancel_bracket_children_for_ticker to pin down
    the helper's contract independent of the place_exit caller."""

    def setUp(self):
        self._mock_ib_async = _install_mock_ib_async()

    def tearDown(self):
        _remove_mock_ib_async()

    @patch("src.trading.ib_broker.IBBroker._ensure_connected")
    def test_returns_empty_list_when_no_children(self, mock_connect):
        broker = IBBroker(port=4002)
        broker._ib = MagicMock()
        broker._ib.openTrades.return_value = []

        result = broker._cancel_bracket_children_for_ticker("AAPL")
        self.assertEqual(result, [])
        broker._ib.cancelOrder.assert_not_called()

    @patch("src.trading.ib_broker.IBBroker._ensure_connected")
    def test_treats_filled_child_as_terminal(self, mock_connect):
        """If a bracket child filled before our cancel landed, openTrades
        will surface it with status='Filled' — that's a terminal state
        and counts as 'no longer racing the exit'."""
        broker = IBBroker(port=4002)
        broker._ib = MagicMock()

        child = _make_bracket_child_trade(101, "AAPL", "STP",
                                          status="Submitted")
        # ack-poll: child now shows Filled (raced the cancel).
        ack_child = _make_bracket_child_trade(101, "AAPL", "STP",
                                               status="Filled")
        broker._ib.openTrades.side_effect = [[child], [ack_child]]

        result = broker._cancel_bracket_children_for_ticker(
            "AAPL", ack_timeout=2.0,
        )
        self.assertEqual(result, ["101"])


if __name__ == "__main__":
    unittest.main()
