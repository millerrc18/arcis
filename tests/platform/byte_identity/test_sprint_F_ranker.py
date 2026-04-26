from __future__ import annotations

import copy

import pytest

from src.platform.strategy_spec import load_spec
from src.ranking.ranker import rank_universe

from .helpers import compute_ranked_outputs, stable_hash


def _ranked_records(ranked: list[dict]) -> list[dict]:
    return [
        {
            "ticker": row["ticker"],
            "score": row["score"],
            "qualification": row["qualification"],
            "features_hash": stable_hash(row["features"]),
        }
        for row in ranked
    ]


def _sample_features() -> dict[str, dict]:
    return {
        "AAPL": {
            "trend_state": "strong_uptrend",
            "relative_strength_state": "strong_outperformer",
            "pullback_depth_pct": -5.0,
            "dist_to_sma20_pct": -2.0,
            "volume_ratio_20d": 0.7,
            "regime_label": "calm_uptrend",
            "market_breadth_label": "healthy",
            "spy_rsi_14": 55.0,
            "event_risk_level": "none",
            "current_price": 100.0,
            "sma_50": 95.0,
            "sma_200": 90.0,
        }
    }


def test_primary_fixture_matches_legacy_and_spec(
    primary_fixture_date,
    load_sprint_f_fixture,
    sprint_f_strategy,
):
    fixture = load_sprint_f_fixture("ranker", primary_fixture_date)

    legacy = compute_ranked_outputs(primary_fixture_date)
    spec = compute_ranked_outputs(primary_fixture_date, strategy=sprint_f_strategy)

    expected = fixture["candidates"]
    assert _ranked_records(legacy) == expected
    assert _ranked_records(spec) == expected


@pytest.mark.timeout(180)
def test_fuzz_dates_match_legacy_and_spec(
    all_fixture_dates,
    load_sprint_f_fixture,
    sprint_f_strategy,
):
    for as_of_date in all_fixture_dates:
        fixture = load_sprint_f_fixture("ranker", as_of_date)
        legacy = compute_ranked_outputs(as_of_date)
        spec = compute_ranked_outputs(as_of_date, strategy=sprint_f_strategy)

        expected = fixture["candidates"]
        assert _ranked_records(legacy) == expected
        assert _ranked_records(spec) == expected


def test_synthetic_incumbent_spec_preserves_sector_fallback(sprint_f_strategy):
    features = _sample_features()

    legacy = rank_universe(copy.deepcopy(features))
    spec = rank_universe(copy.deepcopy(features), strategy=sprint_f_strategy)

    assert spec[0]["score"] == legacy[0]["score"]
    assert spec[0]["qualification"] == legacy[0]["qualification"]


def test_missing_ranking_block_falls_back_for_lazy_prices():
    strategy = load_spec("lazy_prices_v1")
    features = _sample_features()

    legacy = rank_universe(copy.deepcopy(features))
    spec = rank_universe(copy.deepcopy(features), strategy=strategy)

    assert spec[0]["score"] == legacy[0]["score"]
    assert spec[0]["qualification"] == legacy[0]["qualification"]


def test_missing_ranking_block_falls_back_for_post_audit_ruleset():
    strategy = load_spec("post_audit_ruleset_v1")
    features = _sample_features()

    legacy = rank_universe(copy.deepcopy(features))
    spec = rank_universe(copy.deepcopy(features), strategy=strategy)

    assert spec[0]["score"] == legacy[0]["score"]
    assert spec[0]["qualification"] == legacy[0]["qualification"]
