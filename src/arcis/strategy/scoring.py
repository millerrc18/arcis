"""Incumbent pullback ranker — scoring bands.

Clean-room reimplementation from config/incumbent_v1.yaml.
No legacy code was read or ported.

Scoring: each metric maps to a score via first-match-wins bands.
Final score is clamped to [0, 100].

Fail-closed: unknown category labels raise ValueError. Degenerate
inputs raise ValueError. Band boundary operators follow the recovered
Sprint F legacy operators per SCOPE D-028.
"""

from __future__ import annotations

import math

# Scoring labels from incumbent_v1.yaml + classifiers_v1.yaml (D-031).
# D-031 recovered the full 5+5 vocabularies from the legacy archive.
# Unlisted labels score 0 (matching legacy ranker.py:491-501), not fail-closed.
# Truly unknown labels (not in the 5+5) still raise ValueError.
TREND_STATES = {"strong_uptrend", "uptrend", "neutral",
                "downtrend", "strong_downtrend"}
RS_STATES = {"strong_outperformer", "outperformer", "neutral",
             "underperformer", "strong_underperformer"}
REGIME_LABELS = {"calm_uptrend", "transitional", "calm_downtrend",
                 "volatile_downtrend", "volatile_uptrend"}
BREADTH_LABELS = {"healthy", "narrowing"}


def score_trend_state(trend_state: str) -> int:
    """Score the trend state category.

    Bands (incumbent_v1.yaml + classifiers_v1.yaml D-031):
      strong_uptrend -> 30
      uptrend        -> 20
      neutral        -> 5
      downtrend      -> 0
      strong_downtrend -> 0

    Raises ValueError for labels outside the 5-label vocabulary.
    """
    if trend_state not in TREND_STATES:
        raise ValueError(f"unknown trend_state: {trend_state!r} "
                         f"(expected one of {sorted(TREND_STATES)})")
    bands = {
        "strong_uptrend": 30,
        "uptrend": 20,
        "neutral": 5,
        "downtrend": 0,
        "strong_downtrend": 0,
    }
    return bands[trend_state]


def score_relative_strength_state(rs_state: str) -> int:
    """Score the relative strength state category.

    Bands (D-031):
      strong_outperformer  -> 25
      outperformer         -> 15
      neutral              -> 0
      underperformer       -> 0
      strong_underperformer -> 0

    Raises ValueError for labels outside the 5-label vocabulary.
    """
    if rs_state not in RS_STATES:
        raise ValueError(f"unknown rs_state: {rs_state!r} "
                         f"(expected one of {sorted(RS_STATES)})")
    bands = {
        "strong_outperformer": 25,
        "outperformer": 15,
        "neutral": 0,
        "underperformer": 0,
        "strong_underperformer": 0,
    }
    return bands[rs_state]


def score_pullback_depth(pullback_depth_pct: float) -> int:
    """Score pullback depth (negative % from recent high).

    Bands (order-sensitive, first match wins):
      [-8, -3]    -> 25  (D-028: closed upper bound per Sprint F doc §1.4,
                          "pullback sweet spot [-8, -3] -> +25")
      [-12, -8)   -> 10  (upper bound exclusive per YAML note)

    Boundary -8.0 hits the first band via first-match-wins.
    """
    if -8 <= pullback_depth_pct <= -3:
        return 25
    if -12 <= pullback_depth_pct < -8:
        return 10
    return 0


def score_dist_to_sma20(dist_pct: float) -> int:
    """Score distance to SMA20 (negative % = below SMA).

    Bands:
      [-5, -1] -> 10
      (other)  -> 0

    Bands:
      [-5, -1] -> 10  (D-028: closed bounds per Sprint F doc §1.4,
                       "in [-5, -1]")
      (other)  -> 0
    """
    if -5 <= dist_pct <= -1:
        return 10
    return 0


def score_volume_ratio(volume_ratio_20d: float) -> int:
    """Score 20-day volume ratio.

    Bands:
      (-inf, 0.8) -> 15  (D-028: strict < 0.8 per Sprint F doc §1.4)
      (other)     -> 0
    """
    if volume_ratio_20d < 0.8:
        return 15
    return 0


def score_iv_rank(iv_rank: float) -> int:
    """Score IV rank (0-100).

    Bands:
      (-inf, 25) -> 3  (D-028: strict < 25 per Sprint F doc §1.4)
      (other)    -> 0
    """
    if iv_rank < 25:
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


# Set A absolute thresholds (D-026, CEO decision 2026-10-05), in percentage
# points of weighted_excess vs SPY. Calibrated on the 2016-2024 empirical
# distribution (P10 -7.39 / P25 -3.98 / P50 -0.58 / P75 +2.60 / P90 +5.91,
# n=1,123 sector-months; validation in arcis-data/sector_rs/): +5pp sits at
# ~P88 and -5pp at ~P19, so the bands split tail/middle sensibly. Rank-based
# banding was considered and rejected: it discards magnitude, so "25 points"
# would mean something different every month. incumbent_v1.yaml pins only
# the band values [25, 15, 5, 0], never the mapping rule, so this is an
# implementation decision under the CEO-judgment mandate, not a prereg change.
_SECTOR_RS_BANDS = ((5.0, 25), (0.0, 15), (-5.0, 5))


def score_sector_rs(weighted_excess: float) -> int:
    """Score sector relative strength from weighted excess return.

    Set A bands (D-026):
      weighted_excess >= +5  -> 25
      0 <= weighted_excess < +5 -> 15
      -5 <= weighted_excess < 0 -> 5
      weighted_excess < -5 -> 0

    Formula: weighted_excess = 0.20 * excess_1m + 0.50 * excess_3m
                              + 0.30 * excess_6m  (percentage points vs SPY)

    Raises:
      ValueError: on NaN or non-finite input (fail-closed; unavailable
        sector RS is represented as None at the blend step, never as NaN
        here).
    """
    if not math.isfinite(weighted_excess):
        raise ValueError(
            f"score_sector_rs: weighted_excess must be finite, got "
            f"{weighted_excess}")
    for cutoff, points in _SECTOR_RS_BANDS:
        if weighted_excess >= cutoff:
            return points
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

    Raises ValueError for unknown regime or breadth labels (fail-closed).
    """
    if regime_label not in REGIME_LABELS:
        raise ValueError(f"unknown regime_label: {regime_label!r} "
                         f"(expected one of {sorted(REGIME_LABELS)})")
    if (market_breadth_label is not None
            and market_breadth_label not in BREADTH_LABELS):
        raise ValueError(f"unknown breadth: {market_breadth_label!r} "
                         f"(expected one of {sorted(BREADTH_LABELS)})")

    adjustment = 0.0

    if regime_label == "calm_uptrend":
        if market_breadth_label == "healthy":
            adjustment += 5
        elif market_breadth_label == "narrowing":
            adjustment += 2
        # breadth None -> +0 (no adjustment without breadth info)
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


def score_incumbent(
    trend_state: str,
    rs_state: str,
    sector_weighted_excess: float | None,
    pullback_depth: float,
    dist_sma20: float,
    volume_ratio: float,
    iv_rank: float,
    put_call_ratio: float,
    regime_label: str,
    market_breadth: str | None,
    spy_rsi: float | None,
) -> float:
    """Compose the full incumbent score from all bands.

    Sums: trend + RS (60/40 market/sector blend) + pullback + SMA distance
          + volume + IV rank + put/call interaction, then applies regime
          adjustments, then clamps to [0, 100].

    This is the "ranker reproduces incumbent_v1 on fixtures" entry point
    for SCOPE §5 Step 4.

    sector_weighted_excess: the sector's weighted excess return vs SPY in
      percentage points (scored with Set A bands, D-026). When None, sector
      RS is unavailable and market RS receives full effective weight, per
      the YAML fallback (config/incumbent_v1.yaml `_sector_rs_score` note).

    market_breadth and spy_rsi are required arguments (no defaults) so the
    caller must pass them explicitly; None means unknown, which yields no
    adjustment for that component per the YAML conditions.

    Raises:
      ValueError: on unknown labels or degenerate inputs (fail-closed).
    """
    total = 0.0
    total += score_trend_state(trend_state)
    market_rs = score_relative_strength_state(rs_state)
    sector_rs = (score_sector_rs(sector_weighted_excess)
                 if sector_weighted_excess is not None else None)
    total += blend_market_sector_rs(market_rs, sector_rs)
    total += score_pullback_depth(pullback_depth)
    total += score_dist_to_sma20(dist_sma20)
    total += score_volume_ratio(volume_ratio)
    total += score_iv_rank(iv_rank)
    total += score_iv_put_call(iv_rank, put_call_ratio)

    total = apply_regime_adjustments(total, regime_label, market_breadth,
                                     spy_rsi)
    return clamp_score(total)
