"""Tests for SPY benchmark utility (SD#41 REVISED / Sprint D1)."""

from unittest.mock import patch

import pandas as pd
import pytest

from src.analytics.spy_benchmark import (
    _load_sector_lookup,
    excess_return,
    get_sector,
    spy_return_over_range,
)


def test_excess_return_positive_when_beating_spy():
    """pnl_pct=5.0 (percent), spy=0.02 (fraction) -> excess = 5 - 2 = 3.0."""
    assert excess_return(5.0, 0.02) == pytest.approx(3.0)


def test_excess_return_negative_when_losing_to_spy():
    """pnl_pct=1.0, spy=+3% -> excess = 1 - 3 = -2.0."""
    assert excess_return(1.0, 0.03) == pytest.approx(-2.0)


def test_excess_return_none_when_spy_unavailable():
    """Missing SPY data must propagate as None, not as zero."""
    assert excess_return(1.0, None) is None


def test_excess_return_none_when_pnl_none():
    """Missing pnl_pct must propagate as None."""
    assert excess_return(None, 0.02) is None


def test_spy_return_handles_empty_yfinance_response():
    """Empty DataFrame from yfinance -> None (not crash, not zero)."""
    with patch("yfinance.download") as mock_dl:
        mock_dl.return_value = pd.DataFrame()
        assert (
            spy_return_over_range(
                "2026-01-01T10:00:00", "2026-01-05T10:00:00"
            )
            is None
        )


def test_spy_return_handles_exception_gracefully():
    """Any yfinance exception -> None; never propagates to the exit path."""
    with patch("yfinance.download", side_effect=Exception("net")):
        assert (
            spy_return_over_range(
                "2026-01-01T10:00:00", "2026-01-05T10:00:00"
            )
            is None
        )


def test_iso_to_date_coerces_pg_native_datetime_and_string():
    """#132 verify-by-mutation: _iso_to_date must accept a PG-native datetime
    (psycopg2 timestamp return) AND an ISO string.

    The pre-fix inline ``entry_iso.replace("Z", "+00:00")`` called
    ``datetime.replace(year="Z", month="+00:00")`` on a datetime → "'str' object
    cannot be interpreted as an integer". Reverting to that inline form removes
    _iso_to_date and breaks this test.
    """
    from datetime import date, datetime, timezone

    from src.analytics.spy_benchmark import _iso_to_date

    # PG-native tz-aware datetime -> date.
    assert _iso_to_date(datetime(2026, 3, 15, 13, 30, tzinfo=timezone.utc)) == date(2026, 3, 15)
    # plain date passes through.
    assert _iso_to_date(date(2026, 3, 15)) == date(2026, 3, 15)
    # ISO string still parses (SQLite path).
    assert _iso_to_date("2026-03-15T09:30:00-04:00") == date(2026, 3, 15)
    # Z suffix normalized.
    assert _iso_to_date("2026-03-15T09:30:00Z") == date(2026, 3, 15)


def test_spy_return_accepts_pg_native_datetime_inputs():
    """#132 verify-by-mutation: spy_return_over_range must compute a return when
    entry/exit arrive as PG-native datetimes.

    store.py:486 calls spy_return_over_range(row["actual_entry_time"], ...) and
    row["actual_entry_time"] is a psycopg2 datetime under the PG cutover. Pre-fix
    that datetime tripped the .replace crash → caught → None, silently disabling
    SPY attribution on every closed trade. Post-fix it computes the real return.
    """
    from datetime import datetime, timezone

    idx = pd.to_datetime(["2026-03-10", "2026-03-15", "2026-03-20", "2026-03-25"])
    frame = pd.DataFrame({"Close": [100.0, 102.0, 105.0, 107.0]}, index=idx)
    frame.index.name = "Date"
    with patch("yfinance.download", return_value=frame):
        result = spy_return_over_range(
            datetime(2026, 3, 15, 13, 30, tzinfo=timezone.utc),
            datetime(2026, 3, 20, 19, 30, tzinfo=timezone.utc),
        )
    assert result is not None  # pre-fix: None (datetime crashed `.replace`)
    assert result == pytest.approx((105.0 - 102.0) / 102.0)


def test_get_sector_returns_none_for_unknown_ticker():
    """Unknown ticker returns None; must not raise KeyError."""
    _load_sector_lookup.cache_clear()
    assert get_sector("FAKEZZ") is None
