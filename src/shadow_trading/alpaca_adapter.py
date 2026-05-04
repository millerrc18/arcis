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
    if isinstance(val, enum.Enum):
        v = val.value
        return v if isinstance(v, str) else str(v)
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

    api_key = os.environ.get("ALPACA_API_KEY", alpaca_cfg.get("api_key", ""))
    api_secret = os.environ.get("ALPACA_API_SECRET", alpaca_cfg.get("api_secret", ""))
    base_url = os.environ.get("ALPACA_BASE_URL", alpaca_cfg.get("base_url", "https://paper-api.alpaca.markets"))

    paper_env = os.environ.get("ALPACA_PAPER_TRADE", "true").lower()
    if "paper" not in base_url.lower() and paper_env != "true":
        raise PaperTradingError(
            "SAFETY VIOLATION: Alpaca base_url does not contain 'paper' and "
            "ALPACA_PAPER_TRADE is not 'true'. Refusing to connect to a live account."
        )

    if not api_key:
        raise PaperTradingError(
            "Paper trading API key not configured. "
            "Set ALPACA_API_KEY in .env or alpaca.api_key in config."
        )
    if not api_secret:
        raise PaperTradingError(
            "Paper trading API secret not configured. "
            "Set ALPACA_API_SECRET in .env or alpaca.api_secret in config."
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
    """Create and return an Alpaca StockHistoricalDataClient."""
    if desk is not None and desk != "swing":
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
    """Get paper account info: balance, buying power, equity, portfolio value."""
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


def is_connected(desk: str = "swing") -> bool:
    """Return True iff a real Alpaca handshake succeeds and account is ACTIVE."""
    try:
        client = _get_trading_client(desk=desk)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[ALPACA] is_connected: client construction failed: %s", exc)
        return False
    try:
        account = client.get_account()
    except Exception as exc:  # noqa: BLE001
        logger.warning("[ALPACA] is_connected: handshake failed: %s", exc)
        return False
    status = str(getattr(account, "status", "")).upper()
    return status == "ACTIVE"


def get_position_value(ticker: str, desk: str = "swing") -> float:
    """Return current $ market value of an open position, 0.0 if no position."""
    from src.risk.governor import GovernorInputMissingError
    try:
        pos = get_position(ticker, desk=desk)
    except Exception as exc:  # noqa: BLE001
        raise GovernorInputMissingError(
            f"get_position_value: lookup failed for {ticker}: {exc}"
        ) from exc
    if pos is None:
        return 0.0
    market_value = pos.get("market_value")
    if market_value is None:
        raise GovernorInputMissingError(
            f"get_position_value: market_value missing for {ticker}"
        )
    return float(market_value)


def fetch_latest_quotes(tickers: list) -> dict:
    """Return latest quotes for each ticker from Alpaca's market data API.

    Returns a dict keyed by ticker with sub-keys: price, bid, ask, as_of.
    Tickers with no data are omitted from the result. Raises on client
    construction errors so callers can catch and log.
    """
    if not tickers:
        return {}
    client = _get_data_client()
    from alpaca.data.requests import StockLatestQuoteRequest
    from datetime import timezone
    request = StockLatestQuoteRequest(symbol_or_symbols=list(tickers))
    quotes = client.get_stock_latest_quote(request)
    result = {}
    for ticker, quote in quotes.items():
        ask_price = getattr(quote, "ask_price", None)
        bid_price = getattr(quote, "bid_price", None)
        price = None
        if ask_price is not None and bid_price is not None:
            try:
                price = (float(ask_price) + float(bid_price)) / 2
            except (TypeError, ValueError):
                price = None
        if price is None and ask_price is not None:
            try:
                price = float(ask_price)
            except (TypeError, ValueError):
                pass
        if price is None:
            continue
        ts = getattr(quote, "timestamp", None)
        if ts is not None:
            as_of = ts.isoformat() if hasattr(ts, "isoformat") else str(ts)
        else:
            from datetime import datetime
            as_of = datetime.now(timezone.utc).isoformat()
        result[ticker] = {
            "price": price,
            "bid": float(bid_price) if bid_price is not None else None,
            "ask": float(ask_price) if ask_price is not None else None,
            "as_of": as_of,
        }
    return result


# ── Re-exports from helper modules (patch-compat + public API) ────────────

from src.shadow_trading.alpaca_adapter_paper import (  # noqa: E402
    place_paper_entry,
    place_paper_exit,
    place_bracket_order,
    get_position,
    get_all_positions,
    get_current_price,
    get_order_status,
    verify_order_accepted,
    cancel_paper_order,
    cancel_orders_for_ticker,
    cancel_all_orders,
    get_account_equity,
    get_buying_power,
    get_open_orders,
)

from src.shadow_trading.alpaca_adapter_live import (  # noqa: E402
    LiveTradingError,
    _get_live_config,
    _get_live_trading_client,
    get_live_account_info,
    place_live_entry,
    place_live_bracket,
    _build_live_bracket_request,
    place_live_exit,
    get_live_positions,
    get_live_order_status,
)

from src.shadow_trading.alpaca_adapter_verify import (  # noqa: E402
    OrderNotAcceptedError,
    _poll_order_status,
    _classify_order_status,
    _calculate_backoff,
    _handle_poll_attempt,
    verify_live_order_accepted,
)


# ── Public broker class facades ───────────────────────────────────────────

class AlpacaPaperBroker:
    """Facade exposing paper-trading operations as a class interface."""

    @staticmethod
    def place_entry(ticker: str, shares: int, order_type: str = "market",
                    desk: str = "swing") -> dict:
        return place_paper_entry(ticker, shares, order_type=order_type, desk=desk)

    @staticmethod
    def place_exit(ticker: str, shares: int, order_type: str = "market",
                   desk: str = "swing") -> dict:
        return place_paper_exit(ticker, shares, order_type=order_type, desk=desk)

    @staticmethod
    def place_bracket(ticker: str, shares: int, take_profit_price: float,
                      stop_loss_price: float, limit_price: float | None = None,
                      desk: str = "swing") -> dict:
        return place_bracket_order(ticker, shares, take_profit_price,
                                   stop_loss_price, limit_price=limit_price, desk=desk)


class AlpacaLiveBroker:
    """Facade exposing live-trading operations as a class interface."""

    @staticmethod
    def place_entry(ticker: str, shares: int, notional: float | None = None,
                    desk: str = "swing") -> dict:
        return place_live_entry(ticker, shares, notional=notional, desk=desk)

    @staticmethod
    def place_exit(ticker: str, shares: int | float = 0) -> dict:
        return place_live_exit(ticker, shares)

    @staticmethod
    def place_bracket(ticker: str, shares: int, take_profit_price: float,
                      stop_loss_price: float, limit_price: float | None = None) -> dict:
        return place_live_bracket(ticker, shares, take_profit_price,
                                  stop_loss_price, limit_price=limit_price)


# ── Capability Registry registration (Sprint 1B) ─────────────────────────

from datetime import date as _date  # noqa: E402

from src.platform.capability_registry import register_state  # noqa: E402


def _alpaca_account_summary() -> dict:
    """Thin wrapper around get_account_info for the registry."""
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
