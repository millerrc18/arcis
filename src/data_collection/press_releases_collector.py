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

Gate: finnhub_plan_supports('press_releases', config). Returns a healthy
CollectorResult with primary_count 0 and metadata {'gated': 1} when the plan
does not support the feature — no API call is attempted (avoids the 403-burn
on free-tier keys per Decision 30).

PR-D T22 (DD-15 r3 + kin #23): migrated list[dict]/None → CollectorResult. This
is a PAIRED migration concern with its only consumer, scheduler/overnight.py::
_run_plan_gated_collector, whose `collector_fn(...) is not None` mass-failure
detector would silently break against an always-non-None CollectorResult. That
consumer was already made dual-mode in T21b (filings_sentiment): for a
CollectorResult "has data" is `is_healthy AND primary_count > 0`, so no consumer
edit is needed here. Per-ticker (Shape F, like filings_sentiment): each call
returns one CollectorResult; the consumer loop aggregates across the universe.

Gate-closed representation mirrors filings_sentiment (T21b): ok_from_count(
'press_releases', 0, gated=1) — gate-closed is NOT an error (.is_healthy True)
and ran zero items; the metadata {'gated': 1} flags the cause so a gate-closed
run is distinguishable from a healthy-but-empty run. Both gate-closed and empty
resolve to "no data this ticker" under the consumer predicate, preserving the
old None semantics.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import requests

from src.config import DB_PATH
from src.data_collection._finnhub_shared import get_finnhub_key as _get_finnhub_key
from src.data_collection.result import CollectorResult
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
) -> CollectorResult:
    """Collect press releases for one ticker (plan-gated).

    On entry: when ``finnhub_plan_supports('press_releases', config)`` is
    False, log INFO and return ``CollectorResult.ok_from_count(
    'press_releases', 0, gated=1)`` — no API call (Decision 30). Gate-closed
    is healthy (not an error) and ran zero; the ``gated=1`` metadata records
    the cause.

    Otherwise: call Finnhub /press-releases and UPSERT one row per release
    into ``press_releases`` keyed by (ticker, headline, released_at).

    Returns: CollectorResult('press_releases', primary_count=rows_written).
      - plan-gated off    -> ok, count 0, metadata {'gated': 1}
      - fetch failed       -> failed (count 0)
      - empty response     -> ok, count 0
      - rows written       -> ok, count=len(rows)
    """
    if not finnhub_plan_supports("press_releases", config):
        logger.info(
            "[PRESS_REL] Skipped %s — Finnhub plan does not support "
            "press_releases", ticker,
        )
        return CollectorResult.ok_from_count("press_releases", 0, gated=1)

    api_key = _get_finnhub_key()
    if not api_key:
        from src.data_collection.errors import CollectorConfigError
        raise CollectorConfigError(
            "FINNHUB_API_KEY not configured — set in .env or "
            "config/settings.local.yaml"
        )

    releases = _fetch_finnhub_press_releases(ticker, api_key)
    if releases is None:
        return CollectorResult.failed(
            "press_releases",
            errors=[f"[PRESS_REL] fetch failed for {ticker}"],
        )
    if not releases:
        logger.info("[PRESS_REL] No releases returned for %s", ticker)
        return CollectorResult.ok_from_count("press_releases", 0)

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
    return CollectorResult.ok_from_count("press_releases", len(rows))
