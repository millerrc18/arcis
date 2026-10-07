"""Tests for D-031 recovered classifiers."""

import pytest

from arcis.strategy.classifiers import (
    classify_trend_state, classify_rs_state, pct_return, slope_direction,
)
from arcis.strategy.scoring import (
    score_trend_state, score_relative_strength_state,
)


class TestSlopeDirection:
    def test_positive(self):
        # 10 values rising more than 0.1%
        vals = [100 + i for i in range(10)]  # 100 -> 109, diff=9 > 0.1
        assert slope_direction(vals) == "positive"

    def test_negative(self):
        vals = [109 - i for i in range(10)]
        assert slope_direction(vals) == "negative"

    def test_flat(self):
        vals = [100.0] * 10
        assert slope_direction(vals) == "flat"

    def test_insufficient_values(self):
        assert slope_direction([1, 2, 3]) == "flat"


class TestTrendState:
    def test_strong_uptrend(self):
        # price > sma50 > sma200, both slopes positive
        assert classify_trend_state(110, 105, 100, "positive", "positive") == "strong_uptrend"

    def test_uptrend(self):
        # price > sma50 > sma200, slopes not both positive
        assert classify_trend_state(110, 105, 100, "flat", "positive") == "uptrend"

    def test_strong_downtrend(self):
        assert classify_trend_state(90, 95, 100, "negative", "negative") == "strong_downtrend"

    def test_downtrend(self):
        assert classify_trend_state(90, 95, 100, "flat", "negative") == "downtrend"

    def test_neutral_on_equality(self):
        # Strict comparisons: equality falls through to neutral
        assert classify_trend_state(100, 100, 90, "positive", "positive") == "neutral"

    def test_neutral_mixed(self):
        assert classify_trend_state(105, 100, 110, "positive", "positive") == "neutral"


class TestRSState:
    def test_strong_outperformer(self):
        assert classify_rs_state(5, 3, 1) == "strong_outperformer"

    def test_outperformer(self):
        assert classify_rs_state(5, 3, -1) == "outperformer"

    def test_strong_underperformer(self):
        assert classify_rs_state(-5, -3, -1) == "strong_underperformer"

    def test_underperformer(self):
        assert classify_rs_state(-5, -3, 1) == "underperformer"

    def test_neutral(self):
        assert classify_rs_state(5, -3, 0) == "neutral"

    def test_zero_counts_as_neither(self):
        # One positive, one negative, one zero → neutral
        assert classify_rs_state(1, -1, 0) == "neutral"


class TestPctReturn:
    def test_basic(self):
        closes = [100, 105, 110]
        # 2-row return: (110/100 - 1) * 100 = 10
        assert pct_return(closes, 2) == pytest.approx(10.0)

    def test_insufficient_rows(self):
        assert pct_return([100, 105], 5) == 0.0


class TestD031Scoring:
    """D-031: 5+5 labels, unlisted score 0, unknown still raises."""

    def test_trend_all_five(self):
        assert score_trend_state("strong_uptrend") == 30
        assert score_trend_state("uptrend") == 20
        assert score_trend_state("neutral") == 5
        assert score_trend_state("downtrend") == 0
        assert score_trend_state("strong_downtrend") == 0

    def test_rs_all_five(self):
        assert score_relative_strength_state("strong_outperformer") == 25
        assert score_relative_strength_state("outperformer") == 15
        assert score_relative_strength_state("neutral") == 0
        assert score_relative_strength_state("underperformer") == 0
        assert score_relative_strength_state("strong_underperformer") == 0

    def test_truly_unknown_still_raises(self):
        with pytest.raises(ValueError):
            score_trend_state("sideways")
        with pytest.raises(ValueError):
            score_relative_strength_state("mystery")
