"""Staleness detection — per-ticker per-source data freshness tracking.

Tracks when data was last fetched for each source and ticker combination.
Classifies staleness as acceptable/warning/critical based on source type.

Called by: scheduler.watch, scheduler.position_monitor
Calls: none
Owns tables: data_freshness
Config keys: none
Tests: tests/test_staleness.py
"""

import logging
import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo

from src.config import DB_PATH
from src.utils.db import connect_db, engine_aware_upsert

logger = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")

# Staleness thresholds in minutes
STALENESS_THRESHOLDS = {
    "price": {"acceptable": 35, "warning": 60, "critical": 120},
    "vix": {"acceptable": 65, "warning": 120, "critical": 240},
    "news": {"acceptable": 120, "warning": 240, "critical": 480},
    "fundamentals": {"acceptable": 1560, "warning": 2880, "critical": 4320},  # 26h, 48h, 72h
    "regime": {"acceptable": 65, "warning": 120, "critical": 240},
    "insider": {"acceptable": 1560, "warning": 2880, "critical": 4320},
    "macro": {"acceptable": 1560, "warning": 2880, "critical": 4320},
}


def record_fetch(source: str, ticker: str, db_path: str = DB_PATH) -> None:
    """Record that data was fetched for a source+ticker at current time."""
    now = datetime.now(ET).isoformat()
    try:
        with connect_db(db_path) as conn:
            engine_aware_upsert(
                conn,
                "data_freshness",
                {
                    "source": source,
                    "ticker": ticker,
                    "last_fetched_at": now,
                    "status": "acceptable",
                    "created_at": now,
                },
                action="replace",
            )
            conn.commit()
    except Exception as e:
        logger.debug("[STALENESS] record_fetch failed: %s", e)


def check_staleness(source: str, ticker: str,
                    db_path: str = DB_PATH) -> str:
    """Check staleness status for a source+ticker.

    Returns: 'acceptable', 'warning', 'critical', or 'unknown'
    """
    thresholds = STALENESS_THRESHOLDS.get(source, STALENESS_THRESHOLDS["price"])

    try:
        with connect_db(db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT last_fetched_at FROM data_freshness "
                "WHERE source = ? AND ticker = ?",
                (source, ticker),
            ).fetchone()

            if not row:
                return "unknown"

            last_fetched = datetime.fromisoformat(row["last_fetched_at"])
            age_minutes = (datetime.now(ET) - last_fetched.replace(
                tzinfo=ET if not last_fetched.tzinfo else None
            )).total_seconds() / 60

            if age_minutes <= thresholds["acceptable"]:
                return "acceptable"
            elif age_minutes <= thresholds["warning"]:
                return "warning"
            else:
                return "critical"
    except Exception as e:
        logger.debug("[STALENESS] check_staleness failed: %s", e)
        return "unknown"


def get_staleness_report(db_path: str = DB_PATH) -> dict:
    """Get full staleness report for all tracked data.

    Returns dict of {source: {ticker: status}}.
    """
    report = {}
    try:
        with connect_db(db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT source, ticker, last_fetched_at FROM data_freshness"
            ).fetchall()

            for row in rows:
                source = row["source"]
                ticker = row["ticker"]
                status = check_staleness(source, ticker, db_path)

                if source not in report:
                    report[source] = {}
                report[source][ticker] = status
    except Exception as e:
        logger.debug("[STALENESS] get_staleness_report failed: %s", e)

    return report


def get_stale_tickers(source: str, threshold: str = "warning",
                      db_path: str = DB_PATH) -> list[str]:
    """Get tickers with stale data for a given source.

    Args:
        threshold: Minimum staleness level to include ('warning' or 'critical')
    """
    stale = []
    try:
        with connect_db(db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT ticker FROM data_freshness WHERE source = ?",
                (source,),
            ).fetchall()

            for row in rows:
                status = check_staleness(source, row["ticker"], db_path)
                if threshold == "warning" and status in ("warning", "critical"):
                    stale.append(row["ticker"])
                elif threshold == "critical" and status == "critical":
                    stale.append(row["ticker"])
    except Exception as e:
        logger.debug("[STALENESS] get_stale_tickers failed: %s", e)

    return stale
