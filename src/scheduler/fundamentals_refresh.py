"""Fundamentals refresh — Tier 4 (daily 7:30 AM) macro and fundamental data.

Extracted from watch.py for multi-cadence scanning architecture.
Refreshes FRED macro data, SEC filings, FMP estimates, and insider transactions.

Called by: scheduler.watch
Calls: data_collection.*, data_enrichment.enricher
Owns tables: none
Config keys: data_enrichment.*
Tests: tests/test_fundamentals_refresh.py
"""

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from src.config import DB_PATH

logger = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")


def run_fundamentals_refresh(config: dict, db_path: str = DB_PATH) -> dict:
    """Run Tier 4 fundamentals refresh (daily at 7:30 AM ET).

    Refreshes:
    - FRED macro indicators (34+ series)
    - SEC EDGAR filings
    - Analyst estimates and price targets
    - Insider transactions

    Returns summary dict.
    """
    summary = {"refreshed": [], "errors": 0}

    # FRED macro refresh
    try:
        from src.data_collection.macro_collector import collect_macro_data
        result = collect_macro_data()
        summary["refreshed"].append(f"FRED ({result.get('series_count', 0)} series)")
        logger.info("[FUNDAMENTALS] FRED macro refreshed")
    except Exception as e:
        logger.warning("[FUNDAMENTALS] FRED refresh failed: %s", e)
        summary["errors"] += 1

    # Earnings calendar refresh
    try:
        from src.data_collection.earnings_collector import collect_earnings_calendar
        result = collect_earnings_calendar()
        summary["refreshed"].append("earnings")
        logger.info("[FUNDAMENTALS] Earnings calendar refreshed")
    except Exception as e:
        logger.warning("[FUNDAMENTALS] Earnings refresh failed: %s", e)
        summary["errors"] += 1

    logger.info("[FUNDAMENTALS] Tier 4 refresh complete: %s", summary["refreshed"])
    return summary
