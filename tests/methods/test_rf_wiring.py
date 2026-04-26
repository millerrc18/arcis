"""Regression-locking tests for Sprint-0 Wave-3b RF-WIRING.

Locks down the FRED rf-rate adapter wiring across the methodology toolkit:

  Site                                   Test class
  ---------------------------------------- ---------
  src/methods/_rf_vector.py                TestComputePerPeriodRfVector
  src/methods/cpcv.py                      TestCpcvWithFredRf
  src/methods/block_bootstrap.py           TestBlockBootstrapWithFredRf
  src/methods/mc_permutation.py            TestMcPermutationWithFredRf
  src/methods/promotion_gate.py            TestPromotionGateUsesFredRf

Every assertion is designed to FAIL on the pre-Sprint-0-Wave-3b code base
(rf_period=0.0 hardcoded; no FRED reach) and PASS once the wiring is in
place. We mock src.data_ingestion.risk_free_rate.get_rf_rate to keep the
tests fully offline (per CLAUDE.md "Mock all external APIs in tests").
"""
from __future__ import annotations

import datetime as _dt
import logging
from unittest.mock import patch

import numpy as np
import pytest

from src.methods._rf_vector import (
    RF_PERIOD_CONSTANT,
    compute_per_period_rf_vector,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_BASE_DATE = _dt.date(2026, 3, 2)


def _dates(n: int) -> list[_dt.date]:
    """n consecutive calendar dates starting at _BASE_DATE."""
    return [_BASE_DATE + _dt.timedelta(days=i) for i in range(n)]


def _positive_returns(n: int = 60, seed: int = 7) -> np.ndarray:
    """Strong-edge return series — every period has ~+0.01 + small noise."""
    rng = np.random.default_rng(seed)
    return rng.normal(0.01, 0.002, size=n)


def _zero_mean_returns(n: int = 60, seed: int = 7) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return rng.normal(0.0, 0.01, size=n)


# ---------------------------------------------------------------------------
# TestComputePerPeriodRfVector — base helper
# ---------------------------------------------------------------------------

class TestComputePerPeriodRfVector:
    def test_fred_success_returns_per_day_rate_for_each_date(self):
        """Each date returns the FRED per_day rate; used_fred=True."""
        dates = _dates(5)
        with patch(
            "src.data_ingestion.risk_free_rate.get_rf_rate",
            return_value=0.000167,
        ) as mock_rf:
            rf_vec, used_fred = compute_per_period_rf_vector(dates)
        assert used_fred is True
        assert rf_vec == [0.000167] * 5
        assert mock_rf.call_count == 5
        # The mock must have been called with each date in order
        assert [call.args[0] for call in mock_rf.call_args_list] == dates

    def test_config_error_falls_back_to_constant_per_index(self, caplog):
        """CollectorConfigError → placeholder RF_PERIOD_CONSTANT per index."""
        from src.data_collection.errors import CollectorConfigError

        caplog.set_level(logging.WARNING, logger="src.methods._rf_vector")
        with patch(
            "src.data_ingestion.risk_free_rate.get_rf_rate",
            side_effect=CollectorConfigError("FRED_API_KEY missing"),
        ):
            rf_vec, used_fred = compute_per_period_rf_vector(_dates(3))
        assert used_fred is False
        assert rf_vec == [RF_PERIOD_CONSTANT] * 3
        # WARNING fired with the canonical marker
        warnings = [r for r in caplog.records if "[METHODS_RF_FALLBACK]" in r.getMessage()]
        assert len(warnings) >= 3, f"expected >=3 fallback warnings, got {len(warnings)}"

    def test_network_error_falls_back_per_index(self):
        """ConnectionError / KeyError → placeholder per index."""
        with patch(
            "src.data_ingestion.risk_free_rate.get_rf_rate",
            side_effect=KeyError("no obs"),
        ):
            rf_vec, used_fred = compute_per_period_rf_vector(_dates(4))
        assert used_fred is False
        assert rf_vec == [RF_PERIOD_CONSTANT] * 4

    def test_partial_failure_marks_used_fred_true(self):
        """If at least one date succeeds, used_fred=True even when others fail."""
        call_count = {"n": 0}

        def side_effect(d):
            call_count["n"] += 1
            if call_count["n"] == 2:
                return 0.0005
            raise KeyError("no obs")

        with patch(
            "src.data_ingestion.risk_free_rate.get_rf_rate",
            side_effect=side_effect,
        ):
            rf_vec, used_fred = compute_per_period_rf_vector(_dates(3))
        assert used_fred is True
        assert rf_vec[0] == RF_PERIOD_CONSTANT
        assert rf_vec[1] == 0.0005
        assert rf_vec[2] == RF_PERIOD_CONSTANT

    def test_non_date_input_falls_back_to_constant(self):
        """Non-date entries fall through to placeholder without calling FRED."""
        with patch(
            "src.data_ingestion.risk_free_rate.get_rf_rate",
            return_value=0.0005,
        ) as mock_rf:
            rf_vec, used_fred = compute_per_period_rf_vector(["2026-01-01", None])
        assert rf_vec == [RF_PERIOD_CONSTANT, RF_PERIOD_CONSTANT]
        assert used_fred is False
        assert mock_rf.call_count == 0


# ---------------------------------------------------------------------------
# TestCpcvWithFredRf — locks rf gets pre-subtracted from returns
# ---------------------------------------------------------------------------

class TestCpcvWithFredRf:
    def test_fred_rf_changes_fold_sharpes_vs_zero(self):
        """A non-zero FRED rf MUST shift fold Sharpes vs the legacy rf=0 path.

        This is the regression-locker: in the pre-Sprint-0-W3b world the
        only consumer-facing path was `cpcv(returns, rf_period=0.0)` and a
        non-zero rf had no way to enter. With the wiring, `cpcv_with_fred_rf`
        forces rf adjustment.
        """
        from src.methods.cpcv import cpcv, cpcv_with_fred_rf

        T = 300
        returns = _positive_returns(T)
        dates = _dates(T)

        zero_rf = cpcv(returns, k=5, embargo=10, rf_period=0.0)
        with patch(
            "src.data_ingestion.risk_free_rate.get_rf_rate",
            return_value=0.001,  # > zero so the diff is detectable
        ):
            fred_rf = cpcv_with_fred_rf(returns, dates, k=5, embargo=10)

        # Same fold structure
        assert len(fred_rf["fold_sharpes"]) == len(zero_rf["fold_sharpes"]) == 5
        # Non-zero rf MUST shift fold Sharpes lower (mean(returns)=0.01,
        # subtracting 0.001 lowers per-period mean → lower Sharpe)
        assert fred_rf["used_fred"] is True
        for f, z in zip(fred_rf["fold_sharpes"], zero_rf["fold_sharpes"]):
            assert f is not None and z is not None
            assert f < z, (
                f"FRED rf={0.001} should LOWER fold Sharpe vs rf=0; "
                f"got fred={f} vs zero={z}"
            )

    def test_length_mismatch_raises(self):
        from src.methods.cpcv import cpcv_with_fred_rf

        with pytest.raises(ValueError, match="must equal"):
            cpcv_with_fred_rf(_positive_returns(50), _dates(49), k=2, embargo=1)

    def test_fred_failure_falls_back_to_placeholder_used_fred_false(self):
        """When FRED raises everywhere, used_fred=False; rf vector = [RF_PERIOD_CONSTANT]*n."""
        from src.methods.cpcv import cpcv_with_fred_rf

        T = 300
        with patch(
            "src.data_ingestion.risk_free_rate.get_rf_rate",
            side_effect=ConnectionError("FRED unreachable"),
        ):
            result = cpcv_with_fred_rf(_positive_returns(T), _dates(T), k=5, embargo=10)
        assert result["used_fred"] is False
        assert "fold_sharpes" in result


# ---------------------------------------------------------------------------
# TestBlockBootstrapWithFredRf
# ---------------------------------------------------------------------------

class TestBlockBootstrapWithFredRf:
    def test_fred_rf_shifts_ci_vs_zero(self):
        """Non-zero FRED rf must shift the bootstrap CI vs rf=0."""
        from src.methods.block_bootstrap import (
            block_bootstrap_ci,
            block_bootstrap_ci_with_fred_rf,
        )

        T = 100
        rng = np.random.default_rng(42)
        returns = rng.normal(0.005, 0.01, size=T)
        dates = _dates(T)

        ci_zero = block_bootstrap_ci(returns, rf_period=0.0, n_resamples=200, seed=42)
        with patch(
            "src.data_ingestion.risk_free_rate.get_rf_rate",
            return_value=0.002,
        ):
            (ci_fred, used_fred) = block_bootstrap_ci_with_fred_rf(
                returns, dates, n_resamples=200, seed=42,
            )

        assert used_fred is True
        # Subtracting 0.002 per period lowers mean by ~0.002 → both lo and hi
        # should be strictly lower than the zero-rf CI.
        assert ci_fred[0] < ci_zero[0], (
            f"FRED rf>0 should lower CI lower bound: fred lo={ci_fred[0]}, "
            f"zero lo={ci_zero[0]}"
        )
        assert ci_fred[1] < ci_zero[1], (
            f"FRED rf>0 should lower CI upper bound: fred hi={ci_fred[1]}, "
            f"zero hi={ci_zero[1]}"
        )

    def test_length_mismatch_raises(self):
        from src.methods.block_bootstrap import block_bootstrap_ci_with_fred_rf

        rng = np.random.default_rng(0)
        with pytest.raises(ValueError, match="must equal"):
            block_bootstrap_ci_with_fred_rf(
                rng.normal(0, 1, 50), _dates(49),
            )


# ---------------------------------------------------------------------------
# TestMcPermutationWithFredRf
# ---------------------------------------------------------------------------

class TestMcPermutationWithFredRf:
    def test_fred_rf_pre_subtracts_from_returns(self):
        """The FRED-aware sibling MUST pre-subtract the rf vector from the
        returns before calling the permutation core.

        We verify this by patching `mc_permutation_pvalue` itself and
        inspecting the returns it receives — the input must equal
        `original_returns - rf` (within float tolerance), proving the
        wiring actually fires."""
        from src.methods import mc_permutation as mc_module
        from src.methods.mc_permutation import mc_permutation_pvalue_with_fred_rf

        n = 40
        rng = np.random.default_rng(42)
        returns = rng.normal(0.005, 0.01, size=n).tolist()
        directions = [1 if r > 0 else -1 for r in returns]
        dates = _dates(n)
        rf_value = 0.003

        captured_returns: list[list[float]] = []

        def _spy(rets, dirs, n_permutations, seed=None):
            captured_returns.append(list(rets))
            return 0.42  # canned p-value so the wrapper returns it

        with patch(
            "src.data_ingestion.risk_free_rate.get_rf_rate",
            return_value=rf_value,
        ), patch.object(mc_module, "mc_permutation_pvalue", side_effect=_spy):
            (p, used_fred) = mc_permutation_pvalue_with_fred_rf(
                returns, directions, dates, n_permutations=100, seed=99,
            )

        assert used_fred is True
        assert p == 0.42  # the wrapper passes the canned p-value through
        assert len(captured_returns) == 1
        observed = captured_returns[0]
        expected = [r - rf_value for r in returns]
        for o, e in zip(observed, expected):
            assert abs(o - e) < 1e-12, (
                f"mc_permutation_pvalue MUST be called with rf-excess series; "
                f"got {observed[:3]}... vs expected {expected[:3]}..."
            )

    def test_length_mismatch_raises(self):
        from src.methods.mc_permutation import mc_permutation_pvalue_with_fred_rf

        with pytest.raises(ValueError, match="equal length"):
            mc_permutation_pvalue_with_fred_rf(
                [0.01, 0.02], [1, -1], _dates(3),
            )


# ---------------------------------------------------------------------------
# TestPromotionGateUsesFredRf — the integration-level lock
# ---------------------------------------------------------------------------

class TestPromotionGateUsesFredRf:
    """Verifies the promotion_gate orchestrator wires FRED rf into all 5
    methods when `dates=` is supplied, and preserves backward-compat
    behaviour (rf_source='unwired', no FRED calls) when it isn't.
    """

    def test_dates_supplied_calls_fred_and_marks_rf_source_fred(self):
        """When dates are supplied + FRED is reachable → rf_source='fred_dtb3'
        and the FRED adapter is called once per period."""
        from src.methods.promotion_gate import promotion_gate

        n = 200
        returns = _positive_returns(n)
        dates = _dates(n)
        with patch(
            "src.data_ingestion.risk_free_rate.get_rf_rate",
            return_value=0.0001,
        ) as mock_rf:
            result = promotion_gate(returns, n_trials=1, dates=dates)

        assert result["details"]["rf_source"] == "fred_dtb3"
        # FRED must be called exactly once per period (the wiring did fire).
        assert mock_rf.call_count == n, (
            f"expected {n} FRED calls (one per date); got {mock_rf.call_count}. "
            "FRED wiring was bypassed."
        )

    def test_no_dates_legacy_path_does_not_call_fred(self):
        """Backward-compat: when dates is omitted, rf_source='unwired',
        FRED adapter is NOT called, behaviour matches pre-Wave-3b."""
        from src.methods.promotion_gate import promotion_gate

        n = 200
        returns = _positive_returns(n)
        with patch(
            "src.data_ingestion.risk_free_rate.get_rf_rate",
            return_value=0.0001,
        ) as mock_rf:
            result = promotion_gate(returns, n_trials=1)

        assert result["details"]["rf_source"] == "unwired"
        # Critical regression-locker: legacy path MUST NOT touch FRED.
        assert mock_rf.call_count == 0

    def test_dates_supplied_fred_failure_marks_placeholder(self):
        """When FRED raises (no API key / network), rf_source='placeholder'
        and the gate still produces a decision."""
        from src.methods.promotion_gate import promotion_gate

        n = 200
        returns = _positive_returns(n)
        dates = _dates(n)
        with patch(
            "src.data_ingestion.risk_free_rate.get_rf_rate",
            side_effect=ConnectionError("FRED unreachable"),
        ):
            result = promotion_gate(returns, n_trials=1, dates=dates)

        assert result["details"]["rf_source"] == "placeholder"
        assert result["decision"] in ("promote", "defer", "reject")

    def test_dates_length_mismatch_raises(self):
        from src.methods.promotion_gate import promotion_gate

        n = 200
        returns = _positive_returns(n)
        with pytest.raises(ValueError, match="must equal"):
            promotion_gate(returns, n_trials=1, dates=_dates(n - 1))

    def test_fred_rf_changes_decision_inputs(self):
        """A large enough FRED rf (rf > mean(returns)) must convert a
        positive-mean strategy into negative-excess, which the promotion
        gate's downstream methods MUST see — verifies wiring is end-to-end.

        Concretely: with returns ~ N(0.005, 0.01) and rf=0.02 per period,
        the rf-excess series is overwhelmingly negative — the per-method
        votes (e.g. CPCV mean Sharpe) MUST flip vs the rf=0 path.
        """
        from src.methods.promotion_gate import promotion_gate

        n = 200
        rng = np.random.default_rng(123)
        returns = rng.normal(0.005, 0.01, size=n)
        dates = _dates(n)

        # Run 1: legacy (no dates) — uses returns as-is.
        result_legacy = promotion_gate(returns, n_trials=1)
        # Run 2: FRED rf=0.02 per period — drives excess deeply negative.
        with patch(
            "src.data_ingestion.risk_free_rate.get_rf_rate",
            return_value=0.02,
        ):
            result_fred = promotion_gate(returns, n_trials=1, dates=dates)

        # The CPCV vote value (mean OOS Sharpe) MUST be lower under FRED rf
        # because we subtract a large positive rf from positive returns.
        legacy_cpcv = result_legacy["details"]["cpcv"]["value"]
        fred_cpcv = result_fred["details"]["cpcv"]["value"]
        assert fred_cpcv < legacy_cpcv, (
            "FRED rf wiring must lower the CPCV mean OOS Sharpe when "
            f"rf > mean(returns); got legacy={legacy_cpcv} vs fred={fred_cpcv}. "
            "If these are equal, the rf adjustment never reached CPCV."
        )

    def test_rf_source_logged_at_info(self, caplog):
        """`[PROMOTION_GATE_RF]` info-level log fires when dates supplied."""
        from src.methods.promotion_gate import promotion_gate

        n = 200
        returns = _positive_returns(n)
        dates = _dates(n)
        caplog.set_level(logging.INFO, logger="src.methods.promotion_gate")
        with patch(
            "src.data_ingestion.risk_free_rate.get_rf_rate",
            return_value=0.0001,
        ):
            promotion_gate(returns, n_trials=1, dates=dates)
        msgs = [r.getMessage() for r in caplog.records if "[PROMOTION_GATE_RF]" in r.getMessage()]
        assert msgs, f"expected [PROMOTION_GATE_RF] info log; got {[r.getMessage() for r in caplog.records]}"
        # The marker must include rf_source=fred_dtb3
        assert any("fred_dtb3" in m for m in msgs), msgs
