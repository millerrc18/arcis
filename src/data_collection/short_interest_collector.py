"""FINRA short interest collector via Finnhub.

DEPRECATED v0.36.13 — see src/data_collection/short_volume_finra.py.
Finnhub plan no longer entitles /stock/short-interest (403). The early-exit
from v0.36.12 stays in place during transition; this collector will be
removed in v0.37.0.

Called by: scheduler/watch.py
Calls: config.py
Owns tables: short_interest
Config keys: data_enrichment
Tests: tests/test_data_collectors.py

API: Finnhub /stock/short-interest (proxies FINRA data)
Table: short_interest
Schedule: Biweekly (1st, 2nd, 15th, 16th of each month)

Collects short interest snapshots biweekly. FINRA publishes short interest
data twice monthly at settlement dates (mid-month and end-of-month).
We collect on the 1st/2nd and 15th/16th to catch both publication windows.

days_to_cover is computed as short_interest / avg_daily_volume. High DTC
(>5 days) indicates potential short squeeze setups.

Known issue #129: cursor.rowcount is used to count actual inserts
(excluding duplicates from INSERT OR IGNORE). This is correct for SQLite
but note that conn.total_changes() would give cumulative counts including
prior operations on the same connection — do not substitute.
"""

import logging
import sqlite3
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import requests

from src.config import DB_PATH
from src.data_collection._finnhub_shared import get_finnhub_key as _get_finnhub_key
from src.data_collection.result import CollectorResult
from src.utils.db import DBIntegrityError, connect_db, engine_aware_upsert
from src.utils.retry import retry_with_backoff

logger = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")
FINNHUB_BASE = "https://finnhub.io/api/v1"

# Table creation handled by src/schema/registry.py


def collect_short_interest(
    tickers: list[str],
    db_path: str = DB_PATH,
) -> CollectorResult:
    """Collect short interest data for all tickers via Finnhub.

    Returns a CollectorResult: primary_count is records_stored; tickers_processed
    and errors go in metadata.
    """
    # DEPRECATED v0.36.13 — see src/data_collection/short_volume_finra.py.
    # Finnhub plan no longer entitles /stock/short-interest (403). The early-exit
    # from v0.36.12 stays in place during transition; this collector will be
    # removed in v0.37.0.
    # Plan gate (Sprint 5 Wave C7b.6 / T26): defensive — short_interest is in
    # both 'free' and 'fundamental-1' matrices, so this is a no-op on current
    # plans. Guards against future plan tiers that exclude the feature and
    # satisfies the runtime-coverage scanner forward invariant.
    from src.data_enrichment.finnhub_plan import finnhub_plan_supports
    if not finnhub_plan_supports("short_interest"):
        logger.info(
            "[SHORT] Skipped collection — Finnhub plan does not support "
            "short_interest"
        )
        return CollectorResult.ok_from_count(
            "short_interest", 0, tickers_processed=0, errors=0
        )

    api_key = _get_finnhub_key()
    if not api_key:
        from src.data_collection.errors import CollectorConfigError
        raise CollectorConfigError("FINNHUB_API_KEY not configured — set in .env or config/settings.local.yaml")

    now = datetime.now(ET)
    collected_at = now.isoformat()

    tickers_processed = 0
    records_stored = 0
    errors = 0
    entitlement_gap = False  # v0.36.12 R3: set on first 403 to short-circuit

    with connect_db(db_path) as conn:
        for ticker in tickers:
            try:
                resp = retry_with_backoff(
                    lambda: requests.get(
                        f"{FINNHUB_BASE}/stock/short-interest",
                        params={"symbol": ticker},
                        headers={"X-Finnhub-Token": api_key},
                        timeout=15,
                    ),
                    max_retries=3, base_delay=2.0,
                    exceptions=(requests.RequestException, ConnectionError, OSError),
                )
                if resp is None:
                    logger.warning("[SHORT] Failed to fetch %s after retries", ticker)
                    continue
                # v0.36.12 R3: detect 403 entitlement gap and short-circuit
                # the remaining ~101 tickers. Pre-fix this loop log-spammed
                # 102 warnings + threshold-failed the overnight cycle on what
                # is really an API plan / key entitlement issue rather than
                # a system failure.
                if resp.status_code == 403:
                    logger.warning(
                        "[SHORT] Finnhub returned 403 for %s — short-interest "
                        "endpoint not entitled on current API plan. Skipping "
                        "remaining %d tickers for this cycle.",
                        ticker, len(tickers) - tickers_processed - 1,
                    )
                    entitlement_gap = True
                    break
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
                        # Pre-count dedup signal: did this (ticker, settlement_date)
                        # already exist? engine_aware_upsert(action='ignore')
                        # routes through `INSERT OR IGNORE` (SQLite) and `INSERT
                        # ... ON CONFLICT DO NOTHING` (PG), neither of which
                        # expose a reliable rowcount across engines (PG cursors
                        # post-DO-NOTHING report rowcount=0 OR -1 depending on
                        # driver build). We probe before the upsert to keep the
                        # records_stored counter accurate cross-engine.
                        existing = conn.execute(
                            "SELECT 1 FROM short_interest WHERE ticker = ? "
                            "AND settlement_date = ? LIMIT 1",
                            (ticker, settlement_date),
                        ).fetchone()
                        engine_aware_upsert(
                            conn,
                            "short_interest",
                            {
                                "ticker": ticker,
                                "settlement_date": settlement_date,
                                "short_interest": short_vol,
                                "avg_daily_volume": avg_vol,
                                "days_to_cover": dtc,
                                "short_pct_float": entry.get(
                                    "shortInterestPercentFloat"
                                ),
                                "source": "finnhub",
                                "collected_at": collected_at,
                            },
                            action="ignore",
                        )
                        if existing is None:
                            records_stored += 1
                    except DBIntegrityError:
                        pass  # Duplicate — already have this settlement date

                tickers_processed += 1

            except Exception as e:
                logger.warning("[SHORT] Failed for %s: %s", ticker, e)
                errors += 1

            # Rate limit
            time.sleep(1.0)

    total = len(tickers)
    # v0.36.12 R3: if we broke on a 403 entitlement gap, treat as a
    # structured skip rather than a partial-failure exception. The
    # remaining tickers weren't actually attempted, so the >50% threshold
    # would otherwise spuriously trip on what is plan/key state, not a
    # system fault.
    if entitlement_gap:
        # skipped_entitlement narrowed bool->int(1) for the dict[str,int]
        # metadata bucket; it remains a structured skip (ok / count 0), not a
        # failure — the remaining tickers weren't actually attempted.
        result = CollectorResult.ok_from_count(
            "short_interest",
            records_stored,
            tickers_processed=tickers_processed,
            errors=0,
            skipped_entitlement=1,
        )
        logger.info(
            "[SHORT] Collection skipped — Finnhub plan does not entitle "
            "short-interest endpoint (HTTP 403). %s",
            result,
        )
        return result

    if total > 0 and errors > total * 0.5:
        from src.data_collection.errors import CollectorPartialFailureError
        raise CollectorPartialFailureError(
            f"[SHORT] {errors}/{total} tickers failed (>{50}% threshold)",
            errors=errors, total=total,
        )

    if errors:
        result = CollectorResult.partial(
            "short_interest",
            records_stored,
            errors=[f"{errors} ticker(s) failed"],
            tickers_processed=tickers_processed,
        )
    else:
        result = CollectorResult.ok_from_count(
            "short_interest",
            records_stored,
            tickers_processed=tickers_processed,
            errors=0,
        )
    logger.info("[SHORT] Collection complete: %s", result)
    return result
