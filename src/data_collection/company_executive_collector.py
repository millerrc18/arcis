"""Plan-gated Finnhub company executive collector.

Called by: scheduler/overnight.py (nightly tick, plan-gated)
Calls: data_enrichment.finnhub_plan, utils.db, config
Owns tables: company_executives
Config keys: data_enrichment.finnhub_plan, FINNHUB_PLAN, FINNHUB_API_KEY
Tests: tests/data_collection/test_company_executive_collector.py

Sprint v0.36.38 T2.

API: Finnhub /stock/executive (paid fundamental-1 endpoint).
   Returns {"executive": [...]} with name/position/age/since/compensation/currency
   fields per executive. Gate: finnhub_plan_supports('company_executive', config).
   Returns None when the plan does not support the feature — no API call is
   attempted (avoids 403-burn on free-tier keys per Decision 30).

Table: company_executives (UPSERT on (ticker, name, position), action='ignore')
Schedule: Nightly tick from run_data_collection in overnight.py.
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


def _fetch_company_executives(ticker: str, api_key: str) -> list[dict] | None:
    """Single Finnhub call with retry; returns the executives list or None."""
    try:
        resp = retry_with_backoff(
            lambda: requests.get(
                f"{FINNHUB_BASE}/stock/executive",
                params={"symbol": ticker},
                headers={"X-Finnhub-Token": api_key},
                timeout=15,
            ),
            max_retries=3, base_delay=2.0,
            exceptions=(requests.RequestException, ConnectionError, OSError),
        )
        if resp is None:
            logger.warning("[COMPANY_EXEC] Failed to fetch %s after retries", ticker)
            return None
        resp.raise_for_status()
        payload = resp.json() or {}
    except Exception as exc:
        logger.warning("[COMPANY_EXEC] Fetch failed for %s: %s", ticker, exc)
        return None
    return payload.get("executive") or []


def _build_executive_row(ticker: str, exec_data: dict) -> dict | None:
    """Build a company_executives row dict from a Finnhub executive entry.

    Returns None when ``name`` is absent (NOT NULL unique-key component).
    Coerces age and compensation to int defensively.
    """
    name = exec_data.get("name")
    if not name:
        return None
    try:
        age_raw = exec_data.get("age")
        age = int(age_raw) if age_raw is not None else None
    except (TypeError, ValueError):
        age = None
    try:
        comp_raw = exec_data.get("compensation")
        compensation = int(comp_raw) if comp_raw is not None else None
    except (TypeError, ValueError):
        compensation = None
    return {
        "ticker": ticker,
        "name": name,
        "position": exec_data.get("position"),
        "age": age,
        "since": exec_data.get("since"),
        "compensation": compensation,
        "currency": exec_data.get("currency"),
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "source": "finnhub",
    }


def collect_company_executives(
    ticker: str,
    config: dict | None = None,
    db_path: str = DB_PATH,
) -> CollectorResult:
    """Collect company executive roster for one ticker (plan-gated).

    On entry: when ``finnhub_plan_supports('company_executive', config)``
    is False, log INFO and return ``CollectorResult.ok_from_count(
    'company_executive', 0, gated=1)`` — no API call (Decision 30). Gate-closed
    is healthy (not an error) and ran zero; the ``gated=1`` metadata records
    the cause.

    Otherwise: call Finnhub /stock/executive and UPSERT one row per executive
    into ``company_executives`` keyed by (ticker, name, position). Executives
    with no ``name`` are skipped (name is a NOT NULL unique-key component).

    Returns: CollectorResult('company_executive', primary_count=executives_stored).
      - plan-gated off    -> ok, count 0, metadata {'gated': 1}
      - fetch failed       -> failed (count 0)
      - empty response     -> ok, count 0
      - rows written       -> ok, count=executives_stored
    """
    if not finnhub_plan_supports("company_executive", config):
        logger.info(
            "[COMPANY_EXEC] Skipped %s — Finnhub plan does not support "
            "company_executive", ticker,
        )
        return CollectorResult.ok_from_count("company_executive", 0, gated=1)

    api_key = _get_finnhub_key()
    if not api_key:
        from src.data_collection.errors import CollectorConfigError
        raise CollectorConfigError(
            "FINNHUB_API_KEY not configured — set in .env or "
            "config/settings.local.yaml"
        )

    executives = _fetch_company_executives(ticker, api_key)
    if executives is None:
        return CollectorResult.failed(
            "company_executive",
            errors=[f"[COMPANY_EXEC] fetch failed for {ticker}"],
        )
    if not executives:
        logger.info("[COMPANY_EXEC] No executives for %s", ticker)
        return CollectorResult.ok_from_count("company_executive", 0)

    stored = 0
    with connect_db(db_path) as conn:
        for exec_data in executives:
            row = _build_executive_row(ticker, exec_data)
            if row is None:
                continue
            engine_aware_upsert(conn, "company_executives", row, action="ignore")
            stored += 1
        conn.commit()

    logger.info("[COMPANY_EXEC] %s: %s executives stored", ticker, stored)
    return CollectorResult.ok_from_count("company_executive", stored)
