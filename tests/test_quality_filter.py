"""Tests for LLM-as-judge quality filtering."""

import pytest
from unittest.mock import patch
import json


def test_quality_judge_prompt_format():
    from src.training.quality_filter import QUALITY_JUDGE_PROMPT
    assert "thesis_clarity" in QUALITY_JUDGE_PROMPT
    assert "evidence_grounding" in QUALITY_JUDGE_PROMPT
    assert "risk_identification" in QUALITY_JUDGE_PROMPT
    assert "calibration" in QUALITY_JUDGE_PROMPT
    assert "actionability" in QUALITY_JUDGE_PROMPT
    assert "weighted_overall" in QUALITY_JUDGE_PROMPT
    assert "process_quality" in QUALITY_JUDGE_PROMPT


@patch("src.training.claude_client.generate_training_example")
def test_score_training_example_valid(mock_generate):
    from src.training.quality_filter import score_training_example

    mock_generate.return_value = json.dumps({
        "thesis_clarity": 4, "evidence_grounding": 3, "risk_identification": 4,
        "calibration": 3, "structure": 4, "actionability": 4,
        "weighted_overall": 3.6, "process_quality": "good",
        "issues": "Minor calibration gap"
    })

    result = score_training_example("input text", "output text")
    assert result is not None
    # Recalculated: 4*0.25 + 3*0.20 + 4*0.20 + 3*0.15 + 4*0.10 + 4*0.10
    # = 1.0 + 0.6 + 0.8 + 0.45 + 0.4 + 0.4 = 3.65 → rounds to 3.6
    expected = round(4*0.25 + 3*0.20 + 4*0.20 + 3*0.15 + 4*0.10 + 4*0.10, 1)
    assert result["weighted_overall"] == expected
    assert result["overall"] == expected  # backward compat
    assert result["thesis_clarity"] == 4


@patch("src.training.claude_client.generate_training_example")
def test_score_training_example_no_overall(mock_generate):
    from src.training.quality_filter import score_training_example

    mock_generate.return_value = json.dumps({
        "thesis_clarity": 4, "evidence_grounding": 3, "risk_identification": 4,
        "calibration": 3, "structure": 4, "actionability": 4,
    })

    result = score_training_example("input", "output")
    assert result is not None
    assert "overall" in result
    assert "weighted_overall" in result
    expected = round(4*0.25 + 3*0.20 + 4*0.20 + 3*0.15 + 4*0.10 + 4*0.10, 1)
    assert result["overall"] == expected


@patch("src.training.claude_client.generate_training_example")
def test_score_training_example_failure(mock_generate):
    from src.training.quality_filter import score_training_example

    mock_generate.return_value = None
    result = score_training_example("input", "output")
    assert result is None


@patch("src.training.claude_client.generate_training_example")
def test_score_training_example_invalid_json(mock_generate):
    from src.training.quality_filter import score_training_example

    mock_generate.return_value = "This is not JSON at all."
    result = score_training_example("input", "output")
    assert result is None
