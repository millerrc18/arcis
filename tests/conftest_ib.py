"""Mock factories for ib_async objects used in IBBroker tests.

These create MagicMock objects with the exact attribute structure that
ib_async returns from its API calls. Getting these wrong means tests
pass but don't validate real IB behavior.

Reference: ib_async source (Trade, OrderStatus, Position, AccountValue, Stock)
Cross-checked against src/trading/ib_broker.py attribute access patterns.
"""
from unittest.mock import MagicMock


def mock_account_value(tag, value):
    """Create a mock IB AccountValue.

    IB returns ALL account values as strings — even numeric ones like
    NetLiquidation="100000.00". IBBroker must float() cast them.
    """
    av = MagicMock()
    av.tag = tag
    av.value = str(value)  # IB always returns strings
    return av


def mock_trade(order_id=1, ticker="AAPL", status="Filled",
               avg_price=150.0, filled=10, action="BUY",
               order_type="MKT", quantity=10):
    """Create a mock IB Trade with nested order/orderStatus/contract."""
    trade = MagicMock()
    trade.order.orderId = order_id
    trade.order.action = action
    trade.order.orderType = order_type
    trade.order.totalQuantity = quantity
    trade.contract.symbol = ticker
    trade.orderStatus.status = status
    trade.orderStatus.avgFillPrice = avg_price
    trade.orderStatus.filled = filled
    return trade


def mock_position(ticker="AAPL", quantity=100.0, avg_cost=150.0, pnl=500.0):
    """Create a mock IB Position.

    IB returns position quantity as FLOAT (e.g. 100.0 not 100).
    IBBroker must int() cast it for the normalized BrokerPosition.
    """
    pos = MagicMock()
    pos.contract.symbol = ticker
    pos.position = quantity  # float in IB
    pos.avgCost = avg_cost
    pos.unrealizedPNL = pnl
    return pos


def mock_bracket_orders():
    """Create 3 mock Order objects mimicking IB bracketOrder() output.

    IB's bracketOrder() returns [parent, take_profit, stop_loss].
    Default tif is "DAY" — IBBroker must override all three to "GTC".
    """
    parent = MagicMock()
    parent.orderType = "LMT"
    parent.lmtPrice = 150.0
    parent.tif = "DAY"

    take_profit = MagicMock()
    take_profit.orderType = "LMT"
    take_profit.tif = "DAY"

    stop_loss = MagicMock()
    stop_loss.orderType = "STP"
    stop_loss.tif = "DAY"

    return [parent, take_profit, stop_loss]


def mock_ticker_data(price=155.0):
    """Create a mock IB ticker with marketPrice() method."""
    ticker = MagicMock()
    ticker.marketPrice.return_value = price
    return ticker


def mock_account_summary():
    """Create a list of mock AccountValue objects for a typical account.

    Mirrors the 4 tags IBBroker reads from accountSummary():
    NetLiquidation, TotalCashValue, BuyingPower, GrossPositionValue.
    """
    return [
        mock_account_value("NetLiquidation", "100000"),
        mock_account_value("TotalCashValue", "85000"),
        mock_account_value("BuyingPower", "200000"),
        mock_account_value("GrossPositionValue", "15000"),
    ]
