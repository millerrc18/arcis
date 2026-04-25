"""Tests for the /api/kpis endpoint — 5-KPI hero strip backend.

Called by: pytest (CI)
Calls: src.api.cloud_routes.kpis
Owns tables: none
Config keys: none
Tests: Track 1.5 / Round 8.B backend tests; Round 8.E SPY wire-up
"""
from __future__ import annotations

import math
from unittest.mock import patch

import pytest

from src.api.cloud_routes.kpis import (
    _compute_rf_adjusted_kpi,
    _compute_spy_relative_kpi,
    _compute_win_rate_kpi,
    _compute_stage_traffic_light,
    _compute_promotion_gate_kpi,
    _compute_instrumentation_pct,
    _fetch_spy_returns_for_trades,
    get_kpis,
)


# ── Fixtures ─────────────────────────────────────────────────────────────────

_RETURNS_35 = [0.012, -0.005, 0.023, 0.008, -0.003, 0.015, 0.019, -0.002,
               0.011, 0.007, -0.006, 0.018, 0.013, -0.001, 0.022, 0.009,
               0.014, -0.004, 0.017, 0.006, 0.021, -0.008, 0.016, 0.010,
               -0.002, 0.020, 0.005, 0.013, -0.003, 0.018, 0.009, 0.014,
               0.007, -0.001, 0.016]

_SPY_RETURNS_35 = [0.005, 0.002, 0.008, 0.003, 0.001, 0.006, 0.004, 0.002,
                   0.005, 0.003, 0.001, 0.007, 0.004, 0.002, 0.009, 0.003,
                   0.006, 0.001, 0.007, 0.002, 0.008, 0.001, 0.006, 0.004,
                   0.001, 0.008, 0.002, 0.005, 0.001, 0.007, 0.003, 0.005,
                   0.002, 0.001, 0.006]

_WIN_LOSS_TRADES = [
    {"pnl_pct": 2.3, "actual_entry_time": "2026-03-01T10:00:00", "actual_exit_time": "2026-03-05T15:00:00", "excess_return": 0.012},
    {"pnl_pct": -1.1, "actual_entry_time": "2026-03-02T10:00:00", "actual_exit_time": "2026-03-06T15:00:00", "excess_return": -0.005},
    {"pnl_pct": 3.1, "actual_entry_time": "2026-03-03T10:00:00", "actual_exit_time": "2026-03-07T15:00:00", "excess_return": 0.018},
    {"pnl_pct": 1.5, "actual_entry_time": "2026-03-04T10:00:00", "actual_exit_time": "2026-03-08T15:00:00", "excess_return": 0.009},
    {"pnl_pct": -0.8, "actual_entry_time": "2026-03-05T10:00:00", "actual_exit_time": "2026-03-09T15:00:00", "excess_return": -0.003},
]


# ── Shape tests ───────────────────────────────────────────────────────────────

class TestGetKpisResponseShape:
    def test_returns_all_top_level_keys(self):
        with patch("src.api.cloud_routes.kpis._fetch_closed_trades", return_value=[]):
            result = get_kpis()
        assert "n_trades" in result
        assert "n_minimum_trl" in result
        assert "as_of" in result
        assert "rf_adjusted_excess_sharpe" in result
        assert "spy_relative_sharpe" in result
        assert "win_rate" in result
        assert "stage_traffic_light" in result
        assert "promotion_gate" in result

    def test_rf_adjusted_sharpe_has_required_keys(self):
        with patch("src.api.cloud_routes.kpis._fetch_closed_trades", return_value=[]):
            result = get_kpis()
        kpi = result["rf_adjusted_excess_sharpe"]
        for k in ("value", "p_value", "ci_lower", "ci_upper", "status"):
            assert k in kpi, f"Missing key: {k}"

    def test_spy_relative_sharpe_has_required_keys(self):
        with patch("src.api.cloud_routes.kpis._fetch_closed_trades", return_value=[]):
            result = get_kpis()
        kpi = result["spy_relative_sharpe"]
        for k in ("value", "p_value", "ci_lower", "ci_upper", "status"):
            assert k in kpi

    def test_win_rate_has_required_keys(self):
        with patch("src.api.cloud_routes.kpis._fetch_closed_trades", return_value=[]):
            result = get_kpis()
        kpi = result["win_rate"]
        for k in ("value", "n_wins", "n_losses", "status"):
            assert k in kpi

    def test_stage_traffic_light_has_required_keys(self):
        with patch("src.api.cloud_routes.kpis._fetch_closed_trades", return_value=[]):
            result = get_kpis()
        kpi = result["stage_traffic_light"]
        for k in ("status", "S", "t_stat", "ci_lower", "decision_matrix_state"):
            assert k in kpi

    def test_promotion_gate_has_required_keys(self):
        with patch("src.api.cloud_routes.kpis._fetch_closed_trades", return_value=[]):
            result = get_kpis()
        kpi = result["promotion_gate"]
        for k in ("votes_passed", "votes_total", "status", "caption"):
            assert k in kpi

    def test_n_minimum_trl_is_150(self):
        with patch("src.api.cloud_routes.kpis._fetch_closed_trades", return_value=[]):
            result = get_kpis()
        assert result["n_minimum_trl"] == 150


# ── Empty-DB rendering tests ──────────────────────────────────────────────────

class TestEmptyDbRendering:
    def _empty_result(self):
        with patch("src.api.cloud_routes.kpis._fetch_closed_trades", return_value=[]):
            return get_kpis()

    def test_n_trades_is_zero(self):
        result = self._empty_result()
        assert result["n_trades"] == 0

    def test_all_kpi_values_are_null(self):
        result = self._empty_result()
        for key in ("rf_adjusted_excess_sharpe", "spy_relative_sharpe", "win_rate"):
            assert result[key]["value"] is None, f"{key}.value should be None"

    def test_all_kpi_statuses_are_unknown(self):
        result = self._empty_result()
        for key in ("rf_adjusted_excess_sharpe", "spy_relative_sharpe", "win_rate",
                    "stage_traffic_light"):
            assert result[key]["status"] == "unknown", f"{key}.status should be 'unknown'"

    def test_promotion_gate_caption_has_no_closed_trades(self):
        result = self._empty_result()
        assert "no closed trades" in result["promotion_gate"]["caption"].lower()


# ── Color status tests (per Decision 4 rules) ─────────────────────────────────

class TestRfAdjustedSharpeStatus:
    def test_green_when_positive_and_significant(self):
        result = _compute_rf_adjusted_kpi(returns=_RETURNS_35, rf_period=0.0001)
        if result["value"] is not None and result["value"] > 0 and result["p_value"] is not None:
            if result["p_value"] < 0.05:
                assert result["status"] == "green"

    def test_amber_when_positive_but_not_significant(self):
        # Manually test color logic: positive S, p >= 0.05
        from src.api.cloud_routes.kpis import _kpi_status_rf_sharpe
        assert _kpi_status_rf_sharpe(S=1.5, p=0.10) == "amber"

    def test_red_when_negative_and_significant(self):
        from src.api.cloud_routes.kpis import _kpi_status_rf_sharpe
        assert _kpi_status_rf_sharpe(S=-1.5, p=0.02) == "red"

    def test_unknown_when_none(self):
        from src.api.cloud_routes.kpis import _kpi_status_rf_sharpe
        assert _kpi_status_rf_sharpe(S=None, p=None) == "unknown"


class TestSpyRelativeSharpeStatus:
    def test_green_when_positive_significant_ci_positive(self):
        from src.api.cloud_routes.kpis import _kpi_status_spy_sharpe
        assert _kpi_status_spy_sharpe(S=2.0, p=0.05, ci_lower=0.10) == "green"

    def test_amber_when_positive_but_not_sig(self):
        from src.api.cloud_routes.kpis import _kpi_status_spy_sharpe
        assert _kpi_status_spy_sharpe(S=1.0, p=0.20, ci_lower=-0.5) == "amber"

    def test_red_when_negative_and_significant(self):
        from src.api.cloud_routes.kpis import _kpi_status_spy_sharpe
        assert _kpi_status_spy_sharpe(S=-1.5, p=0.05, ci_lower=-2.0) == "red"

    def test_unknown_when_none(self):
        from src.api.cloud_routes.kpis import _kpi_status_spy_sharpe
        assert _kpi_status_spy_sharpe(S=None, p=None, ci_lower=None) == "unknown"


class TestWinRateStatus:
    def test_green_above_55pct(self):
        from src.api.cloud_routes.kpis import _kpi_status_win_rate
        assert _kpi_status_win_rate(0.60) == "green"

    def test_amber_45_to_55(self):
        from src.api.cloud_routes.kpis import _kpi_status_win_rate
        assert _kpi_status_win_rate(0.50) == "amber"

    def test_red_below_45pct(self):
        from src.api.cloud_routes.kpis import _kpi_status_win_rate
        assert _kpi_status_win_rate(0.40) == "red"

    def test_unknown_when_none(self):
        from src.api.cloud_routes.kpis import _kpi_status_win_rate
        assert _kpi_status_win_rate(None) == "unknown"

    def test_boundary_exactly_55_is_green(self):
        from src.api.cloud_routes.kpis import _kpi_status_win_rate
        assert _kpi_status_win_rate(0.55) == "green"

    def test_boundary_exactly_45_is_amber(self):
        from src.api.cloud_routes.kpis import _kpi_status_win_rate
        assert _kpi_status_win_rate(0.45) == "amber"


class TestStageTrafficLight:
    def test_decision_matrix_state_is_enum_string(self):
        result = _compute_stage_traffic_light(returns=_RETURNS_35, rf_period=0.0001)
        assert result["decision_matrix_state"] in ("GREEN", "HOLD", "HALT")

    def test_status_maps_to_css_color(self):
        result = _compute_stage_traffic_light(returns=_RETURNS_35, rf_period=0.0001)
        assert result["status"] in ("green", "amber", "red", "unknown")

    def test_empty_returns_gives_unknown(self):
        result = _compute_stage_traffic_light(returns=[], rf_period=0.0001)
        assert result["status"] == "unknown"
        assert result["decision_matrix_state"] == "HALT"


class TestPromotionGateKpi:
    def test_below_mintrl_gives_blue_status(self):
        result = _compute_promotion_gate_kpi(n_trades=35, returns=_RETURNS_35)
        assert result["status"] == "blue"

    def test_below_mintrl_caption_has_mintrl_text(self):
        result = _compute_promotion_gate_kpi(n_trades=35, returns=_RETURNS_35)
        assert "MinTRL" in result["caption"]

    def test_votes_total_is_5(self):
        result = _compute_promotion_gate_kpi(n_trades=35, returns=_RETURNS_35)
        assert result["votes_total"] == 5

    def test_below_mintrl_votes_passed_is_null(self):
        result = _compute_promotion_gate_kpi(n_trades=35, returns=_RETURNS_35)
        assert result["votes_passed"] is None

    def test_zero_trades_gives_blue_status(self):
        result = _compute_promotion_gate_kpi(n_trades=0, returns=[])
        assert result["status"] == "blue"


# ── Win rate calculation unit test ────────────────────────────────────────────

class TestWinRateCalculation:
    def test_win_rate_value_and_counts(self):
        result = _compute_win_rate_kpi(_WIN_LOSS_TRADES)
        assert result["n_wins"] == 3
        assert result["n_losses"] == 2
        assert abs(result["value"] - 0.60) < 0.01

    def test_all_wins(self):
        trades = [{"pnl_pct": 1.0, "actual_entry_time": "2026-03-01T10:00:00",
                   "actual_exit_time": "2026-03-05T15:00:00", "excess_return": 0.01}] * 3
        result = _compute_win_rate_kpi(trades)
        assert result["n_wins"] == 3
        assert result["n_losses"] == 0
        assert result["value"] == 1.0
        assert result["status"] == "green"


# ── Instrumentation pct ───────────────────────────────────────────────────────

class TestInstrumentationPct:
    def test_all_v3_returns_100(self):
        trades = [{"instrumentation_version": 3}] * 5
        result = _compute_instrumentation_pct(trades)
        assert result == 100.0

    def test_empty_trades_returns_none(self):
        result = _compute_instrumentation_pct([])
        assert result is None

    def test_mixed_returns_correct_pct(self):
        trades = [{"instrumentation_version": 3}] * 3 + [{"instrumentation_version": 2}] * 2
        result = _compute_instrumentation_pct(trades)
        assert abs(result - 60.0) < 0.1


# ── SPY data source wire-up tests (Round 8.E) ────────────────────────────────

class TestFetchSpyReturnsForTrades:
    """Tests for _fetch_spy_returns_for_trades — extracts spy_return_over_hold
    from trade dicts. Replaces the stub that returned [] always."""

    def test_returns_list_of_floats_when_spy_data_present(self):
        trades = [
            {"spy_return_over_hold": 0.005},
            {"spy_return_over_hold": 0.002},
            {"spy_return_over_hold": -0.001},
        ]
        result = _fetch_spy_returns_for_trades(trades)
        assert result == [0.005, 0.002, -0.001]

    def test_returns_empty_list_for_empty_trades(self):
        result = _fetch_spy_returns_for_trades([])
        assert result == []

    def test_filters_out_none_spy_returns_as_empty(self):
        trades = [
            {"spy_return_over_hold": None},
            {"spy_return_over_hold": None},
        ]
        result = _fetch_spy_returns_for_trades(trades)
        assert result == []

    def test_mixed_none_and_real_returns_only_non_none(self):
        trades = [
            {"spy_return_over_hold": 0.005},
            {"spy_return_over_hold": None},
            {"spy_return_over_hold": 0.002},
        ]
        result = _fetch_spy_returns_for_trades(trades)
        assert result == [0.005, 0.002]

    def test_missing_key_treated_as_none(self):
        trades = [
            {"pnl_pct": 1.0},
            {"pnl_pct": 2.0},
        ]
        result = _fetch_spy_returns_for_trades(trades)
        assert result == []


class TestSpyRelativeKpiWithRealData:
    """When spy_return_over_hold data is present, spy_relative_sharpe should
    not be 'unknown'. Previously the stub returned [] causing all operators
    to see status='unknown' for SPY-relative KPI (Decision-4 requirement)."""

    _TRADES_WITH_SPY = [
        {
            "pnl_pct": pnl,
            "spy_return_over_hold": spy,
            "instrumentation_version": 3,
            "actual_entry_time": "2026-03-01T10:00:00",
            "actual_exit_time": "2026-03-05T15:00:00",
            "excess_return": pnl - spy * 100.0,
        }
        for pnl, spy in zip(
            [1.2, -0.5, 2.3, 0.8, -0.3, 1.5, 1.9, -0.2, 1.1, 0.7,
             -0.6, 1.8, 1.3, -0.1, 2.2, 0.9, 1.4, -0.4, 1.7, 0.6,
             2.1, -0.8, 1.6, 1.0, -0.2, 2.0, 0.5, 1.3, -0.3, 1.8,
             0.9, 1.4, 0.7, -0.1, 1.6],
            [0.005, 0.002, 0.008, 0.003, 0.001, 0.006, 0.004, 0.002,
             0.005, 0.003, 0.001, 0.007, 0.004, 0.002, 0.009, 0.003,
             0.006, 0.001, 0.007, 0.002, 0.008, 0.001, 0.006, 0.004,
             0.001, 0.008, 0.002, 0.005, 0.001, 0.007, 0.003, 0.005,
             0.002, 0.001, 0.006],
        )
    ]

    def test_spy_relative_status_not_unknown_when_spy_data_present(self):
        """Core Decision-4 requirement: when SPY data is available, status
        must not be 'unknown'."""
        from src.analytics.instrumentation_filter import filter_fully_instrumented
        instrumented = filter_fully_instrumented(self._TRADES_WITH_SPY)
        returns = [float(t.get("pnl_pct") or 0) / 100.0 for t in instrumented]
        spy_returns = _fetch_spy_returns_for_trades(instrumented)
        result = _compute_spy_relative_kpi(returns, spy_returns)
        assert result["status"] != "unknown", (
            f"SPY-relative status should not be 'unknown' when spy data present, "
            f"got: {result}"
        )

    def test_get_kpis_spy_relative_not_unknown_when_trades_have_spy_data(self):
        """Integration test: get_kpis() uses real spy data from trades."""
        with patch(
            "src.api.cloud_routes.kpis._fetch_closed_trades",
            return_value=self._TRADES_WITH_SPY,
        ):
            result = get_kpis()
        assert result["spy_relative_sharpe"]["status"] != "unknown", (
            f"SPY status should not be unknown with real data, got: {result['spy_relative_sharpe']}"
        )

    def test_get_kpis_spy_relative_unknown_when_no_spy_data(self):
        """When trades have no spy_return_over_hold, status should remain 'unknown'."""
        trades_no_spy = [
            {
                "pnl_pct": 1.0, "spy_return_over_hold": None,
                "instrumentation_version": 3,
                "actual_entry_time": "2026-03-01T10:00:00",
                "actual_exit_time": "2026-03-05T15:00:00",
                "excess_return": 0.5,
            }
        ] * 5
        with patch(
            "src.api.cloud_routes.kpis._fetch_closed_trades",
            return_value=trades_no_spy,
        ):
            result = get_kpis()
        assert result["spy_relative_sharpe"]["status"] == "unknown"


# ── Double-prefix regression test (Round 8.E) ────────────────────────────────

class TestMonitoringRouteNoPrefixDouble:
    """Regression test: system.py routes /monitoring/* must be accessible
    at /api/monitoring/* (not /api/api/monitoring/*) when router is mounted
    with prefix='/api' in app.py."""

    def test_monitoring_history_route_registered_without_api_prefix(self):
        """The route path stored on the router must not start with /api/."""
        from src.api.routes.system import router
        history_routes = [r for r in router.routes if hasattr(r, "path") and "monitoring/history" in r.path]
        assert history_routes, "No monitoring/history route found in system.router"
        for route in history_routes:
            assert not route.path.startswith("/api/"), (
                f"Route '{route.path}' has double /api prefix — "
                f"mount prefix adds /api, so this would serve at /api{route.path}"
            )

    def test_monitoring_snapshot_route_registered_without_api_prefix(self):
        """The route path stored on the router must not start with /api/."""
        from src.api.routes.system import router
        snapshot_routes = [r for r in router.routes if hasattr(r, "path") and "monitoring/snapshot" in r.path]
        assert snapshot_routes, "No monitoring/snapshot route found in system.router"
        for route in snapshot_routes:
            assert not route.path.startswith("/api/"), (
                f"Route '{route.path}' has double /api prefix"
            )
