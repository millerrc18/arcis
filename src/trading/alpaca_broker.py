"""Alpaca broker adapter — wraps existing alpaca_adapter.py live functions.

Called by: trading.broker_factory
Calls: shadow_trading.alpaca_adapter (live trading functions only)
Owns tables: none
Tests: tests/test_broker_interface.py, tests/trading/test_alpaca_live_verification.py

WHY a wrapper instead of rewriting: alpaca_adapter.py is 600+ lines of
battle-tested code handling edge cases (fractional shares, GTC expiry,
order rejection, notional orders). The wrapper is a thin translation layer —
each method is 5-10 lines that call the existing function and normalize
the return type.

WHY keep the original alpaca_adapter.py: Paper trading continues calling it
directly. This wrapper only exists for the live trading path through the
broker factory.

LIVE-VERIFY (Sprint 0 Wave 5c, 2026-04-26): Every submit_order callsite
on the live path now invokes verify_live_order_accepted post-submit.
Network blips during submission DO NOT mean Alpaca rejected the order
(Issue #352). Pre-Wave-5c only the executor's paper-Alpaca branch ran
verification (executor.py:864) — live paths submitted fire-and-forget,
which on a real-money account is a capital-loss vector.
"""

import logging
from typing import Optional

from src.trading.broker_interface import (
    BrokerAdapter, BrokerAccount, BrokerOrder, BrokerPosition
)

logger = logging.getLogger(__name__)


class AlpacaLiveBroker(BrokerAdapter):
    """Wraps Alpaca live trading functions into the BrokerAdapter interface."""

    def _verify_submitted(self, order_id: str, *, kind: str) -> dict | None:
        """Post-submit verification on the live trading path.

        Calls verify_live_order_accepted which polls Alpaca's order status
        endpoint with exponential backoff. Raises OrderNotAcceptedError
        (lets it propagate) when the broker reports terminal-reject.

        kind is a short label (entry/exit/bracket/cancel) used purely for
        log breadcrumbs.
        """
        if not order_id:
            # close_position can return a synthetic placeholder — nothing to verify
            return None
        from src.shadow_trading.alpaca_adapter import verify_live_order_accepted
        result = verify_live_order_accepted(order_id)
        logger.info(
            "[ALPACA-LIVE] %s order %s verified status=%s after %d attempt(s)",
            kind, order_id, result.get("status"), result.get("attempts"),
        )
        return result

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
        """Place a real Alpaca bracket order on the live account (#651).

        Pre-#651 this called place_live_entry (market order with no broker-side
        stop or take-profit) and recorded order_type='bracket' in the DB —
        the comment claimed Alpaca live didn't have a native bracket API,
        which was factually wrong. Alpaca's OrderClass.BRACKET works
        identically on paper and live; only the trading client differs.

        Now: places a real bracket via place_live_bracket (entry + take-profit
        + stop-loss in OCO semantics, all sitting on the broker). Position is
        protected even if our process is down.
        """
        from src.shadow_trading.alpaca_adapter import place_live_bracket
        order = place_live_bracket(
            ticker=ticker,
            shares=quantity,
            take_profit_price=take_profit_price,
            stop_loss_price=stop_loss_price,
            limit_price=limit_price,
        )
        order_id = str(order.get("order_id", ""))
        # LIVE-VERIFY: confirm Alpaca actually accepted the bracket parent.
        # Raises OrderNotAcceptedError on terminal-reject — propagates so
        # the caller (executor) knows not to record a live-trade row for
        # an order that never made it onto the broker.
        verified = self._verify_submitted(order_id, kind="bracket")
        status = str(order.get("status", "pending"))
        if verified and verified.get("status"):
            status = verified["status"]
        return BrokerOrder(
            order_id=order_id,
            ticker=ticker,
            side="buy",
            quantity=quantity,
            order_type="bracket",
            status=status,
            filled_avg_price=float(order["filled_avg_price"]) if order.get("filled_avg_price") else None,
            filled_qty=float(order.get("qty", 0) or 0),
            stop_price=stop_loss_price,
            take_profit_price=take_profit_price,
            child_order_ids=order.get("legs", []) or None,
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
        order_id = str(order.get("order_id", ""))
        # LIVE-VERIFY: market orders on the live path can fail at the
        # broker after the SDK reports submitted. Poll until terminal.
        verified = self._verify_submitted(order_id, kind=f"market-{side}")
        status = str(order.get("status", "pending"))
        if verified and verified.get("status"):
            status = verified["status"]
        return BrokerOrder(
            order_id=order_id,
            ticker=ticker,
            side=side,
            quantity=quantity,
            order_type="market",
            status=status,
            filled_avg_price=float(order["filled_avg_price"]) if order.get("filled_avg_price") else None,
            filled_qty=float(order.get("qty", 0) or 0),
            broker="alpaca",
        )

    def place_exit(self, ticker: str, quantity: int = 0) -> BrokerOrder:
        from src.shadow_trading.alpaca_adapter import place_live_exit
        order = place_live_exit(ticker, quantity)
        order_id = str(order.get("order_id", ""))
        # LIVE-VERIFY: exits are capital-safety critical — a fire-and-
        # forget submit means we'd never know if the broker rejected
        # the close. Skip the synthetic placeholder from close_position.
        if order_id and order_id != "close_position":
            verified = self._verify_submitted(order_id, kind="exit")
        else:
            verified = None
        status = str(order.get("status", "pending"))
        if verified and verified.get("status"):
            status = verified["status"]
        return BrokerOrder(
            order_id=order_id,
            ticker=ticker,
            side="sell",
            quantity=quantity,
            order_type="market",
            status=status,
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
        except Exception as e:
            logger.warning("[ALPACA-LIVE] Cancel failed for %s: %s", order_id, e)
            return False
        # LIVE-VERIFY: cancel may not have actually cancelled — broker
        # could race a fill. Poll for terminal status. If the order ends
        # up filled (raced our cancel) we treat the cancel as
        # unsuccessful from the caller's intent perspective.
        try:
            from src.shadow_trading.alpaca_adapter import (
                verify_live_order_accepted, OrderNotAcceptedError,
            )
            try:
                result = verify_live_order_accepted(order_id)
                # Cancel succeeded only if Alpaca shows the order in a
                # cancelled-equivalent state. "filled" / "partially_filled"
                # mean we lost the race and the order executed.
                if result.get("status") in {"canceled", "expired"}:
                    return True
                logger.warning(
                    "[ALPACA-LIVE] Cancel for %s not terminal: status=%s",
                    order_id, result.get("status"),
                )
                return False
            except OrderNotAcceptedError as exc:
                # Terminal-reject states from verify (canceled/expired/
                # rejected/suspended) all mean the order is no longer
                # active on the broker — that IS a successful cancel
                # from the user's intent perspective. "rejected" here
                # is unusual but it still means inactive.
                if exc.status in {"canceled", "expired", "rejected", "suspended"}:
                    return True
                logger.warning(
                    "[ALPACA-LIVE] Cancel verification reports unexpected "
                    "terminal state %r for %s", exc.status, order_id,
                )
                return False
        except Exception as exc:
            logger.warning(
                "[ALPACA-LIVE] Cancel verification failed for %s: %s",
                order_id, exc,
            )
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
