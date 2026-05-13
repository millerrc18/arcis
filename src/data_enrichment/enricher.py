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
from datetime import datetime, timedelta, timezone
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

# Sprint 5 Wave C7a.3 / T19 — default lookback window (days) for recent
# attribution-trade aggregation. Overridable via
# ``config['data_enrichment']['attribution_window_days']`` at call time.
_RECENT_ATTRIBUTION_DEFAULT_WINDOW_DAYS = 30


def _setup_class_win_rate(conn, setup_class: str, cutoff_iso: str) -> float | None:
    """T19 helper: PASS-rate of closed setup-class attribution trades in window."""
    rows = conn.execute(
        "SELECT a.llm_portfolio_pnl_pct AS pnl FROM attribution_trades a "
        "LEFT JOIN recommendations r ON a.recommendation_id = r.recommendation_id "
        "WHERE a.created_at >= ? AND a.llm_portfolio_pnl_pct IS NOT NULL "
        "AND r.setup_type = ?",
        (cutoff_iso, setup_class),
    ).fetchall()
    if not rows:
        return None
    n_wins = sum(1 for r in rows if (r["pnl"] or 0) > 0)
    return n_wins / len(rows)


def _ticker_mean_pnl(conn, ticker: str, cutoff_iso: str) -> float | None:
    """T19 helper: mean ``llm_portfolio_pnl_pct`` for the ticker in window."""
    rows = conn.execute(
        "SELECT llm_portfolio_pnl_pct AS pnl FROM attribution_trades "
        "WHERE ticker = ? AND created_at >= ? "
        "AND llm_portfolio_pnl_pct IS NOT NULL",
        (ticker, cutoff_iso),
    ).fetchall()
    if not rows:
        return None
    return sum(r["pnl"] for r in rows) / len(rows)


def _similar_sector_mean_pnl(
    conn, sector: str, ticker: str, cutoff_iso: str
) -> float | None:
    """T19 helper: mean PnL for same-sector tickers in window (excluding self)."""
    rows = conn.execute(
        "SELECT a.llm_portfolio_pnl_pct AS pnl FROM attribution_trades a "
        "LEFT JOIN recommendations r ON a.recommendation_id = r.recommendation_id "
        "WHERE a.created_at >= ? AND a.llm_portfolio_pnl_pct IS NOT NULL "
        "AND r.sector_context = ? AND a.ticker != ?",
        (cutoff_iso, sector, ticker),
    ).fetchall()
    if not rows:
        return None
    return sum(r["pnl"] for r in rows) / len(rows)


def enrich_recent_attribution(
    feat: dict,
    ticker: str,
    db_path: str = DB_PATH,
    window_days: int = _RECENT_ATTRIBUTION_DEFAULT_WINDOW_DAYS,
) -> None:
    """Populate recent-attribution feature-dict fields from closed paired trades.

    Sprint 5 Wave C7a.3 / T19. Reads ``attribution_trades`` joined to
    ``recommendations`` for the last ``window_days`` and computes:

      * ``recent_setup_win_rate`` — fraction of closed trades whose
        ``llm_portfolio_pnl_pct`` > 0, filtered by ``feat['setup_class']``.
      * ``recent_ticker_pnl`` — mean ``llm_portfolio_pnl_pct`` for the ticker.
      * ``recent_similar_pnl_30d`` — mean ``llm_portfolio_pnl_pct`` for trades
        in the same sector (``feat['sector']``) excluding the current ticker.

    Closed trades only: rows where ``llm_portfolio_pnl_pct IS NOT NULL``.
    No-recent-trades: feature dict left unchanged; renderer falls back.
    """
    setup_class = feat.get("setup_class")
    sector = feat.get("sector")
    cutoff_iso = (
        datetime.now(timezone.utc) - timedelta(days=window_days)
    ).isoformat()
    try:
        with connect_db(db_path) as conn:
            conn.row_factory = sqlite3.Row
            if setup_class:
                wr = _setup_class_win_rate(conn, setup_class, cutoff_iso)
                if wr is not None:
                    feat["recent_setup_win_rate"] = wr
            tp = _ticker_mean_pnl(conn, ticker, cutoff_iso)
            if tp is not None:
                feat["recent_ticker_pnl"] = tp
            if sector:
                sp = _similar_sector_mean_pnl(conn, sector, ticker, cutoff_iso)
                if sp is not None:
                    feat["recent_similar_pnl_30d"] = sp
    except Exception as exc:
        logger.debug("[ENRICHMENT] Recent attribution read failed: %s", exc)


def enrich_strategy_context(feat: dict, db_path: str = DB_PATH) -> None:
    """Populate strategy-context preamble feature-dict fields.

    Sprint 5 Wave C7a.4 / T20. Reads ``strategy_registry`` keyed by the
    ``strategy_id`` FK present on shadow_trades (added by T2 / #56) and writes:

      * ``strategy_status`` — current_status from registry (e.g. production,
        shadow_trading, deprecated)
      * ``strategy_parent_name`` — display_name from registry

    NULL-strategy_id (legacy trades pre-dating T2 wiring): leaves the registry
    fields unset; the renderer detects via ``feat.get('strategy_id')`` and
    falls back to ``(unassigned - legacy trade)``.

    Args:
        feat: Per-ticker feature dict (mutated in place). Reads ``strategy_id``.
        db_path: SQLite DB path. Defaults to runtime DB.
    """
    strategy_id = feat.get("strategy_id")
    if not strategy_id:
        return
    try:
        with connect_db(db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT display_name, current_status FROM strategy_registry "
                "WHERE strategy_id = ? LIMIT 1",
                (strategy_id,),
            ).fetchone()
            if row:
                feat["strategy_status"] = row["current_status"]
                feat["strategy_parent_name"] = row["display_name"]
    except Exception as exc:
        logger.debug("[ENRICHMENT] Strategy context read failed: %s", exc)


def enrich_historical_credibility(feat: dict, db_path: str = DB_PATH) -> None:
    """Populate walk-forward historical credibility feature-dict fields.

    Sprint 5 Wave C7a.2 / T18. Reads ``walkforward_results`` for runs matching
    ``feat['strategy_id']`` and aggregates a credibility prior:

      * ``setup_walkforward_n_votes`` — count of walk-forward runs found
      * ``setup_walkforward_credibility`` — fraction of PASS runs / total
      * ``setup_psr_pass`` / ``setup_cpcv_pass`` — derived from most recent
        ``outcome_state`` (PASS → both pass; FAIL/INCONCLUSIVE → both fail).
        The schema does not store per-method (PSR vs CPCV) vote outcomes, so
        the renderer surfaces them jointly from the aggregate outcome_state.

    No-match: feature dict is left unchanged; the renderer detects via the
    absence of ``setup_walkforward_n_votes`` and renders the empty-state line.

    Args:
        feat: Per-ticker feature dict (mutated in place). Must already contain
            ``strategy_id`` for the lookup to fire.
        db_path: SQLite DB path. Defaults to runtime DB.
    """
    strategy_id = feat.get("strategy_id")
    if not strategy_id:
        return
    try:
        with connect_db(db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT outcome_state, created_at FROM walkforward_results "
                "WHERE strategy_id = ? ORDER BY created_at DESC",
                (strategy_id,),
            ).fetchall()
            if not rows:
                return
            n_total = len(rows)
            n_pass = sum(1 for r in rows if r["outcome_state"] == "PASS")
            feat["setup_walkforward_n_votes"] = n_total
            feat["setup_walkforward_credibility"] = n_pass / n_total
            latest_pass = rows[0]["outcome_state"] == "PASS"
            feat["setup_psr_pass"] = latest_pass
            feat["setup_cpcv_pass"] = latest_pass
    except Exception as exc:
        logger.debug("[ENRICHMENT] Historical credibility read failed: %s", exc)


def enrich_institutional_flow(
    feat: dict,
    ticker: str,
    config: dict | None = None,
    db_path: str = DB_PATH,
) -> None:
    """Populate INSTITUTIONAL FLOW feature-dict fields (Sprint 5 Wave C7b.1 / T21).

    Always sets ``_institutional_plan_supports`` so the renderer can decide
    between (a) absent section (plan-gated off, Decision 30), (b) empty-state
    line (plan supports but no data yet), and (c) full render (data present).

    When plan supports + a row exists in ``institutional_holdings``, populates
    ``institutional_total_shares``, ``institutional_num_holders``,
    ``institutional_top5_pct``, ``institutional_qoq_delta_pct``,
    ``institutional_data_age_days``.

    The enricher only READS — it never calls the Finnhub API. The collector
    runs nightly in the overnight pipeline.
    """
    from src.data_enrichment.finnhub_plan import finnhub_plan_supports

    supports = finnhub_plan_supports("institutional_ownership", config)
    feat["_institutional_plan_supports"] = supports
    if not supports:
        return
    try:
        with connect_db(db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT total_shares, num_holders, top_5_holders_pct, "
                "qoq_delta_pct, as_of_date FROM institutional_holdings "
                "WHERE ticker = ? ORDER BY as_of_date DESC LIMIT 1",
                (ticker,),
            ).fetchone()
            if not row:
                return
            feat["institutional_total_shares"] = row["total_shares"]
            feat["institutional_num_holders"] = row["num_holders"]
            feat["institutional_top5_pct"] = row["top_5_holders_pct"]
            feat["institutional_qoq_delta_pct"] = row["qoq_delta_pct"]
            try:
                as_of = datetime.fromisoformat(str(row["as_of_date"]))
                if as_of.tzinfo is None:
                    as_of = as_of.replace(tzinfo=timezone.utc)
                feat["institutional_data_age_days"] = max(
                    0, (datetime.now(timezone.utc) - as_of).days
                )
            except (ValueError, TypeError):
                feat["institutional_data_age_days"] = None
    except Exception as exc:
        logger.debug("[ENRICHMENT] Institutional flow read failed: %s", exc)


def enrich_filings_sentiment(
    feat: dict,
    ticker: str,
    config: dict | None = None,
    db_path: str = DB_PATH,
) -> None:
    """Populate filings_sentiment feature-dict fields (Sprint 5 Wave C7b.2 / T22).

    Always sets ``_filings_sentiment_plan_supports`` so the MATERIAL EVENTS
    section renderer can decide between (a) sub-block absent (plan-gated off,
    Decision 30), and (b) full render (data present).

    When plan supports + a row exists in ``filings_sentiment``, populates
    ``filing_sentiment_score``, ``filing_sentiment_label``,
    ``latest_filing_type``, ``latest_filing_age_days``.

    The enricher only READS — it never calls the Finnhub API. The collector
    runs nightly in the overnight pipeline.
    """
    from src.data_enrichment.finnhub_plan import finnhub_plan_supports

    supports = finnhub_plan_supports("filings_sentiment", config)
    feat["_filings_sentiment_plan_supports"] = supports
    if not supports:
        return
    try:
        with connect_db(db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT filing_type, filed_at, sentiment_score, sentiment_label "
                "FROM filings_sentiment WHERE ticker = ? "
                "ORDER BY filed_at DESC LIMIT 1",
                (ticker,),
            ).fetchone()
            if not row:
                return
            feat["filing_sentiment_score"] = row["sentiment_score"]
            feat["filing_sentiment_label"] = row["sentiment_label"]
            feat["latest_filing_type"] = row["filing_type"]
            try:
                filed = datetime.fromisoformat(str(row["filed_at"]).replace(" ", "T"))
                if filed.tzinfo is None:
                    filed = filed.replace(tzinfo=timezone.utc)
                feat["latest_filing_age_days"] = max(
                    0, (datetime.now(timezone.utc) - filed).days
                )
            except (ValueError, TypeError):
                feat["latest_filing_age_days"] = None
    except Exception as exc:
        logger.debug("[ENRICHMENT] Filings sentiment read failed: %s", exc)


def enrich_stock_financials(
    feat: dict,
    ticker: str,
    config: dict | None = None,
) -> None:
    """Populate fundamental_* live-enrichment fields (T24).

    Sprint 5 Wave C7b.4. Reads the per-ticker JSON sink left by
    scripts/finnhub_fundamental_export.py via
    ``src.data_enrichment.financials.load_stock_financials`` and writes
    ``fundamental_pe`` / ``fundamental_debt_to_equity`` /
    ``fundamental_gross_margin`` / ``fundamental_roic`` /
    ``fundamental_quality_flag`` / ``fundamental_snapshot_age_days``
    into the feature dict. The renderer surfaces these inside the
    FUNDAMENTAL SNAPSHOT section as a live trailer; the existing
    SEC-EDGAR ``fundamental_summary`` fallback is preserved untouched.

    Always sets ``_stock_financials_plan_supports`` so the DATA CONTEXT
    header can distinguish plan-gated absence (Decision 30) from a
    transient data gap (sink JSON missing despite plan supporting).
    Plan-gated: when plan does not support stock_financials, no
    fundamental_* fields are written and the renderer's live trailer
    degrades to "".
    """
    from src.data_enrichment.financials import load_stock_financials
    from src.data_enrichment.finnhub_plan import finnhub_plan_supports

    supports = finnhub_plan_supports("stock_financials", config)
    feat["_stock_financials_plan_supports"] = supports
    if not supports:
        return
    result = load_stock_financials(ticker, config=config)
    if result is None:
        return
    feat.update(result)


def enrich_press_releases(
    feat: dict,
    ticker: str,
    config: dict | None = None,
    db_path: str = DB_PATH,
) -> None:
    """Populate press_releases feature-dict fields (Sprint 5 Wave C7b.3 / T23).

    Always sets ``_press_releases_plan_supports`` so the MATERIAL EVENTS
    section renderer can decide between (a) sub-block absent (plan-gated off,
    Decision 30), and (b) full render (data present).

    When plan supports + rows exist in ``press_releases``, populates:
      * ``press_release_count_7d`` — count of releases in the last 7 days
      * ``latest_press_release_headline`` — headline of the most recent
      * ``latest_press_release_age_days`` — age of most recent (days)

    The enricher only READS — it never calls the Finnhub API. The collector
    runs nightly in the overnight pipeline.
    """
    from src.data_enrichment.finnhub_plan import finnhub_plan_supports

    supports = finnhub_plan_supports("press_releases", config)
    feat["_press_releases_plan_supports"] = supports
    if not supports:
        return
    try:
        with connect_db(db_path) as conn:
            conn.row_factory = sqlite3.Row
            cutoff_iso = (
                datetime.now(timezone.utc) - timedelta(days=7)
            ).isoformat()
            count_row = conn.execute(
                "SELECT COUNT(*) AS n FROM press_releases "
                "WHERE ticker = ? AND released_at >= ?",
                (ticker, cutoff_iso),
            ).fetchone()
            if count_row is not None:
                feat["press_release_count_7d"] = int(count_row["n"] or 0)
            latest = conn.execute(
                "SELECT headline, released_at FROM press_releases "
                "WHERE ticker = ? ORDER BY released_at DESC LIMIT 1",
                (ticker,),
            ).fetchone()
            if not latest:
                return
            feat["latest_press_release_headline"] = latest["headline"]
            try:
                released = datetime.fromisoformat(
                    str(latest["released_at"]).replace(" ", "T")
                )
                if released.tzinfo is None:
                    released = released.replace(tzinfo=timezone.utc)
                feat["latest_press_release_age_days"] = max(
                    0, (datetime.now(timezone.utc) - released).days
                )
            except (ValueError, TypeError):
                feat["latest_press_release_age_days"] = None
    except Exception as exc:
        logger.debug("[ENRICHMENT] Press releases read failed: %s", exc)


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
