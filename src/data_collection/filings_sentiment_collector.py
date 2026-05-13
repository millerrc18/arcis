"""Plan-gated Finnhub filings sentiment collector.

Called by: scheduler/overnight.py (nightly tick, plan-gated)
Calls: data_enrichment.finnhub_plan, utils.db, config
Owns tables: filings_sentiment
Config keys: data_enrichment.finnhub_plan, FINNHUB_PLAN, FINNHUB_API_KEY
Tests: tests/data_collection/test_filings_sentiment_collector.py

Sprint 5 Wave C7b.2 / T22.

API: Finnhub /stock/filings-sentiment (paid fundamental-1 endpoint)
Table: filings_sentiment (UPSERT on (ticker, filing_type, filed_at))
Schedule: Nightly tick from run_data_collection in overnight.py.

Decision 27: filings_sentiment is a DISTINCT retrieval cadence from
edgar_filings — keep tables + collectors separate. This collector never
touches edgar_filings.

Gate: finnhub_plan_supports('filings_sentiment', config). Returns None when
the plan does not support the feature — no API call is attempted (avoids the
403-burn on free-tier keys per Decision 30).
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone

import requests

from src.config import DB_PATH
from src.data_enrichment.finnhub_plan import finnhub_plan_supports
from src.utils.db import connect_db, engine_aware_upsert
from src.utils.retry import retry_with_backoff

logger = logging.getLogger(__name__)

FINNHUB_BASE = "https://finnhub.io/api/v1"


def _get_finnhub_key() -> str | None:
    """Get Finnhub API key. .env takes precedence over YAML config."""
    env_key = os.environ.get("FINNHUB_API_KEY")
    if env_key:
        return env_key
    try:
        from src.config import load_config
        config = load_config()
        return config.get("data_enrichment", {}).get("finnhub_api_key")
    except Exception:
        return None


def _fetch_finnhub_filings_sentiment(ticker: str, api_key: str) -> list[dict] | None:
    """Single Finnhub call with retry; returns the sentiment list or None."""
    try:
        resp = retry_with_backoff(
            lambda: requests.get(
                f"{FINNHUB_BASE}/stock/filings-sentiment",
                params={"symbol": ticker},
                headers={"X-Finnhub-Token": api_key},
                timeout=15,
            ),
            max_retries=3, base_delay=2.0,
            exceptions=(requests.RequestException, ConnectionError, OSError),
        )
        if resp is None:
            logger.warning("[FILINGS_SENT] Failed to fetch %s after retries", ticker)
            return None
        resp.raise_for_status()
        payload = resp.json() or {}
    except Exception as exc:
        logger.warning("[FILINGS_SENT] Fetch failed for %s: %s", ticker, exc)
        return None
    return payload.get("sentiment") or payload.get("data") or []


def _label_from_score(score: float | None) -> str | None:
    """Map a numeric sentiment score in [-1.0, 1.0] to a coarse label.

    Thresholds match the convention used elsewhere in the enricher:
      * score >  0.1 → 'positive'
      * score < -0.1 → 'negative'
      * otherwise    → 'neutral'
    """
    if not isinstance(score, (int, float)):
        return None
    if score > 0.1:
        return "positive"
    if score < -0.1:
        return "negative"
    return "neutral"


def _row_from_filing(filing: dict, ticker: str) -> dict | None:
    """Build a filings_sentiment row from one Finnhub filing dict, or None
    when the filing lacks the minimum (filing_type + filed_at)."""
    filing_type = filing.get("type") or filing.get("filing_type")
    filed_at = filing.get("filedDate") or filing.get("filed_at")
    if not filing_type or not filed_at:
        return None
    sentiment = filing.get("sentiment") or {}
    if isinstance(sentiment, dict):
        score = sentiment.get("score")
    else:
        score = sentiment
    try:
        score = float(score) if score is not None else None
    except (TypeError, ValueError):
        score = None
    return {
        "ticker": ticker,
        "filing_type": str(filing_type),
        "filed_at": str(filed_at),
        "sentiment_score": score,
        "sentiment_label": _label_from_score(score),
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
    }


def collect_filings_sentiment(
    ticker: str,
    config: dict | None = None,
    db_path: str = DB_PATH,
) -> list[dict] | None:
    """Collect filings sentiment snapshots for one ticker (plan-gated).

    On entry: when ``finnhub_plan_supports('filings_sentiment', config)`` is
    False, log INFO and return None — no API call (Decision 30).

    Otherwise: call Finnhub /stock/filings-sentiment and UPSERT one row per
    filing into ``filings_sentiment`` keyed by (ticker, filing_type, filed_at).

    Returns the list of inserted row dicts on success, or None when plan-gated
    off / when the API call fails / when the response is empty.
    """
    if not finnhub_plan_supports("filings_sentiment", config):
        logger.info(
            "[FILINGS_SENT] Skipped %s — Finnhub plan does not support "
            "filings_sentiment", ticker,
        )
        return None

    api_key = _get_finnhub_key()
    if not api_key:
        from src.data_collection.errors import CollectorConfigError
        raise CollectorConfigError(
            "FINNHUB_API_KEY not configured — set in .env or "
            "config/settings.local.yaml"
        )

    filings = _fetch_finnhub_filings_sentiment(ticker, api_key)
    if not filings:
        if filings is not None:
            logger.info("[FILINGS_SENT] No filings returned for %s", ticker)
        return None

    rows: list[dict] = []
    with connect_db(db_path) as conn:
        for filing in filings:
            row = _row_from_filing(filing, ticker)
            if row is None:
                continue
            engine_aware_upsert(conn, "filings_sentiment", row, action="ignore")
            rows.append(row)
        conn.commit()
    if rows:
        logger.info(
            "[FILINGS_SENT] %s: %d filing(s) written (types=%s)",
            ticker, len(rows), sorted({r["filing_type"] for r in rows}),
        )
    return rows or None
