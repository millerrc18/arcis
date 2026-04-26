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
"""

from datetime import date


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
