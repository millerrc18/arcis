"""Fetch upcoming earnings dates for the S&P 100 universe.

Stores earnings dates in SQLite for use by the scan pipeline to flag
earnings-adjacent trades. The risk governor and LLM prompt can check
whether a ticker reports earnings within N days.

Usage:
    python scripts/fetch_earnings_calendar.py
    python scripts/fetch_earnings_calendar.py --days-ahead 90

Also callable from the watch loop overnight schedule.
"""

import argparse
import logging
import os
import sqlite3
import sys
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import yfinance as yf

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.config import DB_PATH
from src.journal.store import initialize_database

logger = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")


def fetch_earnings_dates(
    tickers: list[str],
    db_path: str = DB_PATH,
) -> dict:
    """Fetch next earnings dates for all tickers.

    Returns: {"tickers_with_dates": int, "errors": int, "upcoming_7d": list}
    """
    initialize_database(db_path)
    now = datetime.now(ET)
    collected_at = now.isoformat()

    tickers_with_dates = 0
    errors = 0
    upcoming_7d = []
    upcoming_14d = []
    all_earnings = []

    for ticker in tickers:
        try:
            stock = yf.Ticker(ticker)
            cal = stock.calendar

            if cal is None or (hasattr(cal, 'empty') and cal.empty):
                continue

            # yfinance returns calendar as a dict or DataFrame depending on version
            earnings_date = None
            earnings_time = None

            if isinstance(cal, dict):
                # Newer yfinance versions return dict
                ed = cal.get("Earnings Date")
                if ed:
                    if isinstance(ed, list) and len(ed) > 0:
                        earnings_date = ed[0]
                    elif isinstance(ed, (datetime,)):
                        earnings_date = ed
                earnings_time = cal.get("Earnings Time", None)
            else:
                # Older versions return DataFrame
                try:
                    if "Earnings Date" in cal.columns:
                        ed = cal["Earnings Date"].iloc[0]
                        if hasattr(ed, 'strftime'):
                            earnings_date = ed
                except (KeyError, IndexError, AttributeError):
                    pass

            if earnings_date is None:
                # Fallback: try .earnings_dates attribute
                try:
                    ed_series = stock.earnings_dates
                    if ed_series is not None and len(ed_series) > 0:
                        # Get the next future date
                        future_dates = [d for d in ed_series.index if d.tz_localize(None) >= datetime.now()]
                        if future_dates:
                            earnings_date = future_dates[0]
                except Exception:
                    pass

            if earnings_date is None:
                continue

            # Normalize to date string
            if hasattr(earnings_date, 'strftime'):
                date_str = earnings_date.strftime("%Y-%m-%d")
            else:
                date_str = str(earnings_date)[:10]

            # Determine earnings_time if available
            time_str = None
            if earnings_time:
                time_str = str(earnings_time).lower()
                if "bmo" in time_str or "before" in time_str:
                    time_str = "BMO"
                elif "amc" in time_str or "after" in time_str:
                    time_str = "AMC"
                else:
                    time_str = "TBD"

            # Upsert into database
            with sqlite3.connect(db_path) as conn:
                conn.execute(
                    """INSERT INTO earnings_calendar
                    (ticker, earnings_date, earnings_time, confirmed, collected_at)
                    VALUES (?, ?, ?, 0, ?)
                    ON CONFLICT(ticker, earnings_date)
                    DO UPDATE SET earnings_time=excluded.earnings_time,
                                  collected_at=excluded.collected_at""",
                    (ticker, date_str, time_str, collected_at),
                )

            tickers_with_dates += 1
            all_earnings.append({
                "ticker": ticker,
                "earnings_date": date_str,
                "earnings_time": time_str,
            })

            # Check proximity
            try:
                ed_dt = datetime.strptime(date_str, "%Y-%m-%d")
                days_away = (ed_dt - now.replace(tzinfo=None)).days
                if 0 <= days_away <= 7:
                    upcoming_7d.append(f"{ticker} ({date_str}, {time_str or 'TBD'})")
                if 0 <= days_away <= 14:
                    upcoming_14d.append(f"{ticker} ({date_str}, {days_away}d away)")
            except ValueError:
                pass

            logger.info("[EARNINGS] %s: %s (%s)", ticker, date_str, time_str or "TBD")

        except Exception as e:
            logger.debug("[EARNINGS] Error fetching %s: %s", ticker, e)
            errors += 1

        # Rate limit
        time.sleep(0.3)

    result = {
        "tickers_with_dates": tickers_with_dates,
        "errors": errors,
        "upcoming_7d": upcoming_7d,
        "upcoming_14d": upcoming_14d,
        "total_collected": len(all_earnings),
    }
    logger.info("[EARNINGS] Collection complete: %s", result)
    return result


def get_earnings_within_days(
    ticker: str,
    days: int = 3,
    db_path: str = DB_PATH,
) -> dict | None:
    """Check if a ticker has earnings within N days.

    Returns dict with earnings info if within window, None otherwise.
    Used by the risk governor and scan pipeline.
    """
    initialize_database(db_path)
    now = datetime.now(ET)
    cutoff = (now + timedelta(days=days)).strftime("%Y-%m-%d")
    today = now.strftime("%Y-%m-%d")

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            """SELECT * FROM earnings_calendar
            WHERE ticker = ? AND earnings_date >= ? AND earnings_date <= ?
            ORDER BY earnings_date ASC LIMIT 1""",
            (ticker, today, cutoff),
        ).fetchone()

    if row:
        ed = datetime.strptime(row["earnings_date"], "%Y-%m-%d")
        days_away = (ed - now.replace(tzinfo=None)).days
        return {
            "ticker": ticker,
            "earnings_date": row["earnings_date"],
            "earnings_time": row["earnings_time"],
            "days_away": days_away,
        }
    return None


def get_all_upcoming_earnings(
    days: int = 14,
    db_path: str = DB_PATH,
) -> list[dict]:
    """Get all earnings within the next N days.

    Returns list of dicts sorted by date.
    """
    initialize_database(db_path)
    now = datetime.now(ET)
    cutoff = (now + timedelta(days=days)).strftime("%Y-%m-%d")
    today = now.strftime("%Y-%m-%d")

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """SELECT * FROM earnings_calendar
            WHERE earnings_date >= ? AND earnings_date <= ?
            ORDER BY earnings_date ASC""",
            (today, cutoff),
        ).fetchall()

    results = []
    for row in rows:
        ed = datetime.strptime(row["earnings_date"], "%Y-%m-%d")
        days_away = (ed - now.replace(tzinfo=None)).days
        results.append({
            "ticker": row["ticker"],
            "earnings_date": row["earnings_date"],
            "earnings_time": row["earnings_time"],
            "days_away": days_away,
        })
    return results


def main():
    parser = argparse.ArgumentParser(description="Fetch S&P 100 earnings calendar")
    parser.add_argument("--days-ahead", type=int, default=90,
                        help="How many days ahead to look")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    # Handle both standalone and module execution
    import sys
    import os
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    from src.universe.sp100 import get_sp100_universe
    universe = get_sp100_universe()

    print(f"\n{'='*60}")
    print(f"EARNINGS CALENDAR — S&P 100")
    print(f"{'='*60}")
    print(f"Fetching earnings dates for {len(universe)} tickers...\n")

    result = fetch_earnings_dates(universe)

    print(f"\nResults:")
    print(f"  Tickers with dates: {result['tickers_with_dates']}")
    print(f"  Errors: {result['errors']}")
    print(f"  Total stored: {result['total_collected']}")

    if result["upcoming_7d"]:
        print(f"\n⚠️  EARNINGS THIS WEEK ({len(result['upcoming_7d'])} stocks):")
        for item in result["upcoming_7d"]:
            print(f"  • {item}")

    if result["upcoming_14d"]:
        print(f"\n📅 EARNINGS NEXT 14 DAYS ({len(result['upcoming_14d'])} stocks):")
        for item in result["upcoming_14d"]:
            print(f"  • {item}")

    print()


if __name__ == "__main__":
    main()
