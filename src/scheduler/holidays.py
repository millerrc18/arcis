"""NYSE market holiday awareness.

Called by: scheduler.watch
Calls: none
Owns tables: none
Config keys: none
Tests: tests/test_config_tech_debt.py
"""

from datetime import date

# NYSE observed holidays for 2026.
# Source: https://www.nyse.com/markets/hours-calendars
NYSE_HOLIDAYS_2026 = {
    date(2026, 1, 1),   # New Year's Day
    date(2026, 1, 19),  # Martin Luther King Jr. Day
    date(2026, 2, 16),  # Presidents' Day
    date(2026, 4, 3),   # Good Friday
    date(2026, 5, 25),  # Memorial Day
    date(2026, 6, 19),  # Juneteenth — Fix for #270
    date(2026, 7, 3),   # Independence Day (observed)
    date(2026, 9, 7),   # Labor Day
    date(2026, 11, 26), # Thanksgiving Day
    date(2026, 12, 25), # Christmas Day
}


def is_market_holiday(date_str: str | None = None, check_date: date | None = None) -> bool:
    """Return True if the given date is an NYSE holiday.

    Args:
        date_str: ISO date string (YYYY-MM-DD). If None, uses today.
        check_date: date object. Takes precedence over date_str.
    """
    if check_date is None:
        if date_str:
            check_date = date.fromisoformat(date_str)
        else:
            check_date = date.today()
    return check_date in NYSE_HOLIDAYS_2026
