"""Expanded FRED macro indicator collector.

Called by: api/routes/actions.py, cli/commands.py, scheduler/watch.py
Calls: config.py
Owns tables: macro_snapshots
Config keys: data_enrichment, fred, fred_api_key
Tests: tests/test_data_collectors.py

Supplements the existing macro enrichment with additional series:
supply chain, credit stress, oil, dollar index, etc.
"""

import logging
import os
import sqlite3
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import requests

from src.config import DB_PATH

logger = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")
FRED_BASE = "https://api.stlouisfed.org/fred/series/observations"

FRED_SERIES = {
    # Existing core series
    "FEDFUNDS": "Federal Funds Rate",
    "DGS10": "10-Year Treasury Yield",
    "DGS2": "2-Year Treasury Yield",
    "CPIAUCSL": "CPI All Urban Consumers",
    "UNRATE": "Unemployment Rate",
    # Expanded macro series
    "GSCPI": "NY Fed Global Supply Chain Pressure Index",
    "NAPMSDEL": "ISM Supplier Deliveries Index",
    "ISRATIO": "Total Business Inventory/Sales Ratio",
    "T10Y2Y": "10Y-2Y Treasury Spread",
    "TEDRATE": "TED Spread",
    "VIXCLS": "VIX Close (FRED)",
    "BAMLH0A0HYM2": "High Yield Spread (OAS)",
    "DCOILWTICO": "WTI Crude Oil Price",
    "DTWEXBGS": "Trade-Weighted USD Index",
    # Credit & financial conditions (regime transition signals)
    "BAMLC0A4CBBB": "BBB Corporate Bond Spread (OAS)",
    "NFCI": "Chicago Fed National Financial Conditions Index",
    "STLFSI2": "St. Louis Fed Financial Stress Index",
    "ICSA": "Initial Jobless Claims (Weekly)",
    "T10YIE": "10-Year Breakeven Inflation Rate",
    # Housing
    "HOUST": "Housing Starts",
    "PERMIT": "Building Permits",
    "CSUSHPISA": "Case-Shiller Home Price Index",
    # Employment (granular)
    "CCSA": "Continued Jobless Claims",
    "JTSJOL": "JOLTS Job Openings",
    # Trade & manufacturing
    "BOPGSTB": "Trade Balance",
    "IPMAN": "Industrial Production: Manufacturing",
    "DGORDER": "Durable Goods Orders",
    # Consumer
    "UMCSENT": "Michigan Consumer Sentiment",
    "PCE": "Personal Consumption Expenditures",
    "RSAFS": "Retail Sales",
    # Financial conditions (extended)
    "WALCL": "Fed Balance Sheet (Total Assets)",
    "RRPONTSYD": "Overnight Reverse Repo",
    "M2SL": "M2 Money Supply",
}

# Table creation handled by src/schema/registry.py


def _get_fred_api_key() -> str | None:
    """Get FRED API key. .env takes precedence over YAML config.

    Checks multiple config paths for backwards compatibility:
    - os.environ FRED_API_KEY (primary — from .env)
    - data_enrichment.fred_api_key (matches settings.example.yaml)
    - fred.api_key
    - fred_api_key (top-level)
    """
    env_key = os.environ.get("FRED_API_KEY")
    if env_key:
        return env_key
    try:
        from src.config import load_config
        config = load_config()
        return (
            config.get("data_enrichment", {}).get("fred_api_key")
            or config.get("fred", {}).get("api_key")
            or config.get("fred_api_key")
        )
    except Exception:
        return None


def _fetch_latest(series_id: str, api_key: str) -> float | None:
    """Fetch the most recent value for a FRED series."""
    try:
        resp = requests.get(
            FRED_BASE,
            params={
                "series_id": series_id,
                "api_key": api_key,
                "sort_order": "desc",
                "limit": 1,
                "file_type": "json",
            },
            timeout=15,
        )
        resp.raise_for_status()
        observations = resp.json().get("observations", [])
        if observations:
            val = observations[0].get("value", ".")
            if val != ".":
                return float(val)
    except Exception as e:
        logger.debug("Failed to fetch FRED %s: %s", series_id, e)
    return None


def _get_previous_value(
    conn: sqlite3.Connection, series_id: str, today_str: str
) -> float | None:
    """Get the most recent previous value for change computation."""
    row = conn.execute(
        """SELECT value FROM macro_snapshots
        WHERE series_id = ? AND collected_date < ? AND value IS NOT NULL
        ORDER BY collected_date DESC LIMIT 1""",
        (series_id, today_str),
    ).fetchone()
    return row[0] if row else None


def collect_macro_snapshots(db_path: str = DB_PATH) -> dict:
    """Collect latest values for all tracked FRED series.

    Returns: {"series_collected": int, "notable_changes": list}
    """
    api_key = _get_fred_api_key()
    if not api_key:
        from src.data_collection.errors import CollectorConfigError
        raise CollectorConfigError("FRED_API_KEY not configured — set in .env or config/settings.local.yaml")

    now = datetime.now(ET)
    today_str = now.strftime("%Y-%m-%d")

    series_collected = 0
    notable_changes = []

    with sqlite3.connect(db_path) as conn:
        for series_id, series_name in FRED_SERIES.items():
            try:
                value = _fetch_latest(series_id, api_key)
                if value is None:
                    continue

                previous = _get_previous_value(conn, series_id, today_str)
                change_pct = None
                if previous is not None and previous != 0:
                    change_pct = round((value - previous) / abs(previous) * 100, 4)

                conn.execute(
                    """INSERT INTO macro_snapshots
                    (collected_at, collected_date, series_id, series_name,
                     value, previous_value, change_pct)
                    VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        now.isoformat(),
                        today_str,
                        series_id,
                        series_name,
                        value,
                        previous,
                        change_pct,
                    ),
                )
                series_collected += 1

                # Flag notable changes (>5% move)
                if change_pct is not None and abs(change_pct) > 5:
                    notable_changes.append({
                        "series": series_id,
                        "name": series_name,
                        "change_pct": change_pct,
                    })

                logger.debug("[MACRO] %s = %.4f (prev: %s, chg: %s%%)",
                             series_id, value, previous, change_pct)

            except Exception as e:
                logger.warning("[MACRO] Error fetching %s: %s", series_id, e)

            # Rate limit
            time.sleep(0.2)

    result = {"series_collected": series_collected, "notable_changes": notable_changes}
    logger.info("[MACRO] Collection complete: %s", result)
    return result
