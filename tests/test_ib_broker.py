"""Tests for IBBroker — the Interactive Brokers adapter.

Tests must NOT import ib_async. All IB objects are mocked via unittest.mock.
IBBroker uses deferred imports (inside method bodies), so we inject a mock
ib_async module into sys.modules before each test that triggers those imports.

Pattern:
    @patch("src.trading.ib_broker.IBBroker._ensure_connected")
    def test_something(self, mock_connect):
        broker = IBBroker(port=4002)
        broker._ib = MagicMock()
        ...

For methods that do `from ib_async import X` inside the method body,
we inject a mock ib_async module via sys.modules so the import resolves.
"""
import sys
import types
import unittest
from unittest.mock import MagicMock, patch

from src.trading.ib_broker import IBBroker
from src.trading.broker_interface import BrokerOrder, BrokerPosition, BrokerAccount

from tests.conftest_ib import (
    mock_account_summary,
    mock_trade,
    mock_position,
    mock_bracket_orders,
    mock_ticker_data,
    mock_account_value,
)


def _install_mock_ib_async():
    """Inject a mock ib_async module into sys.modules.

    IBBroker uses deferred imports like `from ib_async import Stock`
    inside method bodies. This makes the import resolve without
    installing the real package. Returns the mock module so tests
    can inspect which classes were called.
    """
    mock_mod = types.ModuleType("ib_async")
    mock_mod.Stock = MagicMock(name="Stock")
    mock_mod.MarketOrder = MagicMock(name="MarketOrder")
    mock_mod.IB = MagicMock(name="IB")
    sys.modules["ib_async"] = mock_mod
    return mock_mod


def _remove_mock_ib_async():
    """Remove injected mock from sys.modules."""
    sys.modules.pop("ib_async", None)
    # Also clear the cached import from ib_broker module namespace
    import src.trading.ib_broker as mod
    for attr in ("Stock", "MarketOrder", "IB"):
        if hasattr(mod, attr):
            delattr(mod, attr)


# ---------------------------------------------------------------------------
# TestIBGetAccount
# ---------------------------------------------------------------------------
class TestIBGetAccount(unittest.TestCase):
    """Tests for IBBroker.get_account()."""

    @patch("src.trading.ib_broker.IBBroker._ensure_connected")
    def test_get_account_parses_summary(self, mock_connect):
        """accountSummary() values correctly mapped to BrokerAccount."""
        broker = IBBroker(port=4002)
        broker._ib = MagicMock()
        broker._ib.accountSummary.return_value = mock_account_summary()

        account = broker.get_account()

        assert isinstance(account, BrokerAccount)
        assert account.equity == 100000.0
        assert account.cash == 85000.0
        assert account.buying_power == 200000.0
        assert account.portfolio_value == 15000.0
        assert account.broker == "ib"

    @patch("src.trading.ib_broker.IBBroker._ensure_connected")
    def test_get_account_empty_falls_back(self, mock_connect):
        """Empty accountSummary() triggers reqAccountSummary + sleep + retry."""
        broker = IBBroker(port=4002)
        broker._ib = MagicMock()
        # First call returns empty, second returns data
        broker._ib.accountSummary.side_effect = [[], mock_account_summary()]

        account = broker.get_account()

        broker._ib.reqAccountSummary.assert_called_once()
        broker._ib.sleep.assert_called_once_with(2)
        assert account.equity == 100000.0

    @patch("src.trading.ib_broker.IBBroker._ensure_connected")
    def test_get_account_values_cast_from_string(self, mock_connect):
        """IB returns string values like '99999.99' — must be float, not str."""
        broker = IBBroker(port=4002)
        broker._ib = MagicMock()
        broker._ib.accountSummary.return_value = [
            mock_account_value("NetLiquidation", "99999.99"),
            mock_account_value("TotalCashValue", "50000.50"),
            mock_account_value("BuyingPower", "150000.75"),
            mock_account_value("GrossPositionValue", "49999.49"),
        ]

        account = broker.get_account()

        assert isinstance(account.equity, float)
        assert account.equity == 99999.99
        assert isinstance(account.cash, float)
        assert account.cash == 50000.50


# ---------------------------------------------------------------------------
# TestIBPlaceBracketOrder
# ---------------------------------------------------------------------------
class TestIBPlaceBracketOrder(unittest.TestCase):
    """Tests for IBBroker.place_bracket_order().

    place_bracket_order calls _make_contract which does
    `from ib_async import Stock`. We inject a mock ib_async module
    so the deferred import resolves.
    """

    def setUp(self):
        self._mock_ib_async = _install_mock_ib_async()

    def tearDown(self):
        _remove_mock_ib_async()

    @patch("src.trading.ib_broker.IBBroker._ensure_connected")
    def test_bracket_creates_three_orders(self, mock_connect):
        """bracketOrder() called, placeOrder called 3x, returns bracket type."""
        broker = IBBroker(port=4002)
        broker._ib = MagicMock()
        bracket = mock_bracket_orders()
        broker._ib.bracketOrder.return_value = bracket

        parent_trade = mock_trade(order_id=100, status="PreSubmitted")
        broker._ib.placeOrder.return_value = parent_trade

        result = broker.place_bracket_order(
            ticker="AAPL", quantity=10,
            take_profit_price=160.0, stop_loss_price=140.0,
            limit_price=150.0,
        )

        broker._ib.bracketOrder.assert_called_once()
        assert broker._ib.placeOrder.call_count == 3
        assert result.order_type == "bracket"
        assert isinstance(result, BrokerOrder)

    @patch("src.trading.ib_broker.IBBroker._ensure_connected")
    def test_bracket_market_when_no_limit(self, mock_connect):
        """limit_price=None converts parent to MKT with lmtPrice=0."""
        broker = IBBroker(port=4002)
        broker._ib = MagicMock()
        bracket = mock_bracket_orders()
        broker._ib.bracketOrder.return_value = bracket

        parent_trade = mock_trade(order_id=101, status="PreSubmitted")
        broker._ib.placeOrder.return_value = parent_trade

        broker.place_bracket_order(
            ticker="AAPL", quantity=10,
            take_profit_price=160.0, stop_loss_price=140.0,
            limit_price=None,
        )

        assert bracket[0].orderType == "MKT"
        assert bracket[0].lmtPrice == 0

    @patch("src.trading.ib_broker.IBBroker._ensure_connected")
    def test_bracket_all_gtc(self, mock_connect):
        """All 3 bracket orders must have tif='GTC' after method runs."""
        broker = IBBroker(port=4002)
        broker._ib = MagicMock()
        bracket = mock_bracket_orders()
        # Verify they start as DAY
        assert all(o.tif == "DAY" for o in bracket)

        broker._ib.bracketOrder.return_value = bracket
        parent_trade = mock_trade(order_id=102, status="PreSubmitted")
        broker._ib.placeOrder.return_value = parent_trade

        broker.place_bracket_order(
            ticker="AAPL", quantity=10,
            take_profit_price=160.0, stop_loss_price=140.0,
            limit_price=150.0,
        )

        for order in bracket:
            assert order.tif == "GTC", f"Order tif should be GTC, got {order.tif}"

    @patch("src.trading.ib_broker.IBBroker._ensure_connected")
    def test_bracket_connection_lost_raises(self, mock_connect):
        """placeOrder raising ConnectionError must propagate."""
        broker = IBBroker(port=4002)
        broker._ib = MagicMock()
        bracket = mock_bracket_orders()
        broker._ib.bracketOrder.return_value = bracket
        broker._ib.placeOrder.side_effect = ConnectionError("Gateway down")

        with self.assertRaises(ConnectionError):
            broker.place_bracket_order(
                ticker="AAPL", quantity=10,
                take_profit_price=160.0, stop_loss_price=140.0,
                limit_price=150.0,
            )


    @patch("src.trading.ib_broker.IBBroker._ensure_connected")
    def test_bracket_order_returns_child_ids(self, mock_connect):
        """place_bracket_order must return child order IDs for bracket monitoring."""
        broker = IBBroker(port=4002)
        broker._ib = MagicMock()
        bracket = mock_bracket_orders()
        broker._ib.bracketOrder.return_value = bracket
        # Mock 3 trades with order IDs 100, 101, 102
        trades = [mock_trade(order_id=100 + i) for i in range(3)]
        broker._ib.placeOrder.side_effect = trades
        broker._ib.qualifyContracts = MagicMock()

        result = broker.place_bracket_order("AAPL", 10, 160.0, 140.0, limit_price=150.0)

        assert result.child_order_ids == ["101", "102"]
        assert result.order_id == "100"


# ---------------------------------------------------------------------------
# TestIBPlaceMarketOrder
# ---------------------------------------------------------------------------
class TestIBPlaceMarketOrder(unittest.TestCase):
    """Tests for IBBroker.place_market_order().

    place_market_order does `from ib_async import MarketOrder` and calls
    _make_contract which does `from ib_async import Stock`. We inject a
    mock ib_async module so both deferred imports resolve.
    """

    def setUp(self):
        self._mock_ib_async = _install_mock_ib_async()

    def tearDown(self):
        _remove_mock_ib_async()

    @patch("src.trading.ib_broker.IBBroker._ensure_connected")
    def test_market_buy(self, mock_connect):
        """MarketOrder created with BUY, tif=GTC, result side='buy'."""
        broker = IBBroker(port=4002)
        broker._ib = MagicMock()

        mock_order = MagicMock()
        self._mock_ib_async.MarketOrder.return_value = mock_order

        trade = mock_trade(order_id=200, action="BUY", status="Filled",
                           avg_price=155.0, filled=10)
        broker._ib.placeOrder.return_value = trade

        result = broker.place_market_order("AAPL", 10, side="buy")

        self._mock_ib_async.MarketOrder.assert_called_once_with("BUY", 10)
        assert mock_order.tif == "GTC"
        assert result.side == "buy"
        assert isinstance(result, BrokerOrder)

    @patch("src.trading.ib_broker.IBBroker._ensure_connected")
    def test_market_sell(self, mock_connect):
        """MarketOrder with SELL action, result side='sell'."""
        broker = IBBroker(port=4002)
        broker._ib = MagicMock()

        mock_order = MagicMock()
        self._mock_ib_async.MarketOrder.return_value = mock_order

        trade = mock_trade(order_id=201, action="SELL", status="Filled",
                           avg_price=155.0, filled=10)
        broker._ib.placeOrder.return_value = trade

        result = broker.place_market_order("AAPL", 10, side="sell")

        self._mock_ib_async.MarketOrder.assert_called_once_with("SELL", 10)
        assert result.side == "sell"


# ---------------------------------------------------------------------------
# TestIBPlaceExit
# ---------------------------------------------------------------------------
class TestIBPlaceExit(unittest.TestCase):
    """Tests for IBBroker.place_exit().

    place_exit calls place_market_order (which imports MarketOrder) and
    get_position (no ib_async import), plus _make_contract (imports Stock).
    """

    def setUp(self):
        self._mock_ib_async = _install_mock_ib_async()

    def tearDown(self):
        _remove_mock_ib_async()

    @patch("src.trading.ib_broker.IBBroker._ensure_connected")
    def test_exit_closes_full_position(self, mock_connect):
        """quantity=0 looks up position size and sells all shares."""
        broker = IBBroker(port=4002)
        broker._ib = MagicMock()

        # Mock get_position to return 50 shares
        broker._ib.positions.return_value = [mock_position("AAPL", 50.0)]

        mock_order = MagicMock()
        self._mock_ib_async.MarketOrder.return_value = mock_order

        trade = mock_trade(order_id=300, action="SELL", status="Filled",
                           avg_price=155.0, filled=50, quantity=50)
        broker._ib.placeOrder.return_value = trade

        result = broker.place_exit("AAPL", quantity=0)

        assert result.side == "sell"
        assert result.quantity == 50

    @patch("src.trading.ib_broker.IBBroker._ensure_connected")
    def test_exit_no_position_raises(self, mock_connect):
        """quantity=0 with no position raises ValueError."""
        broker = IBBroker(port=4002)
        broker._ib = MagicMock()
        broker._ib.positions.return_value = []  # No positions

        with self.assertRaises(ValueError):
            broker.place_exit("AAPL", quantity=0)


# ---------------------------------------------------------------------------
# TestIBCancelOrder
# ---------------------------------------------------------------------------
class TestIBCancelOrder(unittest.TestCase):
    """Tests for IBBroker.cancel_order()."""

    @patch("src.trading.ib_broker.IBBroker._ensure_connected")
    def test_cancel_finds_and_cancels(self, mock_connect):
        """Matching order_id in openTrades() -> cancelOrder called, True."""
        broker = IBBroker(port=4002)
        broker._ib = MagicMock()

        trade = mock_trade(order_id=42, status="Submitted")
        broker._ib.openTrades.return_value = [trade]

        result = broker.cancel_order("42")

        assert result is True
        broker._ib.cancelOrder.assert_called_once_with(trade.order)

    @patch("src.trading.ib_broker.IBBroker._ensure_connected")
    def test_cancel_not_found_returns_false(self, mock_connect):
        """No matching order -> returns False, cancelOrder NOT called."""
        broker = IBBroker(port=4002)
        broker._ib = MagicMock()
        broker._ib.openTrades.return_value = [
            mock_trade(order_id=99, status="Submitted"),
        ]

        result = broker.cancel_order("42")

        assert result is False
        broker._ib.cancelOrder.assert_not_called()


# ---------------------------------------------------------------------------
# TestIBGetOrderStatus
# ---------------------------------------------------------------------------
class TestIBGetOrderStatus(unittest.TestCase):
    """Tests for IBBroker.get_order_status()."""

    @patch("src.trading.ib_broker.IBBroker._ensure_connected")
    def test_status_found(self, mock_connect):
        """order_id=42 found in trades(), BrokerOrder fields correct."""
        broker = IBBroker(port=4002)
        broker._ib = MagicMock()

        trade = mock_trade(order_id=42, ticker="MSFT", action="BUY",
                           status="Filled", avg_price=310.0, filled=5,
                           order_type="MKT", quantity=5)
        broker._ib.trades.return_value = [trade]

        result = broker.get_order_status("42")

        assert isinstance(result, BrokerOrder)
        assert result.order_id == "42"
        assert result.ticker == "MSFT"
        assert result.side == "buy"
        assert result.quantity == 5
        assert result.order_type == "mkt"
        assert result.status == "filled"
        assert result.filled_avg_price == 310.0
        assert result.filled_qty == 5
        assert result.broker == "ib"

    @patch("src.trading.ib_broker.IBBroker._ensure_connected")
    def test_status_not_found_raises(self, mock_connect):
        """Empty trades() raises ValueError."""
        broker = IBBroker(port=4002)
        broker._ib = MagicMock()
        broker._ib.trades.return_value = []

        with self.assertRaises(ValueError):
            broker.get_order_status("42")


# ---------------------------------------------------------------------------
# TestIBGetPosition
# ---------------------------------------------------------------------------
class TestIBGetPosition(unittest.TestCase):
    """Tests for IBBroker.get_position()."""

    @patch("src.trading.ib_broker.IBBroker._ensure_connected")
    def test_position_found(self, mock_connect):
        """AAPL in positions(), BrokerPosition correct, broker='ib'."""
        broker = IBBroker(port=4002)
        broker._ib = MagicMock()
        broker._ib.positions.return_value = [
            mock_position("AAPL", 100.0, 150.0, 500.0),
        ]

        result = broker.get_position("AAPL")

        assert isinstance(result, BrokerPosition)
        assert result.ticker == "AAPL"
        assert result.quantity == 100
        assert result.avg_cost == 150.0
        assert result.unrealized_pnl == 500.0
        assert result.broker == "ib"

    @patch("src.trading.ib_broker.IBBroker._ensure_connected")
    def test_position_not_found(self, mock_connect):
        """MSFT not in positions() -> returns None."""
        broker = IBBroker(port=4002)
        broker._ib = MagicMock()
        broker._ib.positions.return_value = [
            mock_position("AAPL", 100.0, 150.0, 500.0),
        ]

        result = broker.get_position("MSFT")

        assert result is None

    @patch("src.trading.ib_broker.IBBroker._ensure_connected")
    def test_position_quantity_cast_to_int(self, mock_connect):
        """IB position=100.0 (float) -> quantity=100 (int)."""
        broker = IBBroker(port=4002)
        broker._ib = MagicMock()
        broker._ib.positions.return_value = [
            mock_position("AAPL", 100.0, 150.0, 500.0),
        ]

        result = broker.get_position("AAPL")

        assert isinstance(result.quantity, int)
        assert result.quantity == 100


# ---------------------------------------------------------------------------
# TestIBGetAllPositions
# ---------------------------------------------------------------------------
class TestIBGetAllPositions(unittest.TestCase):
    """Tests for IBBroker.get_all_positions()."""

    @patch("src.trading.ib_broker.IBBroker._ensure_connected")
    def test_returns_list(self, mock_connect):
        """3 positions (AAPL, MSFT, GOOG), verify len==3, all broker='ib'."""
        broker = IBBroker(port=4002)
        broker._ib = MagicMock()
        broker._ib.positions.return_value = [
            mock_position("AAPL", 100.0, 150.0, 500.0),
            mock_position("MSFT", 50.0, 300.0, 200.0),
            mock_position("GOOG", 25.0, 2800.0, 1000.0),
        ]

        result = broker.get_all_positions()

        assert len(result) == 3
        assert all(isinstance(p, BrokerPosition) for p in result)
        assert all(p.broker == "ib" for p in result)
        tickers = [p.ticker for p in result]
        assert "AAPL" in tickers
        assert "MSFT" in tickers
        assert "GOOG" in tickers


# ---------------------------------------------------------------------------
# TestIBGetCurrentPrice
# ---------------------------------------------------------------------------
class TestIBGetCurrentPrice(unittest.TestCase):
    """Tests for IBBroker.get_current_price().

    get_current_price calls _make_contract which does
    `from ib_async import Stock`.
    """

    def setUp(self):
        self._mock_ib_async = _install_mock_ib_async()

    def tearDown(self):
        _remove_mock_ib_async()

    @patch("src.trading.ib_broker.IBBroker._ensure_connected")
    def test_price_snapshot(self, mock_connect):
        """Verify call sequence: qualify -> reqMktData -> sleep -> price -> cancel."""
        broker = IBBroker(port=4002)
        broker._ib = MagicMock()

        ticker_data = mock_ticker_data(155.0)
        broker._ib.reqMktData.return_value = ticker_data

        result = broker.get_current_price("AAPL")

        broker._ib.qualifyContracts.assert_called_once()
        broker._ib.reqMktData.assert_called_once()
        # Verify snapshot=True in the call
        _, kwargs = broker._ib.reqMktData.call_args
        assert kwargs.get("snapshot") is True
        broker._ib.sleep.assert_called_once_with(3)
        ticker_data.marketPrice.assert_called_once()
        broker._ib.cancelMktData.assert_called_once()
        assert result == 155.0

    @patch("src.trading.ib_broker.IBBroker._ensure_connected")
    def test_price_timeout_returns_none(self, mock_connect):
        """reqMktData raising Exception -> returns None."""
        broker = IBBroker(port=4002)
        broker._ib = MagicMock()
        broker._ib.reqMktData.side_effect = Exception("Timeout")

        result = broker.get_current_price("AAPL")

        assert result is None

    @patch("src.trading.ib_broker.IBBroker._ensure_connected")
    def test_price_zero_returns_none(self, mock_connect):
        """marketPrice() returns 0 -> returns None."""
        broker = IBBroker(port=4002)
        broker._ib = MagicMock()

        ticker_data = mock_ticker_data(0)
        broker._ib.reqMktData.return_value = ticker_data

        result = broker.get_current_price("AAPL")

        assert result is None


# ---------------------------------------------------------------------------
# TestIBConnection
# ---------------------------------------------------------------------------
class TestIBConnection(unittest.TestCase):
    """Tests for IBBroker connection management.

    _ensure_connected does `from ib_async import IB` when reconnecting.
    """

    def setUp(self):
        self._mock_ib_async = _install_mock_ib_async()

    def tearDown(self):
        _remove_mock_ib_async()

    def test_reconnects_when_disconnected(self):
        """isConnected()=False -> new IB() created, connect() called."""
        broker = IBBroker(port=4002)
        broker._ib = MagicMock()
        broker._ib.isConnected.return_value = False

        mock_ib_instance = MagicMock()
        self._mock_ib_async.IB.return_value = mock_ib_instance

        broker._ensure_connected()

        self._mock_ib_async.IB.assert_called_once()
        mock_ib_instance.connect.assert_called_once_with(
            "127.0.0.1", 4002, clientId=1, timeout=10,
        )
        assert broker._ib is mock_ib_instance

    def test_disconnect_safe_when_not_connected(self):
        """_ib=None, disconnect() doesn't crash."""
        broker = IBBroker(port=4002)
        broker._ib = None

        # Should not raise
        broker.disconnect()


if __name__ == "__main__":
    unittest.main()
