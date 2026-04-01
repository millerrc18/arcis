"""CBOE Put/Call ratio collector.

Called by: api/routes/actions.py, cli/commands.py, scheduler/watch.py
Calls: none
Owns tables: cboe_ratios
Config keys: none
Tests: none

Fetches daily aggregate put/call ratios.
Uses yfinance for CBOE P/C ratio proxy data.
"""

import logging
import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")

DB_PATH = "ai_research_desk.sqlite3"

_INIT_SQL = """
CREATE TABLE IF NOT EXISTS cboe_ratios (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    collected_at TEXT NOT NULL,
    collected_date TEXT NOT NULL,
    equity_pc_ratio REAL,
    index_pc_ratio REAL,
    total_pc_ratio REAL,
    equity_pc_vs_20d_avg REAL
);

CREATE INDEX IF NOT EXISTS idx_cboe_ratios_date
    ON cboe_ratios(collected_date);
"""


def _init_table(db_path: str) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.executescript(_INIT_SQL)


def _fetch_cboe_pc_ratio() -> dict:
    """Fetch CBOE put/call ratio data.

    Tries multiple approaches:
    1. CBOE website CSV (free, published daily)
    2. Fallback to computed ratio from VIX options
    """
    import requests

    # Approach 1: CBOE daily P/C ratio CSV
    try:
        url = "https://www.cboe.com/us/options/market_statistics/daily/"
        resp = requests.get(
            url,
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=15,
        )
        if resp.status_code == 200 and "text" in resp.headers.get("content-type", ""):
            parsed = _parse_cboe_page(resp.text)
            if parsed is not None:
                return parsed
    except Exception as e:
        logger.debug("[CBOE] Website fetch failed: %s", e)

    # Approach 2: Use yfinance SPY options as proxy
    try:
        import yfinance as yf
        spy = yf.Ticker("SPY")
        exps = spy.options
        if exps:
            chain = spy.option_chain(exps[0])
            call_vol = int(chain.calls["volume"].sum()) if not chain.calls.empty else 0
            put_vol = int(chain.puts["volume"].sum()) if not chain.puts.empty else 0
            if call_vol > 0:
                return {
                    "equity_pc_ratio": round(put_vol / call_vol, 4),
                    "index_pc_ratio": None,
                    "total_pc_ratio": round(put_vol / call_vol, 4),
                }
    except Exception as e:
        logger.debug("[CBOE] SPY proxy failed: %s", e)

    return {"equity_pc_ratio": None, "index_pc_ratio": None, "total_pc_ratio": None}


def _parse_cboe_page(html: str) -> dict | None:
    """Parse P/C ratios from CBOE market statistics page.

    Returns dict with ratio values, or None if regex extraction fails
    entirely (page format changed).
    """
    import re
    result = {"equity_pc_ratio": None, "index_pc_ratio": None, "total_pc_ratio": None}

    patterns = [
        (r"(?:equity|equities).*?(?:put/call|p/c).*?([\d.]+)", "equity_pc_ratio"),
        (r"(?:index).*?(?:put/call|p/c).*?([\d.]+)", "index_pc_ratio"),
        (r"(?:total).*?(?:put/call|p/c).*?([\d.]+)", "total_pc_ratio"),
    ]
    matched_any = False
    for pattern, key in patterns:
        match = re.search(pattern, html, re.IGNORECASE)
        if match:
            try:
                result[key] = float(match.group(1))
                matched_any = True
            except ValueError:
                pass

    if not matched_any:
        logger.warning("[CBOE] Regex extraction failed — page format may have changed")
        return None

    return result


def _get_20d_avg(conn: sqlite3.Connection, today_str: str) -> float | None:
    """Compute 20-day average equity P/C ratio."""
    rows = conn.execute(
        """SELECT equity_pc_ratio FROM cboe_ratios
        WHERE collected_date < ? AND equity_pc_ratio IS NOT NULL
        ORDER BY collected_date DESC LIMIT 20""",
        (today_str,),
    ).fetchall()
    if not rows:
        return None
    values = [r[0] for r in rows]
    return round(sum(values) / len(values), 4)


def collect_cboe_ratios(db_path: str = DB_PATH) -> dict:
    """Collect daily CBOE put/call ratios.

    Returns: {"equity_pc_ratio": float, "index_pc_ratio": float, "total_pc_ratio": float}
    """
    _init_table(db_path)
    now = datetime.now(ET)
    today_str = now.strftime("%Y-%m-%d")

    data = _fetch_cboe_pc_ratio()

    with sqlite3.connect(db_path) as conn:
        avg_20d = _get_20d_avg(conn, today_str)
        vs_avg = None
        if data.get("equity_pc_ratio") and avg_20d and avg_20d > 0:
            vs_avg = round(data["equity_pc_ratio"] / avg_20d, 4)

        conn.execute(
            """INSERT INTO cboe_ratios
            (collected_at, collected_date, equity_pc_ratio, index_pc_ratio,
             total_pc_ratio, equity_pc_vs_20d_avg)
            VALUES (?, ?, ?, ?, ?, ?)""",
            (
                now.isoformat(),
                today_str,
                data.get("equity_pc_ratio"),
                data.get("index_pc_ratio"),
                data.get("total_pc_ratio"),
                vs_avg,
            ),
        )

    result = {
        "equity_pc_ratio": data.get("equity_pc_ratio"),
        "index_pc_ratio": data.get("index_pc_ratio"),
        "total_pc_ratio": data.get("total_pc_ratio"),
        "vs_20d_avg": vs_avg,
    }
    logger.info("[CBOE] Ratios collected: %s", result)
    return result
