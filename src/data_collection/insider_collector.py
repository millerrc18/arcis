"""SEC insider transactions collector via Finnhub.

Collects Form 4 insider buy/sell data for S&P 100 universe nightly.
Stores metadata: insider name, title, transaction type, shares, price, value.
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
CREATE TABLE IF NOT EXISTS insider_transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    insider_name TEXT,
    title TEXT,
    transaction_type TEXT,
    transaction_date TEXT,
    filing_date TEXT,
    shares REAL,
    price REAL,
    value REAL,
    shares_after REAL,
    source TEXT DEFAULT 'finnhub',
    collected_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_insider_ticker_date
    ON insider_transactions(ticker, filing_date);
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
    _init_table(db_path)

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
                resp = requests.get(
                    f"{FINNHUB_BASE}/stock/insider-transactions",
                    params={"symbol": ticker, "token": api_key},
                    timeout=15,
                )
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
