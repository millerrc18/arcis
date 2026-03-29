"""Earnings date lookup and event-risk classification.

Checks the earnings_calendar table first (populated by overnight scraper),
falls back to yfinance if no cached data exists.
"""

import logging
from datetime import date, datetime

logger = logging.getLogger(__name__)


def get_next_earnings_date(ticker: str) -> str | None:
    """Get the next earnings date for a ticker.

    Checks cached earnings_calendar table first (fast),
    falls back to yfinance API if no cached data.

    Returns ISO date string (YYYY-MM-DD) or None if unavailable.
    """
    # Try cached data first
    try:
        from scripts.fetch_earnings_calendar import get_earnings_within_days
        result = get_earnings_within_days(ticker, days=90)
        if result:
            return result["earnings_date"]
    except Exception:
        pass

    # Fallback to yfinance
    try:
        import yfinance as yf
        from src.universe.sp100 import to_yfinance_ticker
        t = yf.Ticker(to_yfinance_ticker(ticker))
        # Try .calendar first — returns a dict or DataFrame with earnings dates
        cal = t.calendar
        if cal is not None:
            # yfinance calendar may be a dict with 'Earnings Date' key
            if isinstance(cal, dict):
                earnings_dates = cal.get("Earnings Date")
                if earnings_dates:
                    if isinstance(earnings_dates, list) and len(earnings_dates) > 0:
                        d = earnings_dates[0]
                        if hasattr(d, "date"):
                            return d.date().isoformat()
                        return str(d)[:10]
                    elif hasattr(earnings_dates, "date"):
                        return earnings_dates.date().isoformat()
            # May be a DataFrame
            elif hasattr(cal, "index"):
                if "Earnings Date" in cal.index:
                    vals = cal.loc["Earnings Date"]
                    if hasattr(vals, "iloc") and len(vals) > 0:
                        d = vals.iloc[0]
                        if hasattr(d, "date"):
                            return d.date().isoformat()
                        return str(d)[:10]

        # Fallback: try .earnings_dates attribute
        ed = getattr(t, "earnings_dates", None)
        if ed is not None and hasattr(ed, "index") and len(ed.index) > 0:
            today = date.today()
            future = [d for d in ed.index if hasattr(d, "date") and d.date() >= today]
            if future:
                return min(future).date().isoformat()
    except Exception as e:
        logger.warning("Could not fetch earnings date for %s: %s", ticker, e)

    return None


def check_earnings_overlap(earnings_date: str | None,
                           expected_hold_days: int = 10) -> dict:
    """Check if a hold window overlaps with earnings.

    Args:
        earnings_date: ISO date string or None.
        expected_hold_days: Max expected hold period in trading days.

    Returns:
        Dict with earnings_date, hold_overlaps_earnings, days_to_earnings,
        and event_risk_level.
    """
    if not earnings_date:
        return {
            "earnings_date": None,
            "hold_overlaps_earnings": False,
            "days_to_earnings": None,
            "event_risk_level": "none",
        }

    try:
        earn_date = date.fromisoformat(earnings_date)
    except (ValueError, TypeError):
        return {
            "earnings_date": None,
            "hold_overlaps_earnings": False,
            "days_to_earnings": None,
            "event_risk_level": "none",
        }

    today = date.today()
    delta = (earn_date - today).days

    if delta < 0:
        # Earnings already passed
        return {
            "earnings_date": earnings_date,
            "hold_overlaps_earnings": False,
            "days_to_earnings": delta,
            "event_risk_level": "none",
        }

    overlaps = delta <= expected_hold_days

    if delta <= 3:
        level = "imminent"
    elif overlaps:
        level = "elevated"
    else:
        level = "none"

    return {
        "earnings_date": earnings_date,
        "hold_overlaps_earnings": overlaps,
        "days_to_earnings": delta,
        "event_risk_level": level,
    }
