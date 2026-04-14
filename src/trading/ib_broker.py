"""Interactive Brokers adapter via ib_async — production hardened.

Called by: trading.broker_factory
Calls: ib_async (TWS API)
Owns tables: none
Config keys: live_trading.ib.*
Tests: tests/test_ib_broker.py

Requires IB Gateway or TWS running on localhost.
Default ports: 4001 (live), 4002 (paper).

Production hardening (2026-04): exponential-backoff reconnect, bracket
integrity verification, outsideRth on all orders, ocaType=3 on bracket
children, permId cross-session tracking, IB_STATUS_MAP normalization,
partial fill detection, structured IB error code classification.

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

# Maps raw IB statuses to our canonical set (pending/filled/cancelled/rejected).
IB_STATUS_MAP = {
    "presubmitted": "pending",
    "submitted": "pending",
    "filled": "filled",
    "cancelled": "cancelled",
    "inactive": "rejected",
    "pendingsubmit": "pending",
    "pendingcancel": "pending",
    "apicancelled": "cancelled",
}

_IB_ERROR_CODES = {
    110: "price_out_of_range",
    135: "unknown_order_id",
    200: "unknown_contract",
    201: "order_rejected",
    202: "order_cancelled",
    10147: "order_not_active",
}


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
        """Connect to IB Gateway with exponential backoff. Reconnects if disconnected."""
        if self._ib is not None and self._ib.isConnected():
            return
        # Fail fast on missing dependency — ImportError won't resolve by
        # retrying, so the 1+2+4s backoff ladder is wasted (and produces
        # 3 identical "No module named 'ib_async'" warnings per cycle).
        try:
            from ib_async import IB
        except ImportError as e:
            logger.warning("[IB] ib_async not installed — IB broker unavailable: %s", e)
            raise
        import time as _time
        for attempt in range(3):
            try:
                self._ib = IB()
                self._ib.connect(
                    self._host, self._port, clientId=self._client_id,
                    timeout=self._timeout,
                )
                logger.info("[IB] Connected to gateway at %s:%d (client_id=%d)",
                            self._host, self._port, self._client_id)
                return
            except Exception as e:
                delay = 2 ** attempt  # 1, 2, 4
                logger.warning("[IB] Connection attempt %d/3 failed: %s (retry in %ds)",
                              attempt + 1, e, delay)
                self._ib = None
                if attempt < 2:
                    _time.sleep(delay)
        raise ConnectionError(
            f"IB Gateway unreachable after 3 attempts ({self._host}:{self._port})"
        )

    def _make_contract(self, ticker: str):
        """Create an IB Stock contract for a US equity on SMART routing."""
        from ib_async import Stock
        return Stock(ticker, "SMART", "USD")

    def is_connected(self) -> bool:
        return self._ib is not None and self._ib.isConnected()

    def _verify_bracket_integrity(self) -> list[str]:
        """After reconnect, verify all positions have active stop orders.
        Returns list of tickers with missing protection."""
        unprotected = []
        positions = self._ib.positions()
        open_trades = self._ib.openTrades()
        # Build set of tickers with active stop orders
        protected_tickers = set()
        for trade in open_trades:
            if (trade.order.orderType in ("STP", "STP LMT") and
                    trade.order.action == "SELL" and
                    trade.orderStatus.status in ("PreSubmitted", "Submitted")):
                protected_tickers.add(trade.contract.symbol)
        for pos in positions:
            if pos.position > 0 and pos.contract.symbol not in protected_tickers:
                unprotected.append(pos.contract.symbol)
                logger.warning("[IB] UNPROTECTED POSITION: %s (%d shares, no active stop)",
                              pos.contract.symbol, int(pos.position))
        return unprotected

    def _handle_ib_error(self, code: int, msg: str, ticker: str = "") -> None:
        """Log and classify IB error codes."""
        classification = _IB_ERROR_CODES.get(code, "unknown")
        if code in (200, 201):
            logger.error("[IB] %s error for %s (code %d): %s",
                        classification, ticker, code, msg)
        else:
            logger.warning("[IB] %s for %s (code %d): %s",
                          classification, ticker, code, msg)

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
        # outsideRth=True — protective orders must execute 24/7
        for order in bracket:
            order.tif = "GTC"
            order.outsideRth = True  # Execute outside regular trading hours

        # Block/overfill protection on bracket children
        for child in bracket[1:]:
            child.ocaType = 3

        # Place the bracket (parent + children)
        trades = []
        for order in bracket:
            trade = self._ib.placeOrder(contract, order)
            trades.append(trade)

        parent_trade = trades[0]
        # Wait briefly for fill acknowledgement (NOT time.sleep — keeps IB event loop alive)
        self._ib.sleep(2)

        # Check for partial fills
        filled = int(parent_trade.orderStatus.filled or 0)
        if 0 < filled < quantity:
            logger.warning("[IB] Partial fill for %s: %d/%d shares filled",
                          ticker, filled, quantity)

        # Capture child order IDs and permIds for bracket health monitoring
        child_ids = [str(t.order.orderId) for t in trades[1:]] if len(trades) > 1 else None
        child_perm_ids = [str(getattr(t.order, 'permId', '') or '') for t in trades[1:]] if len(trades) > 1 else None

        return BrokerOrder(
            order_id=str(parent_trade.order.orderId),
            ticker=ticker,
            side="buy",
            quantity=quantity,
            order_type="bracket",
            status=IB_STATUS_MAP.get(parent_trade.orderStatus.status.lower(),
                                     parent_trade.orderStatus.status.lower()),
            filled_avg_price=parent_trade.orderStatus.avgFillPrice or None,
            filled_qty=int(parent_trade.orderStatus.filled) if parent_trade.orderStatus.filled else 0,
            stop_price=stop_loss_price,
            take_profit_price=take_profit_price,
            child_order_ids=child_ids,
            broker="ib",
            perm_id=str(getattr(parent_trade.order, 'permId', '') or ''),
        )

    def place_market_order(self, ticker: str, quantity: int,
                           side: str = "buy",
                           outside_rth: bool = True) -> BrokerOrder:
        self._ensure_connected()
        from ib_async import MarketOrder
        contract = self._make_contract(ticker)
        self._ib.qualifyContracts(contract)
        action = "BUY" if side == "buy" else "SELL"
        order = MarketOrder(action, quantity)
        order.tif = "GTC"
        order.outsideRth = outside_rth
        trade = self._ib.placeOrder(contract, order)
        self._ib.sleep(2)

        # Check for partial fills
        filled = int(trade.orderStatus.filled or 0)
        if 0 < filled < quantity:
            logger.warning("[IB] Partial fill for %s: %d/%d shares filled",
                          ticker, filled, quantity)

        return BrokerOrder(
            order_id=str(trade.order.orderId),
            ticker=ticker,
            side=side,
            quantity=quantity,
            order_type="market",
            status=IB_STATUS_MAP.get(trade.orderStatus.status.lower(),
                                     trade.orderStatus.status.lower()),
            filled_avg_price=trade.orderStatus.avgFillPrice or None,
            filled_qty=int(trade.orderStatus.filled) if trade.orderStatus.filled else 0,
            broker="ib",
            perm_id=str(getattr(trade.order, 'permId', '') or ''),
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
                    status=IB_STATUS_MAP.get(trade.orderStatus.status.lower(),
                                             trade.orderStatus.status.lower()),
                    filled_avg_price=trade.orderStatus.avgFillPrice or None,
                    filled_qty=int(trade.orderStatus.filled) if trade.orderStatus.filled else 0,
                    broker="ib",
                    perm_id=str(getattr(trade.order, 'permId', '') or ''),
                )
        raise ValueError(f"Order {order_id} not found")

    def get_position(self, ticker: str) -> Optional[BrokerPosition]:
        """Get position with live price. Task 8: fetch current_price via
        market data snapshot instead of hardcoding 0.0."""
        self._ensure_connected()
        for pos in self._ib.positions():
            if pos.contract.symbol == ticker:
                current = self.get_current_price(ticker) or 0.0
                qty = float(pos.position)
                avg = float(pos.avgCost)
                return BrokerPosition(
                    ticker=ticker,
                    quantity=int(pos.position),
                    avg_cost=avg,
                    current_price=current,
                    unrealized_pnl=qty * (current - avg) if current else 0.0,
                    market_value=qty * current if current else qty * avg,
                    broker="ib",
                )
        return None

    def get_all_positions(self) -> list[BrokerPosition]:
        """Get all positions. Task 8: fetch prices for small portfolios (<=10),
        skip for larger to avoid hitting IB's 100 market data line limit."""
        self._ensure_connected()
        positions = self._ib.positions()
        result = []
        for pos in positions:
            ticker = pos.contract.symbol
            qty = float(pos.position)
            avg = float(pos.avgCost)
            current = 0.0
            if len(positions) <= 10:
                current = self.get_current_price(ticker) or 0.0
            result.append(BrokerPosition(
                ticker=ticker,
                quantity=int(pos.position),
                avg_cost=avg,
                current_price=current,
                unrealized_pnl=qty * (current - avg) if current else 0.0,
                market_value=qty * current if current else qty * avg,
                broker="ib",
            ))
        return result

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
