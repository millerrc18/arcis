"""Analyst estimates and price target collector via Finnhub.

Called by: scheduler/watch.py
Calls: config.py
Owns tables: analyst_estimates
Config keys: data_enrichment
Tests: tests/test_data_collectors.py

Collects consensus recommendations and price targets nightly.
Batches 20 tickers per night to stay within Finnhub free-tier limits.
Rotates through the full S&P 100 universe over multiple nights.
"""

import logging
import os
import sqlite3
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import requests

from src.config import DB_PATH

logger = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")
FINNHUB_BASE = "https://finnhub.io/api/v1"

# Table creation handled by src/schema/registry.py


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


def _get_tickers_to_collect(
    tickers: list[str], batch_size: int, db_path: str
) -> list[str]:
    """Pick tickers not collected in the past 5 days. Rotates through universe."""
    cutoff = (datetime.now(ET) - timedelta(days=5)).strftime("%Y-%m-%d")
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            "SELECT DISTINCT ticker FROM analyst_estimates WHERE date >= ?",
            (cutoff,),
        ).fetchall()
    recent = {r[0] for r in rows}
    pending = [t for t in tickers if t not in recent]
    if not pending:
        pending = list(tickers)
    return pending[:batch_size]


def collect_analyst_estimates(
    tickers: list[str],
    batch_size: int = 20,
    db_path: str = DB_PATH,
) -> dict:
    """Collect analyst recommendations and price targets.

    Returns: {"tickers_processed": int, "estimates_stored": int}
    """
    api_key = _get_finnhub_key()
    if not api_key:
        logger.warning("[ANALYST] No Finnhub API key configured")
        return {"tickers_processed": 0, "estimates_stored": 0, "error": "no_api_key"}

    now = datetime.now(ET)
    today_str = now.strftime("%Y-%m-%d")
    collected_at = now.isoformat()

    to_collect = _get_tickers_to_collect(tickers, batch_size, db_path)
    if not to_collect:
        return {"tickers_processed": 0, "estimates_stored": 0}

    tickers_processed = 0
    estimates_stored = 0

    with sqlite3.connect(db_path) as conn:
        for ticker in to_collect:
            try:
                # Fetch recommendations
                rec_resp = requests.get(
                    f"{FINNHUB_BASE}/stock/recommendation",
                    params={"symbol": ticker, "token": api_key},
                    timeout=15,
                )
                rec_resp.raise_for_status()
                recs = rec_resp.json()

                time.sleep(0.5)  # Rate limit between calls

                # Fetch price targets
                pt_resp = requests.get(
                    f"{FINNHUB_BASE}/stock/price-target",
                    params={"symbol": ticker, "token": api_key},
                    timeout=15,
                )
                pt_resp.raise_for_status()
                pt = pt_resp.json()

                # Use latest recommendation entry
                latest_rec = recs[0] if recs else {}

                try:
                    conn.execute(
                        """INSERT OR IGNORE INTO analyst_estimates
                        (ticker, date, consensus_buy, consensus_hold, consensus_sell,
                         consensus_strong_buy, consensus_strong_sell,
                         price_target_high, price_target_low, price_target_mean,
                         price_target_median, num_analysts, source, collected_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'finnhub', ?)""",
                        (
                            ticker,
                            today_str,
                            latest_rec.get("buy"),
                            latest_rec.get("hold"),
                            latest_rec.get("sell"),
                            latest_rec.get("strongBuy"),
                            latest_rec.get("strongSell"),
                            pt.get("targetHigh"),
                            pt.get("targetLow"),
                            pt.get("targetMean"),
                            pt.get("targetMedian"),
                            pt.get("lastUpdated") and len(recs) or None,
                            collected_at,
                        ),
                    )
                    estimates_stored += 1
                except sqlite3.IntegrityError:
                    pass  # Duplicate — already collected today

                tickers_processed += 1

            except Exception as e:
                logger.warning("[ANALYST] Failed for %s: %s", ticker, e)

            # Rate limit
            time.sleep(1.0)

    result = {
        "tickers_processed": tickers_processed,
        "estimates_stored": estimates_stored,
    }
    logger.info("[ANALYST] Collection complete: %s", result)
    return result
