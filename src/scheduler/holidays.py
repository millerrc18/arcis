"""NYSE market holiday awareness, backed by pandas_market_calendars.

Called by: scheduler.watch
Calls: pandas_market_calendars.get_calendar('NYSE')
Owns tables: none
Config keys: none
Tests: tests/scheduler/test_holidays.py, tests/test_config_tech_debt.py

History
-------
T2.11: Replaced the hardcoded 2026 NYSE_HOLIDAYS_2026 set (which would have
silently failed in 2027) with pandas_market_calendars.get_calendar('NYSE').
The module still exposes NYSE_HOLIDAYS_2026 for back-compat, but it is now
derived from the live calendar at import time. Adds is_market_half_day() so
callers can distinguish full closures (no trading) from early-close days
(NYSE closes at 13:00 ET — e.g. day after Thanksgiving, Christmas Eve).
"""

from datetime import date, timedelta
from functools import lru_cache
from math import ceil

import pandas_market_calendars as mcal


_NYSE = mcal.get_calendar("NYSE")


@lru_cache(maxsize=8)
def _holidays_for_year(year: int) -> frozenset[date]:
    """Return the set of NYSE full-closure holidays for a given year."""
    holidays = _NYSE.holidays().holidays  # numpy array of np.datetime64
    return frozenset(
        date(int(str(h)[:4]), int(str(h)[5:7]), int(str(h)[8:10]))
        for h in holidays
        if str(h).startswith(f"{year}-")
    )


@lru_cache(maxsize=8)
def _half_days_for_year(year: int) -> frozenset[date]:
    """Return the set of NYSE early-close ("half-day") trading days for a year.

    NYSE early-close days close at 13:00 ET instead of the usual 16:00 ET.
    Typical examples: day after Thanksgiving, Christmas Eve, day before
    Independence Day (when 7/4 is mid-week).
    """
    sched = _NYSE.schedule(start_date=f"{year}-01-01", end_date=f"{year}-12-31")
    closes_et = sched["market_close"].dt.tz_convert("America/New_York")
    early = sched[closes_et.dt.hour < 16]
    return frozenset(d.date() for d in early.index)


def _resolve_check_date(date_str: str | None, check_date: date | None) -> date:
    """Resolve which date to use, preserving the legacy precedence rule:
    check_date > date_str > today()."""
    if check_date is not None:
        return check_date
    if date_str:
        return date.fromisoformat(date_str)
    return date.today()


def is_market_holiday(date_str: str | None = None, check_date: date | None = None) -> bool:
    """Return True if the given date is a full NYSE closure (not a half-day).

    Args:
        date_str: ISO date string (YYYY-MM-DD). If None, uses today.
        check_date: date object. Takes precedence over date_str.
    """
    d = _resolve_check_date(date_str, check_date)
    return d in _holidays_for_year(d.year)


def is_market_half_day(date_str: str | None = None, check_date: date | None = None) -> bool:
    """Return True if the given date is an NYSE early-close (half-day).

    Half-days are partial trading days (13:00 ET close). Full holidays
    are NOT half-days; this function returns False for them.
    """
    d = _resolve_check_date(date_str, check_date)
    return d in _half_days_for_year(d.year)


def subtract_trading_days(anchor: date, n: int) -> date:
    """Return the date that is N NYSE trading days before anchor.

    Uses pandas_market_calendars to honor weekends, full holidays, AND
    half-days (which still count as trading days). If anchor itself is
    a non-trading day, round it back to the previous trading day, then
    step back N.

    Args:
        anchor: anchor date.
        n: number of trading days to subtract; must be >= 0.

    Returns:
        A date object N trading days before anchor.

    Raises:
        ValueError: if n < 0.
    """
    if n < 0:
        raise ValueError("n must be non-negative, got %d" % n)
    window_start = anchor - timedelta(days=ceil(n * 1.6) + 10)
    trading_days = _NYSE.valid_days(start_date=window_start, end_date=anchor)
    return trading_days[-(n + 1)].date()


# Back-compat: tests/test_config_tech_debt.py::test_holidays_module_complete
# imports this constant. It is now derived from pandas_market_calendars but
# preserves the original 10-entry shape for 2026.
NYSE_HOLIDAYS_2026: frozenset[date] = _holidays_for_year(2026)
