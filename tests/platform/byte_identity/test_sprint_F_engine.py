from __future__ import annotations

import copy
from unittest.mock import patch

import pandas as pd

from src.data_enrichment.enricher import enrich_features
from src.features.engine import compute_all_features
from src.features.enrichment import attach_post_scan_features

from .helpers import compute_engine_outputs, stable_hash


def _engine_records(features: dict[str, dict]) -> list[dict]:
    return [
        {"ticker": ticker, "features_hash": stable_hash(features[ticker])}
        for ticker in sorted(features)
    ]


def _make_uptrend_ohlcv(n: int = 250, start_price: float = 100.0) -> pd.DataFrame:
    dates = pd.bdate_range(end=pd.Timestamp("2026-03-20"), periods=n)
    close = pd.Series(range(n), index=dates, dtype=float)
    close = start_price + close * 0.15
    close.iloc[-5:] = [133.5, 133.0, 132.5, 132.9, 133.1]
    high = close * 1.01
    low = close * 0.99
    open_ = close * 1.002
    volume = pd.Series(1_000_000.0, index=dates)
    volume.iloc[-5:] = 700_000.0
    return pd.DataFrame(
        {
            "Open": open_,
            "High": high,
            "Low": low,
            "Close": close,
            "Volume": volume,
        },
        index=dates,
    )


def _make_spy_ohlcv(n: int = 250, start_price: float = 450.0) -> pd.DataFrame:
    dates = pd.bdate_range(end=pd.Timestamp("2026-03-20"), periods=n)
    close = pd.Series(range(n), index=dates, dtype=float)
    close = start_price + close * 0.08
    high = close * 1.005
    low = close * 0.995
    open_ = close * 1.001
    volume = pd.Series(50_000_000.0, index=dates)
    return pd.DataFrame(
        {
            "Open": open_,
            "High": high,
            "Low": low,
            "Close": close,
            "Volume": volume,
        },
        index=dates,
    )


def test_primary_fixture_matches_legacy_and_spec(
    primary_fixture_date,
    load_sprint_f_fixture,
    sprint_f_strategy,
):
    fixture = load_sprint_f_fixture("engine", primary_fixture_date)

    legacy = compute_engine_outputs(primary_fixture_date)
    spec = compute_engine_outputs(primary_fixture_date, strategy=sprint_f_strategy)

    expected = fixture["tickers"]
    assert _engine_records(legacy) == expected
    assert _engine_records(spec) == expected


def test_fuzz_dates_match_legacy_and_spec(
    all_fixture_dates,
    load_sprint_f_fixture,
    sprint_f_strategy,
):
    for as_of_date in all_fixture_dates:
        fixture = load_sprint_f_fixture("engine", as_of_date)
        legacy = compute_engine_outputs(as_of_date)
        spec = compute_engine_outputs(as_of_date, strategy=sprint_f_strategy)

        expected = fixture["tickers"]
        assert _engine_records(legacy) == expected
        assert _engine_records(spec) == expected


def test_compute_all_features_can_skip_sector_chain(sprint_f_strategy):
    strategy = copy.deepcopy(sprint_f_strategy)
    strategy.raw["enrichment"]["chain"] = ["technicals"]

    ohlcv = _make_uptrend_ohlcv()
    spy = _make_spy_ohlcv()

    with (
        patch("src.features.engine._load_options_metrics", return_value={}),
        patch("src.features.engine._load_event_proximity", return_value={}),
        patch("src.features.earnings.get_next_earnings_date", return_value=None),
    ):
        result = compute_all_features({"AAPL": ohlcv}, spy, strategy=strategy)

    assert "AAPL" in result
    assert "sector" not in result["AAPL"]
    assert "trend_state" in result["AAPL"]


def test_enrich_features_chain_limits_optional_dispatch(sprint_f_strategy):
    strategy = copy.deepcopy(sprint_f_strategy)
    strategy.raw["enrichment"]["chain"] = ["macro"]

    features = {"AAPL": {"current_price": 100.0, "ticker": "AAPL"}}
    config = {"data_enrichment": {"enabled": True}}

    with (
        patch("src.data_enrichment.macro.fetch_macro_context", return_value={"fed_funds_rate": 4.5}),
        patch("src.data_enrichment.macro.format_macro_summary", return_value="macro ok"),
        patch("src.data_enrichment.fundamentals.fetch_fundamental_snapshot", return_value=None),
        patch("src.data_enrichment.fundamentals.format_fundamental_summary", return_value="fund ok"),
        patch(
            "src.data_enrichment.earnings_signals.compute_earnings_signals",
            return_value={"include_in_prompt": False},
        ),
        patch("src.data_enrichment.insiders.fetch_insider_activity") as insider_fetch,
        patch("src.data_enrichment.news.fetch_recent_news") as news_fetch,
    ):
        result = enrich_features(features, config, strategy=strategy)

    assert result["AAPL"]["macro_summary"] == "macro ok"
    assert result["AAPL"]["fundamental_summary"] == "fund ok"
    assert "insider_summary" not in result["AAPL"]
    assert "news_summary" not in result["AAPL"]
    insider_fetch.assert_not_called()
    news_fetch.assert_not_called()


def test_post_scan_chain_and_quarantine_are_strategy_driven(sprint_f_strategy):
    strategy = copy.deepcopy(sprint_f_strategy)
    strategy.raw["post_scan"]["chain"] = ["event_risk"]
    strategy.raw["event_risk"] = {"quarantine_categories": ["fomc"]}

    features = {"AAPL": {"current_price": 100.0, "event_risk_level": "none"}}

    def _fake_event_risk(feats, **kwargs):
        for feat in feats.values():
            feat["event_risk_multiplier"] = 0.7
            feat["event_risk_score"] = 4
            feat["event_risk_components"] = {"fomc": 2, "earnings_forces_block": False}
        return {"total_score": 4, "components": {"fomc": 2}, "sizing_multiplier": 0.7}

    with (
        patch("src.features.traffic_light.compute_traffic_light") as traffic_light,
        patch(
            "src.features.event_risk_score.attach_event_risk_scores",
            side_effect=_fake_event_risk,
        ),
    ):
        attach_post_scan_features(
            features,
            config={},
            spy=pd.DataFrame(),
            strategy=strategy,
        )

    traffic_light.assert_not_called()
    assert features["AAPL"]["event_risk_quarantined"] is True
    assert features["AAPL"]["event_risk_quarantine_matches"] == ["fomc"]
    assert features["AAPL"]["event_risk_multiplier"] == 0.0
