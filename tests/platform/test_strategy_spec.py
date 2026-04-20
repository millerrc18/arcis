"""Tests for src.platform.strategy_spec — YAML loader + validator."""
from pathlib import Path

import pytest

from src.platform.strategy_spec import (
    StrategySpec,
    _SPECS_DIR,
    list_available_specs,
    load_spec,
    load_spec_from_yaml,
    validate_spec,
)


def test_load_lazy_prices_yaml_valid():
    path = _SPECS_DIR / "lazy_prices_v1.yaml"
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
    specs = list_available_specs(_SPECS_DIR)
    ids = [s.strategy_id for s in specs]
    assert "lazy_prices_v1" in ids


def test_load_spec_by_id_resolves_yaml_path():
    spec = load_spec("lazy_prices_v1")
    assert spec.strategy_id == "lazy_prices_v1"


def test_load_spec_by_id_raises_on_missing(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_spec("does_not_exist", specs_dir=tmp_path)


def test_list_available_specs_warns_on_malformed_yaml(tmp_path, caplog):
    import logging
    bad = tmp_path / "broken.yaml"
    bad.write_text("this: is: not: valid: yaml: [::")  # malformed
    good = tmp_path / "good.yaml"
    good.write_text(
        "spec_version: 1\nstrategy_id: good_spec\ndisplay_name: Good\n"
        "universe: {}\nentry: {kind: scheduled}\nexit: {kind: python_plugin}\n"
        "position_sizing: {}\nattribution: {}\n"
    )
    with caplog.at_level(logging.WARNING, logger="src.platform.strategy_spec"):
        specs = list_available_specs(tmp_path)
    ids = [s.strategy_id for s in specs]
    assert "good_spec" in ids
    assert any("broken.yaml" in r.message or "skipping malformed" in r.message
               for r in caplog.records)


def test_reject_spec_missing_spec_version():
    bad = {
        "strategy_id": "x", "display_name": "x", "universe": {},
        "entry": {"kind": "scheduled"}, "exit": {"kind": "mechanical"},
        "position_sizing": {}, "attribution": {},
    }
    ok, errors = validate_spec(bad)
    assert not ok
    assert any("spec_version" in e for e in errors)
