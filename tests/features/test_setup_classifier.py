"""Tests for the trimmed setup type classifier (T2.13).

Surviving taxonomy (after F-6c trim): only `pullback` and `mean_reversion`.
Dead labels removed: `breakout`, `momentum`, `range_bound`, `breakdown`.
"""

from pathlib import Path

import pytest

from src.features.setup_classifier import classify_setup


# ---- Live-label regression tests (the two surviving classes) ----


class TestLiveLabels:
    """The trimmed taxonomy must still classify the original live-label fixtures."""

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


# ---- Dead-label fixtures must NOT classify as the deleted labels ----


class TestDeadLabelsRemoved:
    """Fixtures that previously produced dead labels must now map to None.

    Choice rationale: returning None (not raising) preserves engine.py:285's
    contract — it stamps whatever the classifier emits without crashing the
    feature pipeline. Engine consumers all use `.get(...)` defaults already.
    """

    def test_old_breakout_fixture_no_longer_classifies_as_breakout(self):
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
        assert result["setup_type"] != "breakout"
        assert result["setup_type"] is None

    def test_old_momentum_fixture_no_longer_classifies_as_momentum(self):
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
        assert result["setup_type"] != "momentum"
        assert result["setup_type"] is None

    def test_old_range_bound_fixture_no_longer_classifies_as_range_bound(self):
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
        assert result["setup_type"] != "range_bound"
        assert result["setup_type"] is None

    def test_old_breakdown_fixture_no_longer_classifies_as_breakdown(self):
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
        assert result["setup_type"] != "breakdown"
        # Note: rsi=28 and price_vs_200<0 with vol_profile=expanding could
        # in principle hit the mean_reversion branch — but rsi 28 > 25, so
        # it falls through to the None default.
        assert result["setup_type"] is None

    def test_default_setup_type_is_none_not_range_bound(self):
        """When no rule matches, classifier returns None (not 'range_bound')."""
        features = {
            "trend_state": "neutral",
            "price_vs_sma200_pct": 0.0,
            "price_vs_sma50_pct": 0.0,
            "sma200_slope": "flat",
            "atr_pct": 1.0,
        }
        result = classify_setup(features)
        assert result["setup_type"] is None


# ---- Import-scan: zero dead-label string literals remain in setup_classifier source ----


class TestSourceFreeOfDeadLabels:
    """Static check: the deleted labels must not appear as string literals
    in setup_classifier.py (allowed in test files / docstrings of other
    modules but not in the trimmed source itself)."""

    def test_setup_classifier_source_has_no_dead_label_literals(self):
        src_path = (
            Path(__file__).resolve().parent.parent.parent
            / "src" / "features" / "setup_classifier.py"
        )
        content = src_path.read_text(encoding="utf-8")
        for dead in ('"breakout"', '"momentum"', '"range_bound"', '"breakdown"'):
            assert dead not in content, (
                f"Dead label literal {dead} still present in {src_path}"
            )
