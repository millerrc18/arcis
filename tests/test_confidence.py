"""Tests for learned confidence output parsing and calibration."""

import pytest


class TestConvictionParsing:
    def test_parse_valid_conviction(self):
        from src.llm.packet_writer import _parse_llm_response

        response = """CONVICTION: 8 Strong convergence of technical and fundamental signals

WHY NOW:
The stock is pulling back into support with strong relative strength.

DEEPER ANALYSIS:
This is a solid setup with multiple confirming factors."""

        conviction, why_now, deeper = _parse_llm_response(response)
        assert conviction == 8
        assert why_now is not None
        assert "pulling back" in why_now
        assert deeper is not None

    def test_parse_conviction_10(self):
        from src.llm.packet_writer import _parse_llm_response

        response = """CONVICTION: 10 Everything aligns perfectly

WHY NOW:
Strong setup.

DEEPER ANALYSIS:
Great trade."""

        conviction, why_now, deeper = _parse_llm_response(response)
        assert conviction == 10

    def test_parse_conviction_1(self):
        from src.llm.packet_writer import _parse_llm_response

        response = """CONVICTION: 1 Weak setup with many risks

WHY NOW:
Marginal opportunity.

DEEPER ANALYSIS:
Risky trade."""

        conviction, why_now, deeper = _parse_llm_response(response)
        assert conviction == 1

    def test_missing_conviction_returns_none(self):
        from src.llm.packet_writer import _parse_llm_response

        response = """WHY NOW:
The stock is pulling back.

DEEPER ANALYSIS:
This is analysis."""

        conviction, why_now, deeper = _parse_llm_response(response)
        assert conviction is None
        assert why_now is not None
        assert deeper is not None

    def test_invalid_conviction_number_skipped(self):
        from src.llm.packet_writer import _parse_llm_response

        response = """CONVICTION: 15 Way too high

WHY NOW:
Setup description.

DEEPER ANALYSIS:
Analysis text."""

        conviction, why_now, deeper = _parse_llm_response(response)
        assert conviction == 10  # 15 is clamped to max 10

    def test_missing_sections_returns_none(self):
        from src.llm.packet_writer import _parse_llm_response

        response = """CONVICTION: 7 Good setup
Just some random text without sections."""

        conviction, why_now, deeper = _parse_llm_response(response)
        assert conviction == 7
        assert why_now is None
        assert deeper is None


class TestConfidenceCalibration:
    def test_calibration_computation(self):
        from src.evaluation.cto_report import _compute_confidence_calibration

        closed = [
            {"recommendation_id": "r1", "pnl_dollars": 10, "pnl_pct": 2.0},
            {"recommendation_id": "r2", "pnl_dollars": -5, "pnl_pct": -1.0},
            {"recommendation_id": "r3", "pnl_dollars": 15, "pnl_pct": 3.0},
            {"recommendation_id": "r4", "pnl_dollars": -3, "pnl_pct": -0.5},
            {"recommendation_id": "r5", "pnl_dollars": 8, "pnl_pct": 1.5},
        ]
        recommendations = [
            {"recommendation_id": "r1", "llm_conviction": 9},
            {"recommendation_id": "r2", "llm_conviction": 3},
            {"recommendation_id": "r3", "llm_conviction": 8},
            {"recommendation_id": "r4", "llm_conviction": 4},
            {"recommendation_id": "r5", "llm_conviction": 7},
        ]

        result = _compute_confidence_calibration(closed, recommendations)

        assert "by_conviction_band" in result
        assert result["by_conviction_band"]["8-10"]["trades"] == 2  # r1 and r3
        assert result["by_conviction_band"]["5-7"]["trades"] == 1   # r5
        assert result["by_conviction_band"]["1-4"]["trades"] == 2   # r2 and r4
        assert "correlation_with_outcomes" in result
        assert "is_calibrated" in result
        assert "overconfidence_rate" in result

    def test_empty_conviction_data(self):
        from src.evaluation.cto_report import _compute_confidence_calibration

        result = _compute_confidence_calibration([], [])
        assert result["total_with_conviction"] == 0
        assert result["by_conviction_band"]["8-10"]["trades"] == 0
