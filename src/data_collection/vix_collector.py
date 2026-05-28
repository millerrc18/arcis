"""VIX term structure snapshot collector.

Called by: api/routes/actions.py, cli/commands.py, scheduler/watch.py
Calls: none
Owns tables: vix_term_structure
Config keys: none (yfinance is free, no key required)
Tests: none

API: yfinance (free, no key)
Table: vix_term_structure
Schedule: Daily in overnight pipeline

Captures VIX, VIX9D, VIX3M, VIX1Y and computes term structure ratios.
The term_structure_slope (VIX/VIX3M) is a key regime signal:
  - < 1.0 = contango (normal): short-term vol is below long-term,
    indicating calm markets. Favorable for the pullback strategy.
  - > 1.0 = backwardation (fear): short-term vol exceeds long-term,
    indicating crisis/stress. Position sizing should be reduced.

The near_term_ratio (VIX9D/VIX) captures intraweek fear spikes — a
ratio > 1.0 means near-term fear is elevated even relative to 30-day VIX.
"""

import logging
import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo

import yfinance as yf

from src.config import DB_PATH
from src.data_collection.result import CollectorResult
from src.utils.db import connect_db

logger = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")

# Table creation handled by src/schema/registry.py


def _fetch_vix_value(symbol: str) -> float | None:
    """Fetch latest close for a VIX-family ticker."""
    try:
        t = yf.Ticker(symbol)
        hist = t.history(period="5d")
        if hist.empty:
            return None
        return float(hist["Close"].iloc[-1])
    except Exception as e:
        logger.debug("Failed to fetch %s: %s", symbol, e)
        return None


def _term_structure(
    vix: float | None, vix9d: float | None, vix3m: float | None
) -> tuple[float | None, float | None, str]:
    """Derive (term_structure_slope, near_term_ratio, label) from VIX tenors."""
    term_structure_slope = None
    if vix is not None and vix3m is not None and vix3m > 0:
        term_structure_slope = round(vix / vix3m, 4)

    near_term_ratio = None
    if vix9d is not None and vix is not None and vix > 0:
        near_term_ratio = round(vix9d / vix, 4)

    if term_structure_slope is None:
        ts_label = "unknown"
    elif term_structure_slope < 1.0:
        ts_label = "contango (normal)"
    elif term_structure_slope > 1.0:
        ts_label = "backwardation (fear)"
    else:
        ts_label = "flat"

    return term_structure_slope, near_term_ratio, ts_label


def collect_vix_term_structure(db_path: str = DB_PATH) -> CollectorResult:
    """Collect VIX term structure snapshot.

    Returns CollectorResult.ok_from_count("vix", <tenors fetched>) once at
    least one VIX-family tenor is fetched and the snapshot row is written.
    When every tenor fetch fails (yfinance unreachable), returns a failed
    result and writes no row.
    """
    now = datetime.now(ET)

    vix = _fetch_vix_value("^VIX")
    vix9d = _fetch_vix_value("^VIX9D")
    vix3m = _fetch_vix_value("^VIX3M")
    vix1y = _fetch_vix_value("^VIX1Y")

    tenors_fetched = sum(
        1 for v in (vix, vix9d, vix3m, vix1y) if v is not None
    )
    if tenors_fetched == 0:
        logger.warning("[VIX] All tenor fetches failed — no snapshot written")
        return CollectorResult.failed(
            "vix", errors=["all VIX tenor fetches returned no data"]
        )

    term_structure_slope, near_term_ratio, ts_label = _term_structure(
        vix, vix9d, vix3m
    )

    with connect_db(db_path) as conn:
        conn.execute(
            """INSERT INTO vix_term_structure
            (collected_at, collected_date, vix, vix9d, vix3m, vix1y,
             term_structure_slope, near_term_ratio)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                now.isoformat(),
                now.strftime("%Y-%m-%d"),
                vix,
                vix9d,
                vix3m,
                vix1y,
                term_structure_slope,
                near_term_ratio,
            ),
        )

    logger.info(
        "[VIX] Term structure: vix=%s vix3m=%s slope=%s (%s)",
        vix,
        vix3m,
        term_structure_slope,
        ts_label,
    )
    return CollectorResult.ok_from_count("vix", tenors_fetched)
