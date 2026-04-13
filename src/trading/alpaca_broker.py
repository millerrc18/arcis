"""Alpaca broker adapter — wraps existing alpaca_adapter.py live functions.

Called by: trading.broker_factory
Calls: shadow_trading.alpaca_adapter (live trading functions only)
Owns tables: none
Tests: tests/test_broker_interface.py

WHY a wrapper instead of rewriting: alpaca_adapter.py is 600+ lines of
battle-tested code handling edge cases (fractional shares, GTC expiry,
order rejection, notional orders). The wrapper is a thin translation layer —
each method is 5-10 lines that call the existing function and normalize
the return type. Zero behavior change.

WHY keep the original alpaca_adapter.py: Paper trading continues calling it
directly. This wrapper only exists for the live trading path through the
broker factory.
"""

import logging
from typing import Optional

from src.trading.broker_interface import (
    BrokerAdapter, BrokerAccount, BrokerOrder, BrokerPosition
)

logger = logging.getLogger(__name__)


class AlpacaLiveBroker(BrokerAdapter):
    """Wraps Alpaca live trading functions into the BrokerAdapter interface."""

    def get_account(self) -> BrokerAccount:
        from src.shadow_trading.alpaca_adapter import get_live_account_info
        acct = get_live_account_info()
        return BrokerAccount(
            equity=float(acct.get("equity", 0)),
            cash=float(acct.get("cash", 0)),
            buying_power=float(acct.get("buying_power", 0)),
            portfolio_value=float(acct.get("portfolio_value", 0)),
            broker="alpaca",
        )

    def place_bracket_order(
        self,
        ticker: str,
        quantity: int,
        take_profit_price: float,
        stop_loss_price: float,
        limit_price: Optional[float] = None,
    ) -> BrokerOrder:
        # Alpaca live doesn't have a native bracket order API like paper.
        # Use market entry; stops are managed by the executor's polling loop.
        from src.shadow_trading.alpaca_adapter import place_live_entry
        order = place_live_entry(ticker, quantity)
        return BrokerOrder(
            order_id=str(order.get("order_id", "")),
            ticker=ticker,
            side="buy",
            quantity=quantity,
            order_type="bracket",
            status=str(order.get("status", "pending")),
            filled_avg_price=float(order["filled_avg_price"]) if order.get("filled_avg_price") else None,
            filled_qty=float(order.get("qty", 0) or 0),
            stop_price=stop_loss_price,
            take_profit_price=take_profit_price,
            broker="alpaca",
        )

    def place_market_order(
        self,
        ticker: str,
        quantity: int,
        side: str = "buy",
    ) -> BrokerOrder:
        if side == "buy":
            from src.shadow_trading.alpaca_adapter import place_live_entry
            order = place_live_entry(ticker, quantity)
        else:
            from src.shadow_trading.alpaca_adapter import place_live_exit
            order = place_live_exit(ticker, quantity)
        return BrokerOrder(
            order_id=str(order.get("order_id", "")),
            ticker=ticker,
            side=side,
            quantity=quantity,
            order_type="market",
            status=str(order.get("status", "pending")),
            filled_avg_price=float(order["filled_avg_price"]) if order.get("filled_avg_price") else None,
            filled_qty=float(order.get("qty", 0) or 0),
            broker="alpaca",
        )

    def place_exit(self, ticker: str, quantity: int = 0) -> BrokerOrder:
        from src.shadow_trading.alpaca_adapter import place_live_exit
        order = place_live_exit(ticker, quantity)
        return BrokerOrder(
            order_id=str(order.get("order_id", "")),
            ticker=ticker,
            side="sell",
            quantity=quantity,
            order_type="market",
            status=str(order.get("status", "pending")),
            filled_avg_price=float(order["filled_avg_price"]) if order.get("filled_avg_price") else None,
            filled_qty=float(order.get("qty", 0) or 0),
            broker="alpaca",
        )

    def cancel_order(self, order_id: str) -> bool:
        # Alpaca live doesn't expose cancel through alpaca_adapter.
        # Use the trading client directly.
        try:
            from src.shadow_trading.alpaca_adapter import _get_live_trading_client
            client = _get_live_trading_client()
            client.cancel_order_by_id(order_id)
            return True
        except Exception as e:
            logger.warning("[ALPACA-LIVE] Cancel failed for %s: %s", order_id, e)
            return False

    def get_order_status(self, order_id: str) -> BrokerOrder:
        from src.shadow_trading.alpaca_adapter import get_live_order_status
        status = get_live_order_status(order_id)
        return BrokerOrder(
            order_id=order_id,
            ticker=str(status.get("symbol", "")),
            side="unknown",
            quantity=float(status.get("filled_qty", 0) or 0),
            order_type="unknown",
            status=str(status.get("status", "unknown")),
            filled_avg_price=float(status["filled_avg_price"]) if status.get("filled_avg_price") else None,
            filled_qty=float(status.get("filled_qty", 0) or 0),
            broker="alpaca",
        )

    def get_position(self, ticker: str) -> Optional[BrokerPosition]:
        from src.shadow_trading.alpaca_adapter import get_live_positions
        for pos in get_live_positions():
            if pos.get("symbol") == ticker:
                return BrokerPosition(
                    ticker=ticker,
                    quantity=float(pos.get("qty", 0) or 0),
                    avg_cost=float(pos.get("avg_entry_price", 0)),
                    current_price=float(pos.get("current_price", 0)),
                    unrealized_pnl=float(pos.get("unrealized_pl", 0)),
                    market_value=float(pos.get("market_value", 0)),
                    broker="alpaca",
                )
        return None

    def get_all_positions(self) -> list[BrokerPosition]:
        from src.shadow_trading.alpaca_adapter import get_live_positions
        return [
            BrokerPosition(
                ticker=str(pos.get("symbol", "")),
                quantity=float(pos.get("qty", 0) or 0),
                avg_cost=float(pos.get("avg_entry_price", 0)),
                current_price=float(pos.get("current_price", 0)),
                unrealized_pnl=float(pos.get("unrealized_pl", 0)),
                market_value=float(pos.get("market_value", 0)),
                broker="alpaca",
            )
            for pos in get_live_positions()
        ]

    def get_current_price(self, ticker: str) -> Optional[float]:
        from src.shadow_trading.alpaca_adapter import get_current_price
        return get_current_price(ticker)

    def is_connected(self) -> bool:
        # Alpaca is always "connected" — it's REST-based, no persistent connection.
        return True
