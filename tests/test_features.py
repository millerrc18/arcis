"""Tests for the feature engine using synthetic data only."""

import numpy as np
import pandas as pd

from src.features.engine import compute_features, compute_all_features


def _make_uptrend_ohlcv(n: int = 250, start_price: float = 100.0) -> pd.DataFrame:
    """Create a synthetic uptrending OHLCV DataFrame."""
    dates = pd.bdate_range(end=pd.Timestamp('2026-03-20'), periods=n)
    # Steady uptrend: ~0.1% daily gain
    close = start_price * np.cumprod(1 + np.full(n, 0.001))
    # Add small recent pullback in last 5 days
    close[-5:] = close[-6] * np.array([0.995, 0.993, 0.991, 0.992, 0.993])
    high = close * 1.01
    low = close * 0.99
    open_ = close * 1.002
    volume = np.full(n, 1_000_000.0)
    # Reduce recent volume for volume contraction signal
    volume[-5:] = 700_000.0

    return pd.DataFrame({
        "Open": open_,
        "High": high,
        "Low": low,
        "Close": close,
        "Volume": volume,
    }, index=dates)


def _make_spy_ohlcv(n: int = 250, start_price: float = 450.0) -> pd.DataFrame:
    """Create a synthetic SPY DataFrame with modest uptrend."""
    dates = pd.bdate_range(end=pd.Timestamp('2026-03-20'), periods=n)
    close = start_price * np.cumprod(1 + np.full(n, 0.0003))
    high = close * 1.005
    low = close * 0.995
    open_ = close * 1.001
    volume = np.full(n, 50_000_000.0)

    return pd.DataFrame({
        "Open": open_,
        "High": high,
        "Low": low,
        "Close": close,
        "Volume": volume,
    }, index=dates)


EXPECTED_KEYS = [
    "ticker", "current_price",
    "sma_50", "sma_200",
    "price_vs_sma50_pct", "price_vs_sma200_pct",
    "sma50_slope", "sma200_slope", "trend_state",
    "rs_vs_spy_1m", "rs_vs_spy_3m", "rs_vs_spy_6m",
    "relative_strength_state",
    "pullback_depth_pct", "atr_14", "atr_pct",
    "dist_to_sma20_pct", "volume_ratio_20d",
]


def test_all_keys_present():
    ohlcv = _make_uptrend_ohlcv()
    spy = _make_spy_ohlcv()
    features = compute_features("TEST", ohlcv, spy)
    for key in EXPECTED_KEYS:
        assert key in features, f"Missing key: {key}"


def test_uptrend_classification():
    ohlcv = _make_uptrend_ohlcv()
    spy = _make_spy_ohlcv()
    features = compute_features("TEST", ohlcv, spy)
    assert features["trend_state"] in ("strong_uptrend", "uptrend"), \
        f"Expected uptrend, got {features['trend_state']}"


def test_pullback_depth():
    ohlcv = _make_uptrend_ohlcv()
    spy = _make_spy_ohlcv()
    features = compute_features("TEST", ohlcv, spy)
    # The synthetic data has a small pullback in the last 5 days
    assert features["pullback_depth_pct"] < 0, "Pullback depth should be negative"
    assert features["pullback_depth_pct"] > -5, "Pullback should be shallow"


def test_relative_strength_outperformer():
    ohlcv = _make_uptrend_ohlcv()
    spy = _make_spy_ohlcv()  # SPY trends slower than the ticker
    features = compute_features("TEST", ohlcv, spy)
    assert features["relative_strength_state"] in ("strong_outperformer", "outperformer"), \
        f"Expected outperformer, got {features['relative_strength_state']}"


def test_volume_ratio():
    ohlcv = _make_uptrend_ohlcv()
    spy = _make_spy_ohlcv()
    features = compute_features("TEST", ohlcv, spy)
    # Recent volume is 700k vs 20-day avg that includes 1M days
    assert features["volume_ratio_20d"] < 1.0, "Volume ratio should be below 1 due to contraction"


def test_compute_all_features_skips_short():
    ohlcv = _make_uptrend_ohlcv(n=100)  # Too short
    spy = _make_spy_ohlcv()
    result = compute_all_features({"SHORT": ohlcv}, spy)
    assert "SHORT" not in result


def test_compute_all_features_processes_valid():
    ohlcv = _make_uptrend_ohlcv()
    spy = _make_spy_ohlcv()
    result = compute_all_features({"GOOD": ohlcv}, spy)
    assert "GOOD" in result
    assert "ticker" in result["GOOD"]
