"""Paper-trading helpers extracted from alpaca_adapter.py (Sprint-0.C/C.2).

Called by: src.shadow_trading.alpaca_adapter
Calls: src.shadow_trading.alpaca_adapter (for _get_trading_client, _check_enabled, _serialize_order)
Owns tables: none
Config keys: alpaca, api_key, api_secret, base_url, shadow_trading, enabled, max_positions
Tests: tests/shadow_trading/test_alpaca_adapter_split.py, tests/test_bracket_orders.py
"""
import logging
import re

logger = logging.getLogger(__name__)

_TERMINAL_STATE_RE = re.compile(r"already in \\?\"?([a-z_]+)\\?\"? state", re.IGNORECASE)


def place_paper_entry(
    ticker: str, shares: int, order_type: str = "market", desk: str = "swing"
) -> dict:
    """Place a paper buy order. Returns order details dict."""
    from src.shadow_trading.alpaca_adapter import _check_enabled, _get_trading_client
    _check_enabled()

    logger.info("[SHADOW] Placing paper BUY: %d shares of %s", shares, ticker)

    client = _get_trading_client(desk=desk)

    from alpaca.trading.requests import MarketOrderRequest
    from alpaca.trading.enums import OrderSide, TimeInForce

    if order_type == "market":
        request = MarketOrderRequest(
            symbol=ticker,
            qty=shares,
            side=OrderSide.BUY,
            time_in_force=TimeInForce.DAY,
        )
    else:
        from src.shadow_trading.alpaca_adapter import PaperTradingError
        raise PaperTradingError(f"Unsupported order type: {order_type}")

    order = client.submit_order(request)

    return {
        "order_id": str(order.id),
        "symbol": str(order.symbol),
        "qty": float(order.qty) if order.qty else shares,
        "side": str(order.side),
        "type": str(order.type),
        "status": str(order.status),
        "filled_avg_price": float(order.filled_avg_price) if order.filled_avg_price else None,
        "filled_at": str(order.filled_at) if order.filled_at else None,
        "created_at": str(order.created_at) if order.created_at else None,
    }


def place_paper_exit(
    ticker: str, shares: int, order_type: str = "market", desk: str = "swing"
) -> dict:
    """Place a paper sell order. Returns order details dict."""
    from src.shadow_trading.alpaca_adapter import _check_enabled, _get_trading_client
    _check_enabled()

    logger.info("[SHADOW] Placing paper SELL: %d shares of %s", shares, ticker)

    client = _get_trading_client(desk=desk)

    from alpaca.trading.requests import MarketOrderRequest
    from alpaca.trading.enums import OrderSide, TimeInForce

    request = MarketOrderRequest(
        symbol=ticker,
        qty=shares,
        side=OrderSide.SELL,
        time_in_force=TimeInForce.DAY,
    )

    order = client.submit_order(request)

    return {
        "order_id": str(order.id),
        "symbol": str(order.symbol),
        "qty": float(order.qty) if order.qty else shares,
        "side": str(order.side),
        "type": str(order.type),
        "status": str(order.status),
        "filled_avg_price": float(order.filled_avg_price) if order.filled_avg_price else None,
        "filled_at": str(order.filled_at) if order.filled_at else None,
    }


def place_bracket_order(
    ticker: str,
    shares: int,
    take_profit_price: float,
    stop_loss_price: float,
    limit_price: float | None = None,
    desk: str = "swing",
) -> dict:
    """Place a bracket order: entry + take-profit + stop-loss as one atomic order.

    Strategy Decision #18: Mechanical bracket exits with 2.0 ATR multiplier.
    When the entry fills, Alpaca automatically places:
    - A limit sell at take_profit_price (target_1 from the packet)
    - A stop sell at stop_loss_price (from packet stop_invalidation)
    When one exit triggers, the other auto-cancels (OCO semantics).

    WHY GTC (Good Till Cancel): Bracket exits must persist across trading
    sessions. DAY orders would expire at close, leaving positions unprotected
    overnight. GTC keeps the stop-loss active until it fills or is canceled.

    WHY limit_price option: For less-liquid names, a limit entry prevents
    paying an unreasonable spread on market open.
    """
    from src.shadow_trading.alpaca_adapter import _check_enabled, _get_trading_client
    _check_enabled()

    # Fix for #263: removed duplicate log line
    logger.info("[SHADOW] Placing BRACKET order: %d shares of %s "
                "(TP=$%.2f, SL=$%.2f)", shares, ticker,
                take_profit_price, stop_loss_price)

    client = _get_trading_client(desk=desk)

    from alpaca.trading.requests import MarketOrderRequest, LimitOrderRequest
    from alpaca.trading.enums import OrderSide, TimeInForce, OrderClass

    if limit_price:
        request = LimitOrderRequest(
            symbol=ticker, qty=shares, side=OrderSide.BUY,
            time_in_force=TimeInForce.GTC, order_class=OrderClass.BRACKET,
            limit_price=round(limit_price, 2),
            take_profit={"limit_price": round(take_profit_price, 2)},
            stop_loss={"stop_price": round(stop_loss_price, 2)},
        )
    else:
        request = MarketOrderRequest(
            symbol=ticker, qty=shares, side=OrderSide.BUY,
            time_in_force=TimeInForce.GTC, order_class=OrderClass.BRACKET,
            take_profit={"limit_price": round(take_profit_price, 2)},
            stop_loss={"stop_price": round(stop_loss_price, 2)},
        )

    order = client.submit_order(request)

    return {
        "order_id": str(order.id),
        "symbol": str(order.symbol),
        "qty": float(order.qty) if order.qty else shares,
        "side": str(order.side),
        "type": str(order.type),
        "order_class": "bracket",
        "status": str(order.status),
        "filled_avg_price": float(order.filled_avg_price) if order.filled_avg_price else None,
        "legs": [str(leg.id) for leg in order.legs] if order.legs else [],
    }


def get_position(ticker: str, desk: str = "swing") -> dict | None:
    """Get current position details for a ticker, or None if no position."""
    from src.shadow_trading.alpaca_adapter import _get_trading_client
    client = _get_trading_client(desk=desk)
    try:
        pos = client.get_open_position(ticker)
        return {
            "symbol": str(pos.symbol),
            "qty": float(pos.qty),
            "avg_entry_price": float(pos.avg_entry_price),
            "current_price": float(pos.current_price),
            "market_value": float(pos.market_value),
            "unrealized_pl": float(pos.unrealized_pl),
            "unrealized_plpc": float(pos.unrealized_plpc),
        }
    except Exception as exc:
        logger.warning("[ALPACA] Failed to get position for %s: %s", ticker, exc)
        return None


def get_all_positions(desk: str = "swing") -> list[dict]:
    """Get all open positions."""
    from src.shadow_trading.alpaca_adapter import _get_trading_client
    client = _get_trading_client(desk=desk)
    positions = client.get_all_positions()
    return [
        {
            "symbol": str(pos.symbol),
            "qty": float(pos.qty),
            "avg_entry_price": float(pos.avg_entry_price),
            "current_price": float(pos.current_price),
            "market_value": float(pos.market_value),
            "unrealized_pl": float(pos.unrealized_pl),
            "unrealized_plpc": float(pos.unrealized_plpc),
        }
        for pos in positions
    ]


def get_current_price(ticker: str, desk: str = "swing") -> float | None:
    """Get the latest trade price for a ticker. Retries on network/DNS errors."""
    from src.shadow_trading.alpaca_adapter import _get_data_client
    for attempt in range(3):
        try:
            client = _get_data_client(desk=desk)
            from alpaca.data.requests import StockLatestTradeRequest
            request = StockLatestTradeRequest(symbol_or_symbols=ticker)
            trades = client.get_stock_latest_trade(request)
            if ticker in trades:
                return float(trades[ticker].price)
            return None
        except (ConnectionError, OSError) as e:
            if attempt < 2:
                import time as _time
                _time.sleep(2 ** attempt)
                continue
            logger.warning("Failed to get current price for %s after 3 retries: %s", ticker, e)
            return None
        except Exception as e:
            logger.warning("Failed to get current price for %s: %s", ticker, e)
            return None


def get_order_status(order_id: str, desk: str = "swing") -> dict:
    """Check the status of an order."""
    from src.shadow_trading.alpaca_adapter import _get_trading_client, _serialize_order
    client = _get_trading_client(desk=desk)
    order = client.get_order_by_id(order_id)
    return _serialize_order(order)


def verify_order_accepted(order_id: str, desk: str = "swing") -> dict:
    """Verify an order was accepted by Alpaca after submission."""
    from src.shadow_trading.alpaca_adapter import _get_trading_client
    try:
        client = _get_trading_client(desk=desk)
        order = client.get_order_by_id(order_id)
        status = str(order.status)
        accepted_states = {"accepted", "new", "pending_new", "filled",
                           "partially_filled", "done_for_day"}
        rejected_states = {"rejected", "canceled", "expired", "suspended"}
        if status in accepted_states:
            return {"verified": True, "status": status, "error": None}
        elif status in rejected_states:
            return {"verified": False, "status": status, "error": None}
        else:
            return {"verified": None, "status": status, "error": "unexpected_status"}
    except Exception as exc:
        logger.warning("[VERIFY] Could not verify order %s: %s", order_id, exc)
        return {"verified": None, "status": "unknown", "error": str(exc)}


def cancel_paper_order(order_id: str, desk: str = "swing") -> dict:
    """Cancel a pending paper order by ID."""
    from src.shadow_trading.alpaca_adapter import _get_trading_client
    try:
        client = _get_trading_client(desk=desk)
        client.cancel_order_by_id(order_id)
        return {"cancelled": True, "terminal_state": None, "error": None}
    except Exception as e:
        terminal_state = None
        m = _TERMINAL_STATE_RE.search(str(e))
        if m:
            terminal_state = m.group(1).lower()
        logger.debug("[CANCEL] Could not cancel order %s: %s", order_id, e)
        return {"cancelled": False, "terminal_state": terminal_state, "error": str(e)}


def cancel_orders_for_ticker(ticker: str, desk: str = "swing") -> int:
    """Cancel all open orders for a specific ticker."""
    from src.shadow_trading.alpaca_adapter import _get_trading_client
    from alpaca.trading.requests import GetOrdersRequest
    from alpaca.trading.enums import QueryOrderStatus
    try:
        client = _get_trading_client(desk=desk)
        orders = client.get_orders(GetOrdersRequest(
            status=QueryOrderStatus.OPEN,
            symbols=[ticker],
        ))
        for order in orders:
            try:
                client.cancel_order_by_id(order.id)
            except Exception as e:
                logger.debug("[CANCEL] Failed to cancel order %s for %s: %s",
                               order.id, ticker, e)
        if orders:
            logger.info("[CANCEL] Cancelled %d open orders for %s", len(orders), ticker)
        return len(orders)
    except Exception as e:
        logger.debug("[CANCEL] Could not list orders for %s: %s", ticker, e)
        return 0


def cancel_all_orders(desk: str = "swing") -> dict:
    """Cancel all pending Alpaca orders. Returns ``{'cancelled': N}``."""
    from src.shadow_trading.alpaca_adapter import _get_trading_client
    try:
        client = _get_trading_client(desk=desk)
        cancelled = client.cancel_orders()
        count = len(cancelled) if cancelled else 0
        logger.info("[CANCEL] Cancelled %d pending orders", count)
        return {"cancelled": count}
    except Exception as e:
        logger.debug("[CANCEL] Could not cancel all orders: %s", e)
        return {"cancelled": 0, "error": str(e)}


# ── T2.17 Fail-CLOSED governor input surfaces ────────────────────────────

def get_account_equity(desk: str = "swing") -> float:
    """Return account equity (USD) or raise GovernorInputMissingError."""
    from src.risk.governor import GovernorInputMissingError
    from src.shadow_trading.alpaca_adapter import get_account_info
    try:
        info = get_account_info(desk=desk)
    except Exception as exc:  # noqa: BLE001
        raise GovernorInputMissingError(
            f"get_account_equity: broker unreachable: {exc}"
        ) from exc
    equity = info.get("equity")
    if equity is None:
        raise GovernorInputMissingError(
            "get_account_equity: equity missing from broker response"
        )
    return float(equity)



def get_buying_power(desk: str = "swing") -> float:
    """Return account buying power (USD) or raise GovernorInputMissingError."""
    from src.risk.governor import GovernorInputMissingError
    from src.shadow_trading.alpaca_adapter import get_account_info
    try:
        info = get_account_info(desk=desk)
    except Exception as exc:  # noqa: BLE001
        raise GovernorInputMissingError(
            f"get_buying_power: broker unreachable: {exc}"
        ) from exc
    bp = info.get("buying_power")
    if bp is None:
        raise GovernorInputMissingError(
            "get_buying_power: buying_power missing from broker response"
        )
    return float(bp)


def get_open_orders(desk: str = "swing") -> list:
    """Return list of currently-open Alpaca orders, raise on lookup failure."""
    from src.risk.governor import GovernorInputMissingError
    from src.shadow_trading.alpaca_adapter import _get_trading_client
    try:
        client = _get_trading_client(desk=desk)
    except Exception as exc:  # noqa: BLE001
        raise GovernorInputMissingError(
            f"get_open_orders: client construction failed: {exc}"
        ) from exc
    try:
        from alpaca.trading.requests import GetOrdersRequest
        from alpaca.trading.enums import QueryOrderStatus
        orders = client.get_orders(GetOrdersRequest(status=QueryOrderStatus.OPEN))
    except Exception as exc:  # noqa: BLE001
        raise GovernorInputMissingError(
            f"get_open_orders: order list retrieval failed: {exc}"
        ) from exc
    if orders is None:
        raise GovernorInputMissingError(
            "get_open_orders: broker returned None for open orders"
        )
    return list(orders)
