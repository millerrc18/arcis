"""Tests for src/services/mr_scan_service.py — mean reversion scan service."""

from unittest.mock import patch

import pytest


class TestMrScanDisabled:
    def test_returns_disabled_when_mr_not_enabled(self):
        from src.services.mr_scan_service import run_mr_scan
        config = {"strategies": {"mean_reversion": {"enabled": False}}}
        result = run_mr_scan(config)
        assert result["status"] == "disabled"
        assert result["candidates"] == 0
        assert result["trades_opened"] == 0


class TestMrScanNoCandidates:
    @patch("src.features.mean_reversion.scan_for_mr_candidates", return_value=[])
    @patch("src.data_ingestion.market_data.fetch_ohlcv", return_value={})
    @patch("src.universe.sp100.get_sp100_universe", return_value=["AAPL"])
    def test_returns_no_candidates(self, mock_uni, mock_ohlcv, mock_scan):
        from src.services.mr_scan_service import run_mr_scan
        config = {
            "strategies": {"mean_reversion": {"enabled": True}},
            "shadow_trading": {"enabled": False},
        }
        result = run_mr_scan(config)
        assert result["status"] == "no_candidates"
        assert result["candidates"] == 0


class TestMrScanDryRun:
    @patch("src.features.mean_reversion.scan_for_mr_candidates")
    @patch("src.data_ingestion.market_data.fetch_ohlcv", return_value={})
    @patch("src.universe.sp100.get_sp100_universe", return_value=["AAPL"])
    def test_dry_run_does_not_open_trades(self, mock_uni, mock_ohlcv, mock_scan):
        from src.services.mr_scan_service import run_mr_scan
        mock_scan.return_value = [
            {"ticker": "AAPL", "features": {"current_price": 150.0, "rsi_2": 5.0},
             "score": 95},
        ]
        config = {
            "strategies": {"mean_reversion": {"enabled": True}},
            "shadow_trading": {"enabled": True},
        }
        result = run_mr_scan(config, dry_run=True)
        assert result["status"] == "complete"
        assert result["candidates"] == 1
        assert result["trades_opened"] == 0
        assert result["results"][0]["action"] == "dry_run"


class TestMrScanEnrichment:
    """Phase 3.3 regression guard — mr_scan_service must attach traffic_light
    and event_risk features before logging the recommendation, else the executor
    defaults to 0.5 traffic_light_multiplier and market_regime persists as NULL
    (2026-04-14: AAPL/COST/DE/DUK/FDX zero-allocation rejections)."""

    @patch("src.features.mean_reversion.scan_for_mr_candidates")
    @patch("src.data_ingestion.market_data.fetch_ohlcv", return_value={})
    @patch("src.universe.sp100.get_sp100_universe", return_value=["AAPL"])
    def test_candidates_enriched_before_recommendation(
            self, mock_uni, mock_ohlcv, mock_scan):
        from src.services.mr_scan_service import run_mr_scan

        mock_scan.return_value = [
            {"ticker": "AAPL",
             "features": {"current_price": 150.0, "rsi_2": 5.0, "atr_14": 3.0},
             "score": 95},
        ]
        config = {
            "strategies": {"mean_reversion": {"enabled": True}},
            "shadow_trading": {"enabled": False},
        }

        # Capture the features passed to log_recommendation
        captured = {}
        def _capture_log(packet, features, score, qual, **kw):
            captured["features"] = features
            return "rec-id-1"

        def _mock_enrich(features, **kw):
            for feat in features.values():
                feat["traffic_light_multiplier"] = 1.0
                feat["event_risk_multiplier"] = 1.0
                feat["regime_label"] = "calm_uptrend"
            return features

        with patch("src.features.enrichment.attach_post_scan_features",
                   side_effect=_mock_enrich) as mock_enrich, \
             patch("src.journal.store.log_recommendation", side_effect=_capture_log), \
             patch("src.packets.template.build_packet_from_features"), \
             patch("src.llm.packet_writer.enhance_packet_with_llm",
                   side_effect=lambda pkt, feat, cfg: pkt):
            run_mr_scan(config, dry_run=False)

        assert mock_enrich.called, (
            "attach_post_scan_features must be called before log_recommendation"
        )
        # Enriched fields must be present when log_recommendation sees the features
        assert "traffic_light_multiplier" in captured["features"]
        assert "event_risk_multiplier" in captured["features"]
        assert "regime_label" in captured["features"]


class TestPromptRouting:
    def test_mr_prompt_returned_for_mean_reversion(self):
        from src.llm.prompts import get_system_prompt, MR_PACKET_SYSTEM_PROMPT
        assert get_system_prompt("mean_reversion") is MR_PACKET_SYSTEM_PROMPT

    def test_main_prompt_returned_for_pullback(self):
        from src.llm.prompts import get_system_prompt, PACKET_SYSTEM_PROMPT
        assert get_system_prompt("pullback") is PACKET_SYSTEM_PROMPT

    def test_main_prompt_returned_for_unknown(self):
        from src.llm.prompts import get_system_prompt, PACKET_SYSTEM_PROMPT
        assert get_system_prompt("unknown_strategy") is PACKET_SYSTEM_PROMPT
