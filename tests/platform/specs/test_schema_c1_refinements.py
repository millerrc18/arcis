"""Tests for Sprint C.1 schema refinements (#569).

Covers:
- Item 1: packet_worthy → min_score (closes #567)
- Item 2: KNOWN_POST_SCAN_HELPERS contents + strict=True (closes #568)
- Item 3: categorical bands
- Item 4: compound AND conditions
- Item 5: weighted bands + blend_group
- Item 6: ranking.adjustments block
- Item 7: ranking.derived_metrics block
- Item 8: KNOWN_SCORING_METRICS registry
- Item 9: KNOWN_EVENT_RISK_CATEGORIES casing convention guard
- Backward compat: lazy_prices_v1, post_audit_ruleset_v1
"""
import logging

import pytest

from src.platform.strategy_spec import (
    KNOWN_EVENT_RISK_CATEGORIES,
    KNOWN_REGIME_LABELS,
    KNOWN_SCORING_METRICS,
    load_spec,
    validate_spec,
)


# ── Fixtures ────────────────────────────────────────────────────────────

def _base_spec() -> dict:
    """Minimal valid spec dict — no ranking / regime_adaptive blocks."""
    return {
        "spec_version": 1,
        "strategy_id": "c1_test",
        "display_name": "Sprint C.1 Test",
        "universe": {"tickers": ["AAPL", "MSFT"]},
        "entry": {"kind": "scheduled"},
        "exit": {"kind": "python_plugin"},
        "position_sizing": {"method": "fixed_pct_equity", "pct": 0.1},
        "attribution": {"benchmark": "SPY"},
    }


def _ranking_spec(ranking: dict) -> dict:
    spec = _base_spec()
    spec["ranking"] = ranking
    return spec


def _regime_adaptive_spec(regimes: dict) -> dict:
    spec = _base_spec()
    spec["position_sizing"] = {"method": "regime_adaptive", "regimes": regimes}
    return spec


# ── Item 1: packet_worthy → min_score (closes #567) ─────────────────────

def test_item1_min_score_accepts_int():
    spec = _regime_adaptive_spec({
        "BULL_LOW_VOL": {"min_score": 40, "position_pct": 1.0},
    })
    ok, errors = validate_spec(spec)
    assert ok, errors


def test_item1_min_score_rejects_bool():
    """Regression guard for #567: previously the validator asserted bool."""
    spec = _regime_adaptive_spec({
        "BULL_LOW_VOL": {"min_score": True, "position_pct": 1.0},
    })
    ok, errors = validate_spec(spec)
    assert not ok
    assert any("min_score" in e and "int" in e for e in errors), errors


def test_item1_min_score_rejects_out_of_range():
    spec = _regime_adaptive_spec({
        "BULL_LOW_VOL": {"min_score": 150, "position_pct": 1.0},
    })
    ok, errors = validate_spec(spec)
    assert not ok
    assert any("min_score" in e for e in errors), errors


# ── Item 2: KNOWN_POST_SCAN_HELPERS drift + strict (closes #568) ────────

def test_item2_post_scan_accepts_new_names():
    spec = _base_spec()
    spec["post_scan"] = {"chain": ["traffic_light", "event_risk"]}
    ok, errors = validate_spec(spec)
    assert ok, errors


def test_item2_post_scan_rejects_obsolete_names_under_strict():
    """Sprint C.1 flipped post_scan.chain to strict=True."""
    spec = _base_spec()
    spec["post_scan"] = {"chain": ["classifier"]}
    ok, errors = validate_spec(spec)
    assert not ok
    assert any("post_scan.chain" in e and "unknown ref" in e for e in errors), errors


# ── Item 3: categorical bands ───────────────────────────────────────────

def test_item3_categorical_band_accepted():
    spec = _ranking_spec({"bands": [
        {"metric": "trend_state", "category": "strong_uptrend", "score": 30},
    ]})
    ok, errors = validate_spec(spec)
    assert ok, errors


def test_item3_range_and_category_mutually_exclusive():
    spec = _ranking_spec({"bands": [
        {"metric": "pullback_depth_pct", "range": [-8, -3], "category": "foo", "score": 10},
    ]})
    ok, errors = validate_spec(spec)
    assert not ok
    assert any("mutually exclusive" in e for e in errors), errors


def test_item3_rejects_duplicate_metric_category():
    spec = _ranking_spec({"bands": [
        {"metric": "trend_state", "category": "strong_uptrend", "score": 30},
        {"metric": "trend_state", "category": "strong_uptrend", "score": 25},
    ]})
    ok, errors = validate_spec(spec)
    assert not ok
    assert any("duplicates" in e for e in errors), errors


# ── Item 4: compound AND conditions ─────────────────────────────────────

def test_item4_compound_band_accepted():
    spec = _ranking_spec({"bands": [{
        "conditions": [
            {"metric": "iv_rank", "operator": ">", "threshold": 75},
            {"metric": "put_call_vol_ratio", "operator": ">", "threshold": 1.2},
        ],
        "score": -3,
    }]})
    ok, errors = validate_spec(spec)
    assert ok, errors


def test_item4_rejects_unknown_operator():
    spec = _ranking_spec({"bands": [{
        "conditions": [{"metric": "iv_rank", "operator": "~~", "threshold": 75}],
        "score": 10,
    }]})
    ok, errors = validate_spec(spec)
    assert not ok
    assert any("operator" in e for e in errors), errors


def test_item4_rejects_mixing_top_level_metric_with_conditions():
    spec = _ranking_spec({"bands": [{
        "metric": "iv_rank",
        "conditions": [{"metric": "put_call_vol_ratio", "operator": ">", "threshold": 1.2}],
        "score": 10,
    }]})
    ok, errors = validate_spec(spec)
    assert not ok
    assert any("mutually exclusive" in e or "may not specify" in e for e in errors), errors


# ── Item 5: weighted bands + blend_group ────────────────────────────────

def test_item5_weighted_blend_accepted():
    spec = _ranking_spec({"bands": [
        {"metric": "relative_strength_state", "category": "strong_outperformer",
         "score": 25, "weight": 0.6, "blend_group": "rs_blend"},
        {"metric": "relative_strength_state", "category": "outperformer",
         "score": 15, "weight": 0.4, "blend_group": "rs_blend"},
    ]})
    ok, errors = validate_spec(spec)
    assert ok, errors


def test_item5_weight_requires_blend_group():
    spec = _ranking_spec({"bands": [
        {"metric": "pullback_depth_pct", "range": [-8, -3], "score": 25, "weight": 0.5},
    ]})
    ok, errors = validate_spec(spec)
    assert not ok
    assert any("blend_group" in e for e in errors), errors


def test_item5_blend_group_weights_warn_if_not_sum_one(caplog):
    spec = _ranking_spec({"bands": [
        {"metric": "trend_state", "category": "uptrend",
         "score": 10, "weight": 0.3, "blend_group": "g"},
        {"metric": "trend_state", "category": "strong_uptrend",
         "score": 10, "weight": 0.3, "blend_group": "g"},
    ]})
    with caplog.at_level(logging.WARNING, logger="src.platform._strategy_spec_ranking"):
        ok, errors = validate_spec(spec)
    assert ok, errors
    warn_msgs = [r.getMessage() for r in caplog.records if r.levelname == "WARNING"]
    assert any("blend_group" in m and ("0.600" in m or "not 1.0" in m) for m in warn_msgs), warn_msgs


# ── Item 6: ranking.adjustments block ───────────────────────────────────

def test_item6_adjustments_block_accepted():
    spec = _ranking_spec({"adjustments": {
        "clamp": [-10, 10],
        "bands": [
            {"conditions": [
                {"metric": "regime_label", "operator": "==", "threshold": "calm_uptrend"},
                {"metric": "market_breadth_label", "operator": "==", "threshold": "healthy"},
            ], "score": 5},
        ],
    }})
    ok, errors = validate_spec(spec)
    assert ok, errors


def test_item6_adjustments_clamp_rejects_lo_gte_hi():
    spec = _ranking_spec({"adjustments": {
        "clamp": [10, -10],
        "bands": [{"metric": "spy_rsi_14", "range": [0, 100], "score": 0}],
    }})
    ok, errors = validate_spec(spec)
    assert not ok
    assert any("clamp" in e for e in errors), errors


def test_item6_regime_label_threshold_validated_against_known_labels():
    spec = _ranking_spec({"bands": [{
        "conditions": [
            {"metric": "regime_label", "operator": "==", "threshold": "not_a_real_regime"},
        ],
        "score": 5,
    }]})
    ok, errors = validate_spec(spec)
    assert not ok
    assert any("KNOWN_REGIME_LABELS" in e for e in errors), errors


# ── Item 7: ranking.derived_metrics block ───────────────────────────────

def test_item7_derived_metrics_subtract_and_weighted_sum():
    spec = _ranking_spec({"derived_metrics": {
        "sector_excess_1m": {"operation": "subtract", "inputs": ["a", "b"]},
        "weighted_excess": {"operation": "weighted_sum",
                            "inputs": {"sector_excess_1m": 0.2, "x": 0.8}},
    }})
    ok, errors = validate_spec(spec)
    assert ok, errors


def test_item7_rejects_unknown_operation():
    spec = _ranking_spec({"derived_metrics": {
        "bad": {"operation": "multiply", "inputs": ["a", "b"]},
    }})
    ok, errors = validate_spec(spec)
    assert not ok
    assert any("operation" in e for e in errors), errors


def test_item7_rejects_cycle():
    spec = _ranking_spec({"derived_metrics": {
        "a": {"operation": "subtract", "inputs": ["b", "x"]},
        "b": {"operation": "subtract", "inputs": ["a", "y"]},
    }})
    ok, errors = validate_spec(spec)
    assert not ok
    assert any("cycle" in e for e in errors), errors


# ── Item 8: KNOWN_SCORING_METRICS registry ──────────────────────────────

def test_item8_known_scoring_metric_accepted():
    spec = _ranking_spec({"bands": [
        {"metric": "pullback_depth_pct", "range": [-8, -3], "score": 25},
    ]})
    ok, errors = validate_spec(spec)
    assert ok, errors


def test_item8_unknown_scoring_metric_rejected():
    spec = _ranking_spec({"bands": [
        {"metric": "made_up_metric", "range": [0, 1], "score": 10},
    ]})
    ok, errors = validate_spec(spec)
    assert not ok
    assert any("known scoring metrics" in e for e in errors), errors


def test_item8_derived_metric_becomes_valid_band_metric():
    """Derived-metric names are added to the effective known set for bands."""
    spec = _ranking_spec({
        "derived_metrics": {
            "custom_metric": {"operation": "subtract", "inputs": ["trend_state", "trend_state"]},
        },
        "bands": [
            {"metric": "custom_metric", "range": [0, 1], "score": 10},
        ],
    })
    ok, errors = validate_spec(spec)
    assert ok, errors


# ── Item 9: casing convention guard ─────────────────────────────────────

def test_item9_known_event_risk_categories_lowercase_with_underscores():
    """Guard against future additions breaking the lowercase convention."""
    for cat in KNOWN_EVENT_RISK_CATEGORIES:
        assert cat == cat.lower(), f"{cat!r} breaks lowercase convention"
        assert " " not in cat, f"{cat!r} contains space (use underscore)"


# ── Backward compat: existing specs still load ──────────────────────────

def test_backward_compat_lazy_prices_v1_still_loads():
    spec = load_spec("lazy_prices_v1")
    assert spec.strategy_id == "lazy_prices_v1"


def test_backward_compat_post_audit_ruleset_v1_still_loads():
    spec = load_spec("post_audit_ruleset_v1")
    assert spec.strategy_id == "post_audit_ruleset_v1"


# ── Registry seed sanity checks ─────────────────────────────────────────

def test_known_scoring_metrics_seed_size():
    """Sprint C.1 Item 8 seed: 10 metrics from _score_ticker + _regime_adjustment."""
    assert len(KNOWN_SCORING_METRICS) == 10


def test_known_regime_labels_seed_size():
    """Sprint C.1 Item 6 addendum: 5-label set from compute_market_regime()."""
    assert len(KNOWN_REGIME_LABELS) == 5
    assert "calm_uptrend" in KNOWN_REGIME_LABELS
    assert "BULL_LOW_VOL" not in KNOWN_REGIME_LABELS  # confirms separation from KEYS
