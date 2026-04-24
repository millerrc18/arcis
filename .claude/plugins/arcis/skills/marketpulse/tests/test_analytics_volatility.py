"""Tests for MarketPulse volatility analytics module."""

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
from lib.analytics.volatility import (  # noqa: E402
    realized_volatility,
    intraday_vol_profile,
    vol_surface,
    garman_klass_vol,
)


# ---------------------------------------------------------------------------
# realized_volatility
# ---------------------------------------------------------------------------


class TestRealizedVolatility:
    """Tests for the ``realized_volatility`` function."""

    def test_realized_vol_single_ticker(self):
        """Vol > 0 and annualized > daily for a single ticker."""
        df = make_bars_df(tickers="AAPL", days=10, bars_per_day=50, seed=42)
        result = realized_volatility(df, window="1d")

        assert len(result.volatilities) == 1
        assert result.window == "1d"

        tv = result.volatilities[0]
        assert tv.ticker == "AAPL"
        assert tv.annualized_vol > 0
        assert tv.daily_vol > 0
        assert tv.annualized_vol > tv.daily_vol  # sqrt(252) scaling
        assert tv.num_periods > 0

    def test_realized_vol_multi_ticker(self):
        """Separate results per ticker."""
        df = make_bars_df(
            tickers=["AAPL", "MSFT", "GOOG"], days=10, bars_per_day=20, seed=7
        )
        result = realized_volatility(df, window="1d")

        assert len(result.volatilities) == 3
        tickers_seen = {tv.ticker for tv in result.volatilities}
        assert tickers_seen == {"AAPL", "MSFT", "GOOG"}

        # Each should have positive vol
        for tv in result.volatilities:
            assert tv.annualized_vol > 0
            assert tv.daily_vol > 0

    def test_realized_vol_intraday_window(self):
        """window='intraday' uses bar-level returns and still produces valid vol."""
        df = make_bars_df(tickers="AAPL", days=5, bars_per_day=50, seed=99)
        result = realized_volatility(df, window="intraday")

        assert result.window == "intraday"
        assert len(result.volatilities) == 1

        tv = result.volatilities[0]
        assert tv.ticker == "AAPL"
        assert tv.annualized_vol > 0
        assert tv.daily_vol > 0
        assert tv.num_periods > 0
        # Intraday should still have annualized > daily
        assert tv.annualized_vol > tv.daily_vol


# ---------------------------------------------------------------------------
# intraday_vol_profile
# ---------------------------------------------------------------------------


class TestIntradayVolProfile:
    """Tests for the ``intraday_vol_profile`` function."""

    def test_intraday_vol_profile_buckets(self):
        """Verify correct bucket count and hour/minute labels."""
        # 390 bars from 14:30 to 21:00 UTC = ~13 30-min buckets
        df = make_bars_df(tickers="AAPL", days=5, bars_per_day=390, seed=42)
        result = intraday_vol_profile(df, ticker="AAPL", bucket_minutes=30)

        assert result.ticker == "AAPL"
        assert len(result.buckets) > 0

        # Each bucket should have valid hour/minute
        for b in result.buckets:
            assert 0 <= b.hour <= 23
            assert b.minute % 30 == 0
            assert b.avg_vol >= 0
            assert b.bar_count > 0

        # With 390 bars starting at 14:30, covering ~6.5 hours,
        # we should have about 13 buckets
        assert len(result.buckets) >= 10


# ---------------------------------------------------------------------------
# vol_surface
# ---------------------------------------------------------------------------


class TestVolSurface:
    """Tests for the ``vol_surface`` function."""

    def test_vol_surface_default_windows(self):
        """Results for all 4 default windows [5, 10, 21, 63]."""
        # Need enough days for the 63-day window
        df = make_bars_df(tickers="AAPL", days=70, bars_per_day=10, seed=42)
        result = vol_surface(df)

        assert result.windows == [5, 10, 21, 63]
        assert len(result.points) == 4  # 1 ticker x 4 windows

        for pt in result.points:
            assert pt.ticker == "AAPL"
            assert pt.window_days in [5, 10, 21, 63]
            assert pt.annualized_vol > 0

    def test_vol_surface_custom_windows(self):
        """Custom windows=[5, 10] produces only those 2 results per ticker."""
        df = make_bars_df(
            tickers=["AAPL", "MSFT"], days=15, bars_per_day=10, seed=55
        )
        result = vol_surface(df, windows=[5, 10])

        assert result.windows == [5, 10]
        # 2 tickers x 2 windows = 4 points
        assert len(result.points) == 4

        for pt in result.points:
            assert pt.window_days in [5, 10]
            assert pt.annualized_vol > 0


# ---------------------------------------------------------------------------
# garman_klass_vol
# ---------------------------------------------------------------------------


class TestGarmanKlass:
    """Tests for the ``garman_klass_vol`` function."""

    def test_garman_klass_positive(self):
        """GK vol > 0 for all tickers."""
        df = make_bars_df(
            tickers=["AAPL", "MSFT", "GOOG"], days=10, bars_per_day=50, seed=42
        )
        results = garman_klass_vol(df)

        assert len(results) == 3
        for r in results:
            assert r.gk_vol > 0
            assert r.annualized_gk_vol > 0
            assert r.num_bars > 0

    def test_garman_klass_vs_realized(self):
        """GK and realized vol should be same order of magnitude."""
        df = make_bars_df(tickers="AAPL", days=20, bars_per_day=50, seed=42)

        rv_result = realized_volatility(df, window="1d")
        gk_results = garman_klass_vol(df)

        rv_vol = rv_result.volatilities[0].annualized_vol
        gk_vol = gk_results[0].annualized_gk_vol

        # Both should be positive
        assert rv_vol > 0
        assert gk_vol > 0

        # Same order of magnitude: ratio between 0.1 and 10
        ratio = gk_vol / rv_vol
        assert 0.1 < ratio < 10, (
            f"GK ({gk_vol:.4f}) and realized ({rv_vol:.4f}) vol differ by "
            f"ratio {ratio:.2f}, expected within 0.1-10x"
        )


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------


class TestSerialization:
    """Verify to_dict() works on volatility result types."""

    def test_to_dict_serialization(self):
        """All volatility result types produce JSON-safe dicts."""
        df = make_bars_df(tickers=["AAPL", "MSFT"], days=10, bars_per_day=20, seed=42)

        # RealizedVolatilityResult
        rv = realized_volatility(df)
        rv_d = rv.to_dict()
        assert isinstance(rv_d, dict)
        assert "volatilities" in rv_d
        assert "window" in rv_d
        assert isinstance(rv_d["volatilities"], list)
        assert len(rv_d["volatilities"]) == 2

        # IntradayVolProfileResult
        ivp = intraday_vol_profile(df, ticker="AAPL")
        ivp_d = ivp.to_dict()
        assert isinstance(ivp_d, dict)
        assert "ticker" in ivp_d
        assert "buckets" in ivp_d
        assert isinstance(ivp_d["buckets"], list)

        # VolSurfaceResult
        vs = vol_surface(df, windows=[5, 10])
        vs_d = vs.to_dict()
        assert isinstance(vs_d, dict)
        assert "points" in vs_d
        assert "windows" in vs_d

        # GarmanKlassResult
        gk = garman_klass_vol(df)
        for r in gk:
            gk_d = r.to_dict()
            assert isinstance(gk_d, dict)
            assert "ticker" in gk_d
            assert "gk_vol" in gk_d
            assert "annualized_gk_vol" in gk_d
            assert "num_bars" in gk_d
