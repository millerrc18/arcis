"""Plan-gated Finnhub price target collector.

Called by: scheduler/overnight.py (nightly tick, plan-gated)
Calls: data_enrichment.finnhub_plan, utils.db, config
Owns tables: price_targets
Config keys: data_enrichment.finnhub_plan, FINNHUB_PLAN, FINNHUB_API_KEY
Tests: tests/data_collection/test_price_target_collector.py

Sprint v0.36.38 T4.

API: Finnhub /stock/price-target (paid fundamental-1 endpoint).
   Returns {'targetHigh': float, 'targetLow': float, 'targetMean': float,
            'targetMedian': float, 'lastUpdated': str, 'symbol': str}.

Table: price_targets (UPSERT on (ticker, as_of_date))
Schedule: Nightly tick from run_data_collection in overnight.py.

Gate: finnhub_plan_supports('price_target', config). Returns None
when the plan does not support the feature — no API call is attempted (avoids
the 403-burn on free-tier keys per Decision 30).

Note: this is the dedicated full-universe plan-gated snapshot, distinct from
analyst_estimates' opportunistic price-target columns — do NOT touch analyst_estimates.
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


def _fetch_price_target(ticker: str, api_key: str) -> dict | None:
    """Single Finnhub call with retry; returns the payload dict or None."""
    try:
        resp = retry_with_backoff(
            lambda: requests.get(
                f"{FINNHUB_BASE}/stock/price-target",
                params={"symbol": ticker},
                headers={"X-Finnhub-Token": api_key},
                timeout=15,
            ),
            max_retries=3, base_delay=2.0,
            exceptions=(requests.RequestException, ConnectionError, OSError),
        )
        if resp is None:
            logger.warning("[PRICE_TARGET] Failed to fetch %s after retries", ticker)
            return None
        resp.raise_for_status()
        payload = resp.json() or {}
    except Exception as exc:
        logger.warning("[PRICE_TARGET] Fetch failed for %s: %s", ticker, exc)
        return None
    return payload


def _build_row(ticker: str, payload: dict) -> dict | None:
    """Build a price_targets table row from a Finnhub payload dict.

    Returns None when payload has no usable price target fields
    (targetMean, targetHigh, targetLow all absent/zero).
    """
    target_mean = payload.get("targetMean")
    target_high = payload.get("targetHigh")
    target_low = payload.get("targetLow")
    if not any([target_mean, target_high, target_low]):
        return None
    as_of_date = datetime.now(timezone.utc).date().isoformat()
    return {
        "ticker": ticker,
        "as_of_date": as_of_date,
        "target_high": target_high,
        "target_low": target_low,
        "target_mean": target_mean,
        "target_median": payload.get("targetMedian"),
        "last_updated": payload.get("lastUpdated"),
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "source": "finnhub",
    }


def collect_price_targets(
    ticker: str,
    config: dict | None = None,
    db_path: str = DB_PATH,
) -> dict | None:
    """Collect price target consensus snapshot for one ticker (plan-gated).

    On entry: when ``finnhub_plan_supports('price_target', config)``
    is False, log INFO and return None — no API call (Decision 30).

    Otherwise: call Finnhub /stock/price-target and UPSERT one row
    into ``price_targets`` keyed by (ticker, as_of_date = today UTC).

    Returns {'ticker': ticker, 'target_mean': <val>} on success, or None
    when plan-gated off / when the API call fails / when the response has
    no usable data (targetMean, targetHigh, targetLow all absent/zero).
    """
    if not finnhub_plan_supports("price_target", config):
        logger.info(
            "[PRICE_TARGET] Skipped %s — Finnhub plan does not support "
            "price_target", ticker,
        )
        return None

    api_key = _get_finnhub_key()
    if not api_key:
        from src.data_collection.errors import CollectorConfigError
        raise CollectorConfigError(
            "FINNHUB_API_KEY not configured — set in .env or "
            "config/settings.local.yaml"
        )

    payload = _fetch_price_target(ticker, api_key)
    if payload is None:
        return None

    row = _build_row(ticker, payload)
    if row is None:
        logger.info("[PRICE_TARGET] No usable data returned for %s", ticker)
        return None

    with connect_db(db_path) as conn:
        engine_aware_upsert(conn, "price_targets", row, action="ignore")
        conn.commit()

    logger.info(
        "[PRICE_TARGET] %s: mean=%.2f high=%.2f low=%.2f as_of=%s",
        ticker, row["target_mean"] or 0.0, row["target_high"] or 0.0,
        row["target_low"] or 0.0, row["as_of_date"],
    )
    return {"ticker": ticker, "target_mean": row["target_mean"]}
