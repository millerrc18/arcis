"""S05 T1-T4: Known-answer tests for the incumbent ranker.

Tests the scoring bands, regime adjustments, and technical features
against hand-computed values. Clean-room implementation; no legacy
code was referenced.
"""

from arcis.strategy import features, scoring


class TestScoringBands:
    def test_trend_state(self):
        assert scoring.score_trend_state("strong_uptrend") == 30
        assert scoring.score_trend_state("uptrend") == 20
        assert scoring.score_trend_state("neutral") == 5
        assert scoring.score_trend_state("downtrend") == 0
        assert scoring.score_trend_state("unknown") == 0

    def test_relative_strength(self):
        assert scoring.score_relative_strength_state("strong_outperformer") == 25
        assert scoring.score_relative_strength_state("outperformer") == 15
        assert scoring.score_relative_strength_state("neutral") == 0

    def test_pullback_depth_sweet_spot(self):
        # [-8, -3) -> 25
        assert scoring.score_pullback_depth(-5.0) == 25
        assert scoring.score_pullback_depth(-8.0) == 25  # inclusive lower
        assert scoring.score_pullback_depth(-3.5) == 25

    def test_pullback_depth_secondary(self):
        # [-12, -8) -> 10
        assert scoring.score_pullback_depth(-10.0) == 10
        assert scoring.score_pullback_depth(-12.0) == 10
        assert scoring.score_pullback_depth(-8.5) == 10

    def test_pullback_depth_exclusive_upper(self):
        # -3.0 is exclusive upper of [-8, -3) -> 0
        assert scoring.score_pullback_depth(-3.0) == 0
        assert scoring.score_pullback_depth(-2.9) == 0
        # -8.0 goes to first band (order-sensitive)
        assert scoring.score_pullback_depth(-8.0) == 25

    def test_pullback_depth_outside(self):
        assert scoring.score_pullback_depth(-15.0) == 0
        assert scoring.score_pullback_depth(0.0) == 0
        assert scoring.score_pullback_depth(5.0) == 0

    def test_dist_to_sma20(self):
        assert scoring.score_dist_to_sma20(-3.0) == 10
        assert scoring.score_dist_to_sma20(-5.0) == 10
        assert scoring.score_dist_to_sma20(-1.0) == 10
        assert scoring.score_dist_to_sma20(-6.0) == 0
        assert scoring.score_dist_to_sma20(0.0) == 0

    def test_volume_ratio(self):
        assert scoring.score_volume_ratio(0.5) == 15
        assert scoring.score_volume_ratio(0.8) == 15
        assert scoring.score_volume_ratio(0.81) == 0
        assert scoring.score_volume_ratio(1.5) == 0

    def test_iv_rank(self):
        assert scoring.score_iv_rank(20.0) == 3
        assert scoring.score_iv_rank(25.0) == 3
        assert scoring.score_iv_rank(25.1) == 0
        assert scoring.score_iv_rank(80.0) == 0

    def test_iv_put_call(self):
        assert scoring.score_iv_put_call(80.0, 1.5) == -3
        assert scoring.score_iv_put_call(80.0, 1.0) == 0
        assert scoring.score_iv_put_call(70.0, 1.5) == 0
        assert scoring.score_iv_put_call(50.0, 0.8) == 0

    def test_blend_market_sector(self):
        # 60/40 blend
        assert scoring.blend_market_sector_rs(25, 15) == 0.6 * 25 + 0.4 * 15
        # Sector unavailable -> full market weight
        assert scoring.blend_market_sector_rs(25, None) == 25.0

    def test_clamp(self):
        assert scoring.clamp_score(150.0) == 100.0
        assert scoring.clamp_score(-10.0) == 0.0
        assert scoring.clamp_score(75.5) == 75.5


class TestRegimeAdjustments:
    def test_calm_uptrend_healthy(self):
        assert scoring.apply_regime_adjustments(
            50.0, "calm_uptrend", "healthy") == 55.0

    def test_calm_uptrend_narrowing(self):
        assert scoring.apply_regime_adjustments(
            50.0, "calm_uptrend", "narrowing") == 52.0

    def test_transitional(self):
        assert scoring.apply_regime_adjustments(
            50.0, "transitional") == 47.0

    def test_calm_downtrend(self):
        assert scoring.apply_regime_adjustments(
            50.0, "calm_downtrend") == 45.0

    def test_volatile_downtrend(self):
        assert scoring.apply_regime_adjustments(
            50.0, "volatile_downtrend") == 40.0

    def test_volatile_uptrend_noop(self):
        assert scoring.apply_regime_adjustments(
            50.0, "volatile_uptrend") == 50.0

    def test_spy_rsi_overbought(self):
        assert scoring.apply_regime_adjustments(
            50.0, "neutral", None, spy_rsi_14=80.0) == 47.0

    def test_spy_rsi_oversold(self):
        assert scoring.apply_regime_adjustments(
            50.0, "neutral", None, spy_rsi_14=25.0) == 53.0

    def test_clamp_adjustment(self):
        # volatile_downtrend (-10) + overbought (-3) = -13 -> clamped to -10
        assert scoring.apply_regime_adjustments(
            50.0, "volatile_downtrend", None,
            spy_rsi_14=80.0) == 40.0


class TestFeatures:
    def test_sma(self):
        assert features.sma([1.0, 2.0, 3.0, 4.0, 5.0], 5) == 3.0
        assert features.sma([10.0, 20.0, 30.0], 3) == 20.0

    def test_rsi_14_all_gains(self):
        # 15 rising closes -> RSI = 100
        closes = [100.0 + i for i in range(15)]
        assert features.rsi_14(closes) == 100.0

    def test_rsi_14_all_losses(self):
        # 15 falling closes -> RSI = 0
        closes = [100.0 - i for i in range(15)]
        assert features.rsi_14(closes) == 0.0

    def test_rsi_14_mixed(self):
        # Hand-computed: alternating +1/-1 for 14 periods
        # Gains: 7 of +1, Losses: 7 of +1 -> RS = 1 -> RSI = 50
        closes = [100.0]
        for i in range(14):
            closes.append(closes[-1] + (1.0 if i % 2 == 0 else -1.0))
        rsi = features.rsi_14(closes)
        assert 49.0 < rsi < 51.0, f"RSI={rsi}"

    def test_atr_14_constant_range(self):
        # Constant $2 range -> ATR = 2.0
        n = 15
        highs = [102.0] * n
        lows = [100.0] * n
        closes = [101.0] * n
        assert abs(features.atr_14(highs, lows, closes) - 2.0) < 0.01

    def test_volume_ratio(self):
        volumes = [1000.0] * 19 + [2000.0]  # avg = 1050, ratio = 2000/1050
        assert abs(features.volume_ratio(volumes, 20) - 2000/1050) < 0.001

    def test_pullback_depth(self):
        closes = [100.0, 105.0, 110.0, 104.5]  # 5% pullback from 110
        depth = features.pullback_depth_pct(closes, lookback=60)
        assert abs(depth - (-5.0)) < 0.01

    def test_dist_to_sma20(self):
        closes = [100.0] * 20  # flat -> 0% distance
        assert features.dist_to_sma20_pct(closes) == 0.0
        closes = [100.0] * 19 + [95.0]  # 5% below
        sma20 = sum(closes) / 20
        expected = (95.0 - sma20) / sma20 * 100
        assert abs(features.dist_to_sma20_pct(closes) - expected) < 0.01

    def test_excess_return(self):
        # Symbol +10%, benchmark +5% -> 5% excess
        sym = [100.0, 110.0]
        bench = [100.0, 105.0]
        assert abs(features.excess_return(sym, bench, 1) - 0.05) < 0.001
