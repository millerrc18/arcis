"""S05 T1-T4: Known-answer tests for the incumbent ranker.

Tests the scoring bands, regime adjustments, and technical features
against hand-computed values. Clean-room implementation; no legacy
code was referenced.

Fail-closed: unknown labels raise ValueError; degenerate data raises ValueError.
"""

import pytest

from arcis.strategy import features, scoring


class TestScoringBands:
    def test_trend_state(self):
        assert scoring.score_trend_state("strong_uptrend") == 30
        assert scoring.score_trend_state("uptrend") == 20
        assert scoring.score_trend_state("neutral") == 5

    def test_trend_state_unknown_raises(self):
        with pytest.raises(ValueError, match="unknown trend_state"):
            scoring.score_trend_state("strong-uptrend")  # typo
        with pytest.raises(ValueError, match="unknown trend_state"):
            scoring.score_trend_state("downtrend")

    def test_relative_strength(self):
        assert scoring.score_relative_strength_state("strong_outperformer") == 25
        assert scoring.score_relative_strength_state("outperformer") == 15

    def test_relative_strength_unknown_raises(self):
        with pytest.raises(ValueError, match="unknown rs_state"):
            scoring.score_relative_strength_state("neutral")

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

    def test_pullback_depth_boundary_d028(self):
        # D-028: Sprint F doc §1.4 "pullback sweet spot [-8, -3] -> +25"
        # (closed upper bound). -3.0 scores 25; -2.9 falls through to 0.
        assert scoring.score_pullback_depth(-3.0) == 25
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
        assert scoring.score_dist_to_sma20(-1.001) == 10
        assert scoring.score_dist_to_sma20(-6.0) == 0
        assert scoring.score_dist_to_sma20(0.0) == 0

    def test_volume_ratio(self):
        assert scoring.score_volume_ratio(0.5) == 15
        assert scoring.score_volume_ratio(0.799) == 15
        assert scoring.score_volume_ratio(0.81) == 0
        assert scoring.score_volume_ratio(1.5) == 0

    def test_iv_rank(self):
        assert scoring.score_iv_rank(20.0) == 3
        assert scoring.score_iv_rank(24.9) == 3
        assert scoring.score_iv_rank(25.1) == 0
        assert scoring.score_iv_rank(80.0) == 0

    def test_iv_put_call(self):
        assert scoring.score_iv_put_call(80.0, 1.5) == -3
        assert scoring.score_iv_put_call(80.0, 1.0) == 0
        assert scoring.score_iv_put_call(70.0, 1.5) == 0
        assert scoring.score_iv_put_call(50.0, 0.8) == 0

    def test_sector_rs_set_a_bands(self):
        # D-026: absolute thresholds +5 / 0 / -5 (percentage points)
        assert scoring.score_sector_rs(37.76) == 25
        assert scoring.score_sector_rs(5.0) == 25
        assert scoring.score_sector_rs(4.999) == 15
        assert scoring.score_sector_rs(2.6) == 15
        assert scoring.score_sector_rs(0.0) == 15
        assert scoring.score_sector_rs(-0.001) == 5
        assert scoring.score_sector_rs(-3.98) == 5
        assert scoring.score_sector_rs(-5.0) == 5
        assert scoring.score_sector_rs(-5.001) == 0
        assert scoring.score_sector_rs(-30.33) == 0

    def test_sector_rs_nan_fail_closed(self):
        with pytest.raises(ValueError, match="must be finite"):
            scoring.score_sector_rs(float("nan"))
        with pytest.raises(ValueError, match="must be finite"):
            scoring.score_sector_rs(float("inf"))

    def test_sector_rs_end_to_end_units(self):
        # The D-026 bands are in percentage points. The composer must emit
        # pp, not fractions: a 20pp lead must score 25, a 20pp lag must
        # score 0. A fractions/pp slip would park everything in 15/5.
        # (Trailing return needs a rise over each window, not a high level.)
        spy = [100.0] * 130
        sector_up = [100.0] * 130
        sector_up[-1] = 120.0    # +20% trailing on 21/63/126-session windows
        wx = features.sector_weighted_excess(sector_up, spy, 21, 63, 126)
        assert abs(wx - 20.0) < 1e-9
        assert scoring.score_sector_rs(wx) == 25
        sector_down = [100.0] * 130
        sector_down[-1] = 80.0   # -20% trailing on 21/63/126-session windows
        wx_down = features.sector_weighted_excess(sector_down, spy, 21, 63,
                                                  126)
        assert abs(wx_down - (-20.0)) < 1e-9
        assert scoring.score_sector_rs(wx_down) == 0

    def test_sector_weighted_excess_blend(self):
        # Mixed windows: +10% / 0% / -10% ->
        # 0.2*10 + 0.5*0 + 0.3*(-10) = -1.0 pp -> 5 points
        spy = [100.0] * 130
        sector = [100.0] * 130
        sector[-1] = 110.0      # +10% over 21 sessions (vs 100.0)
        sector[-64] = 110.0     # 0% over 63 sessions
        sector[-127] = 110.0 / 0.9  # -10% over 126 sessions
        wx = features.sector_weighted_excess(sector, spy, 21, 63, 126)
        assert abs(wx - (-1.0)) < 1e-9
        assert scoring.score_sector_rs(wx) == 5

    def test_blend_market_sector(self):
        # 60/40 blend
        assert scoring.blend_market_sector_rs(25, 15) == 0.6 * 25 + 0.4 * 15
        # Sector unavailable -> full market weight
        assert scoring.blend_market_sector_rs(25, None) == 25.0

    def test_clamp(self):
        assert scoring.clamp_score(150.0) == 100.0
        assert scoring.clamp_score(-10.0) == 0.0
        assert scoring.clamp_score(75.5) == 75.5

    def test_score_incumbent_composed(self):
        # Full ranker with sector RS present: hand arithmetic, no clamp.
        # trend(neutral->5) + rs blend: market outperformer(15),
        #   sector +6.0->25 => 0.6*15 + 0.4*25 = 19.0
        # pullback(-5->25) + sma(-2->10) + vol(0.5->15) + iv(20->3)
        #   + iv_pc(0) = 77 -> transitional -3 -> 74.0
        score = scoring.score_incumbent(
            trend_state="neutral",
            rs_state="outperformer",
            sector_weighted_excess=6.0,
            pullback_depth=-5.0,
            dist_sma20=-2.0,
            volume_ratio=0.5,
            iv_rank=20.0,
            put_call_ratio=1.5,
            regime_label="transitional",
            market_breadth=None,
            spy_rsi=None,
        )
        assert score == 74.0

    def test_score_incumbent_sector_unavailable(self):
        # Same inputs, sector RS unavailable -> market RS at full weight.
        # rs component 15 (not 19): raw 73 -> transitional -3 -> 70.0
        score = scoring.score_incumbent(
            trend_state="neutral",
            rs_state="outperformer",
            sector_weighted_excess=None,
            pullback_depth=-5.0,
            dist_sma20=-2.0,
            volume_ratio=0.5,
            iv_rank=20.0,
            put_call_ratio=1.5,
            regime_label="transitional",
            market_breadth=None,
            spy_rsi=None,
        )
        assert score == 70.0

    def test_every_band_exercised(self):
        # Band-coverage table: each scoring band from incumbent_v1.yaml
        # (plus D-026 sector bands) is hit at least once.
        s = scoring
        assert s.score_trend_state("strong_uptrend") == 30
        assert s.score_trend_state("uptrend") == 20
        assert s.score_trend_state("neutral") == 5
        assert s.score_relative_strength_state("strong_outperformer") == 25
        assert s.score_relative_strength_state("outperformer") == 15
        assert s.score_sector_rs(5.0) == 25
        assert s.score_sector_rs(0.0) == 15
        assert s.score_sector_rs(-5.0) == 5
        assert s.score_sector_rs(-5.01) == 0
        assert s.score_pullback_depth(-5.0) == 25
        assert s.score_pullback_depth(-10.0) == 10
        assert s.score_pullback_depth(-15.0) == 0
        assert s.score_dist_to_sma20(-3.0) == 10
        assert s.score_dist_to_sma20(-8.0) == 0
        assert s.score_volume_ratio(0.5) == 15
        assert s.score_volume_ratio(2.0) == 0
        assert s.score_iv_rank(20.0) == 3
        assert s.score_iv_rank(80.0) == 0
        assert s.score_iv_put_call(80.0, 1.5) == -3
        assert s.score_iv_put_call(20.0, 1.5) == 0

    def test_score_incumbent_fixture_incumbent_v1(self):
        # Fixture reproducing the YAML-specified scoring bands end to end
        # (SCOPE §5 Step 4 done-means for the ranker). Sector-RS bands are
        # D-026 (post-tag CEO decision), not legacy outputs; trend/uptrend
        # band exercised here, full band coverage in test_every_band_exercised.
        # trend(uptrend->20) + rs blend: market outperformer(15),
        #   sector +2.0->15 => 0.6*15 + 0.4*15 = 15.0
        # pullback(-5.5->25) + sma(-3->10) + vol(0.4->15) + iv(80->0)
        #   + iv_pc(80, 1.5 -> -3) = 82
        # calm_uptrend/healthy +5, spy_rsi 50 (no rsi adjustment) -> 87.0
        score = scoring.score_incumbent(
            trend_state="uptrend",
            rs_state="outperformer",
            sector_weighted_excess=2.0,
            pullback_depth=-5.5,
            dist_sma20=-3.0,
            volume_ratio=0.4,
            iv_rank=80.0,
            put_call_ratio=1.5,
            regime_label="calm_uptrend",
            market_breadth="healthy",
            spy_rsi=50.0,
        )
        assert score == 87.0

    def test_score_incumbent_bearish(self):
        # trend(5) + rs(15, sector unavailable) + pullback(-15->0)
        #   + sma(-8->0) + vol(2.0->0) + iv(80->0)
        #   + iv_pc(80,1.5->-3) = 17 -> volatile_downtrend -10 -> 7
        score = scoring.score_incumbent(
            trend_state="neutral",
            rs_state="outperformer",
            sector_weighted_excess=None,
            pullback_depth=-15.0,
            dist_sma20=-8.0,
            volume_ratio=2.0,
            iv_rank=80.0,
            put_call_ratio=1.5,
            regime_label="volatile_downtrend",
            market_breadth=None,
            spy_rsi=None,
        )
        assert score == 7.0

    def test_boundary_values_d028(self):
        # D-028: legacy operators from Sprint F doc §1.4 (line-cited to
        # src/ranking/ranker.py). -1.0 is inside [-5,-1] -> 10; 0.8 fails
        # the strict "< 0.8" -> 0; 25.0 fails the strict "< 25" -> 0.
        assert scoring.score_dist_to_sma20(-1.0) == 10
        assert scoring.score_volume_ratio(0.8) == 0
        assert scoring.score_iv_rank(25.0) == 0
        # Just inside the strict bounds still scores.
        assert scoring.score_volume_ratio(0.7999) == 15
        assert scoring.score_iv_rank(24.9999) == 3


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
            50.0, "transitional", None, spy_rsi_14=80.0) == 44.0

    def test_spy_rsi_oversold(self):
        assert scoring.apply_regime_adjustments(
            50.0, "transitional", None, spy_rsi_14=25.0) == 50.0

    def test_regime_unknown_raises(self):
        with pytest.raises(ValueError, match="unknown regime_label"):
            scoring.apply_regime_adjustments(50.0, "calm_uptrnd")  # typo
        with pytest.raises(ValueError, match="unknown breadth"):
            scoring.apply_regime_adjustments(
                50.0, "calm_uptrend", "helthy")  # typo

    def test_clamp_adjustment(self):
        # volatile_downtrend (-10) + overbought (-3) = -13 -> clamped to -10
        assert scoring.apply_regime_adjustments(
            50.0, "volatile_downtrend", None,
            spy_rsi_14=80.0) == 40.0


class TestFeatures:
    def test_volume_ratio_degenerate_raises(self):
        # Zero average volume: fail-closed, not 0.0 (which scores +15)
        with pytest.raises(ValueError, match="zero average volume"):
            features.volume_ratio([0.0] * 20)

    def test_pullback_depth_degenerate_raises(self):
        with pytest.raises(ValueError, match="zero recent high"):
            features.pullback_depth_pct([0.0] * 60)
        # Shorter than the lookback: fail-closed, no truncated window
        with pytest.raises(ValueError, match="need 60 closes"):
            features.pullback_depth_pct([100.0, 95.0])

    def test_dist_to_sma20_degenerate_raises(self):
        with pytest.raises(ValueError, match="zero SMA20"):
            features.dist_to_sma20_pct([0.0] * 25)
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

    def test_rsi_14_41bar_known_answer(self):
        # 41 closes (seeded pseudo-random walk). Expected value computed
        # with an independent textbook scalar-loop Wilder implementation
        # (not _wilder_smooth): 64.0515615476533. Guards the recursion
        # beyond the 15-bar minimum.
        closes = [100.0, 100.557707, 98.65775, 97.757867, 96.65071,
                  97.596595, 98.303393, 99.872112, 98.219867, 97.907554,
                  96.026743, 94.901295, 94.922716, 93.02886, 91.824211,
                  92.423748, 92.603514, 91.485277, 91.842339, 93.080061,
                  91.106056, 92.329333, 93.121891, 92.482893, 91.104811,
                  92.933663, 92.280041, 90.651025, 89.03789, 90.427868,
                  90.842772, 92.071285, 92.990212, 93.135124, 95.027588,
                  94.541725, 94.749888, 96.067506, 96.541585, 97.988413,
                  98.297821]
        assert abs(features.rsi_14(closes) - 64.0515615476533) < 1e-9

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
        # 60 closes, high 110.0, last 104.5 -> 5% pullback
        closes = [100.0] * 58 + [110.0, 104.5]
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

    def test_d027_session_pins(self):
        # D-027 (CEO 2026-10-05): pinned session counts, trading sessions.
        assert features.PULLBACK_LOOKBACK_SESSIONS == 60
        assert features.SECTOR_RS_SESSIONS_1M == 21
        assert features.SECTOR_RS_SESSIONS_3M == 63
        assert features.SECTOR_RS_SESSIONS_6M == 126

    def test_sector_weighted_excess_default_sessions(self):
        # Defaults are the D-027 pins: omitting them matches explicit args.
        spy = [100.0] * 130
        sector = [100.0] * 130
        sector[-1] = 120.0
        assert (features.sector_weighted_excess(sector, spy)
                == features.sector_weighted_excess(sector, spy, 21, 63, 126))

    def test_sector_weighted_excess_bad_sessions_raise(self):
        spy = [100.0] * 130
        sector = [100.0] * 130
        # Zero sessions would silently return 0.0 (scores 15, not 25).
        with pytest.raises(ValueError, match="0 < s1m"):
            features.sector_weighted_excess(sector, spy, 0, 0, 0)
        # Negative sessions would wrap around the series.
        with pytest.raises(ValueError, match="0 < s1m"):
            features.sector_weighted_excess(sector, spy, -1, 63, 126)
        # Non-ascending windows are misaligned by construction.
        with pytest.raises(ValueError, match="0 < s1m"):
            features.sector_weighted_excess(sector, spy, 63, 21, 126)

    def test_sector_weighted_excess_mismatched_lengths_raise(self):
        # Series ending on different dates silently bias the excess.
        spy = [100.0] * 130
        sector = [100.0] * 129
        with pytest.raises(ValueError, match="equal length"):
            features.sector_weighted_excess(sector, spy)


class TestMembership:
    """S05 T7: point-in-time membership from universe snapshots."""

    def _write_snapshot(self, tmp_path, as_of, symbols):
        universe_dir = tmp_path / "universe"
        universe_dir.mkdir(exist_ok=True)
        (universe_dir / f"{as_of}.csv").write_text(
            "symbol\n" + "\n".join(symbols) + "\n", encoding="utf-8")

    def test_membership_differs_by_date(self, tmp_path):
        # T7 acceptance: membership on 2024-01-02 differs from 2026-10-04
        from arcis.strategy import membership
        root = str(tmp_path)
        self._write_snapshot(tmp_path, "2024-01-02", ["AAPL", "MSFT"])
        self._write_snapshot(tmp_path, "2026-10-04",
                             ["AAPL", "MSFT", "NVDA"])
        old = membership.load_membership(root, "2024-01-02")
        new = membership.load_membership(root, "2026-10-04")
        assert old != new
        assert "NVDA" not in old
        assert "NVDA" in new

    def test_is_member(self, tmp_path):
        from arcis.strategy import membership
        root = str(tmp_path)
        self._write_snapshot(tmp_path, "2024-01-02", ["AAPL"])
        assert membership.is_member("AAPL", root, "2024-01-02")
        assert not membership.is_member("NVDA", root, "2024-01-02")

    def test_missing_snapshot_raises(self, tmp_path):
        from arcis.recorder.errors import UniverseError
        from arcis.strategy import membership
        with pytest.raises(UniverseError, match="not found"):
            membership.load_membership(str(tmp_path), "2024-01-02")

    def test_duplicate_symbols_rejected(self, tmp_path):
        # The S01 reader rejects duplicates; membership must not silently
        # dedupe them either.
        from arcis.recorder.errors import UniverseError
        from arcis.strategy import membership
        universe_dir = tmp_path / "universe"
        universe_dir.mkdir(exist_ok=True)
        (universe_dir / "2024-01-02.csv").write_text(
            "symbol\nAAPL\nMSFT\nAAPL\n", encoding="utf-8")
        with pytest.raises(UniverseError, match="duplicate"):
            membership.load_membership(str(tmp_path), "2024-01-02")
