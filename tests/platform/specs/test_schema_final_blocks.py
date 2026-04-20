"""Tests for src.platform.strategy_spec — 5 final schema blocks (#551).

Covers: hooks.attribution, enrichment.chain, post_scan.chain,
event_risk.quarantine_categories, bootcamp. One valid + one rejection
per block plus combined / backward-compat / edge cases.
"""
import logging

from src.platform.strategy_spec import (
    _SPECS_DIR,
    load_spec_from_yaml,
    validate_spec,
)


def _base_spec() -> dict:
    """Minimal valid spec dict — no Sprint E blocks declared."""
    return {
        "spec_version": 1,
        "strategy_id": "final_blocks_test",
        "display_name": "Final Blocks Test",
        "universe": {"tickers": ["AAPL", "MSFT"]},
        "entry": {"kind": "scheduled"},
        "exit": {"kind": "python_plugin"},
        "position_sizing": {"method": "fixed_pct_equity", "pct": 0.1},
        "attribution": {"benchmark": "SPY"},
    }


# ── Block 1: hooks.attribution (strict) ─────────────────────────────────


def test_hooks_attribution_valid_loads():
    spec = _base_spec()
    spec["hooks"] = {"attribution": ["log_before_llm", "log_after_llm"]}
    ok, errors = validate_spec(spec)
    assert ok, errors
    assert errors == []


def test_hooks_attribution_unknown_ref_rejects():
    spec = _base_spec()
    spec["hooks"] = {"attribution": ["log_before_llm", "frog"]}
    ok, errors = validate_spec(spec)
    assert not ok
    assert any("unknown ref 'frog'" in e for e in errors), errors


# ── Block 2: enrichment.chain (warn) ────────────────────────────────────


def test_enrichment_chain_valid_loads(caplog):
    spec = _base_spec()
    spec["enrichment"] = {"chain": ["technicals", "insider"]}
    with caplog.at_level(logging.WARNING, logger="src.platform.strategy_spec"):
        ok, errors = validate_spec(spec)
    assert ok, errors
    assert errors == []
    warn_msgs = [r.getMessage() for r in caplog.records if r.levelname == "WARNING"]
    assert not any("unknown ref" in m for m in warn_msgs)


def test_enrichment_chain_unknown_ref_warns(caplog):
    spec = _base_spec()
    spec["enrichment"] = {"chain": ["technicals", "frog"]}
    with caplog.at_level(logging.WARNING, logger="src.platform.strategy_spec"):
        ok, errors = validate_spec(spec)
    assert ok, errors
    assert errors == []
    warn_msgs = [r.getMessage() for r in caplog.records if r.levelname == "WARNING"]
    assert any("'frog'" in m and "technicals" in m for m in warn_msgs), warn_msgs


# ── Block 3: post_scan.chain (strict post-Sprint C.1 Item 2 #568) ───────


def test_post_scan_chain_valid_loads():
    """Sprint C.1 Item 2 (#568): frozenset aligned to runtime dispatch names
    (traffic_light, event_risk) and strict=True now that drift is fixed."""
    spec = _base_spec()
    spec["post_scan"] = {"chain": ["traffic_light", "event_risk"]}
    ok, errors = validate_spec(spec)
    assert ok, errors
    assert errors == []


def test_post_scan_chain_unknown_ref_rejects():
    """Sprint C.1 Item 2: strict=True — unknown refs hard-fail, not warn."""
    spec = _base_spec()
    spec["post_scan"] = {"chain": ["frog"]}
    ok, errors = validate_spec(spec)
    assert not ok
    assert any("post_scan.chain" in e and "unknown ref" in e and "'frog'" in e
               for e in errors), errors


# ── Block 4: event_risk.quarantine_categories (warn) ────────────────────


def test_event_risk_valid_loads():
    spec = _base_spec()
    spec["event_risk"] = {"quarantine_categories": ["earnings_imminent", "fomc"]}
    ok, errors = validate_spec(spec)
    assert ok, errors
    assert errors == []


def test_event_risk_unknown_category_warns(caplog):
    spec = _base_spec()
    spec["event_risk"] = {"quarantine_categories": ["frog_moon_vol"]}
    with caplog.at_level(logging.WARNING, logger="src.platform.strategy_spec"):
        ok, errors = validate_spec(spec)
    assert ok, errors
    assert errors == []
    warn_msgs = [r.getMessage() for r in caplog.records if r.levelname == "WARNING"]
    assert any("'frog_moon_vol'" in m for m in warn_msgs), warn_msgs


# ── Block 5: bootcamp (strict) ──────────────────────────────────────────


def test_bootcamp_valid_loads():
    spec = _base_spec()
    spec["bootcamp"] = {"qualification_threshold": 55, "max_positions": 20}
    ok, errors = validate_spec(spec)
    assert ok, errors
    assert errors == []


def test_bootcamp_unknown_key_rejects():
    spec = _base_spec()
    spec["bootcamp"] = {"qualification_threshold": 55, "frog": 42}
    ok, errors = validate_spec(spec)
    assert not ok
    assert any("unknown keys" in e and "frog" in e for e in errors), errors


def test_bootcamp_threshold_out_of_range_rejects():
    spec = _base_spec()
    spec["bootcamp"] = {"qualification_threshold": 150}
    ok, errors = validate_spec(spec)
    assert not ok
    assert any("[0, 100]" in e for e in errors), errors


def test_bootcamp_max_positions_bool_rejects():
    spec = _base_spec()
    spec["bootcamp"] = {"max_positions": True}
    ok, errors = validate_spec(spec)
    assert not ok
    assert any("positive int" in e for e in errors), errors


def test_bootcamp_traffic_light_floor_out_of_range_rejects():
    spec = _base_spec()
    spec["bootcamp"] = {"traffic_light_floor": 1.5}
    ok, errors = validate_spec(spec)
    assert not ok
    assert any("[0.0, 1.0]" in e for e in errors), errors


def test_bootcamp_traffic_light_floor_valid():
    spec = _base_spec()
    spec["bootcamp"] = {"traffic_light_floor": 0.5}
    ok, errors = validate_spec(spec)
    assert ok, errors
    assert errors == []


def test_bootcamp_watchlist_threshold_valid():
    spec = _base_spec()
    spec["bootcamp"] = {"watchlist_threshold": 25}
    ok, errors = validate_spec(spec)
    assert ok, errors
    assert errors == []


# ── Combined + backward-compat ──────────────────────────────────────────


def test_all_five_blocks_combined_loads():
    spec = _base_spec()
    spec["hooks"] = {"attribution": ["log_before_llm"]}
    spec["enrichment"] = {"chain": ["technicals", "macro"]}
    spec["post_scan"] = {"chain": ["traffic_light"]}
    spec["event_risk"] = {"quarantine_categories": ["earnings_imminent", "cpi"]}
    spec["bootcamp"] = {
        "qualification_threshold": 55,
        "watchlist_threshold": 30,
        "max_positions": 20,
        "traffic_light_floor": 0.5,
    }
    ok, errors = validate_spec(spec)
    assert ok, errors
    assert errors == []


def test_lazy_prices_v1_still_loads():
    spec = load_spec_from_yaml(_SPECS_DIR / "lazy_prices_v1.yaml")
    assert spec.strategy_id == "lazy_prices_v1"


def test_post_audit_ruleset_v1_still_loads():
    spec = load_spec_from_yaml(_SPECS_DIR / "post_audit_ruleset_v1.yaml")
    assert spec.strategy_id == "post_audit_ruleset_v1"


def test_none_of_five_blocks_present_still_loads():
    spec = _base_spec()  # No hooks/enrichment/post_scan/event_risk/bootcamp.
    ok, errors = validate_spec(spec)
    assert ok, errors
    assert errors == []


def test_hooks_not_a_dict_ignored():
    spec = _base_spec()
    spec["hooks"] = "not a dict"
    ok, errors = validate_spec(spec)
    assert ok, errors
    assert errors == []


# ── Edge cases ──────────────────────────────────────────────────────────


def test_hooks_attribution_empty_list_rejects():
    spec = _base_spec()
    spec["hooks"] = {"attribution": []}
    ok, errors = validate_spec(spec)
    assert not ok
    assert any("non-empty list" in e for e in errors), errors


def test_hooks_attribution_not_a_list_rejects():
    spec = _base_spec()
    spec["hooks"] = {"attribution": "log_before_llm"}  # string, not list
    ok, errors = validate_spec(spec)
    assert not ok
    assert any("must be a list" in e for e in errors), errors


def test_enrichment_chain_entry_not_a_string_rejects():
    spec = _base_spec()
    spec["enrichment"] = {"chain": [42]}
    ok, errors = validate_spec(spec)
    assert not ok
    assert any("non-empty string" in e for e in errors), errors


def test_bootcamp_not_a_dict_ignored():
    spec = _base_spec()
    spec["bootcamp"] = "not a dict"
    ok, errors = validate_spec(spec)
    assert ok, errors
    assert errors == []


def test_all_five_block_outer_dicts_empty_pass():
    spec = _base_spec()
    spec["hooks"] = {}
    spec["enrichment"] = {}
    spec["post_scan"] = {}
    spec["event_risk"] = {}
    spec["bootcamp"] = {}
    ok, errors = validate_spec(spec)
    assert ok, errors
    assert errors == []
