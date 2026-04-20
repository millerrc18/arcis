"""Tests for src.platform.strategy_spec — ranking.bands scoring-DSL block (#549)."""
import logging

from src.platform.strategy_spec import (
    _SPECS_DIR,
    load_spec_from_yaml,
    validate_spec,
)


def _base_spec() -> dict:
    """Minimal valid spec dict (all REQUIRED_KEYS present)."""
    return {
        "spec_version": 1,
        "strategy_id": "scoring_dsl_test",
        "display_name": "Scoring DSL Test",
        "universe": {"tickers": ["AAPL", "MSFT"]},
        "entry": {"kind": "scheduled"},
        "exit": {"kind": "mechanical"},
        "position_sizing": {"method": "fixed_pct_equity", "pct": 0.1},
        "attribution": {"benchmark": "SPY"},
    }


# ── 1. Valid-bands happy path ──────────────────────────────────────────

def test_valid_bands_spec_loads():
    spec = _base_spec()
    spec["ranking"] = {
        "bands": [
            {"metric": "pullback_depth_pct", "range": [-8, -3], "score": 25},
            {"metric": "volume_ratio_20d", "range": [1.5, 3.0], "score": 15},
        ],
    }
    ok, errors = validate_spec(spec)
    assert ok, errors
    assert errors == []


# ── 2-6. Individual rejection paths ────────────────────────────────────

def test_bands_missing_metric_rejects():
    spec = _base_spec()
    spec["ranking"] = {"bands": [{"range": [-8, -3], "score": 25}]}
    ok, errors = validate_spec(spec)
    assert not ok
    assert any("metric" in e for e in errors)


def test_bands_missing_range_rejects():
    spec = _base_spec()
    spec["ranking"] = {"bands": [{"metric": "pullback_depth_pct", "score": 25}]}
    ok, errors = validate_spec(spec)
    assert not ok
    assert any("range" in e for e in errors)


def test_bands_range_lower_ge_upper_rejects():
    spec = _base_spec()
    spec["ranking"] = {
        "bands": [
            {"metric": "m1", "range": [5, 5], "score": 10},
            {"metric": "m2", "range": [5, 3], "score": 10},
        ],
    }
    ok, errors = validate_spec(spec)
    assert not ok
    assert sum(1 for e in errors if "< range[1]" in e) == 2


def test_bands_range_non_numeric_rejects():
    spec = _base_spec()
    spec["ranking"] = {
        "bands": [{"metric": "pullback_depth_pct", "range": ["a", 3], "score": 10}]
    }
    ok, errors = validate_spec(spec)
    assert not ok
    assert any("range" in e and "numeric" in e for e in errors)


def test_bands_range_wrong_length_rejects():
    spec = _base_spec()
    spec["ranking"] = {
        "bands": [{"metric": "pullback_depth_pct", "range": [-8], "score": 10}]
    }
    ok, errors = validate_spec(spec)
    assert not ok
    assert any("range" in e for e in errors)


def test_bands_score_non_numeric_rejects():
    spec = _base_spec()
    spec["ranking"] = {
        "bands": [
            {"metric": "pullback_depth_pct", "range": [-8, -3], "score": "twenty-five"},
        ],
    }
    ok, errors = validate_spec(spec)
    assert not ok
    assert any("score" in e for e in errors)


def test_bands_score_bool_rejects():
    # bool-is-int trap: isinstance(True, int) is True in Python.
    spec = _base_spec()
    spec["ranking"] = {
        "bands": [{"metric": "pullback_depth_pct", "range": [-8, -3], "score": True}]
    }
    ok, errors = validate_spec(spec)
    assert not ok
    assert any("score" in e for e in errors)


def test_bands_range_bool_rejects():
    spec = _base_spec()
    spec["ranking"] = {
        "bands": [{"metric": "pullback_depth_pct", "range": [True, 3], "score": 10}]
    }
    ok, errors = validate_spec(spec)
    assert not ok
    assert any("range" in e for e in errors)


def test_band_not_dict_rejects():
    spec = _base_spec()
    spec["ranking"] = {"bands": ["not-a-dict"]}
    ok, errors = validate_spec(spec)
    assert not ok
    assert any("must be a dict" in e for e in errors)


def test_bands_empty_metric_string_rejects():
    spec = _base_spec()
    spec["ranking"] = {
        "bands": [{"metric": "", "range": [-8, -3], "score": 25}]
    }
    ok, errors = validate_spec(spec)
    assert not ok
    assert any("metric" in e for e in errors)


# ── Overlap — warn, don't reject ───────────────────────────────────────

def test_bands_overlapping_warns_not_rejects(caplog):
    spec = _base_spec()
    spec["ranking"] = {
        "bands": [
            {"metric": "pullback_depth_pct", "range": [-8, -3], "score": 25},
            {"metric": "pullback_depth_pct", "range": [-5, 0], "score": 10},
        ],
    }
    with caplog.at_level(logging.WARNING, logger="src.platform.strategy_spec"):
        ok, errors = validate_spec(spec)
    assert ok, errors
    assert errors == []
    assert any(
        "ranking.bands overlap" in r.message and "pullback_depth_pct" in r.message
        for r in caplog.records
    )


def test_bands_touching_endpoints_warns(caplog):
    # Incumbent ranker's -8 shared boundary — expected warning.
    spec = _base_spec()
    spec["ranking"] = {
        "bands": [
            {"metric": "pullback_depth_pct", "range": [-12, -8], "score": 10},
            {"metric": "pullback_depth_pct", "range": [-8, -3], "score": 25},
        ],
    }
    with caplog.at_level(logging.WARNING, logger="src.platform.strategy_spec"):
        ok, _ = validate_spec(spec)
    assert ok
    assert any("ranking.bands overlap" in r.message for r in caplog.records)


def test_bands_multiple_per_metric_no_overlap_no_warn(caplog):
    spec = _base_spec()
    spec["ranking"] = {
        "bands": [
            {"metric": "pullback_depth_pct", "range": [-12, -8.01], "score": 10},
            {"metric": "pullback_depth_pct", "range": [-8, -3], "score": 25},
        ],
    }
    with caplog.at_level(logging.WARNING, logger="src.platform.strategy_spec"):
        ok, errors = validate_spec(spec)
    assert ok, errors
    assert not any("ranking.bands overlap" in r.message for r in caplog.records)


def test_bands_different_metrics_no_overlap(caplog):
    # Overlapping numeric ranges on *different* metrics are unrelated.
    spec = _base_spec()
    spec["ranking"] = {
        "bands": [
            {"metric": "pullback_depth_pct", "range": [-8, -3], "score": 25},
            {"metric": "volume_ratio_20d", "range": [-8, -3], "score": 15},
        ],
    }
    with caplog.at_level(logging.WARNING, logger="src.platform.strategy_spec"):
        ok, errors = validate_spec(spec)
    assert ok, errors
    assert not any("ranking.bands overlap" in r.message for r in caplog.records)


def test_bands_float_score_allowed():
    spec = _base_spec()
    spec["ranking"] = {
        "bands": [{"metric": "pullback_depth_pct", "range": [-8.0, -3.0], "score": 12.5}]
    }
    ok, errors = validate_spec(spec)
    assert ok, errors


# ── Structural rejections on the ranking wrapper ───────────────────────

def test_ranking_not_dict_rejects():
    spec = _base_spec()
    spec["ranking"] = "bands-should-be-here"
    ok, errors = validate_spec(spec)
    assert not ok
    assert any("ranking must be a dict" in e for e in errors)


def test_ranking_bands_not_list_rejects():
    spec = _base_spec()
    spec["ranking"] = {"bands": "not-a-list"}
    ok, errors = validate_spec(spec)
    assert not ok
    assert any("ranking.bands must be a list" in e for e in errors)


def test_bands_empty_list_allowed():
    spec = _base_spec()
    spec["ranking"] = {"bands": []}
    ok, errors = validate_spec(spec)
    assert ok, errors


# ── Backward compat ─────────────────────────────────────────────────────

def test_spec_without_ranking_block_still_loads():
    spec = _base_spec()
    assert "ranking" not in spec
    ok, errors = validate_spec(spec)
    assert ok, errors


def test_ranking_weights_still_loads():
    # Hypothetical alternate sub-key — only `bands` is validated; other
    # sub-keys under `ranking` pass through unchecked.
    spec = _base_spec()
    spec["ranking"] = {"weights": {"momentum": 0.5, "quality": 0.5}}
    ok, errors = validate_spec(spec)
    assert ok, errors


def test_lazy_prices_v1_still_loads():
    path = _SPECS_DIR / "lazy_prices_v1.yaml"
    spec = load_spec_from_yaml(path)
    assert spec.strategy_id == "lazy_prices_v1"


def test_post_audit_ruleset_v1_still_loads():
    path = _SPECS_DIR / "post_audit_ruleset_v1.yaml"
    spec = load_spec_from_yaml(path)
    assert spec.strategy_id == "post_audit_ruleset_v1"
