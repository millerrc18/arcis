"""Data enrichment orchestrator.

Called by: scheduler/watch.py, services/scan_service.py
Calls: data_enrichment/earnings_signals.py, data_enrichment/fundamentals.py, data_enrichment/insiders.py, data_enrichment/macro.py, data_enrichment/news.py
Owns tables: none
Config keys: cache_hours, data_enrichment, enabled, finnhub_api_key, fred_api_key, insider_lookback_days
Tests: tests/test_enrichment.py

Adds fundamental, insider, and macro data to all ticker feature dicts.
Called AFTER compute_all_features and BEFORE ranking/packet generation.
"""

from __future__ import annotations

import logging
import os
import sqlite3
import time
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from src.config import DB_PATH
from src.utils.db import connect_db

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from src.platform.strategy_spec import StrategySpec

# Sprint 5 Wave C7a.1 / T17 — pillar agent_name → feature-dict key mapping.
# The council writes one vote row per pillar per session; the LLM packet
# needs each pillar's position surfaced as a separate feature field.
_COUNCIL_PILLAR_KEY = {
    "macro_pillar": "council_macro_vote",
    "strategic_pillar": "council_strategic_vote",
    "tactical_pillar": "council_tactical_vote",
    "innovation_pillar": "council_innovation_vote",
    "risk_pillar": "council_risk_vote",
}

# Sprint 5 Wave C7a.1 / T17 — staleness threshold (days). Sessions older than
# this are still rendered but tagged [STALE] so the LLM downweights them.
_COUNCIL_STALE_THRESHOLD_DAYS = 3


def enrich_council_consensus(feat: dict, db_path: str = DB_PATH) -> None:
    """Populate council-consensus feature-dict fields from the latest session.

    Reads the most recent ``council_sessions`` row (by ``created_at``), joins
    ``council_votes`` per pillar (macro/strategic/tactical/innovation/risk), and
    writes the 5 vote fields + ``council_session_id``, ``council_consensus_score``,
    ``council_session_age_days`` into ``feat``.

    Missing session: ``feat`` is left empty for these keys; callers detect via
    ``council_session_id is None`` and render the empty-state message.

    Stale: no in-DB suppression — the renderer appends ``[STALE]`` when age
    exceeds ``_COUNCIL_STALE_THRESHOLD_DAYS``.

    Args:
        feat: Per-ticker feature dict (mutated in place).
        db_path: SQLite DB path. Defaults to runtime DB.
    """
    try:
        with connect_db(db_path) as conn:
            conn.row_factory = sqlite3.Row
            sess = conn.execute(
                "SELECT session_id, created_at, confidence_weighted_score "
                "FROM council_sessions ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
            if not sess:
                return
            session_id = sess["session_id"]
            feat["council_session_id"] = session_id
            feat["council_consensus_score"] = sess["confidence_weighted_score"]

            created = sess["created_at"]
            try:
                created_dt = datetime.fromisoformat(created)
                if created_dt.tzinfo is None:
                    created_dt = created_dt.replace(tzinfo=timezone.utc)
                age = (datetime.now(timezone.utc) - created_dt).days
                feat["council_session_age_days"] = max(0, age)
            except (ValueError, TypeError):
                feat["council_session_age_days"] = None

            votes = conn.execute(
                "SELECT agent_name, position FROM council_votes "
                "WHERE session_id = ?",
                (session_id,),
            ).fetchall()
            for row in votes:
                key = _COUNCIL_PILLAR_KEY.get(row["agent_name"])
                if key:
                    feat[key] = row["position"]
    except Exception as exc:
        logger.debug("[ENRICHMENT] Council consensus read failed: %s", exc)

_missing_key_alerts_sent: set[str] = set()

# Per-API rate tracking (#133)
_last_request_time: dict[str, float] = {}

# Minimum interval between requests per API (seconds)
_RATE_LIMITS: dict[str, float] = {
    "finnhub": 1.0,
    "sec": 0.1,
}


def _rate_limit(api_name: str, min_interval: float | None = None) -> None:
    """Sleep if needed to enforce minimum interval between API calls."""
    interval = min_interval or _RATE_LIMITS.get(api_name, 1.0)
    now = time.time()
    last = _last_request_time.get(api_name, 0)
    if now - last < interval:
        time.sleep(interval - (now - last))
    _last_request_time[api_name] = time.time()


def _alert_missing_key(key_name: str) -> None:
    """Send a one-time Telegram alert for a missing API key."""
    if key_name in _missing_key_alerts_sent:
        return
    _missing_key_alerts_sent.add(key_name)
    try:
        from src.notifications.telegram import send_telegram
        send_telegram(f"\u26a0\ufe0f Missing API key: <b>{key_name}</b> \u2014 data collection degraded")
    except Exception as exc:
        # #545 \u2014 Don't silently swallow Telegram alert failures; debug-log
        # so the operator can see when the warning channel itself is broken.
        logger.debug("[ENRICHER] Telegram alert for missing key %s failed: %s", key_name, exc)


def enrich_features(
    features: dict[str, dict],
    config: dict,
    strategy: "StrategySpec" | None = None,
    as_of: str | None = None,
    warnings_out: list[str] | None = None,
) -> dict[str, dict]:
    """Add fundamental, insider, and macro data to all ticker feature dicts.

    Fetches data with caching and rate limiting. Never crashes —
    returns features unchanged if enrichment fails.

    ``as_of`` (Sprint 1.C Phase 2 PIT wiring #854-#859) routes sections
    4/5/6/7/10 to point-in-time historical lookups when set; section 11
    has no live producer (#870 pending). ``warnings_out`` (#99) is an
    optional list forwarded to every fetcher's ``warnings`` arg so the
    corpus generator can record per-decision warnings on the
    ``CorpusEntry`` and aggregate prefixes into
    ``CorpusManifest.coverage_limit_hits``.
    """
    enrichment_cfg = config.get("data_enrichment", {})
    if not enrichment_cfg.get("enabled", True):
        logger.info("[ENRICHMENT] Data enrichment disabled in config")
        return features

    chain = _strategy_enrichment_chain(strategy)
    macro_enabled = chain is None or "macro" in chain
    insider_enabled = chain is None or "insider" in chain
    news_enabled = chain is None or "news" in chain
    from src.data_enrichment.finnhub_plan import finnhub_plan_supports

    cache_hours = enrichment_cfg.get("cache_hours", 24)
    finnhub_key = os.environ.get("FINNHUB_API_KEY") or enrichment_cfg.get("finnhub_api_key")
    fred_key = os.environ.get("FRED_API_KEY") or enrichment_cfg.get("fred_api_key")
    lookback_days = enrichment_cfg.get("insider_lookback_days", 90)
    use_premium_news_sentiment = (
        as_of is None and finnhub_plan_supports("news_sentiment", config)
    )

    if not finnhub_key:
        _alert_missing_key("FINNHUB_API_KEY")
    if not fred_key:
        _alert_missing_key("FRED_API_KEY")

    # 1. Fetch macro context ONCE (shared across all tickers)
    # #855 / Sprint 1.C Phase 2: when as_of is set, route to PIT FRED
    # lookup (observation_end=as_of) so the LLM doesn't see future macro
    # data through the prompt. When None, behavior unchanged.
    macro_summary = "No macro data available"
    if macro_enabled:
        try:
            from src.data_enrichment.macro import fetch_macro_context, format_macro_summary
            macro_data = fetch_macro_context(
                fred_api_key=fred_key,
                cache_hours=cache_hours,
                as_of=as_of,
                warnings=warnings_out,
            )
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
        if macro_enabled:
            feat["macro_summary"] = macro_summary

        # Fundamental data
        # #856 / Sprint 1.C Phase 2: when as_of is set, route SEC XBRL
        # lookup to PIT mode — filter entries by `filed <= as_of` BEFORE
        # sorting, then sort by `filed` desc (period-end secondary). This
        # closes the audit's #1 high-severity finding (sort by `end` not
        # `filed`). When as_of is None, runtime behavior unchanged.
        try:
            from src.data_enrichment.fundamentals import (
                fetch_fundamental_snapshot,
                format_fundamental_summary,
            )
            fund_data = fetch_fundamental_snapshot(
                ticker, cache_hours=cache_hours, as_of=as_of,
                warnings=warnings_out,
            )
            price = feat.get("current_price")
            feat["fundamental_summary"] = format_fundamental_summary(fund_data, price)
            if fund_data is None:
                missing_fundamentals += 1
            _rate_limit("sec")
        except Exception as e:
            feat["fundamental_summary"] = "No fundamental data available"
            missing_fundamentals += 1
            logger.debug("[ENRICHMENT] Fundamentals failed for %s: %s", ticker, e)

        # Insider data
        # #857 / Sprint 1.C Phase 2: when as_of is set, route insider fetch
        # to the PIT-aware path (window = [as_of - lookback, as_of] + cache
        # keyed by as_of). When as_of is None, runtime behavior unchanged.
        if insider_enabled:
            try:
                from src.data_enrichment.insiders import (
                    fetch_insider_activity,
                    format_insider_summary,
                )
                _rate_limit("finnhub")
                insider_data = fetch_insider_activity(
                    ticker,
                    lookback_days=lookback_days,
                    finnhub_api_key=finnhub_key,
                    cache_hours=cache_hours,
                    as_of=as_of,
                    warnings=warnings_out,
                )
                feat["insider_summary"] = format_insider_summary(insider_data)
                if insider_data is None:
                    missing_insiders += 1
            except Exception as e:
                feat["insider_summary"] = "No insider data available"
                missing_insiders += 1
                logger.debug("[ENRICHMENT] Insiders failed for %s: %s", ticker, e)

        # News data
        # #854 / Sprint 1.C Phase 2: when as_of is set, route to
        # fetch_historical_news (TEMPORAL COMPLIANCE) instead of
        # fetch_recent_news ("now" data leak for historical decisions).
        # The PIT-clean function already exists in news.py:200; this is
        # just the wiring.
        if news_enabled:
            try:
                from src.data_enrichment.news import (
                    fetch_historical_news,
                    fetch_news_sentiment,
                    fetch_recent_news,
                    format_news_summary,
                )
                _rate_limit("finnhub")
                if as_of is not None:
                    news_data = fetch_historical_news(
                        ticker,
                        as_of_date=as_of,
                        finnhub_api_key=finnhub_key,
                        cache_hours=min(cache_hours, 24),
                        warnings=warnings_out,
                    )
                else:
                    news_data = fetch_recent_news(
                        ticker,
                        finnhub_api_key=finnhub_key,
                        cache_hours=min(cache_hours, 6),
                        warnings=warnings_out,
                    )
                    if news_data and use_premium_news_sentiment:
                        premium_sentiment = fetch_news_sentiment(
                            ticker,
                            finnhub_api_key=finnhub_key,
                            cache_hours=min(cache_hours, 6),
                            warnings=warnings_out,
                        )
                        if premium_sentiment:
                            news_data["headline_sentiment"] = news_data.get("news_sentiment")
                            news_data["news_sentiment"] = premium_sentiment["news_sentiment"]
                            news_data["news_sentiment_source"] = "finnhub"
                            news_data["finnhub_news_sentiment"] = premium_sentiment
                            summary = news_data.get("summary", "")
                            premium_summary = premium_sentiment.get("summary", "")
                            if premium_summary:
                                news_data["summary"] = (
                                    f"{summary} {premium_summary}".strip()
                                    if summary else premium_summary
                                )
                feat["news_summary"] = format_news_summary(news_data)
                feat["news_sentiment"] = (news_data or {}).get("news_sentiment", "no_news")
            except Exception as e:
                feat["news_summary"] = "No recent news"
                feat["news_sentiment"] = "no_news"
                logger.debug("[ENRICHMENT] News failed for %s: %s", ticker, e)

        # Earnings signals (PEAD enrichment)
        # #859 / Sprint 1.C Phase 2: when as_of is set, route the
        # earnings_calendar + analyst_estimates queries through PIT semantics
        # (date(?) bind + collected_at <= as_of filter) so historical decision
        # points don't see future earnings dates / analyst revisions.
        try:
            from src.data_enrichment.earnings_signals import compute_earnings_signals
            earnings = compute_earnings_signals(ticker, as_of=as_of, warnings=warnings_out)
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


def _strategy_enrichment_chain(strategy: "StrategySpec" | None) -> set[str] | None:
    if strategy is None:
        return None
    raw = getattr(strategy, "raw", {}) or {}
    enrichment = raw.get("enrichment")
    if not isinstance(enrichment, dict):
        return None
    chain = enrichment.get("chain")
    if not isinstance(chain, list) or not chain:
        return None
    return {item for item in chain if isinstance(item, str) and item}
