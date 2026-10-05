"""Incumbent pullback ranker — scoring bands.

Clean-room reimplementation from config/incumbent_v1.yaml.
No legacy code was read or ported.

Scoring: each metric maps to a score via first-match-wins bands.
Final score is clamped to [0, 100].
"""

from __future__ import annotations


def score_trend_state(trend_state: str) -> int:
    """Score the trend state category.

    Bands (incumbent_v1.yaml):
      strong_uptrend -> 30
      uptrend        -> 20
      neutral        -> 5
      (other)        -> 0
    """
    bands = {
        "strong_uptrend": 30,
        "uptrend": 20,
        "neutral": 5,
    }
    return bands.get(trend_state, 0)


def score_relative_strength_state(rs_state: str) -> int:
    """Score the relative strength state category.

    Bands:
      strong_outperformer -> 25
      outperformer        -> 15
      (other)             -> 0
    """
    bands = {
        "strong_outperformer": 25,
        "outperformer": 15,
    }
    return bands.get(rs_state, 0)


def score_pullback_depth(pullback_depth_pct: float) -> int:
    """Score pullback depth (negative % from recent high).

    Bands (order-sensitive, first match wins, exclusive upper bound):
      [-8, -3)   -> 25
      [-12, -8)  -> 10
      (other)    -> 0

    UNRESOLVED: The YAML says "exclusive upper bound" for [-12, -8].
    Interpreted as: -8.0 matches [-8, -3), not [-12, -8). I.e., the
    upper bound of each range is exclusive, lower inclusive.
    """
    if -8 <= pullback_depth_pct < -3:
        return 25
    if -12 <= pullback_depth_pct < -8:
        return 10
    return 0


def score_dist_to_sma20(dist_pct: float) -> int:
    """Score distance to SMA20 (negative % = below SMA).

    Bands:
      [-5, -1] -> 10
      (other)  -> 0

    UNRESOLVED: YAML shows range [-5, -1] without explicit bound notes.
    Interpreted as inclusive on both ends (differs from pullback_depth
    which specifies exclusive upper). If -1.0 should be exclusive,
    this needs correction.
    """
    if -5 <= dist_pct <= -1:
        return 10
    return 0


def score_volume_ratio(volume_ratio_20d: float) -> int:
    """Score 20-day volume ratio.

    Bands:
      (-inf, 0.8] -> 15  (sentinel lower bound: no lower limit)
      (other)     -> 0
    """
    if volume_ratio_20d <= 0.8:
        return 15
    return 0


def score_iv_rank(iv_rank: float) -> int:
    """Score IV rank (0-100).

    Bands:
      (-inf, 25] -> 3  (sentinel lower bound)
      (other)    -> 0
    """
    if iv_rank <= 25:
        return 3
    return 0


def score_iv_put_call(iv_rank: float, put_call_vol_ratio: float) -> int:
    """Score IV rank + put/call volume ratio interaction.

    Conditions:
      iv_rank > 75 AND put_call_vol_ratio > 1.2 -> -3
      (other) -> 0
    """
    if iv_rank > 75 and put_call_vol_ratio > 1.2:
        return -3
    return 0


def score_sector_rs(weighted_excess: float) -> int:
    """Score sector relative strength from weighted excess return.

    Bands: [25, 15, 5, 0] — thresholds UNRESOLVED.
    The YAML gives the formula and band values but not the cutoffs
    that map weighted_excess to bands.

    Formula: weighted_excess = 0.20 * excess_1m + 0.50 * excess_3m
                              + 0.30 * excess_6m

    UNRESOLVED: Band thresholds not specified. This function is a
    placeholder returning 0 until thresholds are determined.
    """
    # TODO: Determine band thresholds from legacy behavior or CEO decision.
    return 0


def blend_market_sector_rs(market_rs_score: int,
                           sector_rs_score: int | None) -> float:
    """Blend market and sector RS scores 60/40.

    When sector RS is unavailable (None), market RS receives full weight.
    """
    if sector_rs_score is None:
        return float(market_rs_score)
    return 0.6 * market_rs_score + 0.4 * sector_rs_score


def apply_regime_adjustments(base_score: float,
                             regime_label: str,
                             market_breadth_label: str | None = None,
                             spy_rsi_14: float | None = None) -> float:
    """Apply cumulative regime adjustments, clamped to [-10, 10].

    Adjustments (incumbent_v1.yaml):
      calm_uptrend + healthy breadth   -> +5
      calm_uptrend + narrowing breadth -> +2
      transitional                     -> -3
      calm_downtrend                   -> -5
      volatile_downtrend               -> -10
      volatile_uptrend                 -> +0 (explicit no-op)
      SPY RSI14 > 75                   -> -3
      SPY RSI14 < 30                   -> +3
    """
    adjustment = 0.0

    if regime_label == "calm_uptrend":
        if market_breadth_label == "healthy":
            adjustment += 5
        elif market_breadth_label == "narrowing":
            adjustment += 2
    elif regime_label == "transitional":
        adjustment += -3
    elif regime_label == "calm_downtrend":
        adjustment += -5
    elif regime_label == "volatile_downtrend":
        adjustment += -10
    # volatile_uptrend: explicit no-op (+0)

    if spy_rsi_14 is not None:
        if spy_rsi_14 > 75:
            adjustment += -3
        elif spy_rsi_14 < 30:
            adjustment += 3

    # Clamp to [-10, 10]
    adjustment = max(-10.0, min(10.0, adjustment))
    return base_score + adjustment


def clamp_score(score: float) -> float:
    """Clamp final score to [0, 100]."""
    return max(0.0, min(100.0, score))
