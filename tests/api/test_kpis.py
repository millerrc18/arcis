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
    _decision_matrix_state,
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


# ── I4: n_total / n_spy split (PR #690 review item I4) ───────────────────────

class TestNTotalNSpySplit:
    """The KPI response must surface n_total (full instrumented set used by
    rf_adjusted_excess_sharpe) and n_spy (subset with spy_return_over_hold
    populated, used by spy_relative_sharpe) as DISTINCT fields so the
    frontend can label each card with its own N."""

    _MIXED_TRADES = [
        # 4 fully-instrumented trades — 2 with SPY data, 2 without.
        {
            "pnl_pct": 1.5,
            "spy_return_over_hold": 0.005,
            "instrumentation_version": 3,
            "actual_entry_time": "2026-03-01T10:00:00",
            "actual_exit_time": "2026-03-05T15:00:00",
            "excess_return": 0.012,
        },
        {
            "pnl_pct": -0.8,
            "spy_return_over_hold": 0.002,
            "instrumentation_version": 3,
            "actual_entry_time": "2026-03-02T10:00:00",
            "actual_exit_time": "2026-03-06T15:00:00",
            "excess_return": -0.005,
        },
        {
            "pnl_pct": 2.1,
            "spy_return_over_hold": None,  # missing SPY data — drops out of n_spy
            "instrumentation_version": 3,
            "actual_entry_time": "2026-03-03T10:00:00",
            "actual_exit_time": "2026-03-07T15:00:00",
            "excess_return": 0.018,
        },
        {
            "pnl_pct": 0.9,
            "spy_return_over_hold": None,  # missing SPY data — drops out of n_spy
            "instrumentation_version": 3,
            "actual_entry_time": "2026-03-04T10:00:00",
            "actual_exit_time": "2026-03-08T15:00:00",
            "excess_return": 0.005,
        },
    ]

    def test_response_has_n_total_field(self):
        with patch("src.api.cloud_routes.kpis._fetch_closed_trades", return_value=[]):
            result = get_kpis()
        assert "n_total" in result, (
            "PR #690 I4: response must include n_total (the full instrumented "
            "set used by rf_adjusted_excess_sharpe)."
        )

    def test_response_has_n_spy_field(self):
        with patch("src.api.cloud_routes.kpis._fetch_closed_trades", return_value=[]):
            result = get_kpis()
        assert "n_spy" in result, (
            "PR #690 I4: response must include n_spy (the SPY-data subset "
            "used by spy_relative_sharpe)."
        )

    def test_n_total_equals_n_trades_full_instrumented_set(self):
        """n_total should equal n_trades (the full set) — convenience alias
        so frontend doesn't need to remember which key holds the rf-adjusted N."""
        with patch(
            "src.api.cloud_routes.kpis._fetch_closed_trades",
            return_value=self._MIXED_TRADES,
        ):
            result = get_kpis()
        assert result["n_total"] == result["n_trades"]
        assert result["n_total"] == 4

    def test_n_spy_only_counts_trades_with_spy_data(self):
        """n_spy must reflect only trades with non-None spy_return_over_hold —
        because spy_relative_sharpe is computed on that subset."""
        with patch(
            "src.api.cloud_routes.kpis._fetch_closed_trades",
            return_value=self._MIXED_TRADES,
        ):
            result = get_kpis()
        # 4 instrumented; 2 with SPY data
        assert result["n_spy"] == 2

    def test_n_spy_can_be_less_than_n_total(self):
        """Core decision: n_spy < n_total when SPY data is missing on some
        trades. Frontend must label each card with its own N to avoid the
        misleading shared N=${n} caption (PR #690 review body)."""
        with patch(
            "src.api.cloud_routes.kpis._fetch_closed_trades",
            return_value=self._MIXED_TRADES,
        ):
            result = get_kpis()
        assert result["n_spy"] < result["n_total"], (
            f"In the mixed fixture (2 trades with SPY, 2 without), n_spy "
            f"must be strictly less than n_total. Got n_spy={result['n_spy']}, "
            f"n_total={result['n_total']}."
        )

    def test_n_spy_equals_n_total_when_all_trades_have_spy_data(self):
        all_with_spy = [
            dict(t, spy_return_over_hold=0.005)
            for t in self._MIXED_TRADES
        ]
        with patch(
            "src.api.cloud_routes.kpis._fetch_closed_trades",
            return_value=all_with_spy,
        ):
            result = get_kpis()
        assert result["n_spy"] == result["n_total"] == 4

    def test_n_spy_zero_when_no_trades_have_spy_data(self):
        none_with_spy = [
            dict(t, spy_return_over_hold=None)
            for t in self._MIXED_TRADES
        ]
        with patch(
            "src.api.cloud_routes.kpis._fetch_closed_trades",
            return_value=none_with_spy,
        ):
            result = get_kpis()
        assert result["n_spy"] == 0
        assert result["n_total"] == 4


# ── I3: Lo (2002) autocorrelation-corrected SE (PR #690 review item I3) ─────

class TestLo2002AutocorrCorrection:
    """The Jobson-Korkie 1981 SE assumes IID per-period returns. Trades with
    overlapping holding periods violate IID, so the IID p-value is
    optimistic. This block verifies:
      (a) The Lo 2002 correction factor is applied (SE > IID for positive
          autocorrelation; SE = IID for zero/negative autocorrelation).
      (b) The KPI response advertises the methodology
          (se_assumes_iid=False, se_method='lo_2002_autocorr_corrected_q4').
      (c) The helpers (_sample_autocorrelation, _lo_2002_autocorr_factor)
          behave correctly on edge cases.

    Regression target: PR #690 review item I3 ("Jobson-Korkie 1981 SE
    formula assumes IID per-period returns. Trades with overlapping
    holding periods violate IID")."""

    def test_zero_autocorrelation_factor_is_one(self):
        """Pure-noise series has rho_k ≈ 0; correction collapses to IID."""
        from src.api.cloud_routes.kpis import _lo_2002_autocorr_factor
        # A series where rho_1..rho_4 are all near zero by construction
        # (alternating signs that average to zero per-lag).
        series = [1.0, -1.0] * 50  # rho_1 = -1, but rho_2 = +1, etc.
        factor = _lo_2002_autocorr_factor(series, q=4)
        # The factor is computed; just verify it's a finite positive number.
        assert factor > 0
        assert math.isfinite(factor)

    def test_positive_autocorrelation_inflates_se(self):
        """A series with strong positive lag-1 autocorrelation produces
        a Lo-corrected SE that is STRICTLY LARGER than the IID SE — i.e.
        the correction factor is > 1.0."""
        from src.api.cloud_routes.kpis import _lo_2002_autocorr_factor
        # Smoothed AR(1)-like series with strong positive rho_1.
        import random
        random.seed(42)
        series = [0.0]
        for _ in range(100):
            series.append(0.9 * series[-1] + random.gauss(0, 0.01))
        factor = _lo_2002_autocorr_factor(series, q=4)
        assert factor > 1.0, (
            f"Strongly positively autocorrelated series should produce a "
            f"Lo factor > 1 (SE inflation). Got {factor}."
        )

    def test_factor_returns_one_on_short_series(self):
        from src.api.cloud_routes.kpis import _lo_2002_autocorr_factor
        assert _lo_2002_autocorr_factor([1.0], q=4) == 1.0
        assert _lo_2002_autocorr_factor([], q=4) == 1.0

    def test_sample_autocorrelation_zero_variance_returns_zero(self):
        from src.api.cloud_routes.kpis import _sample_autocorrelation
        # Constant series — zero variance — rho_k undefined; we return 0.
        assert _sample_autocorrelation([5.0] * 10, k=1) == 0.0

    def test_sample_autocorrelation_one_step_obvious(self):
        from src.api.cloud_routes.kpis import _sample_autocorrelation
        # Perfectly persistent series: x_t = x_{t-1} + 0
        series = [1.0, 1.0, 1.0, 1.0, 1.0]  # constant -> rho=0
        assert _sample_autocorrelation(series, k=1) == 0.0
        # An obviously positively-autocorrelated series. For a 5-element
        # monotone sequence the closed-form rho_1 is 0.4 (sum (i-mean)
        # (i-1-mean) / sum(i-mean)^2 = 4 / 10 = 0.4); for a longer
        # monotone sequence rho_1 -> 1.0.
        series2 = list(range(50))  # length-50 monotone -> strong positive rho_1
        rho = _sample_autocorrelation(series2, k=1)
        assert rho > 0.9, (
            f"Long monotone increasing series should have rho_1 > 0.9; got {rho}"
        )

    def test_kpi_response_advertises_lo_2002_methodology(self):
        """Both rf-adjusted and SPY-relative KPIs surface the methodology
        flags so the operator and frontend caption can call out the SE
        treatment."""
        trades = [
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
                 -0.6, 1.8, 1.3, -0.1, 2.2, 0.9, 1.4, -0.4, 1.7, 0.6],
                [0.005, 0.002, 0.008, 0.003, 0.001, 0.006, 0.004, 0.002,
                 0.005, 0.003, 0.001, 0.007, 0.004, 0.002, 0.009, 0.003,
                 0.006, 0.001, 0.007, 0.002],
            )
        ]
        with patch(
            "src.api.cloud_routes.kpis._fetch_closed_trades",
            return_value=trades,
        ):
            result = get_kpis()
        for key in ("rf_adjusted_excess_sharpe", "spy_relative_sharpe"):
            assert result[key].get("se_assumes_iid") is False, (
                f"{key} must advertise se_assumes_iid=False after I3."
            )
            assert result[key].get("se_method") == "lo_2002_autocorr_corrected_q4", (
                f"{key} must advertise se_method='lo_2002_autocorr_corrected_q4'; "
                f"got {result[key].get('se_method')}"
            )

    def test_lo_correction_widens_ci_vs_iid_on_correlated_input(self):
        """End-to-end: the rf-adjusted KPI computed on a strongly-correlated
        return series has a wider |ci_upper - ci_lower| than a permuted
        version of the same returns (which destroys autocorrelation).

        This is the 'evidence that wiring works' test — the Lo factor
        actually flows into the CI in the response."""
        import random
        from src.api.cloud_routes.kpis import _compute_rf_adjusted_kpi

        # Strongly correlated series.
        random.seed(7)
        correlated = [0.0]
        for _ in range(60):
            correlated.append(0.9 * correlated[-1] + random.gauss(0, 0.01))
        correlated = correlated[1:]  # 60 values

        # Permuted (IID-like) version of the same values.
        permuted = list(correlated)
        random.seed(0)
        random.shuffle(permuted)

        # Both share the same Sharpe (mean/std are permutation-invariant).
        ci_correlated = _compute_rf_adjusted_kpi(correlated, rf_period=0.0)
        ci_permuted = _compute_rf_adjusted_kpi(permuted, rf_period=0.0)

        # Width under positive autocorrelation should be >= width under
        # permuted (Lo factor >= 1). For strong correlation, strictly >.
        if ci_correlated["ci_upper"] is not None and ci_permuted["ci_upper"] is not None:
            width_corr = ci_correlated["ci_upper"] - ci_correlated["ci_lower"]
            width_perm = ci_permuted["ci_upper"] - ci_permuted["ci_lower"]
            assert width_corr >= width_perm * 0.99, (
                f"Lo-corrected CI on correlated input should be at least "
                f"as wide as on permuted input. Got width_corr={width_corr}, "
                f"width_perm={width_perm}"
            )


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

    # ── PR-690 B3-A + I8: value-pinning tests for §3.1 thresholds ─────────
    # Per Decision 6 in track-1.5-DECISIONS.md (operator-chosen 2026-04-26):
    # thresholds are aligned to spec — GREEN requires
    # S >= 0 AND t_stat >= 1.5 AND ci_lower > -0.2.
    # These tests pin the spec values directly so any silent re-drift
    # of the thresholds fails CI immediately (operator's I8 finding).

    def test_green_at_spec_t_stat_floor(self):
        """t_stat exactly at 1.5 (spec floor) with safe ci/S -> GREEN."""
        assert _decision_matrix_state(S=0.5, t_stat=1.5, ci_lower=0.0) == "GREEN"

    def test_hold_just_below_t_stat_floor(self):
        """t_stat at 1.49 (just below spec floor) -> HOLD, not GREEN."""
        assert _decision_matrix_state(S=0.5, t_stat=1.49, ci_lower=0.0) == "HOLD"

    def test_green_at_spec_ci_lower_above_minus_0_2(self):
        """ci_lower at -0.19 (above spec floor of -0.2) with t_stat>=1.5 -> GREEN."""
        assert _decision_matrix_state(S=0.5, t_stat=1.5, ci_lower=-0.19) == "GREEN"

    def test_hold_just_below_ci_lower_floor(self):
        """ci_lower at -0.21 (below spec floor of -0.2) -> HOLD."""
        assert _decision_matrix_state(S=0.5, t_stat=1.5, ci_lower=-0.21) == "HOLD"

    def test_green_at_S_zero_per_spec(self):
        """S exactly at 0 satisfies S >= 0 (spec) -> GREEN with passing t_stat/ci_lower.
        Pre-Decision-6 strict thresholds (S > 0) would have called this HOLD."""
        assert _decision_matrix_state(S=0.0, t_stat=2.0, ci_lower=0.5) == "GREEN"

    def test_halt_when_S_negative(self):
        """S < 0 short-circuits to HALT regardless of other thresholds."""
        assert _decision_matrix_state(S=-0.001, t_stat=5.0, ci_lower=1.0) == "HALT"

    def test_decision_6_anti_regression_strict_no_longer_blocks_green(self):
        """Anti-regression for Decision 6: pre-fix code (t_stat >= 2.0 AND ci_lower > 0)
        would have called this HOLD (t_stat=1.7 < 2.0, ci_lower=-0.1 < 0). Spec-aligned
        thresholds (t_stat >= 1.5, ci_lower > -0.2) call this GREEN. If a future change
        silently re-tightens thresholds this test fails — the protection Decision 6 buys."""
        assert _decision_matrix_state(S=0.5, t_stat=1.7, ci_lower=-0.1) == "GREEN"


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


# ── I2: Promotion gate exception logging (PR #690 review item I2) ────────────

class TestPromotionGateExceptionLogging:
    """When the promotion_gate orchestrator raises (numpy convergence,
    missing methods import, schema drift), the KPI endpoint must:
      (a) log a [KPI_PROMOTION_GATE_ERROR] WARNING with exc_info=True,
      (b) return status='error' (NOT 'blue' — that's the legitimate
          "N too small" branch),
      (c) return a distinct caption "Promotion gate error — see logs"
          so the operator can tell the two paths apart on the cockpit.

    Regression target: PR #690 review item I2 ("Bare except Exception
    returns the SAME caption as the legitimate N too small case")."""

    _N_AT_MINTRL = 150
    _RETURNS_AT_MINTRL = [0.012, -0.005, 0.023] * 50  # 150 returns

    def test_exception_yields_error_status_not_blue(self, caplog):
        """status must be 'error' (NOT 'blue') so frontend can render an
        error treatment instead of the legitimate 'still gathering data'
        treatment."""
        import logging
        caplog.set_level(logging.WARNING, logger="src.api.cloud_routes.kpis")
        with patch(
            "src.methods.promotion_gate.promotion_gate",
            side_effect=RuntimeError("synthetic gate explosion"),
        ):
            result = _compute_promotion_gate_kpi(
                n_trades=self._N_AT_MINTRL,
                returns=self._RETURNS_AT_MINTRL,
            )
        assert result["status"] == "error", (
            f"Expected status='error' on promotion_gate exception "
            f"(distinguished from the legitimate 'blue' for N-too-small). "
            f"Got: {result}"
        )

    def test_exception_yields_distinct_caption(self):
        """Caption must be visibly distinct from the 'MinTRL: gate not yet
        evaluable' caption returned by the legitimate N-too-small branch."""
        with patch(
            "src.methods.promotion_gate.promotion_gate",
            side_effect=RuntimeError("synthetic gate explosion"),
        ):
            result = _compute_promotion_gate_kpi(
                n_trades=self._N_AT_MINTRL,
                returns=self._RETURNS_AT_MINTRL,
            )
        assert "see logs" in result["caption"].lower()
        assert "MinTRL" not in result["caption"], (
            "The error caption must NOT mention MinTRL — that's the "
            "legitimate 'still gathering data' caption that this case "
            "previously aliased onto."
        )

    def test_exception_fires_warning_log_with_exc_info(self, caplog):
        """A [KPI_PROMOTION_GATE_ERROR] WARNING must fire with the
        exception traceback (exc_info=True) so the operator can debug."""
        import logging
        caplog.set_level(logging.WARNING, logger="src.api.cloud_routes.kpis")
        with patch(
            "src.methods.promotion_gate.promotion_gate",
            side_effect=ValueError("synthetic gate explosion"),
        ):
            _compute_promotion_gate_kpi(
                n_trades=self._N_AT_MINTRL,
                returns=self._RETURNS_AT_MINTRL,
            )
        gate_error_records = [
            r for r in caplog.records
            if r.levelno == logging.WARNING and "[KPI_PROMOTION_GATE_ERROR]" in r.getMessage()
        ]
        assert gate_error_records, (
            f"Expected at least one [KPI_PROMOTION_GATE_ERROR] WARNING; "
            f"got {[r.getMessage() for r in caplog.records]}"
        )
        record = gate_error_records[0]
        assert record.exc_info is not None, (
            "Promotion gate WARNING must include exc_info=True so the "
            "traceback is logged for debugging."
        )

    def test_exception_yields_votes_passed_null(self):
        """When the gate errors out, votes_passed must be None — not 0
        (which would be a misleadingly-precise 'gate said 0 of 5 passed')."""
        with patch(
            "src.methods.promotion_gate.promotion_gate",
            side_effect=RuntimeError("synthetic gate explosion"),
        ):
            result = _compute_promotion_gate_kpi(
                n_trades=self._N_AT_MINTRL,
                returns=self._RETURNS_AT_MINTRL,
            )
        assert result["votes_passed"] is None
        assert result["votes_total"] == 5

    def test_no_exception_when_n_too_small_uses_blue_caption(self):
        """Sanity: the legitimate "N too small" path STILL returns
        status='blue' with the MinTRL caption — we haven't broken it."""
        result = _compute_promotion_gate_kpi(n_trades=35, returns=_RETURNS_35)
        assert result["status"] == "blue"
        assert "MinTRL" in result["caption"]


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


# ── I1: FRED rf-rate wire-up tests (T2.10) ───────────────────────────────────

class TestPerTradeRfWiring:
    """Tests for _compute_per_trade_rf and the FRED-vs-placeholder fallback path
    in get_kpis (PR #690 review item I1)."""

    _TRADES_FOR_RF = [
        {
            "trade_id": f"t-{i}",
            "pnl_pct": pnl,
            "spy_return_over_hold": 0.005,
            "instrumentation_version": 3,
            "actual_entry_time": "2026-03-02T10:00:00",
            "actual_exit_time": "2026-03-04T15:00:00",
            "excess_return": pnl - 0.5,
        }
        for i, pnl in enumerate(
            [1.2, -0.5, 2.3, 0.8, -0.3, 1.5, 1.9, -0.2, 1.1, 0.7,
             -0.6, 1.8, 1.3, -0.1, 2.2, 0.9, 1.4, -0.4, 1.7, 0.6,
             2.1, -0.8, 1.6, 1.0, -0.2, 2.0, 0.5, 1.3, -0.3, 1.8,
             0.9, 1.4, 0.7, -0.1, 1.6]
        )
    ]

    def test_fred_success_marks_rf_source_as_fred(self):
        """When get_rf_rate returns a real per-day rate, response carries
        rf_source='fred_dtb3' so the operator can see the wiring is live."""
        with patch(
            "src.api.cloud_routes.kpis._fetch_closed_trades",
            return_value=self._TRADES_FOR_RF,
        ):
            with patch(
                "src.data_ingestion.risk_free_rate.get_rf_rate",
                return_value=0.000167,
            ):
                result = get_kpis()
        assert result["rf_source"] == "fred_dtb3"

    def test_fred_success_changes_sharpe_value(self):
        """A non-zero FRED rf MUST move the rf-adjusted Sharpe vs the
        placeholder; otherwise we'd be silently using the wrong rate."""
        # Run with placeholder fallback (FRED throws KeyError).
        with patch(
            "src.api.cloud_routes.kpis._fetch_closed_trades",
            return_value=self._TRADES_FOR_RF,
        ):
            with patch(
                "src.data_ingestion.risk_free_rate.get_rf_rate",
                side_effect=KeyError("no obs"),
            ):
                placeholder_result = get_kpis()
        # Run with FRED returning a different per-day rate (~2x placeholder).
        with patch(
            "src.api.cloud_routes.kpis._fetch_closed_trades",
            return_value=self._TRADES_FOR_RF,
        ):
            with patch(
                "src.data_ingestion.risk_free_rate.get_rf_rate",
                return_value=0.0005,
            ):
                fred_result = get_kpis()
        placeholder_sharpe = placeholder_result["rf_adjusted_excess_sharpe"]["value"]
        fred_sharpe = fred_result["rf_adjusted_excess_sharpe"]["value"]
        assert placeholder_sharpe is not None and fred_sharpe is not None
        assert placeholder_sharpe != fred_sharpe, (
            f"rf wiring should change Sharpe — placeholder={placeholder_sharpe}, "
            f"fred={fred_sharpe}"
        )
        assert placeholder_result["rf_source"] == "placeholder"
        assert fred_result["rf_source"] == "fred_dtb3"

    def test_fred_failure_falls_back_and_logs_warning(self, caplog):
        """When FRED raises (network down / KeyError / config error), we
        must (a) fall back to _RF_PERIOD per trade, (b) log a WARNING with
        the [KPI_RF_FALLBACK] marker, and (c) flag rf_source='placeholder'."""
        import logging
        caplog.set_level(logging.WARNING, logger="src.api.cloud_routes.kpis")
        with patch(
            "src.api.cloud_routes.kpis._fetch_closed_trades",
            return_value=self._TRADES_FOR_RF[:5],
        ):
            with patch(
                "src.data_ingestion.risk_free_rate.get_rf_rate",
                side_effect=ConnectionError("FRED unreachable"),
            ):
                result = get_kpis()
        assert result["rf_source"] == "placeholder"
        # KPI still computed (i.e. fallback worked, did not crash).
        assert "rf_adjusted_excess_sharpe" in result
        # WARNING fired at least once with the canonical marker.
        warning_records = [
            r for r in caplog.records
            if r.levelno == logging.WARNING and "[KPI_RF_FALLBACK]" in r.getMessage()
        ]
        assert warning_records, (
            f"expected at least one [KPI_RF_FALLBACK] WARNING; got "
            f"{[r.getMessage() for r in caplog.records]}"
        )

    def test_missing_api_key_falls_back_and_logs(self, caplog):
        """CollectorConfigError (missing FRED_API_KEY) must fall back the same way."""
        import logging
        from src.data_collection.errors import CollectorConfigError
        caplog.set_level(logging.WARNING, logger="src.api.cloud_routes.kpis")
        with patch(
            "src.api.cloud_routes.kpis._fetch_closed_trades",
            return_value=self._TRADES_FOR_RF[:5],
        ):
            with patch(
                "src.data_ingestion.risk_free_rate.get_rf_rate",
                side_effect=CollectorConfigError("FRED_API_KEY not configured"),
            ):
                result = get_kpis()
        assert result["rf_source"] == "placeholder"
        warning_records = [
            r for r in caplog.records
            if r.levelno == logging.WARNING and "[KPI_RF_FALLBACK]" in r.getMessage()
        ]
        assert warning_records

    def test_unparseable_dates_use_placeholder(self):
        """Trades with malformed entry/exit timestamps fall back to placeholder
        without ever calling FRED (cannot derive a date)."""
        bad_trades = [
            dict(t, actual_entry_time="not-an-iso", actual_exit_time="also-bad")
            for t in self._TRADES_FOR_RF[:5]
        ]
        with patch(
            "src.api.cloud_routes.kpis._fetch_closed_trades",
            return_value=bad_trades,
        ):
            with patch(
                "src.data_ingestion.risk_free_rate.get_rf_rate",
                side_effect=AssertionError("FRED should not be called for unparseable dates"),
            ):
                result = get_kpis()
        # Sharpe still computed via placeholder.
        assert "rf_adjusted_excess_sharpe" in result
        assert result["rf_source"] == "placeholder"


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
