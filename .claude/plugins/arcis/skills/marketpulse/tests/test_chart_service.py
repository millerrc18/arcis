"""Tests for the dashboard chart service."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_MP_ROOT = Path(__file__).resolve().parent.parent
if str(_MP_ROOT) not in sys.path:
    sys.path.insert(0, str(_MP_ROOT))

from tests.fixtures.make_bars import make_bars_df  # noqa: E402
from lib.analytics.summary import daily_summary, biggest_movers, volume_analysis  # noqa: E402
from lib.analytics.volatility import vol_surface  # noqa: E402
from lib.analytics.correlation import pairwise_correlation  # noqa: E402
from lib.analytics.patterns import intraday_patterns, day_of_week_effects  # noqa: E402
from lib.analytics.sectors import sector_rotation, sector_heatmap  # noqa: E402
from lib.analytics.events import volume_spikes, event_impact  # noqa: E402
from lib.dashboard.services.chart_service import (  # noqa: E402
    volume_distribution_chart,
    movers_to_template_data,
    overview_stats,
    candlestick_chart_data,
    volatility_chart_data,
    correlation_heatmap_data,
    pattern_chart_data,
    sector_rotation_chart_data,
    sector_heatmap_chart_data,
    events_table_data,
    event_impact_chart_data,
)


class TestVolumeDistributionChart:
    """Tests for ``volume_distribution_chart``."""

    def test_returns_labels_and_values(self):
        df = make_bars_df(tickers=["AAPL", "MSFT", "GOOG"], days=2, bars_per_day=10, seed=1)
        result = volume_analysis(df)
        chart = volume_distribution_chart(result)

        assert "labels" in chart
        assert "values" in chart
        assert len(chart["labels"]) == 3
        assert len(chart["values"]) == 3
        assert all(isinstance(v, (int, float)) for v in chart["values"])

    def test_sorted_descending_by_volume(self):
        df = make_bars_df(tickers=["AAPL", "MSFT", "GOOG"], days=2, bars_per_day=10, seed=2)
        result = volume_analysis(df)
        chart = volume_distribution_chart(result)

        assert chart["values"] == sorted(chart["values"], reverse=True)


class TestMoversToTemplateData:
    """Tests for ``movers_to_template_data``."""

    def test_returns_gainers_and_losers(self):
        df = make_bars_df(tickers=["AAPL", "MSFT", "GOOG", "AMZN", "META"],
                          days=1, bars_per_day=20, seed=3)
        result = biggest_movers(df, date_str="2022-01-03", n=3)
        data = movers_to_template_data(result)

        assert "gainers" in data
        assert "losers" in data
        assert len(data["gainers"]) <= 3
        assert len(data["losers"]) <= 3

    def test_mover_has_required_keys(self):
        df = make_bars_df(tickers=["AAPL", "MSFT"], days=1, bars_per_day=10, seed=4)
        result = biggest_movers(df, date_str="2022-01-03", n=2)
        data = movers_to_template_data(result)

        if data["gainers"]:
            mover = data["gainers"][0]
            assert "ticker" in mover
            assert "return_pct" in mover
            assert "return_display" in mover


class TestOverviewStats:
    """Tests for ``overview_stats``."""

    def test_returns_four_stats(self):
        cache_status = {
            "total_tickers": 5,
            "total_bars": 100000,
            "total_partitions": 10,
        }
        stats = overview_stats(cache_status)

        assert len(stats) == 4
        for s in stats:
            assert "label" in s
            assert "value" in s

    def test_formats_large_numbers(self):
        cache_status = {
            "total_tickers": 47,
            "total_bars": 2_100_000,
            "total_partitions": 94,
        }
        stats = overview_stats(cache_status)

        bar_stat = next(s for s in stats if s["label"] == "Total Bars")
        assert "M" in bar_stat["value"] or "," in bar_stat["value"]


class TestCandlestickChartData:
    def test_returns_ohlcv_arrays(self):
        df = make_bars_df(tickers="AAPL", days=3, bars_per_day=10, seed=50)
        chart = candlestick_chart_data(df, ticker="AAPL")
        assert "dates" in chart and "open" in chart and "close" in chart
        assert len(chart["dates"]) == 30

    def test_filters_to_single_ticker(self):
        df = make_bars_df(tickers=["AAPL", "MSFT"], days=2, bars_per_day=5, seed=51)
        chart = candlestick_chart_data(df, ticker="AAPL")
        assert len(chart["dates"]) == 10


class TestVolatilityChartData:
    def test_returns_series_list(self):
        df = make_bars_df(tickers=["AAPL", "MSFT"], days=5, bars_per_day=20, seed=52)
        result = vol_surface(df)
        chart = volatility_chart_data(result)
        assert isinstance(chart, list) and len(chart) > 0
        assert "name" in chart[0] and "x" in chart[0] and "y" in chart[0]


class TestCorrelationHeatmapData:
    def test_returns_xyz_arrays(self):
        df = make_bars_df(tickers=["AAPL", "MSFT", "GOOG"], days=10, bars_per_day=20, seed=53)
        result = pairwise_correlation(df)
        chart = correlation_heatmap_data(result)
        assert "x" in chart and "y" in chart and "z" in chart
        assert len(chart["x"]) == 3


class TestPatternChartData:
    def test_intraday_returns_categories_and_series(self):
        df = make_bars_df(tickers="AAPL", days=5, bars_per_day=20, seed=54)
        result = intraday_patterns(df, ticker="AAPL")
        chart = pattern_chart_data(result, "intraday")
        assert "categories" in chart and "series" in chart

    def test_day_of_week_returns_data(self):
        df = make_bars_df(tickers="AAPL", days=20, bars_per_day=20, seed=55)
        result = day_of_week_effects(df, ticker="AAPL")
        chart = pattern_chart_data(result, "day_of_week")
        assert "categories" in chart and "series" in chart


class TestSectorChartData:
    def test_rotation_returns_labels_and_values(self):
        df = make_bars_df(tickers=["AAPL", "MSFT", "XOM"], days=5, bars_per_day=10, seed=56)
        sector_map = {"AAPL": "Technology", "MSFT": "Technology", "XOM": "Energy"}
        result = sector_rotation(df, sector_map)
        chart = sector_rotation_chart_data(result)
        assert "labels" in chart and "values" in chart
        assert len(chart["labels"]) == 2

    def test_heatmap_returns_xyz(self):
        df = make_bars_df(tickers=["AAPL", "XOM"], days=3, bars_per_day=10, seed=57)
        sector_map = {"AAPL": "Technology", "XOM": "Energy"}
        result = sector_heatmap(df, sector_map)
        chart = sector_heatmap_chart_data(result)
        assert "x" in chart and "y" in chart and "z" in chart


class TestEventsChartData:
    def test_events_table_data_volume_spikes(self):
        df = make_bars_df(tickers="AAPL", days=10, bars_per_day=50, seed=58)
        result = volume_spikes(df, threshold=2.0)
        table = events_table_data(result, "volume_spikes")
        assert isinstance(table, list)
        if table:
            assert "ticker" in table[0] and "type" in table[0]

    def test_event_impact_chart_data(self):
        df = make_bars_df(tickers="AAPL", days=20, bars_per_day=20, seed=59)
        result = event_impact(df, ticker="AAPL", event_date="2022-01-14")
        chart = event_impact_chart_data(result)
        assert "pre_return" in chart and "post_return" in chart
