"""CBOE Put/Call ratio collector.

Called by: api/routes/actions.py, cli/commands.py, scheduler/watch.py
Calls: none
Owns tables: cboe_ratios
Config keys: none
Tests: none

API: CBOE website (primary), yfinance SPY options (fallback), FRED (last resort)
Table: cboe_ratios
Schedule: Daily in overnight pipeline

3-tier fallback strategy (#128, #235):
  1. CBOE website scraping — free, published daily, but page format changes
     can break the regex parser (the regex is fragile by nature, #128)
  2. SPY options via yfinance — computes put/call ratio from volume as a
     market-wide proxy. Less accurate but more reliable.
  3. FRED EQUITYPCRATIO series — official data but often delayed 1-2 days.

If all three tiers fail, raises CollectorPartialFailureError rather than
inserting a row with all-NULL ratios (which would pollute the 20-day average).
"""

import logging
import os
import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo

from src.config import DB_PATH

logger = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")

# Table creation handled by src/schema/registry.py


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
        logger.warning("[CBOE] Website fetch failed: %s", e)

    # Approach 2: Use yfinance SPY options as proxy
    try:
        import yfinance as yf
        spy = yf.Ticker("SPY")
        exps = spy.options
        if exps:
            chain = spy.option_chain(exps[0])
            call_vol = chain.calls["volume"].dropna().sum()
            put_vol = chain.puts["volume"].dropna().sum()
            call_vol = int(call_vol) if call_vol > 0 else 0
            put_vol = int(put_vol) if put_vol > 0 else 0
            if call_vol > 0:
                ratio = round(put_vol / call_vol, 4)
                logger.info("[CBOE] SPY proxy P/C ratio: %.4f (put_vol=%d, call_vol=%d)", ratio, put_vol, call_vol)
                return {
                    "equity_pc_ratio": ratio,
                    "index_pc_ratio": None,
                    "total_pc_ratio": ratio,
                }
            else:
                logger.warning("[CBOE] SPY call volume is 0 — cannot compute ratio")
    except Exception as e:
        logger.warning("[CBOE] SPY proxy failed: %s", e)

    # Approach 3: FRED CBOE P/C ratio (series EQUITYPCRATIO)
    try:
        import requests as _req
        fred_key = os.environ.get("FRED_API_KEY")
        if fred_key:
            url = "https://api.stlouisfed.org/fred/series/observations"
            params = {
                "series_id": "EQUITYPCRATIO",
                "api_key": fred_key,
                "file_type": "json",
                "sort_order": "desc",
                "limit": 1,
            }
            resp = _req.get(url, params=params, timeout=10)
            if resp.status_code == 200:
                obs = resp.json().get("observations", [])
                if obs and obs[0].get("value") != ".":
                    ratio = float(obs[0]["value"])
                    logger.info("[CBOE] FRED P/C ratio: %.4f (date=%s)", ratio, obs[0].get("date"))
                    return {
                        "equity_pc_ratio": ratio,
                        "index_pc_ratio": None,
                        "total_pc_ratio": None,
                    }
    except Exception as e:
        logger.warning("[CBOE] FRED fallback failed: %s", e)

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
    # float() cast — SQLite may return TEXT for REAL columns (#195 pattern)
    values = [float(r[0]) for r in rows]
    return round(sum(values) / len(values), 4)


def collect_cboe_ratios(db_path: str = DB_PATH) -> dict:
    """Collect daily CBOE put/call ratios.

    Returns: {"equity_pc_ratio": float, "index_pc_ratio": float, "total_pc_ratio": float}
    """
    now = datetime.now(ET)
    today_str = now.strftime("%Y-%m-%d")

    data = _fetch_cboe_pc_ratio()

    # If all three tiers failed, surface the failure instead of inserting NULLs
    if (data.get("equity_pc_ratio") is None
            and data.get("index_pc_ratio") is None
            and data.get("total_pc_ratio") is None):
        from src.data_collection.errors import CollectorPartialFailureError
        raise CollectorPartialFailureError(
            "All CBOE fallback tiers failed — no ratios collected",
            errors=3, total=3,
        )

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
