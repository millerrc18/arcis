"""FINRA daily short-volume collector.

Called by: scheduler/overnight.py
Calls: src.utils.db, src.utils.retry, src.universe.pit, src.scheduler.holidays
Owns tables: short_volume_daily
Config keys: none (no API key required — FINRA CDN is public)
Tests: tests/data_collection/test_short_volume_finra.py

v0.36.13 stopgap replacing Finnhub /stock/short-interest (HTTP 403 on
current plan). IMPORTANT METRIC DIFFERENCE:

  - FINRA REGSHO daily short volume (this collector):
    Executed short-sale orders per trading day for a given symbol,
    aggregated across FINRA member firms. Published T+1 on the FINRA CDN.
    Source file: CNMSshvol{YYYYMMDD}.txt (pipe-delimited, ~500 KB/day).

  - Finnhub /stock/short-interest (deprecated):
    Total short positions (shares sold short and not yet covered) as
    reported by FINRA member firms on semi-monthly settlement dates.
    Reported twice monthly; reflects aggregate outstanding short exposure.

Both metrics trend in the same direction — elevated short volume days
typically correspond to elevated short interest periods. However, they
are NOT numerically equivalent. short_ratio (short_volume / total_volume)
from this collector is a daily flow measure, not a float-coverage figure.
Operator authorized this substitution as a stopgap pending a Finnhub plan
upgrade or alternative data source.

See also: src/data_collection/short_interest_collector.py (DEPRECATED v0.36.13)
"""

import logging
from datetime import date, datetime
from zoneinfo import ZoneInfo

import requests

from src.config import DB_PATH
from src.data_collection.errors import CollectorConfigError
from src.universe.sp100 import get_sp100_universe
from src.utils.db import connect_db, engine_aware_upsert
from src.utils.retry import retry_with_backoff

logger = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")

_FINRA_BASE_URL = "https://cdn.finra.org/equity/regsho/daily/CNMSshvol"
_CHROME_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36"
)


def collect_finra_short_volume(
    target_date: date | None = None,
    db_path: str = DB_PATH,
) -> dict:
    """Collect FINRA daily short-volume data for the SP100 universe.

    Args:
        target_date: Trading date to fetch. Defaults to the most recent
            trading day (yesterday). Must be a weekday — FINRA does not
            publish on weekends or holidays.
        db_path: SQLite database path. Defaults to DB_PATH from config.

    Returns:
        dict with keys:
            tickers_collected (int): SP100 tickers with data found.
            rows_inserted (int): Rows inserted (deduplicated via upsert).
            target_date (str): ISO date fetched (YYYY-MM-DD).
            source (str): Always "finra".

    Raises:
        CollectorConfigError: If HTTP request fails after all retries
            (4xx/5xx persistent failure from FINRA CDN).
    """
    if target_date is None:
        from src.scheduler.holidays import subtract_trading_days
        target_date = subtract_trading_days(date.today(), 1)

    url = f"{_FINRA_BASE_URL}{target_date.strftime('%Y%m%d')}.txt"
    logger.info("[SHORT_VOLUME_FINRA] Fetching %s", url)

    resp = retry_with_backoff(
        lambda: requests.get(
            url,
            headers={"User-Agent": _CHROME_UA},
            timeout=30,
        ),
        max_retries=3,
        base_delay=2.0,
        exceptions=(requests.RequestException, ConnectionError, OSError),
    )

    if resp is None:
        raise CollectorConfigError(
            f"[SHORT_VOLUME_FINRA] HTTP request to {url} failed after retries"
        )

    if resp.status_code >= 400:
        raise CollectorConfigError(
            f"[SHORT_VOLUME_FINRA] HTTP {resp.status_code} from FINRA CDN: {url}"
        )

    # W21 (2026-05-18 pre-overnight check) — replaced the original
    # `get_sp100_at(target_date)` call. Two issues with the original:
    #   1. Passed a date object to a function expecting an ISO string
    #      (TypeError).
    #   2. Even with the iso fix, `get_sp100_at()` raised
    #      `UniverseDataMissing` when target_date is past the membership
    #      data's `latest` (data/reference/sp100_history.json was 3 weeks
    #      stale; daily collector pulls T+1).
    # The right call for a DAILY data collector is `get_sp100_universe()`
    # (current SP100 membership), not the point-in-time historical lookup.
    # PIT is for backtesting historical signals; for "what's in SP100
    # right now," the current-membership list is correct.
    sp100 = set(get_sp100_universe())

    collected_at = datetime.now(ET).isoformat()
    trade_date_str = target_date.strftime("%Y-%m-%d")

    lines = resp.text.split("\n")
    tickers_collected = 0
    rows_inserted = 0

    with connect_db(db_path) as conn:
        for line in lines[1:]:
            line = line.strip()
            if not line:
                continue
            parts = line.split("|")
            if len(parts) < 5:
                continue

            _date_field, symbol, short_vol_str, short_exempt_str, total_vol_str = (
                parts[0], parts[1], parts[2], parts[3], parts[4]
            )

            if symbol not in sp100:
                continue

            try:
                short_volume = float(short_vol_str)
                short_exempt_volume = float(short_exempt_str)
                total_volume = float(total_vol_str)
            except (ValueError, TypeError):
                logger.warning(
                    "[SHORT_VOLUME_FINRA] Could not parse volumes for %s: %s",
                    symbol, line,
                )
                continue

            short_ratio = None
            if total_volume > 0:
                short_ratio = short_volume / total_volume

            existing = conn.execute(
                "SELECT 1 FROM short_volume_daily WHERE ticker = ? "
                "AND trade_date = ? LIMIT 1",
                (symbol, trade_date_str),
            ).fetchone()

            engine_aware_upsert(
                conn,
                "short_volume_daily",
                {
                    "ticker": symbol,
                    "trade_date": trade_date_str,
                    "short_volume": short_volume,
                    "short_exempt_volume": short_exempt_volume,
                    "total_volume": total_volume,
                    "short_ratio": short_ratio,
                    "source": "finra",
                    "collected_at": collected_at,
                },
                action="ignore",
            )

            if existing is None:
                rows_inserted += 1

            tickers_collected += 1

    result = {
        "tickers_collected": tickers_collected,
        "rows_inserted": rows_inserted,
        "target_date": trade_date_str,
        "source": "finra",
    }
    logger.info("[SHORT_VOLUME_FINRA] Collection complete: %s", result)
    return result
