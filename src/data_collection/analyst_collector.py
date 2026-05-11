"""Analyst estimates and price target collector via Finnhub.

Called by: scheduler/watch.py
Calls: config.py
Owns tables: analyst_estimates
Config keys: data_enrichment
Tests: tests/test_data_collectors.py

API: Finnhub /stock/recommendation + /stock/price-target
Table: analyst_estimates
Schedule: Nightly in overnight pipeline

Collects consensus recommendations and price targets nightly.
Batches 20 tickers per night to stay within Finnhub free-tier limits
(60 calls/min). Rotates through the full S&P 100 universe over multiple
nights — tickers collected in the past 5 days are skipped.

Known issue #234: num_analysts is computed as the sum of all recommendation
categories (buy+hold+sell+strongBuy+strongSell). This is the number of
analysts who submitted the most recent consensus, not the total coverage.
"""

import logging
import os
import sqlite3
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import requests

from src.config import DB_PATH
from src.data_enrichment.finnhub_plan import finnhub_plan_supports
from src.utils.db import connect_db, engine_aware_upsert
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


def _get_tickers_to_collect(
    tickers: list[str], batch_size: int, db_path: str
) -> list[str]:
    """Pick tickers not collected in the past 5 days. Rotates through universe."""
    cutoff = (datetime.now(ET) - timedelta(days=5)).strftime("%Y-%m-%d")
    with connect_db(db_path) as conn:
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
        from src.data_collection.errors import CollectorConfigError
        raise CollectorConfigError("FINNHUB_API_KEY not configured — set in .env or config/settings.local.yaml")

    now = datetime.now(ET)
    today_str = now.strftime("%Y-%m-%d")
    collected_at = now.isoformat()

    to_collect = _get_tickers_to_collect(tickers, batch_size, db_path)
    if not to_collect:
        return {"tickers_processed": 0, "estimates_stored": 0}

    tickers_processed = 0
    estimates_stored = 0
    errors = 0

    with connect_db(db_path) as conn:
        for ticker in to_collect:
            try:
                # Fetch recommendations
                finnhub_headers = {"X-Finnhub-Token": api_key}
                rec_resp = retry_with_backoff(
                    lambda: requests.get(
                        f"{FINNHUB_BASE}/stock/recommendation",
                        params={"symbol": ticker},
                        headers=finnhub_headers,
                        timeout=15,
                    ),
                    max_retries=3, base_delay=2.0,
                    exceptions=(requests.RequestException, ConnectionError, OSError),
                )
                if rec_resp is None:
                    logger.warning("[ANALYST] Failed to fetch recommendations for %s after retries", ticker)
                    continue
                rec_resp.raise_for_status()
                recs = rec_resp.json()

                time.sleep(0.5)  # Rate limit between calls

                # Price-target access varies by Finnhub plan; the operator wants
                # a clean free vs premium toggle, so we only attempt it when the
                # configured plan explicitly supports the endpoint.
                pt = {}
                if finnhub_plan_supports("price_target"):
                    try:
                        pt_resp = retry_with_backoff(
                            lambda: requests.get(
                                f"{FINNHUB_BASE}/stock/price-target",
                                params={"symbol": ticker},
                                headers=finnhub_headers,
                                timeout=15,
                            ),
                            max_retries=1, base_delay=1.0,
                            exceptions=(requests.RequestException, ConnectionError, OSError),
                        )
                        if pt_resp is not None and pt_resp.status_code == 200:
                            pt = pt_resp.json()
                        elif pt_resp is not None and pt_resp.status_code == 403:
                            if ticker == to_collect[0]:  # Log once, not 102 times
                                logger.warning("[ANALYST] price-target endpoint returned 403 "
                                               "(plan access mismatch) — storing recommendations only")
                    except Exception:
                        pass  # Price targets are nice-to-have, not critical

                # Use latest recommendation entry
                latest_rec = recs[0] if recs else {}

                try:
                    row_dict = {
                        "ticker": ticker,
                        "date": today_str,
                        "consensus_buy": latest_rec.get("buy"),
                        "consensus_hold": latest_rec.get("hold"),
                        "consensus_sell": latest_rec.get("sell"),
                        "consensus_strong_buy": latest_rec.get("strongBuy"),
                        "consensus_strong_sell": latest_rec.get("strongSell"),
                        "price_target_high": pt.get("targetHigh"),
                        "price_target_low": pt.get("targetLow"),
                        "price_target_mean": pt.get("targetMean"),
                        "price_target_median": pt.get("targetMedian"),
                        "num_analysts": sum(
                            latest_rec.get(k, 0) or 0
                            for k in ("buy", "hold", "sell", "strongBuy", "strongSell")
                        ) or None,
                        "source": "finnhub",
                        "collected_at": collected_at,
                    }
                    engine_aware_upsert(
                        conn, "analyst_estimates", row_dict, action="ignore"
                    )
                    estimates_stored += 1
                except sqlite3.IntegrityError:
                    pass  # Duplicate — already collected today

                tickers_processed += 1

            except Exception as e:
                logger.warning("[ANALYST] Failed for %s: %s", ticker, e)
                errors += 1

            # Rate limit
            time.sleep(1.0)

    total = len(to_collect)
    if total > 0 and errors > total * 0.5:
        from src.data_collection.errors import CollectorPartialFailureError
        raise CollectorPartialFailureError(
            f"[ANALYST] {errors}/{total} tickers failed (>{50}% threshold)",
            errors=errors, total=total,
        )

    result = {
        "tickers_processed": tickers_processed,
        "estimates_stored": estimates_stored,
        "errors": errors,
    }
    logger.info("[ANALYST] Collection complete: %s", result)
    return result
