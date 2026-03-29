"""VIX term structure snapshot collector.

Captures VIX, VIX9D, VIX3M, VIX1Y and computes term structure ratios.
"""

import logging
import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo

import yfinance as yf

logger = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")

DB_PATH = "ai_research_desk.sqlite3"

_INIT_SQL = """
CREATE TABLE IF NOT EXISTS vix_term_structure (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    collected_at TEXT NOT NULL,
    collected_date TEXT NOT NULL,
    vix REAL,
    vix9d REAL,
    vix3m REAL,
    vix1y REAL,
    term_structure_slope REAL,
    near_term_ratio REAL
);

CREATE INDEX IF NOT EXISTS idx_vix_ts_date
    ON vix_term_structure(collected_date);
"""


def _init_table(db_path: str) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.executescript(_INIT_SQL)


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


def collect_vix_term_structure(db_path: str = DB_PATH) -> dict:
    """Collect VIX term structure snapshot.

    Returns: {"vix": float, "vix3m": float, "term_structure": str}
    """
    _init_table(db_path)
    now = datetime.now(ET)

    vix = _fetch_vix_value("^VIX")
    vix9d = _fetch_vix_value("^VIX9D")
    vix3m = _fetch_vix_value("^VIX3M")
    vix1y = _fetch_vix_value("^VIX1Y")

    # Compute ratios
    term_structure_slope = None
    if vix is not None and vix3m is not None and vix3m > 0:
        term_structure_slope = round(vix / vix3m, 4)

    near_term_ratio = None
    if vix9d is not None and vix is not None and vix > 0:
        near_term_ratio = round(vix9d / vix, 4)

    # Classify term structure
    if term_structure_slope is not None:
        if term_structure_slope < 1.0:
            ts_label = "contango (normal)"
        elif term_structure_slope > 1.0:
            ts_label = "backwardation (fear)"
        else:
            ts_label = "flat"
    else:
        ts_label = "unknown"

    with sqlite3.connect(db_path) as conn:
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

    result = {
        "vix": vix,
        "vix9d": vix9d,
        "vix3m": vix3m,
        "vix1y": vix1y,
        "term_structure_slope": term_structure_slope,
        "term_structure": ts_label,
    }
    logger.info("[VIX] Term structure: %s", result)
    return result
