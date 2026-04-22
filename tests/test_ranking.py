"""Tests for deterministic ranking and qualification."""

from unittest.mock import patch

from src.platform.strategy_spec import StrategySpec
from src.ranking.ranker import _score_ticker, _compute_sector_rs, rank_universe, get_top_candidates


# Mock config that disables bootcamp so tests use default thresholds
_TEST_CONFIG = {
    "ranking": {
        "packet_worthy_threshold": 70,
        "watchlist_threshold": 45,
    },
    "bootcamp": {"enabled": False},
}


def _mock_load_config():
    return _TEST_CONFIG


def _make_strong_features() -> dict:
    """Features that should clearly score as packet_worthy (70+).

    Without sector RS: 30+25+25+10+15 = 105 → capped at 100.
    """
    return {
        "trend_state": "strong_uptrend",       # +30
        "relative_strength_state": "strong_outperformer",  # +25
        "pullback_depth_pct": -5.0,            # +25 (sweet spot -3 to -8)
        "dist_to_sma20_pct": -2.0,             # +10
        "volume_ratio_20d": 0.7,               # +15
        # Total: 105 → capped at 100
        "current_price": 150.0,
        "sma_50": 148.0,
        "sma_200": 140.0,
    }


def _make_weak_features() -> dict:
    """Features that should score as not_interesting (<45)."""
    return {
        "trend_state": "downtrend",             # +0
        "relative_strength_state": "underperformer",  # +0
        "pullback_depth_pct": -20.0,            # +0 (too deep)
        "dist_to_sma20_pct": -8.0,             # +0
        "volume_ratio_20d": 1.5,               # +0
        # Total: 0
        "current_price": 80.0,
        "sma_50": 90.0,
        "sma_200": 100.0,
    }


def _make_watchlist_features() -> dict:
    """Features that should score as watchlist (45-69)."""
    return {
        "trend_state": "uptrend",               # +20
        "relative_strength_state": "outperformer",  # +15
        "pullback_depth_pct": -10.0,            # +10 (-12 to -8 range)
        "dist_to_sma20_pct": -3.0,             # +10
        "volume_ratio_20d": 1.0,               # +0 (not < 0.8)
        # Total: 55
        "current_price": 120.0,
        "sma_50": 118.0,
        "sma_200": 110.0,
    }


def _make_strategy(**overrides) -> StrategySpec:
    base = {
        "strategy_id": "ranker_test",
        "display_name": "Ranker Test",
        "universe": {"tickers": ["AAPL"]},
        "entry": {"kind": "scheduled"},
        "exit": {"kind": "python_plugin"},
        "position_sizing": {"method": "fixed_pct_equity", "pct": 0.1},
        "attribution": {"benchmark": "SPY_matched_window", "metrics": ["sharpe"]},
        "raw": {},
        "source": "test",
    }
    base.update(overrides)
    return StrategySpec(**base)


@patch("src.ranking.ranker.load_config", _mock_load_config)
def test_packet_worthy_score():
    features = {"STRONG": _make_strong_features()}
    ranked = rank_universe(features)
    assert len(ranked) == 1
    assert ranked[0]["qualification"] == "packet_worthy"
    assert ranked[0]["score"] >= 70


@patch("src.ranking.ranker.load_config", _mock_load_config)
def test_not_interesting_score():
    features = {"WEAK": _make_weak_features()}
    ranked = rank_universe(features)
    assert len(ranked) == 1
    assert ranked[0]["qualification"] == "not_interesting"
    assert ranked[0]["score"] < 45


@patch("src.ranking.ranker.load_config", _mock_load_config)
def test_watchlist_score():
    features = {"MID": _make_watchlist_features()}
    ranked = rank_universe(features)
    assert len(ranked) == 1
    assert ranked[0]["qualification"] == "watchlist"


@patch("src.ranking.ranker.load_config", _mock_load_config)
def test_deterministic():
    features = {
        "A": _make_strong_features(),
        "B": _make_weak_features(),
        "C": _make_watchlist_features(),
    }
    ranked_1 = rank_universe(features)
    ranked_2 = rank_universe(features)
    assert [r["score"] for r in ranked_1] == [r["score"] for r in ranked_2]
    assert [r["ticker"] for r in ranked_1] == [r["ticker"] for r in ranked_2]


@patch("src.ranking.ranker.load_config", _mock_load_config)
def test_sorted_by_score_descending():
    features = {
        "A": _make_strong_features(),
        "B": _make_weak_features(),
        "C": _make_watchlist_features(),
    }
    ranked = rank_universe(features)
    scores = [r["score"] for r in ranked]
    assert scores == sorted(scores, reverse=True)


@patch("src.ranking.ranker.load_config", _mock_load_config)
def test_get_top_candidates_limits():
    features = {}
    for i in range(10):
        f = _make_strong_features()
        features[f"STRONG_{i}"] = f
    for i in range(10):
        f = _make_watchlist_features()
        features[f"WATCH_{i}"] = f

    ranked = rank_universe(features)
    top = get_top_candidates(ranked, max_packets=3, max_watchlist=5)
    assert len(top["packet_worthy"]) <= 3
    assert len(top["watchlist"]) <= 5


@patch("src.ranking.ranker.load_config", _mock_load_config)
def test_strategy_bootcamp_thresholds_override_config():
    strategy = _make_strategy(
        raw={"bootcamp": {"qualification_threshold": 50, "watchlist_threshold": 20}}
    )
    features = {"MID": _make_watchlist_features()}
    ranked = rank_universe(features, strategy=strategy)
    assert ranked[0]["qualification"] == "packet_worthy"


@patch("src.ranking.ranker.load_config", _mock_load_config)
@patch("src.features.regime.classify_regime", return_value="CRISIS")
def test_strategy_regime_disable_blocks_candidates(mock_regime):
    strategy = _make_strategy(
        position_sizing={
            "method": "regime_adaptive",
            "regimes": {
                "CRISIS": {"packet_worthy": False, "position_pct": 0.0},
            },
        }
    )
    ranked = rank_universe({"STRONG": _make_strong_features()}, strategy=strategy)
    assert ranked[0]["qualification"] == "not_interesting"


# ── Two-tier RS + enhanced ranker tests ─────────────────────────────────


def test_two_tier_rs_with_sector_data():
    """Verify combined RS scoring when sector data is available."""
    features = {
        "relative_strength_state": "strong_outperformer",  # market_rs_score = 25
    }
    # Sector data showing strong outperformance (excess > 5%)
    sector_data = {"return_1m": 2.0, "return_3m": 5.0, "return_6m": 8.0}
    features["return_1m"] = 10.0
    features["return_3m"] = 15.0
    features["return_6m"] = 20.0

    sector_score = _compute_sector_rs(features, sector_data)
    assert sector_score is not None
    assert sector_score == 25  # Strong outperformer vs sector

    # Verify combined in _score_ticker
    features["_sector_rs_score"] = sector_score
    features["trend_state"] = "strong_uptrend"
    features["pullback_depth_pct"] = -5.0
    features["dist_to_sma20_pct"] = -2.0
    features["volume_ratio_20d"] = 0.7
    score = _score_ticker(features)
    # 30 + (0.6*25 + 0.4*25) + 25 + 10 + 15 = 30 + 25 + 25 + 10 + 15 = 105 → 100
    assert score == 100


def test_two_tier_rs_fallback_no_sector():
    """Verify fallback to market-only RS when sector data is None."""
    features = {
        "relative_strength_state": "strong_outperformer",
        "trend_state": "strong_uptrend",
        "pullback_depth_pct": -5.0,
        "dist_to_sma20_pct": -2.0,
        "volume_ratio_20d": 0.7,
    }
    # No _sector_rs_score → full market RS used
    score = _score_ticker(features)
    # 30 + 25 (market only) + 25 + 10 + 15 = 105 → capped at 100
    assert score == 100

    sector_score = _compute_sector_rs(features, None)
    assert sector_score is None


def test_sector_etf_mapping_completeness():
    """Verify all tickers in SECTOR_MAP have a matching SECTOR_ETF_MAP entry."""
    from src.universe.sectors import SECTOR_MAP, SECTOR_ETF_MAP, get_sector_etf

    unmapped_sectors = set()
    for ticker, sector in SECTOR_MAP.items():
        etf = get_sector_etf(ticker)
        if etf is None:
            unmapped_sectors.add(sector)

    # All sectors used in SECTOR_MAP must have an ETF in SECTOR_ETF_MAP
    assert len(unmapped_sectors) == 0, f"Sectors without ETF mapping: {unmapped_sectors}"

    # Verify all 11 sector ETFs are present
    assert len(SECTOR_ETF_MAP) == 11


def test_narrowed_pullback_sweet_spot():
    """Verify -8% boundary (was -10%)."""
    # -8% should get +25 (inside sweet spot)
    features_in = {"pullback_depth_pct": -8.0}
    score_in = _score_ticker(features_in)

    # -9% should get +10 (outside sweet spot, in moderate range)
    features_out = {"pullback_depth_pct": -9.0}
    score_out = _score_ticker(features_out)

    # -5% is in sweet spot
    features_sweet = {"pullback_depth_pct": -5.0}
    score_sweet = _score_ticker(features_sweet)

    assert score_in > score_out  # -8% scores higher than -9%
    assert score_sweet == score_in  # Both in sweet spot


def test_increased_volume_weight():
    """Verify volume contraction weight is now +15 (was +10)."""
    features_low_vol = {"volume_ratio_20d": 0.7}
    features_high_vol = {"volume_ratio_20d": 1.0}

    score_low = _score_ticker(features_low_vol)
    score_high = _score_ticker(features_high_vol)

    assert score_low - score_high == 15  # +15 for vol < 0.8


def test_score_capped_at_100():
    """Verify max(0, min(100, score)) still enforced."""
    # Max everything — should cap at 100
    features = _make_strong_features()
    score = _score_ticker(features)
    assert score <= 100

    # All negatives — should floor at 0
    features_neg = {
        "trend_state": "downtrend",
        "relative_strength_state": "underperformer",
        "pullback_depth_pct": -30.0,
        "volume_ratio_20d": 2.0,
        "regime_label": "volatile_downtrend",
        "spy_rsi_14": 80,
    }
    score_neg = _score_ticker(features_neg)
    assert score_neg >= 0


def test_backward_compatibility_no_sector():
    """When sector data is None, scores match old behavior exactly."""
    features = {
        "trend_state": "strong_uptrend",           # +30
        "relative_strength_state": "strong_outperformer",  # +25 (market only)
        "pullback_depth_pct": -5.0,                # +25
        "dist_to_sma20_pct": -2.0,                # +10
        "volume_ratio_20d": 0.7,                   # +15
    }
    score = _score_ticker(features)
    # 30 + 25 + 25 + 10 + 15 = 105 → capped at 100
    assert score == 100
