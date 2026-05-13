"""SEC insider transactions collector via Finnhub.

Called by: scheduler/watch.py
Calls: config.py
Owns tables: insider_transactions
Config keys: data_enrichment
Tests: tests/test_data_collectors.py

API: Finnhub /stock/insider-transactions (proxies SEC Form 4 data)
Table: insider_transactions
Schedule: Nightly in overnight pipeline

Collects Form 4 insider buy/sell data for S&P 100 universe nightly.
Stores metadata: insider name, title, transaction type, shares, price, value.

Known issue #233: The date filter uses < (strictly older) rather than <=
(older or equal) when skipping already-collected dates. This means the
boundary date is re-processed, but INSERT OR IGNORE handles the duplicates.
This is intentional — using <= would miss filings added to the same date
after our last collection.
"""

import logging
import sqlite3
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import requests

from src.config import DB_PATH
from src.data_collection._finnhub_shared import get_finnhub_key
from src.utils.db import connect_db, engine_aware_upsert
from src.utils.retry import retry_with_backoff

logger = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")
FINNHUB_BASE = "https://finnhub.io/api/v1"

# Table creation handled by src/schema/registry.py


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
    # Plan gate (Sprint 5 Wave C7b.6 / T26): defensive — insider_transactions
    # is in both 'free' and 'fundamental-1' tier matrices, so this is a no-op
    # on current plans. Guards against future plan tiers that exclude the
    # feature and satisfies the runtime-coverage scanner forward invariant.
    from src.data_enrichment.finnhub_plan import finnhub_plan_supports
    if not finnhub_plan_supports("insider_transactions"):
        logger.info(
            "[INSIDER] Skipped collection — Finnhub plan does not support "
            "insider_transactions"
        )
        return {"tickers_processed": 0, "transactions_stored": 0, "errors": 0}

    api_key = get_finnhub_key()
    if not api_key:
        from src.data_collection.errors import CollectorConfigError
        raise CollectorConfigError("FINNHUB_API_KEY not configured — set in .env or config/settings.local.yaml")

    now = datetime.now(ET)
    collected_at = now.isoformat()

    tickers_processed = 0
    transactions_stored = 0
    errors = 0

    with connect_db(db_path) as conn:
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
                    # Skip strictly older dates; re-process boundary date
                    # (INSERT handles duplicates via unique constraint)
                    if last_date and filing_date < last_date:
                        continue

                    shares = txn.get("change", 0) or 0
                    price = txn.get("transactionPrice", 0) or 0
                    value = abs(shares * price) if shares and price else None

                    engine_aware_upsert(
                        conn,
                        "insider_transactions",
                        {
                            "ticker": ticker,
                            "insider_name": txn.get("name"),
                            "title": txn.get("position", txn.get("title")),
                            "transaction_type": txn.get("transactionCode"),
                            "transaction_date": txn.get("transactionDate"),
                            "filing_date": filing_date,
                            "shares": shares,
                            "price": price,
                            "value": value,
                            "shares_after": txn.get("share"),
                            "source": "finnhub",
                            "collected_at": collected_at,
                        },
                        action="ignore",
                    )
                    transactions_stored += 1

                tickers_processed += 1

            except Exception as e:
                logger.warning("[INSIDER] Failed for %s: %s", ticker, e)
                errors += 1

            # Rate limit: ~60 req/min for free Finnhub
            time.sleep(1.0)

    total = len(tickers)
    if total > 0 and errors > total * 0.5:
        from src.data_collection.errors import CollectorPartialFailureError
        raise CollectorPartialFailureError(
            f"[INSIDER] {errors}/{total} tickers failed (>{50}% threshold)",
            errors=errors, total=total,
        )

    result = {
        "tickers_processed": tickers_processed,
        "transactions_stored": transactions_stored,
        "errors": errors,
    }
    logger.info("[INSIDER] Collection complete: %s", result)
    return result
