"""FINRA short interest collector via Finnhub.

Called by: scheduler/watch.py
Calls: config.py
Owns tables: short_interest
Config keys: data_enrichment
Tests: tests/test_data_collectors.py

Collects short interest snapshots biweekly (1st and 15th of each month).
FINRA publishes short interest data twice monthly at settlement dates.
"""

import logging
import sqlite3
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import requests

logger = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")

DB_PATH = "ai_research_desk.sqlite3"
FINNHUB_BASE = "https://finnhub.io/api/v1"

_INIT_SQL = """
CREATE TABLE IF NOT EXISTS short_interest (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    settlement_date TEXT NOT NULL,
    short_interest REAL,
    avg_daily_volume REAL,
    days_to_cover REAL,
    short_pct_float REAL,
    source TEXT DEFAULT 'finnhub',
    collected_at TEXT NOT NULL,
    UNIQUE(ticker, settlement_date)
);

CREATE INDEX IF NOT EXISTS idx_short_interest_ticker_date
    ON short_interest(ticker, settlement_date);
"""


def _init_table(db_path: str) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.executescript(_INIT_SQL)


def _get_finnhub_key() -> str | None:
    try:
        from src.config import load_config
        config = load_config()
        return config.get("data_enrichment", {}).get("finnhub_api_key")
    except Exception:
        return None


def collect_short_interest(
    tickers: list[str],
    db_path: str = DB_PATH,
) -> dict:
    """Collect short interest data for all tickers via Finnhub.

    Returns: {"tickers_processed": int, "records_stored": int}
    """
    _init_table(db_path)

    api_key = _get_finnhub_key()
    if not api_key:
        logger.warning("[SHORT] No Finnhub API key configured")
        return {"tickers_processed": 0, "records_stored": 0, "error": "no_api_key"}

    now = datetime.now(ET)
    collected_at = now.isoformat()

    tickers_processed = 0
    records_stored = 0

    with sqlite3.connect(db_path) as conn:
        for ticker in tickers:
            try:
                resp = requests.get(
                    f"{FINNHUB_BASE}/stock/short-interest",
                    params={"symbol": ticker, "token": api_key},
                    timeout=15,
                )
                resp.raise_for_status()
                data = resp.json().get("data", [])

                for entry in data:
                    settlement_date = entry.get("settlementDate", "")
                    if not settlement_date:
                        continue

                    short_vol = entry.get("shortInterest")
                    avg_vol = entry.get("avgDailyShareTradeVolume")
                    dtc = None
                    if short_vol and avg_vol and avg_vol > 0:
                        dtc = round(short_vol / avg_vol, 2)

                    try:
                        conn.execute(
                            """INSERT OR IGNORE INTO short_interest
                            (ticker, settlement_date, short_interest,
                             avg_daily_volume, days_to_cover, short_pct_float,
                             source, collected_at)
                            VALUES (?, ?, ?, ?, ?, ?, 'finnhub', ?)""",
                            (
                                ticker,
                                settlement_date,
                                short_vol,
                                avg_vol,
                                dtc,
                                entry.get("shortInterestPercentFloat"),
                                collected_at,
                            ),
                        )
                        if conn.total_changes:
                            records_stored += 1
                    except sqlite3.IntegrityError:
                        pass  # Duplicate — already have this settlement date

                tickers_processed += 1

            except Exception as e:
                logger.warning("[SHORT] Failed for %s: %s", ticker, e)

            # Rate limit
            time.sleep(1.0)

    result = {
        "tickers_processed": tickers_processed,
        "records_stored": records_stored,
    }
    logger.info("[SHORT] Collection complete: %s", result)
    return result
