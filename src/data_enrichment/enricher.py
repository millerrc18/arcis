"""Data enrichment orchestrator.

Called by: scheduler/watch.py, services/scan_service.py
Calls: data_enrichment/earnings_signals.py, data_enrichment/fundamentals.py, data_enrichment/insiders.py, data_enrichment/macro.py, data_enrichment/news.py
Owns tables: none
Config keys: cache_hours, data_enrichment, enabled, finnhub_api_key, fred_api_key, insider_lookback_days
Tests: tests/test_enrichment.py

Adds fundamental, insider, and macro data to all ticker feature dicts.
Called AFTER compute_all_features and BEFORE ranking/packet generation.
"""

import logging
import time

logger = logging.getLogger(__name__)


def enrich_features(features: dict[str, dict], config: dict) -> dict[str, dict]:
    """Add fundamental, insider, and macro data to all ticker feature dicts.

    Fetches data with caching and rate limiting. Never crashes —
    returns features unchanged if enrichment fails.

    Args:
        features: Output of compute_all_features() — dict of ticker -> feature dict
        config: Application config

    Returns:
        Same dict with fundamental_summary, insider_summary, macro_summary added.
    """
    enrichment_cfg = config.get("data_enrichment", {})
    if not enrichment_cfg.get("enabled", True):
        logger.info("[ENRICHMENT] Data enrichment disabled in config")
        return features

    cache_hours = enrichment_cfg.get("cache_hours", 24)
    finnhub_key = enrichment_cfg.get("finnhub_api_key")
    fred_key = enrichment_cfg.get("fred_api_key")
    lookback_days = enrichment_cfg.get("insider_lookback_days", 90)

    # 1. Fetch macro context ONCE (shared across all tickers)
    macro_summary = "No macro data available"
    try:
        from src.data_enrichment.macro import fetch_macro_context, format_macro_summary
        macro_data = fetch_macro_context(fred_api_key=fred_key, cache_hours=cache_hours)
        macro_summary = format_macro_summary(macro_data)
    except Exception as e:
        logger.warning("[ENRICHMENT] Failed to fetch macro context: %s", e)

    # 2. Enrich each ticker
    total = len(features)
    enriched_count = 0
    missing_fundamentals = 0
    missing_insiders = 0

    for ticker, feat in features.items():
        # Always add macro (same for all)
        feat["macro_summary"] = macro_summary

        # Fundamental data
        try:
            from src.data_enrichment.fundamentals import (
                fetch_fundamental_snapshot,
                format_fundamental_summary,
            )
            fund_data = fetch_fundamental_snapshot(ticker, cache_hours=cache_hours)
            price = feat.get("current_price")
            feat["fundamental_summary"] = format_fundamental_summary(fund_data, price)
            if fund_data is None:
                missing_fundamentals += 1
            time.sleep(0.1)  # Rate limit for SEC EDGAR
        except Exception as e:
            feat["fundamental_summary"] = "No fundamental data available"
            missing_fundamentals += 1
            logger.debug("[ENRICHMENT] Fundamentals failed for %s: %s", ticker, e)

        # Insider data
        try:
            from src.data_enrichment.insiders import (
                fetch_insider_activity,
                format_insider_summary,
            )
            insider_data = fetch_insider_activity(
                ticker,
                lookback_days=lookback_days,
                finnhub_api_key=finnhub_key,
                cache_hours=cache_hours,
            )
            feat["insider_summary"] = format_insider_summary(insider_data)
            if insider_data is None:
                missing_insiders += 1
        except Exception as e:
            feat["insider_summary"] = "No insider data available"
            missing_insiders += 1
            logger.debug("[ENRICHMENT] Insiders failed for %s: %s", ticker, e)

        # News data
        try:
            from src.data_enrichment.news import (
                fetch_recent_news,
                format_news_summary,
            )
            news_data = fetch_recent_news(
                ticker,
                finnhub_api_key=finnhub_key,
                cache_hours=min(cache_hours, 6),
            )
            feat["news_summary"] = format_news_summary(news_data)
            feat["news_sentiment"] = (news_data or {}).get("news_sentiment", "no_news")
        except Exception as e:
            feat["news_summary"] = "No recent news"
            feat["news_sentiment"] = "no_news"
            logger.debug("[ENRICHMENT] News failed for %s: %s", ticker, e)

        # Earnings signals (PEAD enrichment)
        try:
            from src.data_enrichment.earnings_signals import compute_earnings_signals
            earnings = compute_earnings_signals(ticker)
            feat["earnings_signals"] = earnings
            if earnings.get("include_in_prompt"):
                logger.debug("[ENRICHMENT] Earnings context for %s (proximity: %s days, strength: %s)",
                             ticker, earnings.get("earnings_proximity_days"), earnings.get("earnings_signal_strength"))
        except Exception as e:
            feat["earnings_signals"] = {"include_in_prompt": False}
            logger.debug("[ENRICHMENT] Earnings signals failed for %s: %s", ticker, e)

        enriched_count += 1

    logger.info(
        "[ENRICHMENT] Enriched %d/%d tickers (%d missing fundamentals, %d missing insider data)",
        enriched_count, total, missing_fundamentals, missing_insiders,
    )

    return features
