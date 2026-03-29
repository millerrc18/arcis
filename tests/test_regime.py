"""Tests for market regime indicators, sector mapping, and regime-aware scoring."""

import numpy as np
import pandas as pd
import pytest


def _make_price_series(prices: list[float], start="2024-01-01") -> pd.DataFrame:
    """Build a minimal OHLCV DataFrame from closing prices."""
    n = len(prices)
    dates = pd.bdate_range(start=start, periods=n)
    return pd.DataFrame({
        "Open": prices,
        "High": [p * 1.01 for p in prices],
        "Low": [p * 0.99 for p in prices],
        "Close": prices,
        "Volume": [1_000_000] * n,
    }, index=dates)


class TestRSI:
    def test_rsi_known_values(self):
        from src.features.regime import _compute_rsi
        # Build a series that trends up then down
        prices = list(range(100, 120)) + list(range(120, 110, -1))
        close = pd.Series(prices, dtype=float)
        rsi = _compute_rsi(close, 14)
        assert 0 <= rsi <= 100

    def test_rsi_all_up(self):
        from src.features.regime import _compute_rsi
        close = pd.Series(list(range(100, 130)), dtype=float)
        rsi = _compute_rsi(close, 14)
        assert rsi > 70  # Should be overbought

    def test_rsi_all_down(self):
        from src.features.regime import _compute_rsi
        close = pd.Series(list(range(130, 100, -1)), dtype=float)
        rsi = _compute_rsi(close, 14)
        assert rsi < 30  # Should be oversold


class TestVolatilityClassification:
    def test_low(self):
        from src.features.regime import _classify_volatility
        assert _classify_volatility(10) == "low"

    def test_normal(self):
        from src.features.regime import _classify_volatility
        assert _classify_volatility(15) == "normal"

    def test_elevated(self):
        from src.features.regime import _classify_volatility
        assert _classify_volatility(25) == "elevated"

    def test_extreme(self):
        from src.features.regime import _classify_volatility
        assert _classify_volatility(35) == "extreme"

    def test_boundary_12(self):
        from src.features.regime import _classify_volatility
        assert _classify_volatility(12) == "normal"

    def test_boundary_20(self):
        from src.features.regime import _classify_volatility
        assert _classify_volatility(20) == "normal"

    def test_boundary_30(self):
        from src.features.regime import _classify_volatility
        assert _classify_volatility(30) == "elevated"


class TestRegimeLabelCompositing:
    def test_calm_uptrend(self):
        from src.features.regime import compute_market_regime
        # Strong uptrending SPY with low volatility
        prices = [100 + i * 0.3 for i in range(260)]
        spy = _make_price_series(prices)
        ohlcv = {"TEST": _make_price_series(prices)}
        regime = compute_market_regime(spy, ohlcv)
        assert regime["regime_label"] in ("calm_uptrend", "volatile_uptrend", "transitional")
        assert regime["market_trend"] in ("strong_uptrend", "uptrend", "neutral")

    def test_regime_keys_present(self):
        from src.features.regime import compute_market_regime
        prices = [100 + i * 0.1 for i in range(260)]
        spy = _make_price_series(prices)
        ohlcv = {"A": _make_price_series(prices)}
        regime = compute_market_regime(spy, ohlcv)
        expected_keys = [
            "market_trend", "volatility_regime", "vix_proxy", "spy_rsi_14",
            "spy_above_sma50", "spy_above_sma200", "spy_sma50_slope",
            "spy_drawdown_from_high", "spy_20d_return", "market_breadth_pct",
            "market_breadth_label", "regime_label",
        ]
        for key in expected_keys:
            assert key in regime, f"Missing key: {key}"

    def test_breadth_proxy(self):
        from src.features.regime import compute_market_regime
        # All tickers above 50d SMA = healthy breadth
        prices = [100 + i * 0.2 for i in range(260)]
        spy = _make_price_series(prices)
        ohlcv = {f"T{i}": _make_price_series(prices) for i in range(10)}
        regime = compute_market_regime(spy, ohlcv)
        assert regime["market_breadth_pct"] > 50
        assert regime["market_breadth_label"] in ("healthy", "narrowing")


class TestRegimeScoreAdjustment:
    def test_calm_uptrend_healthy_bonus(self):
        from src.ranking.ranker import _regime_adjustment
        features = {
            "regime_label": "calm_uptrend",
            "market_breadth_label": "healthy",
            "spy_rsi_14": 55,
        }
        adj = _regime_adjustment(features)
        assert adj == 5

    def test_volatile_downtrend_penalty(self):
        from src.ranking.ranker import _regime_adjustment
        features = {
            "regime_label": "volatile_downtrend",
            "market_breadth_label": "weak",
            "spy_rsi_14": 40,
        }
        adj = _regime_adjustment(features)
        assert adj == -10

    def test_overbought_penalty(self):
        from src.ranking.ranker import _regime_adjustment
        features = {
            "regime_label": "calm_uptrend",
            "market_breadth_label": "healthy",
            "spy_rsi_14": 80,  # Overbought
        }
        adj = _regime_adjustment(features)
        assert adj == 2  # +5 from calm uptrend, -3 from overbought

    def test_oversold_bonus(self):
        from src.ranking.ranker import _regime_adjustment
        features = {
            "regime_label": "transitional",
            "market_breadth_label": "narrowing",
            "spy_rsi_14": 25,  # Oversold
        }
        adj = _regime_adjustment(features)
        assert adj == 0  # -3 from transitional, +3 from oversold

    def test_adjustment_capped(self):
        from src.ranking.ranker import _regime_adjustment
        features = {
            "regime_label": "volatile_downtrend",
            "market_breadth_label": "weak",
            "spy_rsi_14": 80,  # -10 + -3 = -13, should cap at -10
        }
        adj = _regime_adjustment(features)
        assert adj >= -10


class TestSectorMapCompleteness:
    def test_all_sp100_tickers_have_sector(self):
        from src.universe.sp100 import get_sp100_universe
        from src.universe.sectors import SECTOR_MAP

        universe = get_sp100_universe()
        missing = [t for t in universe if t not in SECTOR_MAP]
        assert missing == [], f"Tickers missing from SECTOR_MAP: {missing}"

    def test_no_extra_tickers_in_sector_map(self):
        from src.universe.sp100 import get_sp100_universe
        from src.universe.sectors import SECTOR_MAP

        universe = set(get_sp100_universe())
        extras = [t for t in SECTOR_MAP if t not in universe]
        assert extras == [], f"Extra tickers in SECTOR_MAP: {extras}"


class TestSectorContext:
    def test_sector_context_basic(self):
        from src.features.regime import compute_sector_context
        all_features = {
            "AAPL": {"_score": 80},
            "MSFT": {"_score": 90},
            "NVDA": {"_score": 70},
        }
        ctx = compute_sector_context("AAPL", 80, all_features)
        assert ctx["sector"] == "Technology"
        assert ctx["sector_peer_count"] == 3
        assert ctx["sector_avg_score"] == 80.0
        assert ctx["sector_rs_rank"] in ("top_quartile", "upper_half", "lower_half", "bottom_quartile")
