"""Tests for src/features/enrichment.py — shared post-scan feature enrichment."""

from unittest.mock import patch, MagicMock

import pandas as pd
import pytest


def _make_features(tickers):
    return {t: {"current_price": 100.0} for t in tickers}


def _mock_tl(mult=1.0, regime="calm_uptrend"):
    return {
        "regime_label": regime,
        "sizing_multiplier": mult,
        "total_score": 8,
        "vix_score": 3,
        "trend_score": 3,
        "credit_score": 2,
    }


class TestAttachPostScanFeatures:
    """Phase 3.1 — helper attaches all three post-scan enrichments consistently."""

    def test_attaches_traffic_light_multiplier_to_every_ticker(self):
        from src.features.enrichment import attach_post_scan_features
        features = _make_features(["AAPL", "MSFT", "GOOG"])

        with patch("src.features.traffic_light.compute_traffic_light",
                   return_value=_mock_tl(mult=0.5)), \
             patch("src.features.event_risk_score.attach_event_risk_scores"):
            attach_post_scan_features(
                features, config={}, spy=pd.DataFrame(), vix_value=15.0,
            )

        for t in ("AAPL", "MSFT", "GOOG"):
            assert features[t]["traffic_light_multiplier"] == 0.5, (
                f"{t} missing or wrong traffic_light_multiplier"
            )

    def test_spreads_regime_label_to_top_level(self):
        """2026-04-14 regression guard: mr_scan_service did not spread
        traffic_light's regime_label to the top-level features dict, so
        log_recommendation wrote market_regime=NULL for all MR candidates."""
        from src.features.enrichment import attach_post_scan_features
        features = _make_features(["AAPL", "COST"])

        with patch("src.features.traffic_light.compute_traffic_light",
                   return_value=_mock_tl(regime="volatile_uptrend")), \
             patch("src.features.event_risk_score.attach_event_risk_scores"):
            attach_post_scan_features(
                features, config={}, spy=pd.DataFrame(), vix_value=18.0,
            )

        for t in ("AAPL", "COST"):
            assert features[t]["regime_label"] == "volatile_uptrend", (
                f"{t} regime_label not spread to top level"
            )

    def test_preserves_pre_existing_regime_label(self):
        """If the upstream feature pipeline already set regime_label (e.g. via
        features/engine.py::feat.update(regime)), the helper must not clobber it."""
        from src.features.enrichment import attach_post_scan_features
        features = {"AAPL": {"current_price": 100.0, "regime_label": "calm_downtrend"}}

        with patch("src.features.traffic_light.compute_traffic_light",
                   return_value=_mock_tl(regime="volatile_uptrend")), \
             patch("src.features.event_risk_score.attach_event_risk_scores"):
            attach_post_scan_features(
                features, config={}, spy=pd.DataFrame(), vix_value=18.0,
            )

        # Engine's regime wins; helper fills only the gap
        assert features["AAPL"]["regime_label"] == "calm_downtrend"

    def test_attaches_event_risk_multiplier(self):
        from src.features.enrichment import attach_post_scan_features
        features = _make_features(["AAPL"])

        def _fake_event_risk(feats, **kwargs):
            for feat in feats.values():
                feat["event_risk_multiplier"] = 0.7
                feat["event_risk_score"] = 4
            return {"total_score": 4, "components": {}, "sizing_multiplier": 0.7}

        with patch("src.features.traffic_light.compute_traffic_light",
                   return_value=_mock_tl()), \
             patch("src.features.event_risk_score.attach_event_risk_scores",
                   side_effect=_fake_event_risk):
            attach_post_scan_features(
                features, config={}, spy=pd.DataFrame(), vix_value=15.0,
            )

        assert features["AAPL"]["event_risk_multiplier"] == 0.7

    def test_graceful_traffic_light_failure(self):
        """If compute_traffic_light raises, helper must NOT propagate —
        must set conservative defaults so scanners don't crash mid-cycle."""
        from src.features.enrichment import attach_post_scan_features
        features = _make_features(["AAPL"])

        with patch("src.features.traffic_light.compute_traffic_light",
                   side_effect=RuntimeError("vix fetch failed")), \
             patch("src.features.event_risk_score.attach_event_risk_scores"):
            # Must not raise
            attach_post_scan_features(
                features, config={}, spy=pd.DataFrame(), vix_value=None,
            )

        assert features["AAPL"]["traffic_light_multiplier"] == 1.0

    def test_bootcamp_floor_applied(self):
        """Bootcamp mode raises the traffic_light_multiplier floor so data is
        still collected in restrictive regimes."""
        from src.features.enrichment import attach_post_scan_features
        features = _make_features(["AAPL"])
        config = {"bootcamp": {"enabled": True, "traffic_light_floor": 0.5}}

        with patch("src.features.traffic_light.compute_traffic_light",
                   return_value=_mock_tl(mult=0.1)), \
             patch("src.features.event_risk_score.attach_event_risk_scores"):
            attach_post_scan_features(
                features, config=config, spy=pd.DataFrame(), vix_value=30.0,
            )

        assert features["AAPL"]["traffic_light_multiplier"] == 0.5
