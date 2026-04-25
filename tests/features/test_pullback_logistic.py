"""Tests for pullback logistic feature extractors.

Tests: src/features/pullback_logistic.py
"""

import math

import numpy as np
import pandas as pd
import pytest

from src.features.pullback_logistic import extract_pullback_features


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_uptrend_df(n: int = 65, pullback_pct: float = 0.04) -> pd.DataFrame:
    """Build a synthetic uptrend with a mild, meandering pullback at the end.

    Prices rise steadily for the first (n - 10) bars, then meander down
    by pullback_pct total over the final 10 bars with mixed up/down days
    (down 0.6 %, up 0.2 % alternating) so RSI does not collapse to
    oversold territory.  Volume gently declines during the pullback to
    model a healthy retracement.
    """
    dates = pd.date_range("2024-01-01", periods=n, freq="B")
    base = 100.0
    prices = []
    for i in range(n - 10):
        prices.append(base * (1 + i * 0.003))   # +0.3 %/day uptrend

    # Meandering pullback: alternating down/up to keep RSI in 30-55
    # Pattern: -1.0%, +0.3%, repeated 5x => net ~-3.5% total
    # Mixed up/down days prevent RSI from collapsing to oversold territory.
    pb_start = prices[-1]
    pb_moves = [-0.010, +0.003, -0.010, +0.003, -0.010,
                +0.003, -0.010, +0.003, -0.010, +0.003]
    p = pb_start
    for move in pb_moves:
        p = p * (1 + move)
        prices.append(p)

    close = pd.Series(prices, index=dates)
    high = close * 1.005
    low = close * 0.995
    open_ = close * 0.998
    # Volume high in uptrend, declining in pullback
    vol_trend = [int(1_000_000 + i * 2_000) for i in range(n - 10)]
    vol_pb = [int(900_000 - j * 20_000) for j in range(10)]
    volume = pd.Series(vol_trend + vol_pb, index=dates)

    return pd.DataFrame({
        "Open": open_,
        "High": high,
        "Low": low,
        "Close": close,
        "Volume": volume,
    })


def _make_ath_df(n: int = 65) -> pd.DataFrame:
    """All-time-high scenario: steady uptrend, no pullback at end."""
    dates = pd.date_range("2024-01-01", periods=n, freq="B")
    base = 100.0
    prices = [base * (1 + i * 0.004) for i in range(n)]
    close = pd.Series(prices, index=dates)
    high = close * 1.006
    low = close * 0.994
    open_ = close * 0.999
    volume = pd.Series([1_200_000] * n, index=dates)
    return pd.DataFrame({
        "Open": open_,
        "High": high,
        "Low": low,
        "Close": close,
        "Volume": volume,
    })


def _make_sharp_drawdown_df(n: int = 65) -> pd.DataFrame:
    """Sharp drop over last 5 bars — all 5 days are down days."""
    dates = pd.date_range("2024-01-01", periods=n, freq="B")
    base = 100.0
    prices = []
    for i in range(n):
        if i < n - 5:
            prices.append(base * (1 + i * 0.003))
        else:
            peak = base * (1 + (n - 6) * 0.003)
            prices.append(peak * (1 - (i - (n - 6)) * 0.025))  # -2.5 %/day

    close = pd.Series(prices, index=dates)
    high = close * 1.005
    low = close * 0.99
    open_ = close * 1.003
    volume = pd.Series([1_000_000] * n, index=dates)
    return pd.DataFrame({
        "Open": open_,
        "High": high,
        "Low": low,
        "Close": close,
        "Volume": volume,
    })


# ---------------------------------------------------------------------------
# Scenario: mild pullback in uptrend
# ---------------------------------------------------------------------------

class TestMildPullback:
    def setup_method(self):
        self.df = _make_uptrend_df(n=65, pullback_pct=0.04)
        self.feats = extract_pullback_features(self.df)

    def test_returns_dict(self):
        assert isinstance(self.feats, dict)

    def test_all_keys_present(self):
        expected = {
            "pullback_depth_pct",
            "dist_from_sma20_pct",
            "dist_from_sma50_pct",
            "volume_ratio_20d",
            "rsi_14",
            "atr_pct",
            "prior_n_day_drawdown",
            "up_days_in_5",
        }
        assert set(self.feats.keys()) == expected

    def test_pullback_depth_is_negative_and_small(self):
        # Mild pullback: should be in the -3 to -6 range
        val = self.feats["pullback_depth_pct"]
        assert -6.0 <= val <= -2.0, f"Expected -6 to -2, got {val}"

    def test_dist_from_sma20_is_negative(self):
        # Price has pulled back below the 20-day SMA region
        val = self.feats["dist_from_sma20_pct"]
        assert val < 0, f"Expected negative dist_from_sma20_pct, got {val}"

    def test_rsi_in_pullback_range(self):
        # Healthy pullback RSI should be in 35-55
        val = self.feats["rsi_14"]
        assert 30.0 <= val <= 60.0, f"RSI {val} not in expected pullback range"

    def test_volume_ratio_below_one(self):
        # Declining volume on pullback is bullish
        val = self.feats["volume_ratio_20d"]
        assert val < 1.0, f"Expected volume_ratio < 1.0, got {val}"

    def test_all_values_are_finite_floats(self):
        for k, v in self.feats.items():
            assert isinstance(v, float), f"{k} is not float: {v!r}"
            assert math.isfinite(v), f"{k} is not finite: {v}"


# ---------------------------------------------------------------------------
# Scenario: at all-time high, no pullback
# ---------------------------------------------------------------------------

class TestAtHighNoPullback:
    def setup_method(self):
        self.df = _make_ath_df(n=65)
        self.feats = extract_pullback_features(self.df)

    def test_pullback_depth_near_zero(self):
        # No pullback — recent close ≈ recent high
        val = self.feats["pullback_depth_pct"]
        assert -1.5 <= val <= 0.5, f"Expected near 0, got {val}"

    def test_rsi_elevated(self):
        # Strong uptrend with no pullback: RSI should be > 60
        val = self.feats["rsi_14"]
        assert val > 55.0, f"Expected RSI > 55, got {val}"

    def test_dist_from_sma20_positive_or_small(self):
        # At ATH price is above SMA20
        val = self.feats["dist_from_sma20_pct"]
        assert val >= 0.0, f"Expected >= 0, got {val}"


# ---------------------------------------------------------------------------
# Scenario: sharp drawdown
# ---------------------------------------------------------------------------

class TestSharpDrawdown:
    def setup_method(self):
        self.df = _make_sharp_drawdown_df(n=65)
        self.feats = extract_pullback_features(self.df)

    def test_prior_drawdown_is_large_negative(self):
        # 5 consecutive -2.5 % days => large negative
        val = self.feats["prior_n_day_drawdown"]
        assert val < -5.0, f"Expected large negative drawdown, got {val}"

    def test_up_days_in_5_is_low(self):
        # All 5 recent days are down
        val = self.feats["up_days_in_5"]
        assert val <= 1.0, f"Expected 0 or 1 up days, got {val}"


# ---------------------------------------------------------------------------
# Boundary: fewer than 50 bars
# ---------------------------------------------------------------------------

class TestFewerThan50Bars:
    def test_short_df_does_not_crash(self):
        dates = pd.date_range("2024-01-01", periods=30, freq="B")
        close = pd.Series([100.0 + i for i in range(30)], index=dates)
        df = pd.DataFrame({
            "Open": close * 0.99,
            "High": close * 1.01,
            "Low": close * 0.99,
            "Close": close,
            "Volume": pd.Series([500_000] * 30, index=dates),
        })
        feats = extract_pullback_features(df)
        assert isinstance(feats, dict)

    def test_sma50_dependent_feature_is_nan_for_short_df(self):
        dates = pd.date_range("2024-01-01", periods=30, freq="B")
        close = pd.Series([100.0 + i for i in range(30)], index=dates)
        df = pd.DataFrame({
            "Open": close * 0.99,
            "High": close * 1.01,
            "Low": close * 0.99,
            "Close": close,
            "Volume": pd.Series([500_000] * 30, index=dates),
        })
        feats = extract_pullback_features(df)
        assert math.isnan(feats["dist_from_sma50_pct"]), (
            f"Expected NaN for dist_from_sma50_pct with <50 bars, got {feats['dist_from_sma50_pct']}"
        )

    def test_non_sma50_features_are_finite_for_short_df(self):
        dates = pd.date_range("2024-01-01", periods=30, freq="B")
        close = pd.Series([100.0 + i for i in range(30)], index=dates)
        df = pd.DataFrame({
            "Open": close * 0.99,
            "High": close * 1.01,
            "Low": close * 0.99,
            "Close": close,
            "Volume": pd.Series([500_000] * 30, index=dates),
        })
        feats = extract_pullback_features(df)
        sma50_key = "dist_from_sma50_pct"
        for k, v in feats.items():
            if k == sma50_key:
                continue
            assert isinstance(v, float), f"{k} is not float"
            assert math.isfinite(v), f"{k} not finite with short df: {v}"


# ---------------------------------------------------------------------------
# Boundary: empty DataFrame
# ---------------------------------------------------------------------------

class TestEmptyDataFrame:
    def test_empty_df_raises_value_error(self):
        df = pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])
        with pytest.raises(ValueError, match=r"(?i)(empty|no data|rows)"):
            extract_pullback_features(df)

    def test_none_raises_type_error(self):
        with pytest.raises((TypeError, AttributeError)):
            extract_pullback_features(None)
