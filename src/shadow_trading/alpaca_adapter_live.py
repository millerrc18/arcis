"""Live-trading helpers extracted from alpaca_adapter.py (Sprint-0.C/C.2).

Called by: src.shadow_trading.alpaca_adapter, src.shadow_trading.alpaca_adapter_verify
Calls: src.config
Owns tables: none
Config keys: live_trading, api_key, secret_key, enabled, starting_capital, max_open_positions
Tests: tests/shadow_trading/test_alpaca_adapter_split.py, tests/test_live_trading.py
"""
import logging
import os

from src.config import load_config

logger = logging.getLogger(__name__)


class LiveTradingError(Exception):
    """Raised when live trading operations fail."""


def _get_live_config() -> dict:
    """Load live trading config from settings."""
    config = load_config()
    live_cfg = config.get("live_trading", {})

    api_key = os.environ.get("ALPACA_LIVE_API_KEY", live_cfg.get("api_key", ""))
    api_secret = os.environ.get("ALPACA_LIVE_SECRET_KEY", live_cfg.get("secret_key", ""))

    if not api_key or not api_secret:
        raise LiveTradingError(
            "Live trading API credentials not configured. "
            "Set live_trading.api_key and live_trading.secret_key in config."
        )

    return {
        "api_key": api_key,
        "api_secret": api_secret,
        "enabled": live_cfg.get("enabled", False),
        "starting_capital": live_cfg.get("starting_capital", 100),
        "max_open_positions": live_cfg.get("max_open_positions", 2),
    }


def _get_live_trading_client():
    """Create and return an Alpaca TradingClient for LIVE trading."""
    cfg = _get_live_config()
    from alpaca.trading.client import TradingClient
    return TradingClient(
        api_key=cfg["api_key"],
        secret_key=cfg["api_secret"],
        paper=False,  # LIVE account
    )


def get_live_account_info(desk: str = "swing") -> dict:
    """Get live account info: balance, buying power, equity.

    Args:
        desk: Must be 'swing' — live trading is swing-only. Parameter accepted
              for API consistency; non-swing desks should not call this function.
    """
    client = _get_live_trading_client()
    account = client.get_account()
    return {
        "account_id": str(account.id),
        "status": str(account.status),
        "cash": float(account.cash),
        "buying_power": float(account.buying_power),
        "equity": float(account.equity),
        "portfolio_value": float(account.portfolio_value),
        "currency": str(account.currency),
    }


def place_live_entry(
    ticker: str, shares: int, notional: float | None = None, desk: str = "swing"
) -> dict:
    """Place a LIVE market buy order. Returns order details dict.

    COMPLIANCE GUARDRAIL: live trading is swing-only. Raises ValueError if
    desk != 'swing' — research desks must use paper trading only.

    Args:
        ticker: Stock symbol
        shares: Number of whole shares (used if notional is None)
        notional: Dollar amount to invest (enables fractional shares).
                  If provided, overrides shares parameter.
        desk: Must be 'swing' — live trading restricted to swing desk.

    WHY notional ordering: Live account starts with small capital ($100).
    Whole-share ordering can't buy stocks above $100/share. Notional lets
    us invest exact dollar amounts and get fractional shares automatically.
    Strategy Decision #6: Equal weight (1/N) until 200+ trades.
    """
    if desk != "swing":
        raise ValueError(
            f"live trading only supports swing desk; got desk={desk!r}. "
            "Research strategies must use paper trading only."
        )
    cfg = _get_live_config()
    if not cfg["enabled"]:
        raise LiveTradingError("Live trading is disabled in config.")

    client = _get_live_trading_client()

    from alpaca.trading.requests import MarketOrderRequest
    from alpaca.trading.enums import OrderSide, TimeInForce

    if notional and notional > 1.0:
        logger.info("[LIVE] Placing LIVE BUY: $%.2f notional of %s", notional, ticker)
        request = MarketOrderRequest(
            symbol=ticker,
            notional=round(notional, 2),
            side=OrderSide.BUY,
            time_in_force=TimeInForce.DAY,
        )
    else:
        logger.info("[LIVE] Placing LIVE BUY: %d shares of %s", shares, ticker)
        request = MarketOrderRequest(
            symbol=ticker,
            qty=shares,
            side=OrderSide.BUY,
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
        "created_at": str(order.created_at) if order.created_at else None,
    }


def _build_live_bracket_request(
    ticker: str, shares: int,
    take_profit_price: float, stop_loss_price: float,
    limit_price: float | None,
):
    """Construct the Alpaca order request for a live bracket order.

    Returns a LimitOrderRequest when limit_price is provided (slippage
    protection), else a MarketOrderRequest. Both use GTC + BRACKET class
    so stop and take-profit legs persist across sessions.
    """
    from alpaca.trading.requests import MarketOrderRequest, LimitOrderRequest
    from alpaca.trading.enums import OrderSide, TimeInForce, OrderClass
    tp = {"limit_price": round(take_profit_price, 2)}
    sl = {"stop_price": round(stop_loss_price, 2)}
    if limit_price:
        return LimitOrderRequest(
            symbol=ticker, qty=shares, side=OrderSide.BUY,
            time_in_force=TimeInForce.GTC, order_class=OrderClass.BRACKET,
            limit_price=round(limit_price, 2), take_profit=tp, stop_loss=sl,
        )
    return MarketOrderRequest(
        symbol=ticker, qty=shares, side=OrderSide.BUY,
        time_in_force=TimeInForce.GTC, order_class=OrderClass.BRACKET,
        take_profit=tp, stop_loss=sl,
    )


def place_live_bracket(
    ticker: str,
    shares: int,
    take_profit_price: float,
    stop_loss_price: float,
    limit_price: float | None = None,
) -> dict:
    """Place a LIVE bracket order: entry + take-profit + stop-loss as one atomic order.

    Mirrors place_bracket_order (paper) but routes through the live trading
    client. WHY GTC: bracket exits must persist across sessions. WHY limit_price
    option: live entries are real money — slippage protection on illiquid names.
    See SBUX incident (2026-04-10) for history of why bracket is essential.
    Request construction delegated to _build_live_bracket_request.
    """
    cfg = _get_live_config()
    if not cfg["enabled"]:
        raise LiveTradingError("Live trading is disabled in config.")

    logger.info(
        "[LIVE] Placing BRACKET order: %d shares of %s "
        "(TP=$%.2f, SL=$%.2f%s)",
        shares, ticker, take_profit_price, stop_loss_price,
        f", LMT=${limit_price:.2f}" if limit_price else "",
    )

    client = _get_live_trading_client()
    request = _build_live_bracket_request(
        ticker, shares, take_profit_price, stop_loss_price, limit_price,
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


def place_live_exit(ticker: str, shares: int | float = 0) -> dict:
    """Place a LIVE market sell order. Returns order details dict.

    If shares is 0 or not provided, closes the entire position via
    Alpaca's close_position API (handles fractional shares automatically).

    WHY close_position instead of market sell: With fractional shares from
    notional ordering, we may hold e.g., 0.847 shares. A qty-based sell
    can't express fractional amounts, but close_position liquidates the
    exact position regardless of share count.
    """
    cfg = _get_live_config()
    if not cfg["enabled"]:
        raise LiveTradingError("Live trading is disabled in config.")

    client = _get_live_trading_client()

    # Use close_position for clean fractional exits
    if shares <= 0:
        logger.info("[LIVE] Closing entire position for %s", ticker)
        try:
            order = client.close_position(ticker)
            return {
                "order_id": str(order.id) if hasattr(order, 'id') else "close_position",
                "symbol": ticker,
                "qty": float(order.qty) if hasattr(order, 'qty') and order.qty else 0,
                "side": "sell",
                "type": "market",
                "status": str(order.status) if hasattr(order, 'status') else "closed",
                "filled_avg_price": float(order.filled_avg_price) if hasattr(order, 'filled_avg_price') and order.filled_avg_price else None,
                "filled_at": str(order.filled_at) if hasattr(order, 'filled_at') and order.filled_at else None,
            }
        except Exception as e:
            logger.warning("[LIVE] close_position failed for %s: %s, trying market sell", ticker, e)

    logger.info("[LIVE] Placing LIVE SELL: %s shares of %s", shares, ticker)

    from alpaca.trading.requests import MarketOrderRequest
    from alpaca.trading.enums import OrderSide, TimeInForce

    request = MarketOrderRequest(
        symbol=ticker,
        qty=float(shares),
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


def get_live_positions(desk: str = "swing") -> list[dict]:
    """Get all open live positions.

    Args:
        desk: Must be 'swing' — live trading is swing-only. Parameter accepted
              for API consistency; non-swing desks should not call this function.
    """
    client = _get_live_trading_client()
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


def get_live_order_status(order_id: str) -> dict:
    """Check the status of a live order."""
    client = _get_live_trading_client()
    order = client.get_order_by_id(order_id)
    return {
        "order_id": str(order.id),
        "symbol": str(order.symbol),
        "status": str(order.status),
        "filled_qty": str(order.filled_qty) if order.filled_qty else "0",
        "filled_avg_price": float(order.filled_avg_price) if order.filled_avg_price else None,
        "filled_at": str(order.filled_at) if order.filled_at else None,
    }
