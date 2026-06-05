"""Tests for the server-side metric registry single-source layer (T2).

Covers MetricDef registration + duplicate-id rejection, the canonical
envelope shape returned by compute_metric/compute_all, sentinel/no-data
state flagging, and single-source equivalence with the legacy
kpis_compute helpers the registry wraps.
"""
from __future__ import annotations

import math

import pytest

from src.metrics.registry import (
    REGISTRY,
    MetricDef,
    compute_all,
    compute_metric,
    register,
)
from src.api.cloud_routes import kpis_compute


# ── MetricDef registration + duplicate rejection ──────────────────────────


def test_register_adds_metricdef_to_registry():
    md = MetricDef(
        id="__test_reg__",
        label="Test Reg",
        compute=lambda: {"value": 1.0, "n": 1, "as_of": None,
                         "cohort": "none", "unit": "ratio", "state": "ok"},
        cohort="none",
        window="all",
        unit="ratio",
        fmt="{:.2f}",
    )
    register(md)
    try:
        assert REGISTRY["__test_reg__"] is md
    finally:
        REGISTRY.pop("__test_reg__", None)


def test_register_rejects_duplicate_id():
    md = MetricDef(
        id="__dup__", label="Dup", compute=lambda: {},
        cohort="none", window="all", unit="ratio", fmt="{}",
    )
    register(md)
    try:
        with pytest.raises(ValueError):
            register(md)
    finally:
        REGISTRY.pop("__dup__", None)


# ── Canonical envelope shape ──────────────────────────────────────────────

_ENVELOPE_KEYS = {"value", "n", "as_of", "cohort", "unit", "state"}


def test_builtin_metrics_registered():
    # The wrapped KPIs must self-register on import.
    for mid in ("rf_adjusted_sharpe", "spy_relative_sharpe", "win_rate"):
        assert mid in REGISTRY


def test_compute_metric_returns_canonical_envelope():
    env = compute_metric("win_rate", trades=[{"pnl_pct": 1.0}, {"pnl_pct": -1.0}])
    assert _ENVELOPE_KEYS <= set(env)
    assert env["state"] == "ok"
    assert env["n"] == 2
    assert env["cohort"] == "trades.all_closed"
    assert env["unit"] == "ratio"
    assert env["value"] == pytest.approx(0.5)


def test_compute_all_returns_envelope_per_metric():
    out = compute_all(
        rf_adjusted_sharpe={"returns": [0.01, 0.02, -0.005, 0.015]},
        spy_relative_sharpe={"returns": [0.01, 0.02, -0.005],
                             "spy_returns": [0.0, 0.01, 0.0]},
        win_rate={"trades": [{"pnl_pct": 1.0}, {"pnl_pct": -1.0}]},
    )
    # Derived from source (not a hardcoded id list) so this never drifts RED
    # when a new metric is registered: compute_all must return exactly one
    # envelope per registered metric. The 3 KPIs we pass kwargs for must be
    # present; metrics registered without kwargs still get an envelope.
    assert set(out) == set(REGISTRY)
    assert {"rf_adjusted_sharpe", "spy_relative_sharpe", "win_rate"} <= set(out)
    for env in out.values():
        assert _ENVELOPE_KEYS <= set(env)


# ── no-data and sentinel state flagging (laws #2/#3) ──────────────────────


def test_no_data_surfaces_state_not_raw_value():
    env = compute_metric("win_rate", trades=[])
    assert env["state"] == "no_data"
    assert env["value"] is None
    assert env["n"] == 0


def test_rf_sharpe_no_data_on_empty_returns():
    env = compute_metric("rf_adjusted_sharpe", returns=[])
    assert env["state"] == "no_data"
    assert env["value"] is None


def test_sentinel_value_surfaces_as_state_flag():
    # A metric whose compute helper yields a sentinel (999 / NaN / -1 / inf)
    # must NOT leak the raw sentinel through `value`.
    for sentinel in (999, -1, float("nan"), float("inf"), float("-inf")):
        md = MetricDef(
            id="__sentinel__",
            label="Sentinel",
            compute=lambda s=sentinel: {"value": s, "status": "x"},
            cohort="none", window="all", unit="ratio", fmt="{}",
        )
        register(md)
        try:
            env = compute_metric("__sentinel__")
            assert env["state"] == "sentinel", f"sentinel {sentinel!r} not flagged"
            assert env["value"] is None
            # never leak a raw NaN/inf/sentinel
            if isinstance(env["value"], float):
                assert not math.isnan(env["value"])
        finally:
            REGISTRY.pop("__sentinel__", None)


def test_ok_value_passes_through_unchanged():
    md = MetricDef(
        id="__ok__",
        label="Ok",
        compute=lambda: {"value": 1.23, "status": "green"},
        cohort="none", window="all", unit="ratio", fmt="{:.2f}",
    )
    register(md)
    try:
        env = compute_metric("__ok__")
        assert env["state"] == "ok"
        assert env["value"] == pytest.approx(1.23)
    finally:
        REGISTRY.pop("__ok__", None)


def test_unknown_metric_id_raises():
    with pytest.raises(KeyError):
        compute_metric("__not_a_metric__")


# ── single-source equivalence (load-bearing) ──────────────────────────────


def test_rf_sharpe_matches_legacy_compute():
    returns = [0.01, 0.02, -0.005, 0.015, 0.008, -0.002, 0.011, 0.004]
    legacy = kpis_compute._compute_rf_adjusted_kpi(returns)
    env = compute_metric("rf_adjusted_sharpe", returns=returns)
    assert env["state"] == "ok"
    assert env["value"] == pytest.approx(legacy["value"])
    assert env["n"] == len(returns)


def test_spy_sharpe_matches_legacy_compute():
    returns = [0.01, 0.02, -0.005, 0.015, 0.008]
    spy = [0.0, 0.01, 0.0, 0.005, 0.002]
    legacy = kpis_compute._compute_spy_relative_kpi(returns, spy)
    env = compute_metric("spy_relative_sharpe", returns=returns, spy_returns=spy)
    assert env["state"] == "ok"
    assert env["value"] == pytest.approx(legacy["value"])
    assert env["n"] == len(returns)


def test_win_rate_matches_legacy_compute():
    trades = [{"pnl_pct": x} for x in (1.0, 2.0, -1.0, 0.5, -0.2, 3.0)]
    legacy = kpis_compute._compute_win_rate_kpi(trades)
    env = compute_metric("win_rate", trades=trades)
    assert env["state"] == "ok"
    assert env["value"] == pytest.approx(legacy["value"])
    assert env["n"] == legacy["n_wins"] + legacy["n_losses"]


def test_equivalence_test_can_fail_if_miswired():
    # Non-vacuous guard: prove the equivalence assertion has teeth by feeding
    # the wrapper a different input than the legacy helper.
    returns = [0.01, 0.02, -0.005, 0.015, 0.008, -0.002, 0.011, 0.004]
    legacy = kpis_compute._compute_rf_adjusted_kpi(returns)
    env = compute_metric("rf_adjusted_sharpe", returns=[r * 5 for r in returns])
    assert env["value"] != pytest.approx(legacy["value"])
