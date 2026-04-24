"""Alpaca paper trading adapter with safety guardrails.

This module is the ONLY code that talks to the Alpaca API. All broker
interactions (paper and live) go through functions defined here.

Two separate client paths:
  - Paper: _get_trading_client() — always paper=True, verified against base_url.
  - Live: _get_live_trading_client() — paper=False, separate config section.
    The live path intentionally has NO paper-safety check since it must
    connect to the real-money endpoint.

Key design decisions:
  - Every function creates a fresh client (no module-level singleton) to avoid
    stale connections after network drops.
  - All order responses are normalized to plain dicts via _serialize_order()
    so downstream code never depends on alpaca-py SDK objects.
  - Fix for #248: _strip_enum() handles Alpaca SDK enums that stringify as
    "OrderStatus.held" — downstream code compares against plain "held".

Called by: cli.commands, evaluation.system_validator, risk.governor, services.shadow_service, shadow_trading.bracket_monitor, shadow_trading.executor (cancel_paper_order), shadow_trading.reconcile
Calls: config
Owns tables: none
Config keys: alpaca, api_key, api_secret, base_url, default_order_type, enabled, live_trading, max_open_positions, max_positions, secret_key, shadow_trading, starting_capital, timeout_days
Tests: tests/test_bracket_orders.py, tests/test_executor_import.py, tests/test_live_trading.py
"""

import enum
import logging
import os
import re
from datetime import datetime
from zoneinfo import ZoneInfo

from src.config import load_config

logger = logging.getLogger(__name__)


def _strip_enum(val) -> str | None:
    """Strip Python enum class prefix from str(enum); prefer enum.value.

    Fix for #248: Alpaca SDK enums like OrderStatus.held stringify as
    "OrderStatus.held", but downstream code (bracket monitor) compares
    against plain "held".

    Sprint fix/paper-exit-qty-asymmetry Commit 6: alpaca-py 0.43 exposes
    regular `Enum` (not `StrEnum`), so `str(OrderStatus.FILLED)` returns
    'OrderStatus.FILLED' and the .split('.')[-1] fallback produces
    'FILLED' (uppercase from enum NAME, not VALUE). Downstream checks at
    executor.py:1470 and :1478 compare against lowercase sets and
    silently miss every filled bracket leg — producing phantom exits.

    Primary fix: when given an `enum.Enum` instance, return `.value`
    directly (alpaca-py values are lowercase strings). String-input
    fallback retains the current .split('.')[-1] behavior per operator
    spec; the raw `str(order.status)` callsites in place_paper_*/
    place_live_* (8 locations) remain a pre-existing bug and are
    scope-deferred to a follow-up sprint.
    """
    if val is None:
        return None
    # Primary path: extract .value directly from Enum instances. This
    # yields the alpaca-py lowercase value ('filled', 'pending_new',
    # 'canceled', etc.) regardless of how Python's enum.__str__ behaves.
    if isinstance(val, enum.Enum):
        v = val.value
        return v if isinstance(v, str) else str(v)
    # Fallback: plain strings — split on "." for the enum-prefixed form
    # and return the segment unchanged (CURRENT behavior). See docstring.
    s = str(val)
    return s.split(".")[-1] if "." in s else s


def _serialize_order(order, fallback_qty: int | float = 0) -> dict:
    """Normalize Alpaca order objects into plain dicts, including bracket legs.

    WHY: Downstream code (bracket_monitor, executor, reconcile) needs stable
    string-keyed dicts, not alpaca-py SDK objects that change between versions.
    This is the single normalization point — every order goes through here.

    GOTCHA: order.qty can be None for notional orders (live fractional shares).
    The fallback_qty parameter handles this so callers don't need to check.
    """
    return {
        "order_id": str(order.id),
        "symbol": str(order.symbol),
        "qty": float(order.qty) if getattr(order, "qty", None) else fallback_qty,
        # Fix for #248: strip enum prefix so "OrderSide.buy" → "buy"
        "side": _strip_enum(order.side) if getattr(order, "side", None) else None,
        "type": _strip_enum(order.type) if getattr(order, "type", None) else None,
        "status": _strip_enum(order.status) if getattr(order, "status", None) else None,
        "filled_qty": str(order.filled_qty) if getattr(order, "filled_qty", None) else "0",
        "filled_avg_price": (
            float(order.filled_avg_price)
            if getattr(order, "filled_avg_price", None)
            else None
        ),
        "filled_at": str(order.filled_at) if getattr(order, "filled_at", None) else None,
        "created_at": str(order.created_at) if getattr(order, "created_at", None) else None,
        "limit_price": (
            float(order.limit_price)
            if getattr(order, "limit_price", None) not in (None, "")
            else None
        ),
        "stop_price": (
            float(order.stop_price)
            if getattr(order, "stop_price", None) not in (None, "")
            else None
        ),
        "legs": [
            _serialize_order(leg, fallback_qty=fallback_qty)
            for leg in (getattr(order, "legs", None) or [])
        ],
    }


class PaperTradingError(Exception):
    """Raised when paper trading safety checks fail."""


def _get_alpaca_config() -> dict:
    """Load Alpaca config from settings and environment, with safety checks."""
    config = load_config()
    alpaca_cfg = config.get("alpaca", {})
    shadow_cfg = config.get("shadow_trading", {})

    # Allow env vars to override config file
    api_key = os.environ.get("ALPACA_API_KEY", alpaca_cfg.get("api_key", ""))
    api_secret = os.environ.get("ALPACA_API_SECRET", alpaca_cfg.get("api_secret", ""))
    base_url = os.environ.get("ALPACA_BASE_URL", alpaca_cfg.get("base_url", "https://paper-api.alpaca.markets"))

    # SAFETY: Verify paper mode — this is the critical guardrail that prevents
    # the paper trading path from accidentally connecting to a live account.
    # Two independent checks: URL must contain "paper" OR env var must be "true".
    paper_env = os.environ.get("ALPACA_PAPER_TRADE", "true").lower()
    if "paper" not in base_url.lower() and paper_env != "true":
        raise PaperTradingError(
            "SAFETY VIOLATION: Alpaca base_url does not contain 'paper' and "
            "ALPACA_PAPER_TRADE is not 'true'. Refusing to connect to a live account."
        )

    return {
        "api_key": api_key,
        "api_secret": api_secret,
        "base_url": base_url,
        "enabled": shadow_cfg.get("enabled", False),
        "max_positions": shadow_cfg.get("max_positions", 10),
        "default_order_type": shadow_cfg.get("default_order_type", "market"),
        "timeout_days": shadow_cfg.get("timeout_days", 15),
    }


def _check_enabled() -> dict:
    """Check shadow trading is enabled and return config. Raises if disabled."""
    cfg = _get_alpaca_config()
    if not cfg["enabled"]:
        raise PaperTradingError(
            "Shadow trading is disabled. Set shadow_trading.enabled: true in config."
        )
    return cfg


def _get_trading_client(desk: str | None = None):
    """Create and return an Alpaca TradingClient for paper trading.

    If desk is specified (e.g. 'research_lazy_prices_v1'), dispatches
    through src.shadow_trading.alpaca_clients.get_client for per-desk
    routing. If desk is None or 'swing', uses the legacy swing-config
    path for full backward compatibility with existing swing code.

    Args:
        desk: Named desk to route through (e.g. 'swing', 'research_xxx').
              None and 'swing' both use the legacy _get_alpaca_config path.
    """
    if desk is not None and desk != "swing":
        from src.shadow_trading.alpaca_clients import get_client
        return get_client(desk)
    cfg = _get_alpaca_config()
    from alpaca.trading.client import TradingClient
    return TradingClient(
        api_key=cfg["api_key"],
        secret_key=cfg["api_secret"],
        paper=True,
    )


def _get_data_client(desk: str | None = None):
    """Create and return an Alpaca StockHistoricalDataClient.

    desk kwarg accepted for parallel signature with _get_trading_client;
    data client reuses the desk's trading-credentials (market data API
    uses the same api_key/secret). None or 'swing' → legacy path.

    Args:
        desk: Named desk to route through. None and 'swing' use legacy config.
    """
    if desk is not None and desk != "swing":
        # Research desk — resolve credentials through desks.{desk}.*
        import os as _os
        desks_cfg = load_config().get("desks", {})
        dc = desks_cfg.get(desk, {})
        key_var = dc.get("alpaca_key_env")
        sec_var = dc.get("alpaca_secret_env")
        if not key_var or not sec_var:
            raise ValueError(
                f"desk {desk!r} has no alpaca_key_env / alpaca_secret_env "
                "in config; cannot construct data client"
            )
        api_key = _os.environ.get(key_var)
        api_sec = _os.environ.get(sec_var)
        if not api_key or not api_sec:
            raise RuntimeError(
                f"desk {desk!r} credentials not in environment"
            )
        from alpaca.data.historical import StockHistoricalDataClient
        return StockHistoricalDataClient(api_key=api_key, secret_key=api_sec)
    cfg = _get_alpaca_config()
    from alpaca.data.historical import StockHistoricalDataClient
    return StockHistoricalDataClient(
        api_key=cfg["api_key"],
        secret_key=cfg["api_secret"],
    )


def get_account_info(desk: str = "swing") -> dict:
    """Get paper account info: balance, buying power, equity, portfolio value.

    Args:
        desk: Named desk to route through (default 'swing').
              Routes to per-desk Alpaca client via _get_trading_client(desk=desk).
    """
    client = _get_trading_client(desk=desk)
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


def place_paper_entry(
    ticker: str, shares: int, order_type: str = "market", desk: str = "swing"
) -> dict:
    """Place a paper buy order. Returns order details dict.

    Args:
        desk: Named desk to route through (default 'swing').
    """
    _check_enabled()

    logger.info("[SHADOW] Placing paper BUY: %d shares of %s", shares, ticker)

    client = _get_trading_client(desk=desk)

    from alpaca.trading.requests import MarketOrderRequest, LimitOrderRequest
    from alpaca.trading.enums import OrderSide, TimeInForce

    if order_type == "market":
        request = MarketOrderRequest(
            symbol=ticker,
            qty=shares,
            side=OrderSide.BUY,
            time_in_force=TimeInForce.DAY,
        )
    else:
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
    """Place a paper sell order. Returns order details dict.

    Args:
        desk: Named desk to route through (default 'swing').
    """
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

    Args:
        desk: Named desk to route through (default 'swing').
    """
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
            symbol=ticker,
            qty=shares,
            side=OrderSide.BUY,
            time_in_force=TimeInForce.GTC,
            order_class=OrderClass.BRACKET,
            limit_price=round(limit_price, 2),
            take_profit={"limit_price": round(take_profit_price, 2)},
            stop_loss={"stop_price": round(stop_loss_price, 2)},
        )
    else:
        request = MarketOrderRequest(
            symbol=ticker,
            qty=shares,
            side=OrderSide.BUY,
            time_in_force=TimeInForce.GTC,
            order_class=OrderClass.BRACKET,
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
    """Get current position details for a ticker, or None if no position.

    Args:
        desk: Named desk to route through (default 'swing').
    """
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
    """Get all open positions.

    Args:
        desk: Named desk to route through (default 'swing').
    """
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
    """Get the latest trade price for a ticker. Retries on network/DNS errors.

    WHY 3 retries with exponential backoff (0s, 1s, 2s): Alpaca's data API
    occasionally returns DNS errors or 503s during high-volume periods.
    The executor calls this for every open position every scan cycle, so
    transient failures are common and worth retrying.

    GOTCHA: Only retries ConnectionError/OSError (network issues). Other
    exceptions (e.g., invalid ticker) fail immediately to avoid wasting time.

    Args:
        desk: Named desk to route through (default 'swing').
    """
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
                _time.sleep(2 ** attempt)  # 0s, 1s, 2s backoff
                continue
            logger.warning("Failed to get current price for %s after 3 retries: %s", ticker, e)
            return None
        except Exception as e:
            logger.warning("Failed to get current price for %s: %s", ticker, e)
            return None


def get_order_status(order_id: str, desk: str = "swing") -> dict:
    """Check the status of an order.

    Args:
        desk: Named desk to route through (default 'swing').
    """
    client = _get_trading_client(desk=desk)
    order = client.get_order_by_id(order_id)
    return _serialize_order(order)


def verify_order_accepted(order_id: str, desk: str = "swing") -> dict:
    """Verify an order was accepted by Alpaca after submission.

    Fix #352: fire-and-forget submission can miss acceptances when
    the SDK raises an exception after Alpaca has already accepted.

    Returns:
        {"verified": True/False/None, "status": str, "error": str|None}
        - True: order confirmed accepted/filled/partially_filled
        - False: order confirmed rejected/canceled
        - None: verification failed (API error) — status uncertain

    Args:
        desk: Named desk to route through (default 'swing').
    """
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


_TERMINAL_STATE_RE = re.compile(r"already in \\?\"?([a-z_]+)\\?\"? state", re.IGNORECASE)


def cancel_paper_order(order_id: str, desk: str = "swing") -> dict:
    """Cancel a pending paper order by ID.

    Returns a dict: ``{cancelled: bool, terminal_state: str|None, error: str|None}``.

    When Alpaca responds "order is already in 'filled' state" (code 42210000),
    the order raced the cancel and filled at the broker — we extract the
    terminal state so callers can detect the background fill and avoid
    resubmitting a duplicate order. That race was the root cause of the
    2026-04-14 NVDA/GOOGL exit-loop short-position accumulation.

    Args:
        desk: Named desk to route through (default 'swing').
    """
    try:
        client = _get_trading_client(desk=desk)
        client.cancel_order_by_id(order_id)
        return {"cancelled": True, "terminal_state": None, "error": None}
    except Exception as e:
        terminal_state = None
        m = _TERMINAL_STATE_RE.search(str(e))
        if m:
            terminal_state = m.group(1).lower()
        logger.warning("[CANCEL] Could not cancel order %s: %s", order_id, e)
        return {"cancelled": False, "terminal_state": terminal_state, "error": str(e)}


def cancel_orders_for_ticker(ticker: str, desk: str = "swing") -> int:
    """Cancel all open orders for a specific ticker.

    Fix #356: Required before closing a position — pending orders lock
    shares as 'held_for_orders', preventing close_position from working.

    Returns the number of orders cancelled.

    Args:
        desk: Named desk to route through (default 'swing').
    """
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
                logger.warning("[CANCEL] Failed to cancel order %s for %s: %s",
                               order.id, ticker, e)
        if orders:
            logger.info("[CANCEL] Cancelled %d open orders for %s", len(orders), ticker)
        return len(orders)
    except Exception as e:
        logger.warning("[CANCEL] Could not list orders for %s: %s", ticker, e)
        return 0


def cancel_all_orders(desk: str = "swing") -> dict:
    """Cancel all pending Alpaca orders.  Returns ``{'cancelled': N}``.

    Args:
        desk: Named desk to route through (default 'swing').
    """
    try:
        client = _get_trading_client(desk=desk)
        cancelled = client.cancel_orders()
        count = len(cancelled) if cancelled else 0
        logger.info("[CANCEL] Cancelled %d pending orders", count)
        return {"cancelled": count}
    except Exception as e:
        logger.warning("[CANCEL] Could not cancel all orders: %s", e)
        return {"cancelled": 0, "error": str(e)}


# ── Live Trading Adapter ──────────────────────────────────────────────
#
# Separate client creation for live (real-money) Alpaca account.
# Uses live_trading config section, NOT the paper alpaca section.
# No paper-safety checks — this deliberately connects to a live account.
#
# WHY separate from paper: Different API keys, different risk parameters,
# different ordering modes (notional vs qty). Keeping them separate prevents
# accidentally using paper credentials for live or vice versa.
# ──────────────────────────────────────────────────────────────────────


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


def place_live_bracket(
    ticker: str,
    shares: int,
    take_profit_price: float,
    stop_loss_price: float,
    limit_price: float | None = None,
) -> dict:
    """Place a LIVE bracket order: entry + take-profit + stop-loss as one atomic order.

    Mirrors place_bracket_order (paper) but routes through the live trading
    client. Alpaca's OrderClass.BRACKET works identically for paper and live
    accounts — the comment in src/trading/alpaca_broker.py that claimed
    otherwise was wrong (#651).

    WHY this matters: previously AlpacaLiveBroker.place_bracket_order called
    place_live_entry (a market order) and recorded order_type='bracket' in
    the DB despite no broker-side stop or take-profit being submitted. If
    the watch loop process died, the position had zero downside protection
    and zero gain capture. SBUX (2026-04-10, sat open 14d, operator manually
    liquidated on Alpaca) was the canonical victim.

    With this function, the broker holds the stop and take-profit legs in
    OCO semantics — they survive process restarts, network blips, and
    overnight scheduler gaps.

    WHY GTC: bracket exits must persist across sessions. DAY orders would
    expire at close, leaving positions unprotected overnight.

    WHY limit_price option: live entries are real money — operators may
    want slippage protection on illiquid names or volatile open windows.
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

    from alpaca.trading.requests import MarketOrderRequest, LimitOrderRequest
    from alpaca.trading.enums import OrderSide, TimeInForce, OrderClass

    if limit_price:
        request = LimitOrderRequest(
            symbol=ticker,
            qty=shares,
            side=OrderSide.BUY,
            time_in_force=TimeInForce.GTC,
            order_class=OrderClass.BRACKET,
            limit_price=round(limit_price, 2),
            take_profit={"limit_price": round(take_profit_price, 2)},
            stop_loss={"stop_price": round(stop_loss_price, 2)},
        )
    else:
        request = MarketOrderRequest(
            symbol=ticker,
            qty=shares,
            side=OrderSide.BUY,
            time_in_force=TimeInForce.GTC,
            order_class=OrderClass.BRACKET,
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


# ── Capability Registry registration (Sprint 1B) ───────────────────────

from datetime import date as _date  # noqa: E402

from src.platform.capability_registry import register_state  # noqa: E402


def _alpaca_account_summary() -> dict:
    """Thin wrapper around get_account_info for the registry.

    Failures bubble up as exceptions; the endpoint's timeout/exception
    handler converts them to {status: unavailable}.
    """
    info = get_account_info(desk="swing")
    return {
        "value": {
            "equity": info.get("equity"),
            "cash": info.get("cash"),
            "buying_power": info.get("buying_power"),
            "portfolio_value": info.get("portfolio_value"),
            "status": info.get("status"),
        },
    }


@register_state(
    name="alpaca_account",
    description=(
        "Current Alpaca paper account snapshot — equity, cash, buying "
        "power, portfolio value, account status. Swing desk only."
    ),
    category="trading",
    version="1.0",
    maintainer="ai_session",
    introduced_in="v0.13.0",
    last_reviewed_date=_date(2026, 4, 18),
    refresh_hint="real-time",
)
def alpaca_account_state() -> dict:
    return _alpaca_account_summary()
