"""Plan-gated Finnhub institutional ownership collector.

Called by: scheduler/overnight.py (nightly tick, plan-gated)
Calls: data_enrichment.finnhub_plan, utils.db, config
Owns tables: institutional_holdings
Config keys: data_enrichment.finnhub_plan, FINNHUB_PLAN, FINNHUB_API_KEY
Tests: tests/data_collection/test_institutional_ownership_collector.py

Sprint 5 Wave C7b.1 / T21.

API: Finnhub /stock/institutional-ownership (paid fundamental-1 endpoint)
Table: institutional_holdings (UPSERT on (ticker, as_of_date))
Schedule: Nightly tick from run_data_collection in overnight.py.

Gate: finnhub_plan_supports('institutional_ownership', config). Returns None
when the plan does not support the feature — no API call is attempted (avoids
the 403-burn on free-tier keys per Decision 30).
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


def _fetch_finnhub_ownership(ticker: str, api_key: str) -> list[dict] | None:
    """Single Finnhub call with retry; returns the holders list or None."""
    try:
        resp = retry_with_backoff(
            lambda: requests.get(
                f"{FINNHUB_BASE}/stock/institutional-ownership",
                params={"symbol": ticker},
                headers={"X-Finnhub-Token": api_key},
                timeout=15,
            ),
            max_retries=3, base_delay=2.0,
            exceptions=(requests.RequestException, ConnectionError, OSError),
        )
        if resp is None:
            logger.warning("[INST_OWNERSHIP] Failed to fetch %s after retries", ticker)
            return None
        resp.raise_for_status()
        payload = resp.json() or {}
    except Exception as exc:
        logger.warning("[INST_OWNERSHIP] Fetch failed for %s: %s", ticker, exc)
        return None
    return payload.get("ownership") or payload.get("data") or []


def _aggregate_holders(holders: list[dict], ticker: str) -> dict:
    """Aggregate a list of Finnhub holder dicts into a single TableDef row."""
    total_shares = 0
    shares: list[int] = []
    for h in holders:
        try:
            s = int(h.get("share", 0) or 0)
        except (TypeError, ValueError):
            continue
        total_shares += s
        shares.append(s)
    top5_pct: float | None = None
    if total_shares > 0:
        top5_pct = round(100.0 * sum(sorted(shares, reverse=True)[:5]) / total_shares, 2)
    filing_dates = [h.get("filingDate") for h in holders if h.get("filingDate")]
    as_of_date = (
        max(filing_dates) if filing_dates
        else datetime.now(timezone.utc).date().isoformat()
    )
    return {
        "ticker": ticker,
        "as_of_date": as_of_date,
        "total_shares": total_shares or None,
        "num_holders": len(holders) or None,
        "top_5_holders_pct": top5_pct,
        # qoq_delta_pct populated by a downstream consolidator; left NULL here.
        "qoq_delta_pct": None,
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "source": "finnhub",
    }


def collect_institutional_ownership(
    ticker: str,
    config: dict | None = None,
    db_path: str = DB_PATH,
) -> dict | None:
    """Collect institutional ownership snapshot for one ticker (plan-gated).

    On entry: when ``finnhub_plan_supports('institutional_ownership', config)``
    is False, log INFO and return None — no API call (Decision 30).

    Otherwise: call Finnhub /stock/institutional-ownership and UPSERT one
    aggregate row into ``institutional_holdings`` keyed by (ticker, as_of_date).

    Returns the inserted row dict on success, or None when plan-gated off /
    when the API call fails / when the response is empty.
    """
    if not finnhub_plan_supports("institutional_ownership", config):
        logger.info(
            "[INST_OWNERSHIP] Skipped %s — Finnhub plan does not support "
            "institutional_ownership", ticker,
        )
        return None

    api_key = _get_finnhub_key()
    if not api_key:
        from src.data_collection.errors import CollectorConfigError
        raise CollectorConfigError(
            "FINNHUB_API_KEY not configured — set in .env or "
            "config/settings.local.yaml"
        )

    holders = _fetch_finnhub_ownership(ticker, api_key)
    if not holders:
        if holders is not None:
            logger.info("[INST_OWNERSHIP] No holders returned for %s", ticker)
        return None

    row = _aggregate_holders(holders, ticker)
    with connect_db(db_path) as conn:
        engine_aware_upsert(conn, "institutional_holdings", row, action="ignore")
        conn.commit()
    logger.info(
        "[INST_OWNERSHIP] %s: %s holders, %s total shares, as_of=%s",
        ticker, row["num_holders"], row["total_shares"], row["as_of_date"],
    )
    return row
