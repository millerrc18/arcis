"""Spec-loading + R8 firewall tests for post_audit_ruleset_v1.

Validates that the v0.26.2-scoped schema additions (universe.sector_filter,
entry.event_exclusion.categories) parse correctly, that the R8(a) firewall
accepts the forensic-audit derived_from block with source_trade_ids
omitted, and that the baseline lazy_prices spec still loads unchanged.
"""

import pytest

from src.platform.rigor.walkforward_firewall import (
    R8ViolationError,
    validate_derived_from,
)
from src.platform.strategy_spec import load_spec, validate_spec


def test_loads_post_audit_ruleset_v1_spec():
    spec = load_spec("post_audit_ruleset_v1")
    assert spec.strategy_id == "post_audit_ruleset_v1"
    assert spec.universe.get("sector_filter") == [
        "Consumer Staples", "Utilities", "Health Care",
    ]
    assert (spec.entry.get("event_exclusion") or {}).get("categories") == [
        "Trade Policy",
    ]


def test_r8a_parses_without_source_trade_ids():
    spec = load_spec("post_audit_ruleset_v1")
    assert "source_trade_ids" not in spec.raw["derived_from"]
    validate_derived_from(spec.raw)


def test_sector_filter_required_type_list():
    bad = {
        "spec_version": 1, "strategy_id": "x", "display_name": "x",
        "universe": {"tickers": "sp100", "sector_filter": "Consumer Staples"},
        "entry": {"kind": "event_driven"},
        "exit": {"kind": "mechanical"},
        "position_sizing": {}, "attribution": {},
    }
    ok, errors = validate_spec(bad)
    assert not ok
    assert any("sector_filter" in e for e in errors)


def test_sector_filter_required_non_empty():
    bad = {
        "spec_version": 1, "strategy_id": "x", "display_name": "x",
        "universe": {"tickers": "sp100", "sector_filter": []},
        "entry": {"kind": "event_driven"},
        "exit": {"kind": "mechanical"},
        "position_sizing": {}, "attribution": {},
    }
    ok, errors = validate_spec(bad)
    assert not ok
    assert any("sector_filter" in e for e in errors)


def test_event_exclusion_categories_required_type():
    bad = {
        "spec_version": 1, "strategy_id": "x", "display_name": "x",
        "universe": {"tickers": "sp100"},
        "entry": {"kind": "event_driven", "event_exclusion": {"categories": "Trade Policy"}},
        "exit": {"kind": "mechanical"},
        "position_sizing": {}, "attribution": {},
    }
    ok, errors = validate_spec(bad)
    assert not ok
    assert any("event_exclusion.categories" in e for e in errors)


def test_event_exclusion_block_must_be_dict():
    bad = {
        "spec_version": 1, "strategy_id": "x", "display_name": "x",
        "universe": {"tickers": "sp100"},
        "entry": {"kind": "event_driven", "event_exclusion": ["Trade Policy"]},
        "exit": {"kind": "mechanical"},
        "position_sizing": {}, "attribution": {},
    }
    ok, errors = validate_spec(bad)
    assert not ok
    assert any("event_exclusion" in e for e in errors)


def test_lazy_prices_still_loads_without_new_fields():
    """Regression: pre-existing spec unaffected by optional schema extension."""
    spec = load_spec("lazy_prices_v1")
    assert spec.strategy_id == "lazy_prices_v1"
    assert "sector_filter" not in spec.universe
    assert "event_exclusion" not in spec.entry
    validate_derived_from(spec.raw)
