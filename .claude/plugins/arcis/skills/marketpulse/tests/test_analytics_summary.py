"""Tests for MarketPulse summary analytics module."""

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
from lib.analytics.summary import daily_summary, biggest_movers, volume_analysis  # noqa: E402


# ---------------------------------------------------------------------------
# daily_summary
# ---------------------------------------------------------------------------


class TestDailySummary:
    """Tests for the ``daily_summary`` function."""

    def test_daily_summary_single_ticker(self):
        """1 ticker, 3 days -- verify OHLCV aggregation per day."""
        df = make_bars_df(tickers="AAPL", days=3, bars_per_day=10, seed=1)
        result = daily_summary(df)

        assert result.ticker_count == 1
        assert result.date_count == 3
        assert len(result.summaries) == 3

        for s in result.summaries:
            assert s.ticker == "AAPL"
            assert s.bar_count == 10
            # OHLCV sanity: high >= low, volume > 0
            assert s.high >= s.low
            assert s.volume > 0
            assert s.vwap > 0

    def test_daily_summary_multi_ticker(self):
        """3 tickers -- verify separate summaries, ticker_count=3."""
        df = make_bars_df(tickers=["AAPL", "MSFT", "GOOG"], days=2, bars_per_day=5, seed=7)
        result = daily_summary(df)

        assert result.ticker_count == 3
        assert result.date_count == 2
        # 3 tickers x 2 days = 6 summaries
        assert len(result.summaries) == 6

        tickers_seen = {s.ticker for s in result.summaries}
        assert tickers_seen == {"AAPL", "MSFT", "GOOG"}

    def test_daily_summary_ticker_filter(self):
        """Passing tickers= should filter results."""
        df = make_bars_df(tickers=["AAPL", "MSFT", "GOOG"], days=2, bars_per_day=5, seed=7)
        result = daily_summary(df, tickers=["AAPL", "GOOG"])

        assert result.ticker_count == 2
        tickers_seen = {s.ticker for s in result.summaries}
        assert tickers_seen == {"AAPL", "GOOG"}

    def test_daily_summary_return_and_range(self):
        """Verify daily_return and intraday_range are reasonable floats."""
        df = make_bars_df(tickers="AAPL", days=5, bars_per_day=50, seed=99)
        result = daily_summary(df)

        for s in result.summaries:
            # daily_return should be a finite float, typically small
            assert isinstance(s.daily_return, float)
            assert -1.0 < s.daily_return < 1.0  # shouldn't move >100% in a day

            # intraday_range is always non-negative
            assert isinstance(s.intraday_range, float)
            assert s.intraday_range >= 0.0


# ---------------------------------------------------------------------------
# biggest_movers
# ---------------------------------------------------------------------------


class TestBiggestMovers:
    """Tests for the ``biggest_movers`` function."""

    def test_biggest_movers_gainers_losers(self):
        """Gainers sorted descending, losers sorted ascending by return."""
        df = make_bars_df(
            tickers=["A", "B", "C", "D", "E"],
            days=1,
            bars_per_day=20,
            seed=42,
        )
        # Extract the date from the DataFrame
        date_str = str(df["timestamp"].iloc[0].date())

        result = biggest_movers(df, date_str=date_str, n=5)

        # Gainers: descending by return_pct
        for i in range(len(result.gainers) - 1):
            assert result.gainers[i].return_pct >= result.gainers[i + 1].return_pct

        # Losers: ascending by return_pct
        for i in range(len(result.losers) - 1):
            assert result.losers[i].return_pct <= result.losers[i + 1].return_pct

        assert result.date == date_str
        assert result.n == 5

    def test_biggest_movers_n_param(self):
        """n=2 should return at most 2 gainers and 2 losers."""
        df = make_bars_df(
            tickers=["A", "B", "C", "D", "E"],
            days=1,
            bars_per_day=10,
            seed=55,
        )
        date_str = str(df["timestamp"].iloc[0].date())

        result = biggest_movers(df, date_str=date_str, n=2)

        assert len(result.gainers) == 2
        assert len(result.losers) == 2
        assert result.n == 2

    def test_biggest_movers_empty_date(self):
        """A date with no data should produce empty lists."""
        df = make_bars_df(tickers="AAPL", days=1, bars_per_day=10, seed=1)
        result = biggest_movers(df, date_str="1999-01-01")

        assert len(result.gainers) == 0
        assert len(result.losers) == 0


# ---------------------------------------------------------------------------
# volume_analysis
# ---------------------------------------------------------------------------


class TestVolumeAnalysis:
    """Tests for the ``volume_analysis`` function."""

    def test_volume_analysis_stats(self):
        """Verify total > 0, avg > 0, max >= avg, std >= 0."""
        df = make_bars_df(tickers="AAPL", days=3, bars_per_day=50, seed=10)
        result = volume_analysis(df)

        assert len(result.stats) == 1
        vs = result.stats[0]
        assert vs.ticker == "AAPL"
        assert vs.total_volume > 0
        assert vs.avg_volume > 0
        assert vs.max_volume >= vs.avg_volume
        assert vs.volume_std >= 0

    def test_volume_analysis_multi_ticker(self):
        """3 tickers should produce 3 VolumeStats."""
        df = make_bars_df(tickers=["AAPL", "MSFT", "GOOG"], days=2, bars_per_day=10, seed=20)
        result = volume_analysis(df)

        assert len(result.stats) == 3
        tickers_seen = {vs.ticker for vs in result.stats}
        assert tickers_seen == {"AAPL", "MSFT", "GOOG"}

    def test_volume_analysis_ticker_filter(self):
        """Passing tickers= should filter volume stats."""
        df = make_bars_df(tickers=["AAPL", "MSFT", "GOOG"], days=2, bars_per_day=10, seed=20)
        result = volume_analysis(df, tickers=["MSFT"])

        assert len(result.stats) == 1
        assert result.stats[0].ticker == "MSFT"

    def test_volume_analysis_date_range(self):
        """date_range should be a string in 'YYYY-MM-DD to YYYY-MM-DD' format."""
        df = make_bars_df(tickers="AAPL", days=5, bars_per_day=10, seed=30)
        result = volume_analysis(df)

        assert " to " in result.date_range
        parts = result.date_range.split(" to ")
        assert len(parts) == 2
        # Both should be parseable dates
        for p in parts:
            assert len(p) == 10  # YYYY-MM-DD


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------


class TestSerialization:
    """Verify to_dict() works on all result types."""

    def test_to_dict_daily_summary(self):
        """DailySummaryResult.to_dict() returns a dict with expected keys."""
        df = make_bars_df(tickers="AAPL", days=2, bars_per_day=5, seed=1)
        result = daily_summary(df)
        d = result.to_dict()

        assert isinstance(d, dict)
        assert "summaries" in d
        assert "ticker_count" in d
        assert "date_count" in d
        assert isinstance(d["summaries"], list)
        assert len(d["summaries"]) == 2

    def test_to_dict_biggest_movers(self):
        """BiggestMoversResult.to_dict() returns a dict with expected keys."""
        df = make_bars_df(tickers=["A", "B"], days=1, bars_per_day=5, seed=2)
        date_str = str(df["timestamp"].iloc[0].date())
        result = biggest_movers(df, date_str=date_str)
        d = result.to_dict()

        assert isinstance(d, dict)
        assert "gainers" in d
        assert "losers" in d
        assert "date" in d
        assert "n" in d

    def test_to_dict_volume_analysis(self):
        """VolumeAnalysisResult.to_dict() returns a dict with expected keys."""
        df = make_bars_df(tickers="AAPL", days=2, bars_per_day=5, seed=3)
        result = volume_analysis(df)
        d = result.to_dict()

        assert isinstance(d, dict)
        assert "stats" in d
        assert "date_range" in d
        assert isinstance(d["stats"], list)
