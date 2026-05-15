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
Nightly batch size is plan-conditional: fundamental-1 tier → 100 tickers/night
(well within the 30 calls/sec global limit); free tier → 20 tickers/night
(preserves previous behavior within 60 calls/min free-tier limit). Rotates
through the full S&P 100 universe over multiple nights — tickers collected
in the past 5 days are skipped.

Known issue #234: num_analysts is computed as the sum of all recommendation
categories (buy+hold+sell+strongBuy+strongSell). This is the number of
analysts who submitted the most recent consensus, not the total coverage.
"""

import logging
import sqlite3
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import requests

from src.config import DB_PATH
from src.data_collection._finnhub_shared import get_finnhub_key as _get_finnhub_key
from src.data_enrichment.finnhub_plan import finnhub_plan_supports, get_finnhub_plan
from src.utils.db import DBIntegrityError, connect_db, engine_aware_upsert
from src.utils.retry import retry_with_backoff

logger = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")
FINNHUB_BASE = "https://finnhub.io/api/v1"

# Table creation handled by src/schema/registry.py


def _get_nightly_cap(config) -> int:
    """Return per-night cap for analyst data fetches based on Finnhub plan tier.

    fundamental-1: 100/night (well within tier's 30 calls/sec rate-limit)
    free / auto: 20/night (preserved current behavior)

    Note: `auto` plan also gets the free-tier cap (conservative default against
    accidental upgrade-then-downgrade). Explicit `fundamental-1` plan required
    to unlock 100/night. This is asymmetric vs `finnhub_plan_supports()` which
    treats `auto` as `fundamental-1`-equivalent, but the asymmetry is intentional:
    feature gates are binary, rate caps are tier-numeric.
    """
    return 100 if get_finnhub_plan(config) == "fundamental-1" else 20


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
    batch_size: int | None = None,
    db_path: str = DB_PATH,
) -> dict:
    """Collect analyst recommendations and price targets.

    Returns: {"tickers_processed": int, "estimates_stored": int}
    """
    if batch_size is None:
        batch_size = _get_nightly_cap(None)

    # Plan gate (Sprint 5 Wave C7b.6 / T26): defensive — recommendation_trends
    # is in both 'free' and 'fundamental-1' matrices, so this is a no-op on
    # current plans. Guards against future plan tiers that exclude the
    # feature and satisfies the runtime-coverage scanner forward invariant.
    # (price_target is gated separately below and remains a known-latent
    # gate-off site — see T26 reverse-invariant allowlist.)
    if not finnhub_plan_supports("recommendation_trends"):
        logger.info(
            "[ANALYST] Skipped collection — Finnhub plan does not support "
            "recommendation_trends"
        )
        return {"tickers_processed": 0, "estimates_stored": 0, "errors": 0}

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
                except DBIntegrityError:
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
