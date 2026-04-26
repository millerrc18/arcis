"""Earnings date lookup and event-risk classification.

Called by: features.engine
Calls: universe.sp100
Owns tables: none
Config keys: none
Tests: tests/test_earnings.py

Checks the earnings_calendar table first (populated by overnight scraper),
falls back to yfinance if no cached data exists.
"""

import logging
from datetime import date, datetime, timedelta

logger = logging.getLogger(__name__)


def _coerce_as_of(as_of: date | str | None) -> date | None:
    """Normalize as_of input to a date, or None."""
    if as_of is None:
        return None
    if isinstance(as_of, datetime):
        return as_of.date()
    if isinstance(as_of, date):
        return as_of
    if isinstance(as_of, str):
        try:
            return date.fromisoformat(as_of[:10])
        except (ValueError, TypeError):
            return None
    return None


def _parse_yfinance_calendar(cal) -> str | None:
    """Try to extract an ISO earnings date from a yfinance calendar object.

    yfinance returns either a dict (newer versions) or a DataFrame (older);
    we handle both. Returns None when nothing parseable is present.
    """
    if cal is None:
        return None
    if isinstance(cal, dict):
        earnings_dates = cal.get("Earnings Date")
        if not earnings_dates:
            return None
        if isinstance(earnings_dates, list) and len(earnings_dates) > 0:
            d = earnings_dates[0]
            return d.date().isoformat() if hasattr(d, "date") else str(d)[:10]
        if hasattr(earnings_dates, "date"):
            return earnings_dates.date().isoformat()
        return None
    if hasattr(cal, "index") and "Earnings Date" in cal.index:
        vals = cal.loc["Earnings Date"]
        if hasattr(vals, "iloc") and len(vals) > 0:
            d = vals.iloc[0]
            return d.date().isoformat() if hasattr(d, "date") else str(d)[:10]
    return None


def _yfinance_next_earnings(ticker: str) -> str | None:
    """yfinance fallback for live (as_of=None) scans only.

    Never call this with a historical as_of — yfinance always returns
    today's view and would leak future earnings dates into training data.
    """
    try:
        import yfinance as yf
        from src.universe.sp100 import to_yfinance_ticker
        t = yf.Ticker(to_yfinance_ticker(ticker))
        parsed = _parse_yfinance_calendar(t.calendar)
        if parsed:
            return parsed
        # Secondary fallback: .earnings_dates attribute (live-only).
        ed = getattr(t, "earnings_dates", None)
        if ed is not None and hasattr(ed, "index") and len(ed.index) > 0:
            today = date.today()
            future = [d for d in ed.index if hasattr(d, "date") and d.date() >= today]
            if future:
                return min(future).date().isoformat()
    except Exception as e:
        logger.warning("Could not fetch earnings date for %s: %s", ticker, e)
    return None


def get_next_earnings_date(
    ticker: str,
    as_of: date | str | None = None,
) -> str | None:
    """Get the next earnings date for a ticker.

    Checks cached earnings_calendar table first (fast),
    falls back to yfinance API if no cached data.

    Args:
        ticker: Ticker symbol.
        as_of: Point-in-time cutoff. When provided, only earnings with
            date >= as_of and date <= as_of + 90d are returned from cache,
            and the yfinance fallback is suppressed (yfinance always
            returns "today's view" and cannot answer point-in-time
            queries — using it for historical scans would leak future
            information into training data). None preserves live-scan
            behavior (today + 90d window, yfinance fallback enabled).

    Returns ISO date string (YYYY-MM-DD) or None if unavailable.
    """
    cutoff = _coerce_as_of(as_of)

    # Try cached data first. Sprint 0/Wave 5a EARNINGS-PIT: pass as_of so
    # the SQL window is anchored to as_of (not today()) when the caller
    # is doing a historical scan / backtest.
    try:
        from scripts.fetch_earnings_calendar import get_earnings_within_days
        result = get_earnings_within_days(ticker, days=90, as_of=cutoff)
        if result:
            return result["earnings_date"]
    except Exception as e:
        # #587 — never silently swallow cache failures; log at DEBUG so
        # operators have a breadcrumb if the cache disappears entirely.
        logger.debug("earnings_calendar lookup failed for %s: %s", ticker, e)

    # yfinance fallback: only safe for live (as_of=None) scans.
    if cutoff is not None:
        return None

    return _yfinance_next_earnings(ticker)


_EMPTY_OVERLAP = {
    "earnings_date": None,
    "hold_overlaps_earnings": False,
    "days_to_earnings": None,
    "event_risk_level": "none",
}


def check_earnings_overlap(
    earnings_date: str | None,
    expected_hold_days: int = 10,
    as_of: date | str | None = None,
) -> dict:
    """Check if a hold window overlaps with earnings.

    Args:
        earnings_date: ISO date string or None.
        expected_hold_days: Max expected hold period in trading days.
        as_of: Point-in-time reference date. When provided, days_to_earnings
            and overlap classification use as_of instead of date.today().
            None preserves live-scan behavior (today).

    Returns:
        Dict with earnings_date, hold_overlaps_earnings, days_to_earnings,
        and event_risk_level.
    """
    if not earnings_date:
        return dict(_EMPTY_OVERLAP)

    try:
        earn_date = date.fromisoformat(earnings_date)
    except (ValueError, TypeError):
        return dict(_EMPTY_OVERLAP)

    cutoff = _coerce_as_of(as_of)
    today = cutoff if cutoff is not None else date.today()
    delta = (earn_date - today).days

    if delta < 0:
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
