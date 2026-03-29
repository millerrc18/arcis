"""Tests for the process-first quality rubric."""

import json
import pytest
from unittest.mock import patch

from src.training.quality_filter import score_training_example


class TestWeightedOverall:
    """Test weighted_overall calculation matches manual computation."""

    def test_weighted_overall_calculation(self):
        """Verify the weighted formula: thesis*0.25 + evidence*0.20 + risk*0.20 + calibration*0.15 + structure*0.10 + actionability*0.10"""
        mock_response = json.dumps({
            "thesis_clarity": 4,
            "evidence_grounding": 3,
            "risk_identification": 5,
            "calibration": 3,
            "structure": 4,
            "actionability": 2,
            "weighted_overall": 3.7,
            "process_quality": "good",
            "issues": "Could improve actionability"
        })

        with patch("src.training.claude_client.generate_training_example", return_value=mock_response):
            result = score_training_example("input data", "output text")

        assert result is not None
        # Manual calculation: 4*0.25 + 3*0.20 + 5*0.20 + 3*0.15 + 4*0.10 + 2*0.10
        # = 1.0 + 0.6 + 1.0 + 0.45 + 0.4 + 0.2 = 3.65
        expected = round(4*0.25 + 3*0.20 + 5*0.20 + 3*0.15 + 4*0.10 + 2*0.10, 1)
        assert result["weighted_overall"] == expected

    def test_perfect_scores(self):
        mock_response = json.dumps({
            "thesis_clarity": 5, "evidence_grounding": 5,
            "risk_identification": 5, "calibration": 5,
            "structure": 5, "actionability": 5,
            "weighted_overall": 5.0, "process_quality": "excellent",
            "issues": "None"
        })

        with patch("src.training.claude_client.generate_training_example", return_value=mock_response):
            result = score_training_example("input", "output")

        assert result["weighted_overall"] == 5.0
        assert result["process_quality"] == "excellent"

    def test_minimum_scores(self):
        mock_response = json.dumps({
            "thesis_clarity": 1, "evidence_grounding": 1,
            "risk_identification": 1, "calibration": 1,
            "structure": 1, "actionability": 1,
            "weighted_overall": 1.0, "process_quality": "poor",
            "issues": "Everything needs improvement"
        })

        with patch("src.training.claude_client.generate_training_example", return_value=mock_response):
            result = score_training_example("input", "output")

        assert result["weighted_overall"] == 1.0
        assert result["process_quality"] == "poor"


class TestProcessQualityClassification:
    """Test process_quality tiers: excellent >= 4.0, good >= 3.0, etc."""

    def _make_response(self, scores):
        return json.dumps({
            "thesis_clarity": scores[0], "evidence_grounding": scores[1],
            "risk_identification": scores[2], "calibration": scores[3],
            "structure": scores[4], "actionability": scores[5],
            "weighted_overall": 0, "process_quality": "", "issues": ""
        })

    def test_excellent_classification(self):
        # All 4s → weighted = 4.0
        with patch("src.training.claude_client.generate_training_example",
                    return_value=self._make_response([4, 4, 4, 4, 4, 4])):
            result = score_training_example("input", "output")
        assert result["process_quality"] == "excellent"

    def test_good_classification(self):
        # All 3s → weighted = 3.0
        with patch("src.training.claude_client.generate_training_example",
                    return_value=self._make_response([3, 3, 3, 3, 3, 3])):
            result = score_training_example("input", "output")
        assert result["process_quality"] == "good"

    def test_adequate_classification(self):
        # All 2s → weighted = 2.0
        with patch("src.training.claude_client.generate_training_example",
                    return_value=self._make_response([2, 2, 2, 2, 2, 2])):
            result = score_training_example("input", "output")
        assert result["process_quality"] == "adequate"

    def test_poor_classification(self):
        # All 1s → weighted = 1.0
        with patch("src.training.claude_client.generate_training_example",
                    return_value=self._make_response([1, 1, 1, 1, 1, 1])):
            result = score_training_example("input", "output")
        assert result["process_quality"] == "poor"


class TestOutcomeOverlay:
    """Test that outcome overlay is separate from process score."""

    def test_outcome_overlay_stored_separately(self):
        mock_response = json.dumps({
            "thesis_clarity": 4, "evidence_grounding": 4,
            "risk_identification": 4, "calibration": 4,
            "structure": 4, "actionability": 4,
            "weighted_overall": 4.0, "process_quality": "excellent",
            "issues": "None"
        })

        with patch("src.training.claude_client.generate_training_example", return_value=mock_response):
            result = score_training_example("input", "output", outcome="win")

        assert "outcome_overlay" in result
        assert result["outcome_overlay"]["outcome"] == "win"
        # Process score unchanged by outcome
        assert result["weighted_overall"] == 4.0

    def test_no_overlay_without_outcome(self):
        mock_response = json.dumps({
            "thesis_clarity": 3, "evidence_grounding": 3,
            "risk_identification": 3, "calibration": 3,
            "structure": 3, "actionability": 3,
            "weighted_overall": 3.0, "process_quality": "good", "issues": ""
        })

        with patch("src.training.claude_client.generate_training_example", return_value=mock_response):
            result = score_training_example("input", "output")

        assert "outcome_overlay" not in result


class TestRubricEdgeCases:
    """Test rubric handles missing dimensions and API failures."""

    def test_missing_dimensions_default_to_3(self):
        """Missing dimensions should default to 3 in weighted calculation."""
        mock_response = json.dumps({
            "thesis_clarity": 5,
            "evidence_grounding": 4,
            # Missing: risk_identification, calibration, structure, actionability
            "weighted_overall": 0, "process_quality": "", "issues": ""
        })

        with patch("src.training.claude_client.generate_training_example", return_value=mock_response):
            result = score_training_example("input", "output")

        assert result is not None
        # 5*0.25 + 4*0.20 + 3*0.20 + 3*0.15 + 3*0.10 + 3*0.10
        expected = round(5*0.25 + 4*0.20 + 3*0.20 + 3*0.15 + 3*0.10 + 3*0.10, 1)
        assert result["weighted_overall"] == expected

    def test_api_failure_returns_none(self):
        with patch("src.training.claude_client.generate_training_example", return_value=None):
            result = score_training_example("input", "output")
        assert result is None

    def test_invalid_json_returns_none(self):
        with patch("src.training.claude_client.generate_training_example", return_value="not json"):
            result = score_training_example("input", "output")
        assert result is None

    def test_markdown_fenced_json(self):
        """Should handle JSON wrapped in markdown code fences."""
        mock_response = '```json\n{"thesis_clarity": 4, "evidence_grounding": 3, "risk_identification": 3, "calibration": 3, "structure": 3, "actionability": 3, "weighted_overall": 3.3, "process_quality": "good", "issues": "none"}\n```'

        with patch("src.training.claude_client.generate_training_example", return_value=mock_response):
            result = score_training_example("input", "output")

        assert result is not None
        assert result["thesis_clarity"] == 4

    def test_backward_compat_overall_field(self):
        """Should store both weighted_overall and overall for backward compat."""
        mock_response = json.dumps({
            "thesis_clarity": 4, "evidence_grounding": 4,
            "risk_identification": 4, "calibration": 4,
            "structure": 4, "actionability": 4,
            "weighted_overall": 4.0, "process_quality": "excellent", "issues": ""
        })

        with patch("src.training.claude_client.generate_training_example", return_value=mock_response):
            result = score_training_example("input", "output")

        assert "overall" in result
        assert result["overall"] == result["weighted_overall"]
