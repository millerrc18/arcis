"""Tests for setup type classifier."""

import pytest

from src.features.setup_classifier import classify_setup


class TestClassifySetup:
    """Tests for the classify_setup function."""

    def test_pullback_in_uptrend(self):
        features = {
            "trend_state": "uptrend",
            "price_vs_sma200_pct": 8.0,
            "price_vs_sma50_pct": -2.5,
            "sma200_slope": "positive",
            "atr_pct": 1.5,
            "adx": 30.0,
            "rsi_14": 42.0,
            "volume_profile": "declining",
        }
        result = classify_setup(features)
        assert result["setup_type"] == "pullback"
        assert result["confidence"] >= 0.6
        assert result["tradeable_by_desk"] == "equity_swing"

    def test_breakout(self):
        features = {
            "trend_state": "neutral",
            "price_vs_sma200_pct": 3.0,
            "price_vs_sma50_pct": 2.0,
            "sma200_slope": "flat",
            "atr_pct": 2.0,
            "adx": 18.0,
            "rsi_14": 58.0,
            "volume_profile": "expanding",
        }
        result = classify_setup(features)
        assert result["setup_type"] == "breakout"
        assert result["tradeable_by_desk"] == "equity_momentum"

    def test_momentum(self):
        features = {
            "trend_state": "strong_uptrend",
            "price_vs_sma200_pct": 15.0,
            "price_vs_sma50_pct": 5.0,
            "sma200_slope": "positive",
            "atr_pct": 2.5,
            "adx": 35.0,
            "rsi_14": 62.0,
            "volume_profile": "normal",
        }
        result = classify_setup(features)
        assert result["setup_type"] == "momentum"
        assert result["tradeable_by_desk"] == "equity_momentum"

    def test_mean_reversion(self):
        features = {
            "trend_state": "downtrend",
            "price_vs_sma200_pct": -5.0,
            "price_vs_sma50_pct": -8.0,
            "sma200_slope": "negative",
            "atr_pct": 3.0,
            "adx": 20.0,
            "rsi_14": 20.0,
            "volume_profile": "expanding",
        }
        result = classify_setup(features)
        assert result["setup_type"] == "mean_reversion"
        assert result["tradeable_by_desk"] == "equity_swing"

    def test_range_bound(self):
        features = {
            "trend_state": "neutral",
            "price_vs_sma200_pct": 1.0,
            "price_vs_sma50_pct": 0.5,
            "sma200_slope": "flat",
            "atr_pct": 1.0,
            "adx": 15.0,
            "rsi_14": 50.0,
            "volume_profile": "normal",
        }
        result = classify_setup(features)
        assert result["setup_type"] == "range_bound"
        assert result["tradeable_by_desk"] == "none"

    def test_breakdown(self):
        features = {
            "trend_state": "strong_downtrend",
            "price_vs_sma200_pct": -12.0,
            "price_vs_sma50_pct": -8.0,
            "sma200_slope": "negative",
            "atr_pct": 3.5,
            "adx": 35.0,
            "rsi_14": 28.0,
            "volume_profile": "expanding",
        }
        result = classify_setup(features)
        assert result["setup_type"] == "breakdown"
        assert result["tradeable_by_desk"] == "none"

    def test_confidence_between_0_and_1(self):
        features = {
            "trend_state": "neutral",
            "price_vs_sma200_pct": 0.0,
            "price_vs_sma50_pct": 0.0,
            "sma200_slope": "flat",
            "atr_pct": 1.0,
        }
        result = classify_setup(features)
        assert 0.0 <= result["confidence"] <= 1.0

    def test_features_used_populated(self):
        features = {
            "trend_state": "uptrend",
            "price_vs_sma200_pct": 5.0,
            "price_vs_sma50_pct": -1.0,
            "sma200_slope": "positive",
            "atr_pct": 1.5,
            "adx": 28.0,
            "rsi_14": 45.0,
            "volume_profile": "declining",
        }
        result = classify_setup(features)
        assert "adx" in result["features_used"]
        assert "rsi" in result["features_used"]
        assert "atr_ratio" in result["features_used"]

    def test_handles_missing_features_gracefully(self):
        """Should not crash with minimal features."""
        features = {"trend_state": "neutral"}
        result = classify_setup(features)
        assert "setup_type" in result
        assert "confidence" in result
