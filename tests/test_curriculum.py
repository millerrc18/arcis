"""Tests for three-stage curriculum training."""

import pytest


def test_classify_difficulty_easy_win():
    from src.training.curriculum import classify_difficulty

    example = {
        "input_text": "Score: 95/100\n=== ACTUAL OUTCOME ===\nExit Reason: target_2_hit\nclean_win",
        "output_text": "WHY NOW: Great setup.\nDEEPER ANALYSIS: Strong trend.",
        "feature_snapshot": "",
    }
    assert classify_difficulty(example) == "easy"


def test_classify_difficulty_easy_loss():
    from src.training.curriculum import classify_difficulty

    example = {
        "input_text": "Score: 45/100\n=== ACTUAL OUTCOME ===\nExit Reason: stop_hit\nclean_loss",
        "output_text": "WHY NOW: Weak setup.\nDEEPER ANALYSIS: Poor trend.",
        "feature_snapshot": "",
    }
    assert classify_difficulty(example) == "easy"


def test_classify_difficulty_hard_conflicting():
    from src.training.curriculum import classify_difficulty

    example = {
        "input_text": (
            "Score: 85/100\n"
            "insider_sentiment: net_selling\n"
            "Regime: volatile_downtrend\n"
            "MFE: $5.00\nMAE: $-4.00\n"
            "news_sentiment: negative"
        ),
        "output_text": "Analysis",
        "feature_snapshot": "",
    }
    assert classify_difficulty(example) == "hard"


def test_classify_difficulty_medium_default():
    from src.training.curriculum import classify_difficulty

    example = {
        "input_text": "Score: 75/100\nSome normal setup",
        "output_text": "Analysis",
        "feature_snapshot": "",
    }
    assert classify_difficulty(example) == "medium"


def test_assign_stage_structure():
    from src.training.curriculum import assign_curriculum_stage

    example = {"input_text": "Basic setup", "source": "historical_backfill"}
    assert assign_curriculum_stage(example, "easy") == "structure"


def test_assign_stage_evidence():
    from src.training.curriculum import assign_curriculum_stage

    example = {
        "input_text": (
            "=== FUNDAMENTAL SNAPSHOT ===\nRevenue growth 15%\n"
            "=== INSIDER ACTIVITY ===\nNet buying: 3 buys\n"
            "=== RECENT NEWS ===\nPositive news\n"
        ),
        "source": "historical_backfill",
    }
    assert assign_curriculum_stage(example, "medium") == "evidence"


def test_assign_stage_decision():
    from src.training.curriculum import assign_curriculum_stage

    example = {"input_text": "Hard setup", "source": "contrastive_pair"}
    assert assign_curriculum_stage(example, "hard") == "decision"


def test_contrastive_pair_matching():
    """Test that contrastive pairs require same sector and similar score."""
    from src.training.curriculum import _extract_score, _extract_sector

    text_a = "Score: 82/100\nSector: Technology"
    text_b = "Score: 78/100\nSector: Technology"

    score_a = _extract_score(text_a)
    score_b = _extract_score(text_b)
    sector_a = _extract_sector(text_a)
    sector_b = _extract_sector(text_b)

    assert score_a == 82
    assert score_b == 78
    assert abs(score_a - score_b) <= 10
    assert sector_a == sector_b == "Technology"


def test_extract_score():
    from src.training.curriculum import _extract_score
    assert _extract_score("Score: 85/100") == 85.0
    assert _extract_score("Score: 92.5/100") == 92.5
    assert _extract_score("No score here") is None
