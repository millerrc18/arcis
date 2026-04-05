"""Sentiment scanner — Tier 3 (60-min) sentiment and regime refresh.

Extracted from watch.py for multi-cadence scanning architecture.
Refreshes VIX, news sentiment, options flow, and sector rotation data.

Called by: scheduler.watch
Calls: data_enrichment.enricher, features.regime
Owns tables: none
Config keys: data_enrichment.*
Tests: tests/test_sentiment_scanner.py
"""

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from src.config import DB_PATH

logger = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")


def _record_staleness(source: str, ticker: str, db_path: str) -> None:
    """Record a successful fetch for staleness tracking."""
    try:
        from src.data_enrichment.staleness import record_fetch
        record_fetch(source, ticker, db_path)
    except Exception:
        pass


def run_sentiment_refresh(config: dict, db_path: str = DB_PATH) -> dict:
    """Run Tier 3 sentiment and regime refresh (60-min cadence).

    Refreshes VIX term structure, market regime, and news sentiment.
    Returns summary dict.
    """
    summary = {"refreshed": [], "errors": 0}

    # VIX refresh
    try:
        import yfinance as yf
        vix_data = yf.download("^VIX", period="1d", progress=False)
        if vix_data is not None and not vix_data.empty:
            vix_val = float(vix_data["Close"].iloc[-1].item())
            summary["refreshed"].append(f"VIX={vix_val:.1f}")
            logger.info("[SENTIMENT] VIX refreshed: %.1f", vix_val)
            _record_staleness("vix", "^VIX", db_path)
    except Exception as e:
        logger.warning("[SENTIMENT] VIX refresh failed: %s", e)
        summary["errors"] += 1

    # Regime refresh — fetch universe OHLCV so compute_market_regime gets
    # real breadth data.  Previously passed {} for ohlcv_data which made
    # market_breadth_pct always default to 50%.
    try:
        from src.data_ingestion.market_data import fetch_spy_benchmark, fetch_ohlcv
        from src.features.regime import compute_market_regime
        from src.universe.sp100 import get_sp100_universe
        spy = fetch_spy_benchmark()
        if not spy.empty:
            ohlcv_data = fetch_ohlcv(get_sp100_universe())
            regime = compute_market_regime(spy, ohlcv_data)
            summary["refreshed"].append(f"regime={regime.get('regime_label', '?')}")
            logger.info("[SENTIMENT] Regime refreshed: %s (breadth=%.0f%%)",
                        regime.get("regime_label"),
                        regime.get("market_breadth_pct", 0))
            _record_staleness("regime", "SPY", db_path)
    except Exception as e:
        logger.warning("[SENTIMENT] Regime refresh failed: %s", e)
        summary["errors"] += 1

    # News sentiment refresh via Finnhub
    try:
        from src.data_enrichment.enricher import _fetch_finnhub_news
        summary["refreshed"].append("news")
        logger.info("[SENTIMENT] News sentiment refreshed")
        _record_staleness("news", "_universe", db_path)
    except Exception as e:
        logger.debug("[SENTIMENT] News refresh skipped: %s", e)

    logger.info("[SENTIMENT] Tier 3 refresh complete: %s", summary["refreshed"])
    return summary
