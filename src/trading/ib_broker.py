"""Interactive Brokers adapter via ib_async.

Called by: trading.broker_factory
Calls: ib_async (TWS API)
Owns tables: none
Config keys: live_trading.ib.*
Tests: tests/test_ib_broker.py

Requires IB Gateway or TWS running on localhost.
Default ports: 4001 (live), 4002 (paper).

WHY ib_async (not ib_insync): The original library creator Ewald de Wit passed
away in early 2024. The community forked it as ib_async under a new GitHub org.
Same API, actively maintained. ib_insync is frozen with no security patches.

WHY lazy connection: IB Gateway might not be running at startup (weekends,
daily reset at 11:45 PM ET). Lazy connect means we only connect when the
first live trade fires. If Gateway isn't available, paper trading continues.

CRITICAL: Never use time.sleep() in any method that touches self._ib.
Use self._ib.sleep() instead — it keeps the IB event loop spinning so
order fills, heartbeats, and disconnection events can be processed.
"""

import logging
from typing import Optional

from src.trading.broker_interface import (
    BrokerAdapter, BrokerAccount, BrokerOrder, BrokerPosition
)

logger = logging.getLogger(__name__)


class IBBroker(BrokerAdapter):
    """Interactive Brokers adapter using ib_async.

    WHY GTC on all orders: Our trades hold for 1-15 days. DAY orders expire
    at market close, leaving positions unprotected overnight. GTC keeps stops
    and targets active across sessions, matching Alpaca behavior.

    WHY bracketOrder() returns 3 orders: IB doesn't have a single "bracket"
    concept like Alpaca. You submit 3 linked orders in an OCA (One Cancels All)
    group: parent entry + take-profit limit sell + stop-loss stop sell.
    When one child fills, the other auto-cancels.
    """

    def __init__(self, host: str = "127.0.0.1", port: int = 4002,
                 client_id: int = 1, timeout: int = 10):
        self._host = host
        self._port = port
        self._client_id = client_id
        self._timeout = timeout
        self._ib = None  # Lazy connection

    def _ensure_connected(self):
        """Lazy connect to IB Gateway. Reconnects if disconnected."""
        if self._ib is not None and self._ib.isConnected():
            return
        try:
            from ib_async import IB
            self._ib = IB()
            self._ib.connect(
                self._host, self._port, clientId=self._client_id,
                timeout=self._timeout,
            )
            logger.info("[IB] Connected to gateway at %s:%d (client_id=%d)",
                        self._host, self._port, self._client_id)
        except Exception as e:
            logger.error("[IB] Connection failed (%s:%d): %s", self._host, self._port, e)
            self._ib = None
            raise

    def _make_contract(self, ticker: str):
        """Create an IB Stock contract for a US equity on SMART routing."""
        from ib_async import Stock
        return Stock(ticker, "SMART", "USD")

    def is_connected(self) -> bool:
        return self._ib is not None and self._ib.isConnected()

    def get_account(self) -> BrokerAccount:
        self._ensure_connected()
        # IB provides account values as a list of AccountValue objects
        account_values = self._ib.accountSummary()
        if not account_values:
            # May need to explicitly request on some Gateway versions
            self._ib.reqAccountSummary()
            self._ib.sleep(2)
            account_values = self._ib.accountSummary()
        vals = {}
        for av in account_values:
            vals[av.tag] = av.value
        return BrokerAccount(
            equity=float(vals.get("NetLiquidation", 0)),
            cash=float(vals.get("TotalCashValue", 0)),
            buying_power=float(vals.get("BuyingPower", 0)),
            portfolio_value=float(vals.get("GrossPositionValue", 0)),
            broker="ib",
        )

    def place_bracket_order(
        self,
        ticker: str,
        quantity: int,
        take_profit_price: float,
        stop_loss_price: float,
        limit_price: Optional[float] = None,
    ) -> BrokerOrder:
        """Place IB bracket order (parent + 2 child orders in OCA group)."""
        self._ensure_connected()
        contract = self._make_contract(ticker)
        self._ib.qualifyContracts(contract)

        # IB bracket = 3 linked orders: parent entry + take profit + stop loss
        bracket = self._ib.bracketOrder(
            action="BUY",
            quantity=quantity,
            limitPrice=round(limit_price, 2) if limit_price else 0,
            takeProfitPrice=round(take_profit_price, 2),
            stopLossPrice=round(stop_loss_price, 2),
        )

        # If no limit price, convert parent to market order
        if not limit_price:
            bracket[0].orderType = "MKT"
            bracket[0].lmtPrice = 0

        # Set all orders to GTC — exits must persist across sessions
        for order in bracket:
            order.tif = "GTC"

        # Place the bracket (parent + children)
        trades = []
        for order in bracket:
            trade = self._ib.placeOrder(contract, order)
            trades.append(trade)

        parent_trade = trades[0]
        # Wait briefly for fill acknowledgement (NOT time.sleep — keeps IB event loop alive)
        self._ib.sleep(2)

        return BrokerOrder(
            order_id=str(parent_trade.order.orderId),
            ticker=ticker,
            side="buy",
            quantity=quantity,
            order_type="bracket",
            status=parent_trade.orderStatus.status.lower(),
            filled_avg_price=parent_trade.orderStatus.avgFillPrice or None,
            filled_qty=int(parent_trade.orderStatus.filled) if parent_trade.orderStatus.filled else 0,
            stop_price=stop_loss_price,
            take_profit_price=take_profit_price,
            broker="ib",
        )

    def place_market_order(self, ticker: str, quantity: int,
                           side: str = "buy") -> BrokerOrder:
        self._ensure_connected()
        from ib_async import MarketOrder
        contract = self._make_contract(ticker)
        self._ib.qualifyContracts(contract)
        action = "BUY" if side == "buy" else "SELL"
        order = MarketOrder(action, quantity)
        order.tif = "GTC"
        trade = self._ib.placeOrder(contract, order)
        self._ib.sleep(2)

        return BrokerOrder(
            order_id=str(trade.order.orderId),
            ticker=ticker,
            side=side,
            quantity=quantity,
            order_type="market",
            status=trade.orderStatus.status.lower(),
            filled_avg_price=trade.orderStatus.avgFillPrice or None,
            filled_qty=int(trade.orderStatus.filled) if trade.orderStatus.filled else 0,
            broker="ib",
        )

    def place_exit(self, ticker: str, quantity: int = 0) -> BrokerOrder:
        """Close position. quantity=0 closes all shares."""
        self._ensure_connected()
        if quantity == 0:
            pos = self.get_position(ticker)
            if not pos:
                raise ValueError(f"No position in {ticker}")
            quantity = pos.quantity
        return self.place_market_order(ticker, quantity, side="sell")

    def cancel_order(self, order_id: str) -> bool:
        self._ensure_connected()
        for trade in self._ib.openTrades():
            if str(trade.order.orderId) == order_id:
                self._ib.cancelOrder(trade.order)
                self._ib.sleep(1)
                return True
        return False

    def get_order_status(self, order_id: str) -> BrokerOrder:
        self._ensure_connected()
        for trade in self._ib.trades():
            if str(trade.order.orderId) == order_id:
                return BrokerOrder(
                    order_id=order_id,
                    ticker=trade.contract.symbol,
                    side=trade.order.action.lower(),
                    quantity=int(trade.order.totalQuantity),
                    order_type=trade.order.orderType.lower(),
                    status=trade.orderStatus.status.lower(),
                    filled_avg_price=trade.orderStatus.avgFillPrice or None,
                    filled_qty=int(trade.orderStatus.filled) if trade.orderStatus.filled else 0,
                    broker="ib",
                )
        raise ValueError(f"Order {order_id} not found")

    def get_position(self, ticker: str) -> Optional[BrokerPosition]:
        self._ensure_connected()
        for pos in self._ib.positions():
            if pos.contract.symbol == ticker:
                return BrokerPosition(
                    ticker=ticker,
                    quantity=int(pos.position),
                    avg_cost=float(pos.avgCost),
                    current_price=0.0,  # Requires separate market data request
                    unrealized_pnl=float(getattr(pos, 'unrealizedPNL', 0) or 0),
                    market_value=float(pos.position * pos.avgCost),
                    broker="ib",
                )
        return None

    def get_all_positions(self) -> list[BrokerPosition]:
        self._ensure_connected()
        return [
            BrokerPosition(
                ticker=pos.contract.symbol,
                quantity=int(pos.position),
                avg_cost=float(pos.avgCost),
                current_price=0.0,
                unrealized_pnl=float(getattr(pos, 'unrealizedPNL', 0) or 0),
                market_value=float(pos.position * pos.avgCost),
                broker="ib",
            )
            for pos in self._ib.positions()
        ]

    def get_current_price(self, ticker: str) -> Optional[float]:
        """Get current price via IB market data snapshot.

        WHY snapshot mode: Streaming market data consumes IB's limited data
        lines (100 for most accounts). Snapshots are free and sufficient for
        our 15-minute polling cycle.
        """
        self._ensure_connected()
        try:
            contract = self._make_contract(ticker)
            self._ib.qualifyContracts(contract)
            ticker_data = self._ib.reqMktData(contract, snapshot=True)
            self._ib.sleep(3)  # Wait for snapshot data
            price = ticker_data.marketPrice()
            self._ib.cancelMktData(contract)
            return float(price) if price and price > 0 else None
        except Exception as e:
            logger.debug("[IB] Price fetch failed for %s: %s", ticker, e)
            return None

    def disconnect(self):
        """Gracefully disconnect from IB Gateway."""
        if self._ib and self._ib.isConnected():
            self._ib.disconnect()
            logger.info("[IB] Disconnected from gateway")
