"""Plan-gated Finnhub stock fundamentals metrics collector.

Called by: scheduler/overnight.py (nightly tick, plan-gated)
Calls: data_enrichment.finnhub_plan, utils.db, config
Owns tables: stock_financials
Config keys: data_enrichment.finnhub_plan, FINNHUB_PLAN, FINNHUB_API_KEY
Tests: tests/data_collection/test_stock_financials_collector.py

Sprint v0.36.38 T3.

API: Finnhub /stock/metric?metric=all (paid fundamental-1 endpoint).
   Returns a flat dict of ~100 named ratios under the 'metric' key.
   This is the current metric snapshot — NOT /stock/financials-reported.

Table: stock_financials (UPSERT on (ticker, as_of_date))
Schedule: Nightly tick from run_data_collection in overnight.py.

Gate: finnhub_plan_supports('stock_financials', config). Returns None
when the plan does not support the feature — no API call is attempted
(avoids the 403-burn on free-tier keys per Decision 30).
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


def _fetch_stock_metrics(ticker: str, api_key: str) -> dict | None:
    """Single Finnhub /stock/metric call with retry; returns metric dict or None."""
    try:
        resp = retry_with_backoff(
            lambda: requests.get(
                f"{FINNHUB_BASE}/stock/metric",
                params={"symbol": ticker, "metric": "all"},
                headers={"X-Finnhub-Token": api_key},
                timeout=15,
            ),
            max_retries=3, base_delay=2.0,
            exceptions=(requests.RequestException, ConnectionError, OSError),
        )
        if resp is None:
            logger.warning("[STOCK_FIN] Failed to fetch %s after retries", ticker)
            return None
        resp.raise_for_status()
        payload = resp.json() or {}
    except Exception as exc:
        logger.warning("[STOCK_FIN] Fetch failed for %s: %s", ticker, exc)
        return None
    return payload.get("metric") or {}


def collect_stock_financials(
    ticker: str,
    config: dict | None = None,
    db_path: str = DB_PATH,
) -> dict | None:
    """Collect fundamental metrics snapshot for one ticker (plan-gated).

    On entry: when ``finnhub_plan_supports('stock_financials', config)``
    is False, log INFO and return None — no API call (Decision 30).

    Otherwise: call Finnhub /stock/metric?metric=all and UPSERT one
    row into ``stock_financials`` keyed by (ticker, as_of_date).

    Returns {'ticker': ticker, 'as_of_date': as_of_date} on success,
    or None when plan-gated off / API call fails / metric dict empty.
    """
    if not finnhub_plan_supports("stock_financials", config):
        logger.info(
            "[STOCK_FIN] Skipped %s — Finnhub plan does not support "
            "stock_financials", ticker,
        )
        return None

    api_key = _get_finnhub_key()
    if not api_key:
        from src.data_collection.errors import CollectorConfigError
        raise CollectorConfigError(
            "FINNHUB_API_KEY not configured — set in .env or "
            "config/settings.local.yaml"
        )

    metric = _fetch_stock_metrics(ticker, api_key)
    if not metric:
        logger.info("[STOCK_FIN] Empty metric dict returned for %s", ticker)
        return None

    as_of_date = datetime.now(timezone.utc).date().isoformat()

    # Coerce market_cap float -> int (BIGINT column; megacaps exceed int32).
    raw_market_cap = metric.get("marketCapitalization")
    market_cap: int | None
    if raw_market_cap is not None:
        try:
            market_cap = int(raw_market_cap)
        except (TypeError, ValueError):
            market_cap = None
    else:
        market_cap = None

    row = {
        "ticker": ticker,
        "as_of_date": as_of_date,
        "pe_ratio": metric.get("peTTM"),
        "pb_ratio": metric.get("pbAnnual") if metric.get("pbAnnual") is not None
                    else metric.get("pbQuarterly"),
        "ps_ratio": metric.get("psTTM"),
        "ev_ebitda": metric.get("evToEbitdaTTM"),
        "roe": metric.get("roeTTM"),
        "roa": metric.get("roaTTM"),
        "gross_margin": metric.get("grossMarginTTM"),
        "net_margin": metric.get("netProfitMarginTTM"),
        "debt_to_equity": (
            metric.get("longTermDebt/equityAnnual")
            if metric.get("longTermDebt/equityAnnual") is not None
            else metric.get("totalDebt/totalEquityAnnual")
        ),
        "current_ratio": (
            metric.get("currentRatioAnnual")
            if metric.get("currentRatioAnnual") is not None
            else metric.get("currentRatioQuarterly")
        ),
        "dividend_yield": metric.get("dividendYieldIndicatedAnnual"),
        "market_cap": market_cap,
        "week52_high": metric.get("52WeekHigh"),
        "week52_low": metric.get("52WeekLow"),
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "source": "finnhub",
    }

    with connect_db(db_path) as conn:
        engine_aware_upsert(conn, "stock_financials", row, action="ignore")
        conn.commit()

    logger.info(
        "[STOCK_FIN] %s: pe=%.2f, market_cap=%s, as_of=%s",
        ticker,
        row["pe_ratio"] if row["pe_ratio"] is not None else float("nan"),
        row["market_cap"],
        as_of_date,
    )
    return {"ticker": ticker, "as_of_date": as_of_date}
