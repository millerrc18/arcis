"""Tests for _resolve_event_risk_multiplier — the on-demand compute fallback (#422).

The prior behavior silently defaulted missing multipliers to 0.5, halving
allocations for tickers whose feature dict never routed through
``attach_event_risk_scores``.  This test pins the new resolution order:
  present-in-features -> compute -> 0.5 (only if compute fails).
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from src.shadow_trading.executor import _resolve_event_risk_multiplier


class TestResolveEventRiskMultiplier:
    def test_uses_features_value_when_present(self):
        features = {"event_risk_multiplier": 0.75}
        out = _resolve_event_risk_multiplier(features, "AAPL")
        assert out == 0.75
        assert features["event_risk_multiplier"] == 0.75

    def test_present_value_bypasses_compute(self):
        features = {"event_risk_multiplier": 1.0}
        with patch(
            "src.features.event_risk_score.compute_event_risk_score"
        ) as mock_compute:
            _resolve_event_risk_multiplier(features, "AAPL")
            mock_compute.assert_not_called()

    def test_computes_on_demand_when_missing(self, caplog):
        features = {}
        fake_result = {"sizing_multiplier": 0.65, "total_score": 4}
        with patch(
            "src.features.event_risk_score.compute_event_risk_score",
            return_value=fake_result,
        ) as mock_compute:
            # Production logs this at WARNING (executor.py:143), not ERROR.
            with caplog.at_level("WARNING"):
                out = _resolve_event_risk_multiplier(features, "BMY")
        assert out == 0.65
        assert features["event_risk_multiplier"] == 0.65
        mock_compute.assert_called_once_with("BMY")
        assert any("computed on-demand" in r.message for r in caplog.records)

    def test_compute_failure_falls_back_to_0_5(self, caplog):
        features = {}
        with patch(
            "src.features.event_risk_score.compute_event_risk_score",
            side_effect=RuntimeError("db locked"),
        ):
            with caplog.at_level("WARNING"):
                out = _resolve_event_risk_multiplier(features, "BMY")
        assert out == 0.5
        assert features["event_risk_multiplier"] == 0.5
        assert any("compute failed" in r.message for r in caplog.records)
        assert any("fail-conservative" in r.message for r in caplog.records)

    def test_compute_missing_sizing_multiplier_defaults_to_1_0(self):
        features = {}
        with patch(
            "src.features.event_risk_score.compute_event_risk_score",
            return_value={"total_score": 0},
        ):
            out = _resolve_event_risk_multiplier(features, "AAPL")
        assert out == 1.0

    def test_log_prefix_live_path(self, caplog):
        features = {}
        with patch(
            "src.features.event_risk_score.compute_event_risk_score",
            side_effect=RuntimeError("nope"),
        ):
            with caplog.at_level("WARNING"):
                _resolve_event_risk_multiplier(features, "BMY", path="LIVE")
        assert any("[LIVE]" in r.message for r in caplog.records)

    def test_explicit_zero_treated_as_present(self):
        features = {"event_risk_multiplier": 0.0}
        with patch(
            "src.features.event_risk_score.compute_event_risk_score"
        ) as mock_compute:
            out = _resolve_event_risk_multiplier(features, "AAPL")
        assert out == 0.0
        mock_compute.assert_not_called()
