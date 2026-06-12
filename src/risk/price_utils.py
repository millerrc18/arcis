"""Shared price-lookup helper for risk + execution paths.

Extracted from src/shadow_trading/executor.py to break the circular import
between src.risk.governor and src.shadow_trading.executor (#461 Cycle 1).

Both the risk governor (sector-exposure valuation) and the shadow-trading
executor (exit-price fetch) call this helper. Placing it in src.risk (no
dependency on shadow_trading.executor) keeps the call graph acyclic.

Called by: risk.governor (sector exposure), shadow_trading.executor (exits)
Calls: shadow_trading.alpaca_adapter.get_current_price, data_ingestion.market_data.fetch_ohlcv
Owns tables: none
Config keys: none
Tests: tests/test_circular_imports.py
"""
from __future__ import annotations

import logging
import math

logger = logging.getLogger(__name__)


def _get_current_price_safe(ticker: str) -> float | None:
    """Get current price, trying Alpaca first then falling back to yfinance.

    Returns ``None`` (never a non-finite/non-positive value) so callers can
    skip rather than derive a NaN pnl. ``if price:`` alone is insufficient —
    ``float('nan')`` is truthy — so both branches require ``math.isfinite``
    (2026-06-12 NaN-pnl incident; sibling of the reconcile guard).
    """
    try:
        from src.shadow_trading.alpaca_adapter import get_current_price
        price = get_current_price(ticker)
        if price is not None and math.isfinite(price) and price > 0:
            return price
    except Exception as e:
        logger.debug("[PRICE] Alpaca price fetch failed for %s: %s", ticker, e)

    try:
        from src.data_ingestion.market_data import fetch_ohlcv
        data = fetch_ohlcv([ticker], period="5d")
        if ticker in data and not data[ticker].empty:
            px = float(data[ticker]["Close"].iloc[-1])
            if math.isfinite(px) and px > 0:
                return px
    except Exception as e:
        logger.debug("[PRICE] yfinance price fetch failed for %s: %s", ticker, e)

    return None
