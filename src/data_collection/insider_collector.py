"""SEC insider transactions collector via Finnhub.

Called by: scheduler/watch.py
Calls: config.py
Owns tables: insider_transactions
Config keys: data_enrichment
Tests: tests/test_data_collectors.py

Collects Form 4 insider buy/sell data for S&P 100 universe nightly.
Stores metadata: insider name, title, transaction type, shares, price, value.
"""

import logging
import os
import sqlite3
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import requests

from src.config import DB_PATH
from src.utils.retry import retry_with_backoff

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


def _get_last_filing_date(conn: sqlite3.Connection, ticker: str) -> str | None:
    """Get the most recent filing_date we have for this ticker."""
    row = conn.execute(
        "SELECT MAX(filing_date) FROM insider_transactions WHERE ticker = ?",
        (ticker,),
    ).fetchone()
    return row[0] if row and row[0] else None


def collect_insider_transactions(
    tickers: list[str],
    db_path: str = DB_PATH,
) -> dict:
    """Collect insider transactions for all tickers via Finnhub.

    Returns: {"tickers_processed": int, "transactions_stored": int}
    """
    api_key = _get_finnhub_key()
    if not api_key:
        logger.warning("[INSIDER] No Finnhub API key configured")
        return {"tickers_processed": 0, "transactions_stored": 0, "error": "no_api_key"}

    now = datetime.now(ET)
    collected_at = now.isoformat()

    tickers_processed = 0
    transactions_stored = 0

    with sqlite3.connect(db_path) as conn:
        for ticker in tickers:
            try:
                resp = retry_with_backoff(
                    lambda: requests.get(
                        f"{FINNHUB_BASE}/stock/insider-transactions",
                        params={"symbol": ticker},
                        headers={"X-Finnhub-Token": api_key},
                        timeout=15,
                    ),
                    max_retries=3, base_delay=2.0,
                    exceptions=(requests.RequestException, ConnectionError, OSError),
                )
                if resp is None:
                    logger.warning("[INSIDER] Failed to fetch %s after retries", ticker)
                    continue
                resp.raise_for_status()
                data = resp.json().get("data", [])

                last_date = _get_last_filing_date(conn, ticker)

                for txn in data:
                    filing_date = txn.get("filingDate", "")
                    # Skip if we already have this or older
                    if last_date and filing_date <= last_date:
                        continue

                    shares = txn.get("change", 0) or 0
                    price = txn.get("transactionPrice", 0) or 0
                    value = abs(shares * price) if shares and price else None

                    conn.execute(
                        """INSERT INTO insider_transactions
                        (ticker, insider_name, title, transaction_type,
                         transaction_date, filing_date, shares, price,
                         value, shares_after, source, collected_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'finnhub', ?)""",
                        (
                            ticker,
                            txn.get("name"),
                            txn.get("position", txn.get("title")),
                            txn.get("transactionCode"),
                            txn.get("transactionDate"),
                            filing_date,
                            shares,
                            price,
                            value,
                            txn.get("share"),
                            collected_at,
                        ),
                    )
                    transactions_stored += 1

                tickers_processed += 1

            except Exception as e:
                logger.warning("[INSIDER] Failed for %s: %s", ticker, e)

            # Rate limit: ~60 req/min for free Finnhub
            time.sleep(1.0)

    result = {
        "tickers_processed": tickers_processed,
        "transactions_stored": transactions_stored,
    }
    logger.info("[INSIDER] Collection complete: %s", result)
    return result
