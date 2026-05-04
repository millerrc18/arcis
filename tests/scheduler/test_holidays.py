"""Tests for src.scheduler.holidays — NYSE holiday + half-day detection
backed by pandas_market_calendars (T2.11).

Covers:
- Spot-check 5 known half-days (NYSE early closes)
- Spot-check 3 known holidays (full closures)
- Regression: every date in the legacy hardcoded 2026 set is still a holiday
- Forward-looking: 2027 dates correctly identified
- Public API preserved: is_market_holiday(date_str=None, check_date=None)
- Module-level export NYSE_HOLIDAYS_2026 still present (back-compat for
  tests/test_config_tech_debt.py::test_holidays_module_complete).
- subtract_trading_days(anchor, n) — NYSE-calendar-aware trading-day subtraction
"""

from datetime import date, datetime


# ---------------------------------------------------------------------------
# Holidays (full closures)
# ---------------------------------------------------------------------------

def test_full_closure_2026_independence_day_observed():
    from src.scheduler.holidays import is_market_holiday

    # 2026-07-04 is Saturday, so observed on Friday 2026-07-03.
    assert is_market_holiday(check_date=date(2026, 7, 3)) is True


def test_full_closure_2026_thanksgiving():
    from src.scheduler.holidays import is_market_holiday

    assert is_market_holiday(check_date=date(2026, 11, 26)) is True


def test_full_closure_2026_christmas():
    from src.scheduler.holidays import is_market_holiday

    assert is_market_holiday("2026-12-25") is True


def test_regular_trading_day_is_not_holiday():
    from src.scheduler.holidays import is_market_holiday

    # 2026-03-10 — regular Tuesday, no observance.
    assert is_market_holiday("2026-03-10") is False


# ---------------------------------------------------------------------------
# Half-days (early closes — markets still open, NOT full holidays)
# ---------------------------------------------------------------------------

def test_half_day_2026_day_after_thanksgiving():
    from src.scheduler.holidays import is_market_half_day

    assert is_market_half_day(check_date=date(2026, 11, 27)) is True


def test_half_day_2026_christmas_eve():
    from src.scheduler.holidays import is_market_half_day

    assert is_market_half_day(check_date=date(2026, 12, 24)) is True


def test_half_day_string_arg():
    from src.scheduler.holidays import is_market_half_day

    assert is_market_half_day("2026-11-27") is True


def test_half_day_2027_day_after_thanksgiving():
    from src.scheduler.holidays import is_market_half_day

    # 2027 Thanksgiving = 2027-11-25 → half-day on 2027-11-26.
    assert is_market_half_day(check_date=date(2027, 11, 26)) is True


def test_half_day_excludes_full_holiday():
    from src.scheduler.holidays import is_market_half_day

    # Christmas day is a full closure, NOT a half-day.
    assert is_market_half_day(check_date=date(2026, 12, 25)) is False


def test_half_day_excludes_regular_trading_day():
    from src.scheduler.holidays import is_market_half_day

    assert is_market_half_day(check_date=date(2026, 3, 10)) is False


def test_half_day_is_not_a_full_holiday():
    """Early-close days must not be reported as is_market_holiday=True."""
    from src.scheduler.holidays import is_market_holiday

    assert is_market_holiday(check_date=date(2026, 11, 27)) is False
    assert is_market_holiday(check_date=date(2026, 12, 24)) is False


# ---------------------------------------------------------------------------
# Regression: legacy hardcoded set must still be a subset of detected holidays
# ---------------------------------------------------------------------------

def test_legacy_2026_holidays_still_detected():
    """Every date the old hardcoded NYSE_HOLIDAYS_2026 contained must
    still be reported as a holiday by the new calendar-backed logic."""
    from src.scheduler.holidays import is_market_holiday

    legacy_2026 = {
        date(2026, 1, 1),    # New Year's Day
        date(2026, 1, 19),   # MLK Day
        date(2026, 2, 16),   # Presidents' Day
        date(2026, 4, 3),    # Good Friday
        date(2026, 5, 25),   # Memorial Day
        date(2026, 6, 19),   # Juneteenth
        date(2026, 7, 3),    # Independence Day (observed)
        date(2026, 9, 7),    # Labor Day
        date(2026, 11, 26),  # Thanksgiving
        date(2026, 12, 25),  # Christmas
    }
    for d in legacy_2026:
        assert is_market_holiday(check_date=d) is True, f"Regression: {d} no longer detected as holiday"


def test_nyse_holidays_2026_constant_preserved():
    """Module-level NYSE_HOLIDAYS_2026 export still exists (back-compat for
    tests/test_config_tech_debt.py::test_holidays_module_complete)."""
    from src.scheduler.holidays import NYSE_HOLIDAYS_2026

    assert len(NYSE_HOLIDAYS_2026) == 10
    assert date(2026, 6, 19) in NYSE_HOLIDAYS_2026   # Juneteenth (#270)
    assert date(2026, 11, 26) in NYSE_HOLIDAYS_2026  # Thanksgiving


# ---------------------------------------------------------------------------
# Forward-looking: 2027 — old hardcoded code would have failed in 2027.
# ---------------------------------------------------------------------------

def test_forward_looking_2027_new_years_day():
    from src.scheduler.holidays import is_market_holiday

    assert is_market_holiday(check_date=date(2027, 1, 1)) is True


def test_forward_looking_2027_christmas_observed():
    from src.scheduler.holidays import is_market_holiday

    # 2027-12-25 is Saturday → observed Friday 2027-12-24.
    assert is_market_holiday(check_date=date(2027, 12, 24)) is True


def test_forward_looking_2027_thanksgiving():
    from src.scheduler.holidays import is_market_holiday

    assert is_market_holiday(check_date=date(2027, 11, 25)) is True


def test_forward_looking_2027_regular_day():
    from src.scheduler.holidays import is_market_holiday

    # 2027-03-09 — regular Tuesday.
    assert is_market_holiday(check_date=date(2027, 3, 9)) is False


# ---------------------------------------------------------------------------
# Default-arg behavior preserved (today())
# ---------------------------------------------------------------------------

def test_is_market_holiday_no_args_returns_bool():
    from src.scheduler.holidays import is_market_holiday

    # Without args, falls back to today(). Just confirm it returns a bool
    # without raising.
    assert isinstance(is_market_holiday(), bool)


# ---------------------------------------------------------------------------
# Sprint 0 Wave 2a (HALF-DAY, T10) — _is_market_open must respect half-days.
# Pre-fix: _is_market_open ignored is_market_half_day, so the watch loop
# scanned/traded 13:00-16:00 ET on early-close days.
# ---------------------------------------------------------------------------


def test_is_market_open_returns_false_after_1pm_on_half_day():
    """On NYSE half-days (1pm ET close), _is_market_open must return False
    after 13:00 ET. Pre-fix this returned True until 16:00 ET.

    Reference half-day: 2026-11-27 (day after Thanksgiving) is a real NYSE
    half-day per pandas_market_calendars.
    """
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from src.scheduler.watch import WatchLoop

    wl = WatchLoop.__new__(WatchLoop)
    wl.market_open_hour = 9
    wl.market_open_minute = 30
    wl.market_close_hour = 16

    et = ZoneInfo("America/New_York")
    # 13:30 ET on a real NYSE half-day
    now = datetime(2026, 11, 27, 13, 30, tzinfo=et)
    assert wl._is_market_open(now) is False


def test_is_market_open_returns_true_before_1pm_on_half_day():
    """Half-days are still open in the morning — only the 13:00-16:00
    window should be blocked. Confirms we don't over-suppress."""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from src.scheduler.watch import WatchLoop

    wl = WatchLoop.__new__(WatchLoop)
    wl.market_open_hour = 9
    wl.market_open_minute = 30
    wl.market_close_hour = 16

    et = ZoneInfo("America/New_York")
    # 11:00 ET on the same half-day — market still open
    now = datetime(2026, 11, 27, 11, 0, tzinfo=et)
    assert wl._is_market_open(now) is True


def test_is_market_open_unaffected_on_regular_trading_day():
    """Regression: a regular trading day must still be open at 13:30 ET."""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from src.scheduler.watch import WatchLoop

    wl = WatchLoop.__new__(WatchLoop)
    wl.market_open_hour = 9
    wl.market_open_minute = 30
    wl.market_close_hour = 16

    et = ZoneInfo("America/New_York")
    # 2026-03-10 is a regular Tuesday (not holiday, not half-day)
    now = datetime(2026, 3, 10, 13, 30, tzinfo=et)
    assert wl._is_market_open(now) is True


def test_is_market_open_returns_false_on_full_holiday():
    """Regression: full closures still suppress the market regardless of time."""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from src.scheduler.watch import WatchLoop

    wl = WatchLoop.__new__(WatchLoop)
    wl.market_open_hour = 9
    wl.market_open_minute = 30
    wl.market_close_hour = 16

    et = ZoneInfo("America/New_York")
    # 2026-11-26 is Thanksgiving (full closure)
    now = datetime(2026, 11, 26, 11, 0, tzinfo=et)
    assert wl._is_market_open(now) is False


# ---------------------------------------------------------------------------
# subtract_trading_days — B.1 (#106) NYSE-calendar-aware trading-day subtraction
# ---------------------------------------------------------------------------


def test_subtract_trading_days_one_step_weekday():
    """Mon 2026-01-05, n=1 -> prior Friday 2026-01-02 (one step back)."""
    from src.scheduler.holidays import subtract_trading_days

    result = subtract_trading_days(date(2026, 1, 5), 1)
    assert result == date(2026, 1, 2)
    assert isinstance(result, date) and not isinstance(result, datetime)


def test_subtract_trading_days_crosses_holiday():
    """Tue 2026-01-20, n=1 -> Fri 2026-01-16 (skips MLK Day Mon 2026-01-19)."""
    from src.scheduler.holidays import subtract_trading_days

    result = subtract_trading_days(date(2026, 1, 20), 1)
    assert result == date(2026, 1, 16)
    assert isinstance(result, date) and not isinstance(result, datetime)


def test_subtract_trading_days_crosses_weekend():
    """Mon 2026-01-05, n=2 -> Wed 2025-12-31 (skips Sat/Sun + New Year's 2026-01-01)."""
    from src.scheduler.holidays import subtract_trading_days

    result = subtract_trading_days(date(2026, 1, 5), 2)
    assert result == date(2025, 12, 31)
    assert isinstance(result, date) and not isinstance(result, datetime)


def test_subtract_trading_days_two_hundred_anchor():
    """anchor=2026-05-01, n=200 -> 2025-07-16.

    Verified by independent calendar count: there are exactly 200 NYSE trading
    days in the half-open interval (2025-07-16, 2026-05-01] (i.e. 2025-07-17
    through 2026-05-01 inclusive = 200 trading days). The window start is
    2025-06-05 (ceil(200*1.6)+10=330 calendar days before anchor), well inside
    the 228-day trading-day window that pandas_market_calendars returns.
    """
    from src.scheduler.holidays import subtract_trading_days

    result = subtract_trading_days(date(2026, 5, 1), 200)
    assert result == date(2025, 7, 16)
    assert isinstance(result, date) and not isinstance(result, datetime)


def test_subtract_trading_days_zero_returns_anchor_or_prior():
    """n=0 returns anchor if anchor is a NYSE trading day.

    Semantic: n=0 means 'the trading day at or immediately before anchor'.
    For a regular weekday (2026-01-05, Monday) that is anchor itself.
    """
    from src.scheduler.holidays import subtract_trading_days

    result = subtract_trading_days(date(2026, 1, 5), 0)
    assert result == date(2026, 1, 5)
    assert isinstance(result, date) and not isinstance(result, datetime)


def test_subtract_trading_days_raises_on_negative():
    """n < 0 must raise ValueError with a message containing the bad value."""
    import pytest
    from src.scheduler.holidays import subtract_trading_days

    with pytest.raises(ValueError, match="-1"):
        subtract_trading_days(date(2026, 1, 5), -1)


def test_subtract_trading_days_anchor_on_saturday():
    """Sat 2026-01-17, n=1 -> Thu 2026-01-15.

    Saturday is not a trading day; anchor rounds back to Fri 2026-01-16,
    then one step back lands on Thu 2026-01-15.
    """
    from src.scheduler.holidays import subtract_trading_days

    result = subtract_trading_days(date(2026, 1, 17), 1)
    assert result == date(2026, 1, 15)
    assert isinstance(result, date) and not isinstance(result, datetime)
