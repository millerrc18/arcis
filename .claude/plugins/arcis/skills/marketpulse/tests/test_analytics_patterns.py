"""Tests for MarketPulse pattern analytics module."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Ensure lib is importable
# ---------------------------------------------------------------------------
_MP_ROOT = Path(__file__).resolve().parent.parent
if str(_MP_ROOT) not in sys.path:
    sys.path.insert(0, str(_MP_ROOT))

from tests.fixtures.make_bars import make_bars_df  # noqa: E402
from lib.analytics.patterns import (  # noqa: E402
    intraday_patterns,
    day_of_week_effects,
    monthly_seasonality,
)


# ---------------------------------------------------------------------------
# intraday_patterns
# ---------------------------------------------------------------------------


class TestIntradayPatterns:
    """Tests for the ``intraday_patterns`` function."""

    def test_intraday_patterns_buckets(self):
        """30-min buckets from 390 bars should yield 13 buckets."""
        df = make_bars_df(tickers="AAPL", days=30, bars_per_day=390, seed=42)
        result = intraday_patterns(df, ticker="AAPL", bucket_minutes=30)

        assert result.ticker == "AAPL"
        # 390 minutes / 30-min buckets = 13 buckets
        assert len(result.buckets) == 13

        # Each bucket should have valid hour/minute
        for b in result.buckets:
            assert 0 <= b.hour <= 23
            assert b.minute % 30 == 0
            assert b.bar_count > 0

    def test_intraday_patterns_avg_return(self):
        """avg_return should be a finite float for every bucket."""
        df = make_bars_df(tickers="AAPL", days=30, bars_per_day=390, seed=42)
        result = intraday_patterns(df, ticker="AAPL", bucket_minutes=30)

        for b in result.buckets:
            assert isinstance(b.avg_return, float)
            assert b.avg_return == b.avg_return  # not NaN

    def test_intraday_patterns_volume(self):
        """avg_volume should be > 0 for every bucket."""
        df = make_bars_df(tickers="AAPL", days=30, bars_per_day=390, seed=42)
        result = intraday_patterns(df, ticker="AAPL", bucket_minutes=30)

        for b in result.buckets:
            assert b.avg_volume > 0


# ---------------------------------------------------------------------------
# day_of_week_effects
# ---------------------------------------------------------------------------


class TestDayOfWeekEffects:
    """Tests for the ``day_of_week_effects`` function."""

    def test_day_of_week_five_days(self):
        """With 30 days of data, all 5 weekdays should be represented."""
        df = make_bars_df(tickers="AAPL", days=30, bars_per_day=50, seed=42)
        result = day_of_week_effects(df, ticker="AAPL")

        assert result.ticker == "AAPL"
        assert len(result.days) == 5

    def test_day_of_week_day_names(self):
        """Day names should be Monday through Friday in order."""
        df = make_bars_df(tickers="AAPL", days=30, bars_per_day=50, seed=42)
        result = day_of_week_effects(df, ticker="AAPL")

        expected_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
        actual_names = [d.day_name for d in result.days]
        assert actual_names == expected_names

        expected_numbers = [0, 1, 2, 3, 4]
        actual_numbers = [d.day_number for d in result.days]
        assert actual_numbers == expected_numbers

    def test_day_of_week_t_test(self):
        """With 30 days of data, t_stat and p_value should be populated."""
        df = make_bars_df(tickers="AAPL", days=30, bars_per_day=50, seed=42)
        result = day_of_week_effects(df, ticker="AAPL")

        for d in result.days:
            assert d.t_stat is not None, f"{d.day_name} t_stat is None"
            assert d.p_value is not None, f"{d.day_name} p_value is None"
            assert isinstance(d.t_stat, float)
            assert isinstance(d.p_value, float)
            assert 0 <= d.p_value <= 1


# ---------------------------------------------------------------------------
# monthly_seasonality
# ---------------------------------------------------------------------------


class TestMonthlySeasonality:
    """Tests for the ``monthly_seasonality`` function."""

    def test_monthly_seasonality_months(self):
        """Month count should match unique months present in the data."""
        df = make_bars_df(tickers="AAPL", days=30, bars_per_day=50, seed=42)
        result = monthly_seasonality(df, ticker="AAPL")

        assert result.ticker == "AAPL"

        # Data starts 2022-01-03, 30 trading days spans roughly Jan-Feb
        # Verify that the number of months matches what's in the data
        import pandas as pd

        ts = pd.to_datetime(df[df["ticker"] == "AAPL"]["timestamp"])
        expected_months = ts.dt.month.nunique()
        assert len(result.months) == expected_months

    def test_monthly_seasonality_names(self):
        """Month names should be valid calendar month names."""
        df = make_bars_df(tickers="AAPL", days=30, bars_per_day=50, seed=42)
        result = monthly_seasonality(df, ticker="AAPL")

        import calendar

        valid_names = list(calendar.month_name[1:])  # January..December
        for m in result.months:
            assert m.month_name in valid_names
            assert m.month_name == calendar.month_name[m.month]
            assert m.sample_count > 0
            assert m.avg_volume > 0


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Edge-case and graceful-degradation tests."""

    def test_insufficient_data_graceful(self):
        """1 day of data -- day_of_week_effects should not crash."""
        df = make_bars_df(tickers="AAPL", days=1, bars_per_day=50, seed=42)
        result = day_of_week_effects(df, ticker="AAPL")

        assert result.ticker == "AAPL"
        # With 1 day, only 1 weekday represented
        assert len(result.days) == 1
        # t-test should be None (sample too small for that day or other days)
        d = result.days[0]
        assert d.sample_count == 1
        assert d.t_stat is None
        assert d.p_value is None


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------


class TestSerialization:
    """Verify to_dict() works on pattern result types."""

    def test_to_dict_serialization(self):
        """All pattern result types produce JSON-safe dicts."""
        df = make_bars_df(tickers="AAPL", days=30, bars_per_day=50, seed=42)

        ip = intraday_patterns(df, ticker="AAPL")
        ip_d = ip.to_dict()
        assert isinstance(ip_d, dict)
        assert "ticker" in ip_d
        assert "buckets" in ip_d
        assert isinstance(ip_d["buckets"], list)

        dow = day_of_week_effects(df, ticker="AAPL")
        dow_d = dow.to_dict()
        assert isinstance(dow_d, dict)
        assert "ticker" in dow_d
        assert "days" in dow_d
        assert len(dow_d["days"]) == 5

        ms = monthly_seasonality(df, ticker="AAPL")
        ms_d = ms.to_dict()
        assert isinstance(ms_d, dict)
        assert "ticker" in ms_d
        assert "months" in ms_d
        assert isinstance(ms_d["months"], list)
