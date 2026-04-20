"""Tests for src.platform.strategy_spec — multi-target brackets + regime-adaptive sizing (#550)."""
import logging

from src.platform.strategy_spec import (
    KNOWN_REGIME_KEYS,
    _SPECS_DIR,
    load_spec_from_yaml,
    validate_spec,
)


def _base_spec() -> dict:
    """Minimal valid spec dict (all REQUIRED_KEYS present)."""
    return {
        "spec_version": 1,
        "strategy_id": "brackets_sizing_test",
        "display_name": "Brackets + Sizing Test",
        "universe": {"tickers": ["AAPL", "MSFT"]},
        "entry": {"kind": "scheduled"},
        "exit": {"kind": "python_plugin"},  # default: plugin owns brackets → no target/targets required
        "position_sizing": {"method": "fixed_pct_equity", "pct": 0.1},
        "attribution": {"benchmark": "SPY"},
    }


def _valid_targets_exit() -> dict:
    return {
        "kind": "mechanical",
        "timeout_days": 21,
        "stop": {"atr_multiple": 2.0},
        "targets": [
            {"name": "target_1", "atr_multiple": 1.5},
            {"name": "target_2", "atr_multiple": 3.0},
        ],
    }


def _valid_regime_adaptive() -> dict:
    return {
        "method": "regime_adaptive",
        "regimes": {
            "BULL_LOW_VOL": {"packet_worthy": True, "position_pct": 0.05},
            "CRISIS": {"packet_worthy": False, "position_pct": 0.0},
        },
    }


# ── Block 1: multi-target brackets ──────────────────────────────────────


def test_exit_targets_list_form_loads():
    spec = _base_spec()
    spec["exit"] = _valid_targets_exit()
    ok, errors = validate_spec(spec)
    assert ok, errors
    assert errors == []


def test_exit_target_singular_still_loads():
    spec = _base_spec()
    spec["exit"] = {
        "kind": "mechanical",
        "timeout_days": 21,
        "stop": {"method": "atr_based", "atr_period": 14, "multiplier": 3.0},
        "target": {"method": "atr_based", "atr_period": 14, "multiplier": 6.0},
    }
    ok, errors = validate_spec(spec)
    assert ok, errors
    assert errors == []


def test_exit_both_target_and_targets_rejects():
    spec = _base_spec()
    spec["exit"] = {
        "kind": "mechanical",
        "target": {"method": "atr_based", "multiplier": 6.0},
        "targets": [{"name": "t1", "atr_multiple": 1.5}],
        "stop": {"atr_multiple": 2.0},
    }
    ok, errors = validate_spec(spec)
    assert not ok
    assert any("mutually exclusive" in e for e in errors)


def test_exit_neither_target_nor_targets_rejects():
    spec = _base_spec()
    spec["exit"] = {"kind": "mechanical", "timeout_days": 5}
    ok, errors = validate_spec(spec)
    assert not ok
    assert any("requires one of" in e for e in errors)


def test_exit_python_plugin_allows_neither():
    spec = _base_spec()
    spec["exit"] = {"kind": "python_plugin", "plugin": "some.module.plugin"}
    ok, errors = validate_spec(spec)
    assert ok, errors
    assert errors == []


def test_exit_targets_empty_list_rejects():
    spec = _base_spec()
    spec["exit"] = {"kind": "mechanical", "targets": [], "stop": {"atr_multiple": 2.0}}
    ok, errors = validate_spec(spec)
    assert not ok
    assert any("non-empty list" in e for e in errors)


def test_exit_targets_entry_missing_name_rejects():
    spec = _base_spec()
    spec["exit"] = {
        "kind": "mechanical",
        "targets": [{"atr_multiple": 1.5}],
        "stop": {"atr_multiple": 2.0},
    }
    ok, errors = validate_spec(spec)
    assert not ok
    assert any("name" in e for e in errors)


def test_exit_targets_entry_missing_atr_multiple_rejects():
    spec = _base_spec()
    spec["exit"] = {
        "kind": "mechanical",
        "targets": [{"name": "t1"}],
        "stop": {"atr_multiple": 2.0},
    }
    ok, errors = validate_spec(spec)
    assert not ok
    assert any("atr_multiple" in e for e in errors)


def test_exit_targets_duplicate_names_rejects():
    spec = _base_spec()
    spec["exit"] = {
        "kind": "mechanical",
        "targets": [
            {"name": "target_1", "atr_multiple": 1.5},
            {"name": "target_1", "atr_multiple": 3.0},
        ],
        "stop": {"atr_multiple": 2.0},
    }
    ok, errors = validate_spec(spec)
    assert not ok
    assert any("duplicates" in e for e in errors)


def test_exit_targets_atr_multiple_zero_rejects():
    spec = _base_spec()
    spec["exit"] = {
        "kind": "mechanical",
        "targets": [{"name": "t1", "atr_multiple": 0.0}],
        "stop": {"atr_multiple": 2.0},
    }
    ok, errors = validate_spec(spec)
    assert not ok
    assert any("positive number" in e and "targets[0]" in e for e in errors)


def test_exit_targets_atr_multiple_negative_rejects():
    spec = _base_spec()
    spec["exit"] = {
        "kind": "mechanical",
        "targets": [{"name": "t1", "atr_multiple": -1.5}],
        "stop": {"atr_multiple": 2.0},
    }
    ok, errors = validate_spec(spec)
    assert not ok
    assert any("positive number" in e and "targets[0]" in e for e in errors)


def test_exit_targets_atr_multiple_bool_rejects():
    spec = _base_spec()
    spec["exit"] = {
        "kind": "mechanical",
        "targets": [{"name": "t1", "atr_multiple": True}],
        "stop": {"atr_multiple": 2.0},
    }
    ok, errors = validate_spec(spec)
    assert not ok
    assert any("positive number" in e and "targets[0]" in e for e in errors)


def test_exit_targets_requires_stop_atr_multiple():
    spec = _base_spec()
    spec["exit"] = {
        "kind": "mechanical",
        "targets": [{"name": "t1", "atr_multiple": 1.5}],
        # legacy rich stop shape — no atr_multiple key
        "stop": {"method": "atr_based", "atr_period": 14, "multiplier": 3.0},
    }
    ok, errors = validate_spec(spec)
    assert not ok
    assert any("atr_multiple" in e and "stop" in e for e in errors)


def test_exit_targets_stop_atr_multiple_zero_rejects():
    spec = _base_spec()
    spec["exit"] = {
        "kind": "mechanical",
        "targets": [{"name": "t1", "atr_multiple": 1.5}],
        "stop": {"atr_multiple": 0},
    }
    ok, errors = validate_spec(spec)
    assert not ok
    assert any("positive number" in e and "stop" in e for e in errors)


def test_lazy_prices_v1_still_loads():
    spec = load_spec_from_yaml(_SPECS_DIR / "lazy_prices_v1.yaml")
    assert spec.strategy_id == "lazy_prices_v1"
    assert spec.exit["kind"] == "mechanical"
    # legacy singular target block still present
    assert "target" in spec.exit
    assert "targets" not in spec.exit


def test_post_audit_ruleset_v1_still_loads():
    spec = load_spec_from_yaml(_SPECS_DIR / "post_audit_ruleset_v1.yaml")
    assert spec.strategy_id == "post_audit_ruleset_v1"
    assert spec.exit["kind"] == "mechanical"
    assert "target" in spec.exit
    assert "targets" not in spec.exit


# ── Block 2: regime-adaptive sizing ─────────────────────────────────────


def test_regime_adaptive_valid_spec_loads():
    spec = _base_spec()
    spec["position_sizing"] = _valid_regime_adaptive()
    ok, errors = validate_spec(spec)
    assert ok, errors
    assert errors == []


def test_fixed_pct_equity_still_loads():
    spec = _base_spec()
    spec["position_sizing"] = {
        "method": "fixed_pct_equity",
        "pct": 0.15,
        "max_concurrent": 5,
    }
    ok, errors = validate_spec(spec)
    assert ok, errors
    assert errors == []


def test_unknown_method_rejects():
    spec = _base_spec()
    spec["position_sizing"] = {"method": "frog_sizing"}
    ok, errors = validate_spec(spec)
    assert not ok
    assert any("method" in e and "fixed_pct_equity" in e and "regime_adaptive" in e for e in errors)


def test_regime_adaptive_missing_regimes_rejects():
    spec = _base_spec()
    spec["position_sizing"] = {"method": "regime_adaptive"}
    ok, errors = validate_spec(spec)
    assert not ok
    assert any("regimes" in e and "non-empty dict" in e for e in errors)


def test_regime_adaptive_empty_regimes_rejects():
    spec = _base_spec()
    spec["position_sizing"] = {"method": "regime_adaptive", "regimes": {}}
    ok, errors = validate_spec(spec)
    assert not ok
    assert any("regimes" in e and "non-empty dict" in e for e in errors)


def test_regime_adaptive_regime_missing_packet_worthy_rejects():
    spec = _base_spec()
    spec["position_sizing"] = {
        "method": "regime_adaptive",
        "regimes": {"BULL_LOW_VOL": {"position_pct": 0.05}},
    }
    ok, errors = validate_spec(spec)
    assert not ok
    assert any("packet_worthy" in e and "BULL_LOW_VOL" in e for e in errors)


def test_regime_adaptive_regime_missing_position_pct_rejects():
    spec = _base_spec()
    spec["position_sizing"] = {
        "method": "regime_adaptive",
        "regimes": {"BULL_LOW_VOL": {"packet_worthy": True}},
    }
    ok, errors = validate_spec(spec)
    assert not ok
    assert any("position_pct" in e and "BULL_LOW_VOL" in e for e in errors)


def test_regime_adaptive_packet_worthy_non_bool_rejects():
    spec = _base_spec()
    spec["position_sizing"] = {
        "method": "regime_adaptive",
        "regimes": {"BULL_LOW_VOL": {"packet_worthy": 0.5, "position_pct": 0.05}},
    }
    ok, errors = validate_spec(spec)
    assert not ok
    assert any("packet_worthy" in e and "bool" in e for e in errors)


def test_regime_adaptive_position_pct_out_of_range_rejects():
    spec = _base_spec()
    spec["position_sizing"] = {
        "method": "regime_adaptive",
        "regimes": {"BULL_LOW_VOL": {"packet_worthy": True, "position_pct": 1.5}},
    }
    ok, errors = validate_spec(spec)
    assert not ok
    assert any("position_pct" in e and "[0.0, 1.0]" in e for e in errors)


def test_regime_adaptive_position_pct_bool_rejects():
    spec = _base_spec()
    spec["position_sizing"] = {
        "method": "regime_adaptive",
        "regimes": {"BULL_LOW_VOL": {"packet_worthy": True, "position_pct": True}},
    }
    ok, errors = validate_spec(spec)
    assert not ok
    assert any("position_pct" in e for e in errors)


def test_regime_adaptive_unknown_key_warns_not_rejects(caplog):
    spec = _base_spec()
    spec["position_sizing"] = {
        "method": "regime_adaptive",
        "regimes": {
            "BULL_LOW_VOL": {"packet_worthy": True, "position_pct": 0.05},
            "FROG_MOON_VOL": {"packet_worthy": True, "position_pct": 0.03},
        },
    }
    with caplog.at_level(logging.WARNING, logger="src.platform.strategy_spec"):
        ok, errors = validate_spec(spec)
    assert ok, errors
    assert errors == []
    assert any(
        "unknown regime key" in r.getMessage() and "FROG_MOON_VOL" in r.getMessage()
        for r in caplog.records
    )
    # The log line lists the known keys for operator guidance
    known_line = next(
        (r.getMessage() for r in caplog.records if "unknown regime key" in r.getMessage()),
        "",
    )
    for key in KNOWN_REGIME_KEYS:
        assert key in known_line


def test_regime_adaptive_all_known_keys_no_warning(caplog):
    spec = _base_spec()
    spec["position_sizing"] = {
        "method": "regime_adaptive",
        "regimes": {
            k: {"packet_worthy": True, "position_pct": 0.05}
            for k in KNOWN_REGIME_KEYS
        },
    }
    with caplog.at_level(logging.WARNING, logger="src.platform.strategy_spec"):
        ok, errors = validate_spec(spec)
    assert ok, errors
    assert errors == []
    assert not any("unknown regime key" in r.getMessage() for r in caplog.records)


def test_regime_adaptive_regime_entry_not_dict_rejects():
    spec = _base_spec()
    spec["position_sizing"] = {
        "method": "regime_adaptive",
        "regimes": {"BULL_LOW_VOL": "not a dict"},
    }
    ok, errors = validate_spec(spec)
    assert not ok
    assert any("must be a dict" in e and "BULL_LOW_VOL" in e for e in errors)
