"""Integration smoke tests for the MarketPulse analytics suite.

Verifies that the full pipeline from synthetic data through each analytics
module produces valid results and serializes without error.
"""

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
from lib.analytics.volatility import (  # noqa: E402
    realized_volatility,
    intraday_vol_profile,
    vol_surface,
    garman_klass_vol,
)
from lib.analytics.correlation import (  # noqa: E402
    pairwise_correlation,
    sector_correlation,
    rolling_correlation,
)
from lib.analytics.patterns import (  # noqa: E402
    intraday_patterns,
    day_of_week_effects,
    monthly_seasonality,
)
from lib.analytics.sectors import sector_rotation, sector_heatmap, relative_strength  # noqa: E402
from lib.analytics.events import (  # noqa: E402
    volume_spikes,
    price_gaps,
    anomaly_detection,
    event_impact,
)

# ---------------------------------------------------------------------------
# Shared constants
# ---------------------------------------------------------------------------

TICKERS = ["AAPL", "MSFT", "GOOG"]
SECTOR_MAP = {
    "AAPL": "Technology",
    "MSFT": "Technology",
    "GOOG": "Communication Services",
}
START_DATE = "2022-01-03"
# First trading day in the synthetic dataset
FIRST_DATE = "2022-01-03"


class TestAnalyticsSmokeTests:
    """Verify all analytics functions work end-to-end with synthetic data."""

    def test_summary_pipeline(self):
        """daily_summary -> biggest_movers -> volume_analysis chain."""
        df = make_bars_df(TICKERS, start=START_DATE, days=10)

        summary = daily_summary(df)
        assert summary.ticker_count == 3
        assert summary.date_count == 10

        movers = biggest_movers(df, date_str=FIRST_DATE)
        assert len(movers.gainers) + len(movers.losers) > 0

        vol = volume_analysis(df)
        assert len(vol.stats) == 3

    def test_volatility_pipeline(self):
        """realized_volatility -> vol_surface -> garman_klass chain."""
        df = make_bars_df(TICKERS, start=START_DATE, days=10)

        rv = realized_volatility(df, window="1d")
        assert len(rv.volatilities) == 3
        assert rv.window == "1d"

        ivp = intraday_vol_profile(df, ticker="AAPL", bucket_minutes=30)
        assert ivp.ticker == "AAPL"
        assert len(ivp.buckets) > 0

        vs = vol_surface(df)
        # Default windows are [5, 10, 21, 63]; 10-day data covers 5 and 10
        assert len(vs.points) > 0
        assert len(vs.windows) > 0

        gk = garman_klass_vol(df)
        assert len(gk) == 3
        for r in gk:
            assert r.gk_vol >= 0.0
            assert r.annualized_gk_vol >= 0.0

    def test_correlation_pipeline(self):
        """pairwise -> sector -> rolling chain."""
        df = make_bars_df(TICKERS, start=START_DATE, days=30)

        pw = pairwise_correlation(df)
        assert len(pw.tickers) == 3
        assert len(pw.pairs) == 3  # C(3,2) = 3 unique pairs
        assert len(pw.matrix) == 3

        sc = sector_correlation(df, sector_map=SECTOR_MAP)
        # Two sectors: Technology and Communication Services
        assert len(sc.sectors) == 2

        rc = rolling_correlation(df, ticker_a="AAPL", ticker_b="MSFT", window=5)
        assert rc.ticker_a == "AAPL"
        assert rc.ticker_b == "MSFT"
        assert rc.window == 5
        # 30 days of data with window=5 should produce points
        assert len(rc.points) > 0

    def test_events_pipeline(self):
        """volume_spikes -> price_gaps -> anomaly_detection chain."""
        # Use more days so rolling windows have enough data
        df = make_bars_df(TICKERS, start=START_DATE, days=30)

        spikes = volume_spikes(df, threshold=3.0)
        assert spikes.threshold == 3.0
        assert isinstance(spikes.spikes, list)

        gaps = price_gaps(df, threshold=0.001)
        assert gaps.threshold == 0.001
        assert isinstance(gaps.gaps, list)

        anomalies = anomaly_detection(df, z_threshold=3.0)
        assert anomalies.z_threshold == 3.0
        assert isinstance(anomalies.anomalies, list)

        impact = event_impact(df, ticker="AAPL", event_date="2022-01-07")
        assert impact.ticker == "AAPL"
        assert impact.event_date == "2022-01-07"

    def test_patterns_pipeline(self):
        """intraday_patterns -> day_of_week_effects -> monthly_seasonality chain."""
        # Need multiple months for monthly_seasonality; use 60 days
        df = make_bars_df(TICKERS, start=START_DATE, days=60)

        ip = intraday_patterns(df, ticker="AAPL", bucket_minutes=30)
        assert ip.ticker == "AAPL"
        assert len(ip.buckets) > 0

        dow = day_of_week_effects(df, ticker="MSFT")
        assert dow.ticker == "MSFT"
        assert len(dow.days) > 0

        ms = monthly_seasonality(df, ticker="GOOG")
        assert ms.ticker == "GOOG"
        assert len(ms.months) > 0

    def test_sectors_pipeline(self):
        """sector_rotation -> sector_heatmap -> relative_strength chain."""
        df = make_bars_df(TICKERS, start=START_DATE, days=10)

        rot = sector_rotation(df, sector_map=SECTOR_MAP)
        assert len(rot.sectors) == 2
        assert rot.period != ""

        hm = sector_heatmap(df, sector_map=SECTOR_MAP)
        assert len(hm.cells) > 0
        assert len(hm.sectors) == 2
        assert len(hm.dates) > 0

        rs = relative_strength(df, sector_map=SECTOR_MAP)
        assert len(rs.tickers) == 3
        assert rs.benchmark != ""

    def test_all_to_dict(self):
        """Every result type serializes to a dict without error."""
        df = make_bars_df(TICKERS, start=START_DATE, days=10)

        results = [
            daily_summary(df),
            biggest_movers(df, date_str=FIRST_DATE),
            volume_analysis(df),
            realized_volatility(df),
            intraday_vol_profile(df, ticker="AAPL"),
            vol_surface(df),
            pairwise_correlation(df),
            sector_correlation(df, sector_map=SECTOR_MAP),
            rolling_correlation(df, ticker_a="AAPL", ticker_b="MSFT", window=5),
            intraday_patterns(df, ticker="AAPL"),
            day_of_week_effects(df, ticker="AAPL"),
            monthly_seasonality(df, ticker="AAPL"),
            sector_rotation(df, sector_map=SECTOR_MAP),
            sector_heatmap(df, sector_map=SECTOR_MAP),
            relative_strength(df, sector_map=SECTOR_MAP),
            volume_spikes(df),
            price_gaps(df),
            anomaly_detection(df),
            event_impact(df, ticker="AAPL", event_date="2022-01-07"),
        ]

        # garman_klass_vol returns a list, not a single result
        gk_results = garman_klass_vol(df)

        for result in results:
            d = result.to_dict()
            assert isinstance(d, dict), f"{type(result).__name__}.to_dict() must return dict"

        for gk in gk_results:
            d = gk.to_dict()
            assert isinstance(d, dict), f"GarmanKlassResult.to_dict() must return dict"

    def test_all_to_rich_table(self):
        """Every result type renders a Rich table without error."""
        from rich.table import Table

        df = make_bars_df(TICKERS, start=START_DATE, days=10)

        results = [
            daily_summary(df),
            biggest_movers(df, date_str=FIRST_DATE),
            volume_analysis(df),
            realized_volatility(df),
            intraday_vol_profile(df, ticker="AAPL"),
            vol_surface(df),
            pairwise_correlation(df),
            sector_correlation(df, sector_map=SECTOR_MAP),
            rolling_correlation(df, ticker_a="AAPL", ticker_b="MSFT", window=5),
            intraday_patterns(df, ticker="AAPL"),
            day_of_week_effects(df, ticker="AAPL"),
            monthly_seasonality(df, ticker="AAPL"),
            sector_rotation(df, sector_map=SECTOR_MAP),
            sector_heatmap(df, sector_map=SECTOR_MAP),
            relative_strength(df, sector_map=SECTOR_MAP),
            volume_spikes(df),
            price_gaps(df),
            anomaly_detection(df),
            event_impact(df, ticker="AAPL", event_date="2022-01-07"),
        ]

        gk_results = garman_klass_vol(df)

        for result in results:
            table = result.to_rich_table()
            assert isinstance(table, Table), (
                f"{type(result).__name__}.to_rich_table() must return a Rich Table"
            )

        for gk in gk_results:
            table = gk.to_rich_table()
            assert isinstance(table, Table), (
                "GarmanKlassResult.to_rich_table() must return a Rich Table"
            )
