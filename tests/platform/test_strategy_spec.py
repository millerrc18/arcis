"""Tests for src.platform.strategy_spec — YAML loader + validator."""
from pathlib import Path

import pytest

from src.platform.strategy_spec import (
    StrategySpec,
    list_available_specs,
    load_spec,
    load_spec_from_yaml,
    validate_spec,
)


def test_load_lazy_prices_yaml_valid():
    path = Path("src/platform/specs/lazy_prices.yaml")
    spec = load_spec_from_yaml(path)
    assert isinstance(spec, StrategySpec)
    assert spec.strategy_id == "lazy_prices_v1"
    assert spec.universe["tickers"] == "sp100"
    assert spec.entry["kind"] == "event_driven"
    assert spec.exit["kind"] == "mechanical"


def test_reject_spec_missing_strategy_id():
    bad = {"display_name": "x", "universe": {}, "entry": {}, "exit": {},
           "position_sizing": {}, "attribution": {}}
    ok, errors = validate_spec(bad)
    assert not ok
    assert any("strategy_id" in e for e in errors)


def test_reject_spec_invalid_universe():
    bad = {"strategy_id": "x", "display_name": "x",
           "universe": "not-a-dict",
           "entry": {}, "exit": {}, "position_sizing": {}, "attribution": {}}
    ok, errors = validate_spec(bad)
    assert not ok
    assert any("universe" in e for e in errors)


def test_reject_spec_unknown_entry_kind():
    bad = {"strategy_id": "x", "display_name": "x", "universe": {},
           "entry": {"kind": "telepathy"},
           "exit": {"kind": "mechanical"},
           "position_sizing": {}, "attribution": {}}
    ok, errors = validate_spec(bad)
    assert not ok
    assert any("entry.kind" in e for e in errors)


def test_list_available_specs_finds_lazy_prices():
    specs = list_available_specs(Path("src/platform/specs"))
    ids = [s.strategy_id for s in specs]
    assert "lazy_prices_v1" in ids


def test_load_spec_by_id_resolves_yaml_path():
    spec = load_spec("lazy_prices_v1")
    assert spec.strategy_id == "lazy_prices_v1"


def test_load_spec_by_id_raises_on_missing(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_spec("does_not_exist", specs_dir=tmp_path)
