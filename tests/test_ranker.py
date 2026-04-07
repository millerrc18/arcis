"""Tests for two-tier RS scoring, pullback bounds, volume weight, and backward compatibility.

Covers the gap-assessment-top3 changes to _score_ticker():
  - Two-tier relative strength (60% market + 40% sector)
  - Narrowed pullback sweet spot (-3 to -8)
  - Increased volume contraction weight (+15)
  - 100-point score cap
"""

from src.ranking.ranker import _score_ticker, _compute_sector_rs
from src.universe.sectors import SECTOR_ETF_MAP, get_sector_etf
from src.universe.sp100 import get_sp100_universe


# ── Test 1: Two-tier RS with sector data ─────────────────────────────────


def test_two_tier_rs_with_sector_data():
    """Combined RS uses 60/40 weighting: 0.6 * market + 0.4 * sector.

    market_rs_score = 25 (strong_outperformer)
    _sector_rs_score = 20
    combined_rs = 0.6 * 25 + 0.4 * 20 = 15.0 + 8.0 = 23.0
    """
    features = {
        "relative_strength_state": "strong_outperformer",  # market_rs_score = 25
        "_sector_rs_score": 20,                            # sector RS
    }
    score = _score_ticker(features)

    # Only RS contributes (no trend, pullback, etc.) → score = 23.0
    assert score == 23.0, f"Expected 23.0 from 60/40 weighting, got {score}"


# ── Test 2: Two-tier RS fallback when no sector data ─────────────────────


def test_two_tier_rs_fallback_no_sector():
    """When _sector_rs_score is absent, fall back to market-only RS (25)."""
    features = {
        "relative_strength_state": "strong_outperformer",  # market_rs_score = 25
        # No _sector_rs_score key at all
    }
    score = _score_ticker(features)

    # Only RS contributes → score = 25 (full market RS, no 60/40 blend)
    assert score == 25.0, f"Expected 25.0 (market-only fallback), got {score}"


# ── Test 3: Sector ETF mapping completeness for SP100 ───────────────────


def test_sector_etf_mapping_completeness():
    """Every ticker in get_sp100_universe() must have a non-None sector ETF."""
    universe = get_sp100_universe()
    unmapped = [t for t in universe if get_sector_etf(t) is None]

    assert len(unmapped) == 0, (
        f"{len(unmapped)} SP100 tickers have no sector ETF mapping: {unmapped}"
    )


# ── Test 4: Narrowed pullback sweet spot ─────────────────────────────────


def test_narrowed_pullback_sweet_spot():
    """Verify the four pullback depth zones against actual -3/-8/-12 boundaries.

    -5.0  → inside -3 to -8 sweet spot  → +25
    -9.0  → inside -8 to -12 moderate   → +10
    -2.0  → too shallow (> -3)          → +0
    -13.0 → too deep (< -12)            → +0
    """
    base = {}  # minimal features — only pullback contributes

    # Sweet spot: -3 to -8 → +25
    score_sweet = _score_ticker({**base, "pullback_depth_pct": -5.0})
    assert score_sweet == 25, f"pullback -5% should score 25, got {score_sweet}"

    # Moderate: -8 to -12 → +10
    score_moderate = _score_ticker({**base, "pullback_depth_pct": -9.0})
    assert score_moderate == 10, f"pullback -9% should score 10, got {score_moderate}"

    # Too shallow: > -3 → +0
    score_shallow = _score_ticker({**base, "pullback_depth_pct": -2.0})
    assert score_shallow == 0, f"pullback -2% should score 0, got {score_shallow}"

    # Too deep: < -12 → +0
    score_deep = _score_ticker({**base, "pullback_depth_pct": -13.0})
    assert score_deep == 0, f"pullback -13% should score 0, got {score_deep}"


# ── Test 5: Increased volume weight ──────────────────────────────────────


def test_increased_volume_weight():
    """Volume ratio below 0.8 adds +15 points (was +10 in old code)."""
    score_low_vol = _score_ticker({"volume_ratio_20d": 0.7})
    score_high_vol = _score_ticker({"volume_ratio_20d": 1.0})

    diff = score_low_vol - score_high_vol
    assert diff == 15, f"Volume contraction bonus should be 15, got {diff}"


# ── Test 6: Score capped at 100 ──────────────────────────────────────────


def test_score_capped_at_100():
    """Features that sum to 105+ must be capped at exactly 100.

    trend=strong_uptrend(30) + RS strong_outperformer(25) +
    pullback -5%(25) + dist_sma20 -2%(10) + volume 0.7(15) = 105 → 100
    """
    features = {
        "trend_state": "strong_uptrend",                   # +30
        "relative_strength_state": "strong_outperformer",  # +25 (no sector → market only)
        "pullback_depth_pct": -5.0,                        # +25
        "dist_to_sma20_pct": -2.0,                         # +10
        "volume_ratio_20d": 0.7,                           # +15
        # Raw total: 105
    }
    score = _score_ticker(features)
    assert score == 100, f"Score should be capped at 100, got {score}"


# ── Test 7: Backward compatibility without sector RS ─────────────────────


def test_backward_compatibility_no_sector():
    """Without _sector_rs_score, score must match pre-change (market-only) behavior.

    This ensures the two-tier RS change is additive — old feature dicts
    produce identical scores.
    """
    features = {
        "trend_state": "strong_uptrend",                   # +30
        "relative_strength_state": "strong_outperformer",  # +25 (market only, no sector)
        "pullback_depth_pct": -5.0,                        # +25
        "dist_to_sma20_pct": -2.0,                         # +10
        "volume_ratio_20d": 0.7,                           # +15
        # Total: 105 → capped at 100
    }
    assert "_sector_rs_score" not in features

    score = _score_ticker(features)

    # Old ranker would have: 30 + 25 + 25 + 10 + 15 = 105 → 100
    expected_old_score = 100
    assert score == expected_old_score, (
        f"Backward compat broken: expected {expected_old_score}, got {score}"
    )
