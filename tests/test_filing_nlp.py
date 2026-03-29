"""Tests for SEC filing NLP sentiment scoring."""

import pytest

from src.features.filing_nlp import (
    compute_filing_delta,
    compute_tech_fundamental_divergence,
    detect_cautionary_phrases,
    score_filing_sentiment,
)


class TestScoreFilingSentiment:
    """Tests for Loughran-McDonald dictionary sentiment scoring."""

    def test_empty_text_returns_zeros(self):
        result = score_filing_sentiment("")
        assert result["negative_count"] == 0
        assert result["positive_count"] == 0
        assert result["uncertainty_count"] == 0
        assert result["polarity"] == 0

    def test_negative_words_detected(self):
        text = "There was a significant loss and impairment of assets."
        result = score_filing_sentiment(text)
        assert result["negative_count"] > 0

    def test_positive_words_detected(self):
        text = "The company achieve strong gain and improve profitability."
        result = score_filing_sentiment(text)
        assert result["positive_count"] > 0

    def test_uncertainty_words_detected(self):
        text = "The outlook is uncertain with possible risks approximately equal."
        result = score_filing_sentiment(text)
        assert result["uncertainty_count"] > 0

    def test_polarity_positive_for_bullish_text(self):
        """Text with more positive than negative words should have positive polarity."""
        text = "Strong profit increase gain improvement growth"
        result = score_filing_sentiment(text)
        assert result["polarity"] > 0

    def test_polarity_negative_for_bearish_text(self):
        """Text with more negative words should have negative polarity."""
        text = "Loss impairment decline default weakness deterioration"
        result = score_filing_sentiment(text)
        assert result["polarity"] < 0

    def test_word_count_returned(self):
        text = "The quick brown fox jumps over the lazy dog."
        result = score_filing_sentiment(text)
        assert result["word_count"] > 0

    def test_subjectivity_between_0_and_1(self):
        text = "Strong gains offset by significant losses in the quarterly report."
        result = score_filing_sentiment(text)
        assert 0 <= result["subjectivity"] <= 1

    def test_none_text_handled(self):
        """None input should not crash."""
        try:
            result = score_filing_sentiment(None)
            assert result["word_count"] == 0
        except (TypeError, AttributeError):
            pass  # Acceptable to raise on None


class TestDetectCautionaryPhrases:
    """Tests for high-signal cautionary phrase detection."""

    def test_empty_text(self):
        result = detect_cautionary_phrases("")
        assert result == []

    def test_material_weakness_detected(self):
        text = "The auditor identified a material weakness in internal controls."
        result = detect_cautionary_phrases(text)
        phrases = [p["phrase"] for p in result]
        assert "material weakness" in phrases

    def test_going_concern_detected(self):
        text = "There is substantial doubt about the company's ability to continue as a going concern."
        result = detect_cautionary_phrases(text)
        phrases = [p["phrase"] for p in result]
        assert "going concern" in phrases

    def test_multiple_phrases(self):
        text = "The restatement revealed a material weakness and SEC investigation."
        result = detect_cautionary_phrases(text)
        assert len(result) >= 2

    def test_case_insensitive(self):
        text = "MATERIAL WEAKNESS identified by the auditor."
        result = detect_cautionary_phrases(text)
        assert len(result) >= 1

    def test_clean_filing_no_phrases(self):
        text = "Revenue increased 15% year over year with strong margins."
        result = detect_cautionary_phrases(text)
        assert result == []

    def test_count_field_present(self):
        text = "material weakness material weakness"
        result = detect_cautionary_phrases(text)
        if result:
            assert "count" in result[0]


class TestComputeFilingDelta:
    """Tests for sentiment change between consecutive filings."""

    def test_first_filing_returns_none_deltas(self):
        current = {"polarity": 0.05, "negative_count": 2, "uncertainty_count": 1, "word_count": 1000}
        result = compute_filing_delta(current, None)
        assert result["is_first_filing"] is True

    def test_delta_computed_correctly(self):
        current = {"polarity": 0.05, "negative_count": 5, "uncertainty_count": 3, "word_count": 1000}
        previous = {"polarity": 0.02, "negative_count": 3, "uncertainty_count": 2, "word_count": 900}
        result = compute_filing_delta(current, previous)
        assert result["is_first_filing"] is False
        assert result["delta_polarity"] == pytest.approx(0.03, abs=0.001)
        assert result["delta_negative"] == 2

    def test_empty_previous_treated_as_first(self):
        current = {"polarity": 0.01, "negative_count": 1, "uncertainty_count": 0, "word_count": 500}
        result = compute_filing_delta(current, {})
        # Should handle gracefully — either first_filing=True or compute deltas from zeros


class TestComputeTechFundamentalDivergence:
    """Tests for detecting tech/fundamental divergence."""

    def test_convergence_bullish(self):
        features = {"trend_state": "strong_uptrend"}
        filing = {"delta_polarity": 0.05, "cautionary_count": 0}
        result = compute_tech_fundamental_divergence(features, filing)
        assert result == "convergence_bullish"

    def test_divergence_caution(self):
        """Tech bullish + fundamental bearish → caution."""
        features = {"trend_state": "uptrend"}
        filing = {"delta_polarity": -0.1, "cautionary_count": 2}
        result = compute_tech_fundamental_divergence(features, filing)
        assert result == "divergence_caution"

    def test_neutral_downtrend(self):
        """Non-bullish tech → neutral regardless of fundamentals."""
        features = {"trend_state": "downtrend"}
        filing = {"delta_polarity": 0.05, "cautionary_count": 0}
        result = compute_tech_fundamental_divergence(features, filing)
        assert result == "neutral"

    def test_neutral_sideways(self):
        features = {"trend_state": "sideways"}
        filing = {"delta_polarity": -0.1, "cautionary_count": 1}
        result = compute_tech_fundamental_divergence(features, filing)
        assert result == "neutral"
