"""Plan-gated Finnhub press releases collector.

Called by: scheduler/overnight.py (nightly tick, plan-gated)
Calls: data_enrichment.finnhub_plan, utils.db, config
Owns tables: press_releases
Config keys: data_enrichment.finnhub_plan, FINNHUB_PLAN, FINNHUB_API_KEY
Tests: tests/data_collection/test_press_releases_collector.py

Sprint 5 Wave C7b.3 / T23.

API: Finnhub /press-releases (paid fundamental-1 endpoint)
Table: press_releases (UPSERT on (ticker, headline, released_at))
Schedule: Nightly tick from run_data_collection in overnight.py.

Decision 27: press releases are a DISTINCT catalyst category from RECENT
NEWS — keep tables + renderers separate. This collector never touches
the news collectors; the data lands in MATERIAL EVENTS, not RECENT NEWS.

Gate: finnhub_plan_supports('press_releases', config). Returns None when
the plan does not support the feature — no API call is attempted (avoids
the 403-burn on free-tier keys per Decision 30).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import requests

from src.config import DB_PATH
from src.data_collection._finnhub_shared import get_finnhub_key as _get_finnhub_key
from src.data_enrichment.finnhub_plan import finnhub_plan_supports
from src.utils.db import connect_db, engine_aware_upsert
from src.utils.retry import retry_with_backoff

logger = logging.getLogger(__name__)

FINNHUB_BASE = "https://finnhub.io/api/v1"


def _fetch_finnhub_press_releases(ticker: str, api_key: str) -> list[dict] | None:
    """Single Finnhub call with retry; returns the press release list or None."""
    try:
        resp = retry_with_backoff(
            lambda: requests.get(
                f"{FINNHUB_BASE}/press-releases",
                params={"symbol": ticker},
                headers={"X-Finnhub-Token": api_key},
                timeout=15,
            ),
            max_retries=3, base_delay=2.0,
            exceptions=(requests.RequestException, ConnectionError, OSError),
        )
        if resp is None:
            logger.warning("[PRESS_REL] Failed to fetch %s after retries", ticker)
            return None
        resp.raise_for_status()
        payload = resp.json() or {}
    except Exception as exc:
        logger.warning("[PRESS_REL] Fetch failed for %s: %s", ticker, exc)
        return None
    # Finnhub keys press releases under 'majorDevelopment' (legacy) or 'data'.
    return payload.get("majorDevelopment") or payload.get("data") or []


def _row_from_press_release(pr: dict, ticker: str) -> dict | None:
    """Build a press_releases row from one Finnhub press release dict, or
    None when the entry lacks the minimum (headline + released_at)."""
    headline = pr.get("headline") or pr.get("title")
    released_at = pr.get("datetime") or pr.get("released_at") or pr.get("publishedDate")
    if not headline or not released_at:
        return None
    return {
        "ticker": ticker,
        "headline": str(headline),
        "released_at": str(released_at),
        "url": pr.get("url"),
        "description": pr.get("description") or pr.get("summary"),
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
    }


def collect_press_releases(
    ticker: str,
    config: dict | None = None,
    db_path: str = DB_PATH,
) -> list[dict] | None:
    """Collect press releases for one ticker (plan-gated).

    On entry: when ``finnhub_plan_supports('press_releases', config)`` is
    False, log INFO and return None — no API call (Decision 30).

    Otherwise: call Finnhub /press-releases and UPSERT one row per release
    into ``press_releases`` keyed by (ticker, headline, released_at).

    Returns the list of inserted row dicts on success, or None when
    plan-gated off / when the API call fails / when the response is empty.
    """
    if not finnhub_plan_supports("press_releases", config):
        logger.info(
            "[PRESS_REL] Skipped %s — Finnhub plan does not support "
            "press_releases", ticker,
        )
        return None

    api_key = _get_finnhub_key()
    if not api_key:
        from src.data_collection.errors import CollectorConfigError
        raise CollectorConfigError(
            "FINNHUB_API_KEY not configured — set in .env or "
            "config/settings.local.yaml"
        )

    releases = _fetch_finnhub_press_releases(ticker, api_key)
    if not releases:
        if releases is not None:
            logger.info("[PRESS_REL] No releases returned for %s", ticker)
        return None

    rows: list[dict] = []
    with connect_db(db_path) as conn:
        for pr in releases:
            row = _row_from_press_release(pr, ticker)
            if row is None:
                continue
            engine_aware_upsert(conn, "press_releases", row, action="ignore")
            rows.append(row)
        conn.commit()
    if rows:
        logger.info(
            "[PRESS_REL] %s: %d release(s) written", ticker, len(rows),
        )
    return rows or None
