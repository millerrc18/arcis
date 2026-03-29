"""Tests for deterministic ranking and qualification."""

from unittest.mock import patch

from src.ranking.ranker import rank_universe, get_top_candidates


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
    """Features that should clearly score as packet_worthy (70+)."""
    return {
        "trend_state": "strong_uptrend",       # +30
        "relative_strength_state": "strong_outperformer",  # +25
        "pullback_depth_pct": -5.0,            # +25 (sweet spot)
        "dist_to_sma20_pct": -2.0,             # +10
        "volume_ratio_20d": 0.7,               # +10
        # Total: 100
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
        "pullback_depth_pct": -12.0,            # +10 (moderate pullback)
        "dist_to_sma20_pct": -3.0,             # +10
        "volume_ratio_20d": 1.0,               # +0
        # Total: 55
        "current_price": 120.0,
        "sma_50": 118.0,
        "sma_200": 110.0,
    }


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
