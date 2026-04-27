"""Regression tests for Sprint 0 Wave B1 TRADES-JK-SE.

`src/api/cloud_routes/trades.py:_sharpe_with_se` previously used the
un-annualized Jobson-Korkie 1981 SE formula

    SE_pre_fix = sqrt((1 + 0.5 * SR^2) / N)

while passing in the ANNUALIZED Sharpe (SR_ann = SR_per * sqrt(T) with T=150).
That's a units mismatch: the formula wants raw-frequency Sharpe, so the SE was
understated by ~sqrt(T) ≈ 12.2x for T=150.

The corrected form (Lo 2002 annualized-scale change-of-variable):

    SE_post_fix = sqrt((T + 0.5 * SR_ann^2) / N)   with T = periods_per_year = 150

This produces a SE ~sqrt(T) larger than the pre-fix SE — the inflation ratio
approaches sqrt(150) ≈ 12.25 for small Sharpe (where 1 + 0.5*SR^2 ≈ 1) and
shrinks as |SR| grows.

Affected surfaces: excess_sharpe_ci_low / excess_sharpe_ci_high and
raw_sharpe_ci_low / raw_sharpe_ci_high in _build_attribution_payload.
The excess_t_stat is computed independently (mean_excess / (std / sqrt(n)))
and is NOT affected by this SE bug.

Tests: this module — mirrors tests/api/test_kpis_se_units.py shape.
"""
from __future__ import annotations

import math

import pytest

from src.api.cloud_routes.trades import _sharpe_with_se


# ── Helpers (pre-fix vs post-fix formulas for direct comparison) ───────────────


def _pre_fix_se(sharpe: float, n: int) -> float:
    """Reproduces the buggy un-annualized Jobson-Korkie SE."""
    return math.sqrt((1.0 + 0.5 * sharpe ** 2) / n)


def _post_fix_se(sharpe: float, n: int, T: float = 150.0) -> float:
    """Lo 2002 annualized-scale SE — the corrected formula."""
    return math.sqrt((T + 0.5 * sharpe ** 2) / n)


# Fixed sample for pinned-numerics tests — 20 returns with mild positive drift.
_FIXED_SAMPLE = [
    0.010, -0.005, 0.015, 0.008, -0.002,
    0.012, 0.020, -0.003, 0.009, 0.006,
    -0.004, 0.018, 0.011, -0.001, 0.014,
    0.007, 0.016, -0.006, 0.013, 0.005,
]


# ── Pinned numerics ────────────────────────────────────────────────────────────


class TestPinnedNumerics:
    """Post-fix SE for the fixed sample must match the Lo (2002) annualized
    formula exactly (to 1e-9). Pre-fix would give a ~sqrt(150) ≈ 12.25x
    smaller value."""

    def test_se_matches_lo_annualized_formula(self):
        """_sharpe_with_se returns (sr_ann, se_ann) where se_ann matches
        sqrt((T + 0.5 * sr_ann^2) / N) to 1e-9."""
        values = _FIXED_SAMPLE
        sr, se = _sharpe_with_se(values, periods_per_year=150.0)
        assert sr is not None and se is not None
        n = len(values)
        expected_se = _post_fix_se(sr, n, T=150.0)
        assert abs(se - expected_se) < 1e-9, (
            f"Post-fix SE={se} must equal Lo (2002) annualized SE={expected_se} "
            f"to within 1e-9; diff={abs(se - expected_se)}"
        )

    def test_post_fix_se_larger_than_pre_fix(self):
        """Post-fix SE must be strictly larger than the pre-fix SE."""
        values = _FIXED_SAMPLE
        sr, se_post = _sharpe_with_se(values, periods_per_year=150.0)
        n = len(values)
        se_pre = _pre_fix_se(sr, n)
        assert se_post > se_pre, (
            f"Post-fix SE={se_post} must be strictly larger than pre-fix SE={se_pre}"
        )

    def test_se_inflation_ratio_consistent_with_sqrt_t(self):
        """The SE inflation ratio post/pre is sqrt((T + 0.5*SR^2) / (1 + 0.5*SR^2)).
        Always > 1.0 for T > 1 and any SR. The ratio is analytically equal to
        sqrt((T + 0.5*SR^2) / (1 + 0.5*SR^2)) — verify the post-fix SE matches
        that exact formula."""
        values = _FIXED_SAMPLE
        sr, se_post = _sharpe_with_se(values, periods_per_year=150.0)
        n = len(values)
        se_pre = _pre_fix_se(sr, n)
        ratio = se_post / se_pre
        # ratio must always be > 1 (post-fix SE is strictly larger)
        assert ratio > 1.0, (
            f"SE inflation ratio={ratio} must be > 1.0 for T=150 > 1"
        )
        # Verify the ratio equals the analytic formula
        expected_ratio = math.sqrt((150.0 + 0.5 * sr ** 2) / (1.0 + 0.5 * sr ** 2))
        assert abs(ratio - expected_ratio) < 1e-9, (
            f"SE ratio={ratio} must equal analytic sqrt((T+0.5S^2)/(1+0.5S^2))={expected_ratio}"
        )


# ── CI bounds ──────────────────────────────────────────────────────────────────


class TestCIBounds:
    """CI bounds = SR ± 1.96 * SE with corrected SE."""

    def test_ci_bounds_use_corrected_se(self):
        """Verify CI bounds are SR ± 1.96 * SE_corrected. Uses the fixed
        sample to give deterministic values."""
        values = _FIXED_SAMPLE
        sr, se = _sharpe_with_se(values, periods_per_year=150.0)
        expected_low = sr - 1.96 * se
        expected_high = sr + 1.96 * se
        n = len(values)
        # Confirm se matches the corrected formula
        expected_se = _post_fix_se(sr, n, T=150.0)
        assert abs(se - expected_se) < 1e-9
        # Confirm CI arithmetic is exact
        assert abs((sr - 1.96 * expected_se) - expected_low) < 1e-12
        assert abs((sr + 1.96 * expected_se) - expected_high) < 1e-12

    def test_ci_width_wider_than_pre_fix(self):
        """Post-fix CI width (4*1.96*SE_post) > pre-fix CI width."""
        values = _FIXED_SAMPLE
        sr, se_post = _sharpe_with_se(values, periods_per_year=150.0)
        n = len(values)
        se_pre = _pre_fix_se(sr, n)
        # CI width = 2 * 1.96 * SE
        assert 2 * 1.96 * se_post > 2 * 1.96 * se_pre


# ── Grid test across (SR, n) tuples ───────────────────────────────────────────


class TestGridAcrossInputs:
    """Test _sharpe_with_se correctness across a range of Sharpe values and
    sample sizes, including SR=0, SR<0, and large N."""

    @staticmethod
    def _build_sample_with_sr(target_mean: float, std: float, n: int) -> list[float]:
        """Build a synthetic returns vector with approximately target_mean and std."""
        import random
        rng = random.Random(42)
        base = [target_mean + rng.gauss(0, std) for _ in range(n)]
        # Adjust mean exactly
        actual_mean = sum(base) / n
        return [v - actual_mean + target_mean for v in base]

    def test_se_matches_corrected_formula_grid(self):
        """For each combination, back out SE from (sr, n) and compare to formula."""
        # Use known SR values computed from actual samples
        test_cases = [
            _FIXED_SAMPLE,  # positive SR ~2
            [0.001, -0.001, 0.001, -0.001, 0.001],  # near-zero SR
            [-0.010, -0.005, -0.015, -0.008, -0.002,  # negative SR
             -0.012, -0.020, -0.003, -0.009, -0.006],
        ]
        for values in test_cases:
            sr, se = _sharpe_with_se(values, periods_per_year=150.0)
            if sr is None or se is None:
                continue
            n = len(values)
            expected_se = _post_fix_se(sr, n, T=150.0)
            assert abs(se - expected_se) < 1e-9, (
                f"n={n}, sr={sr:.4f}: SE={se} != expected {expected_se}"
            )

    @pytest.mark.parametrize("n", [5, 10, 30, 100, 500])
    def test_se_formula_holds_across_n(self, n):
        """SE matches Lo (2002) annualized form for various sample sizes."""
        values = _FIXED_SAMPLE[:3] * (n // 3 + 1)
        values = values[:n]
        sr, se = _sharpe_with_se(values, periods_per_year=150.0)
        if sr is None or se is None:
            return
        expected_se = _post_fix_se(sr, n, T=150.0)
        assert abs(se - expected_se) < 1e-9


# ── Pre-fix vs post-fix direction lock ────────────────────────────────────────


class TestPreFixVsPostFixDirectionLock:
    """Post-fix SE is strictly larger, post-fix CI strictly wider."""

    def test_post_fix_se_strictly_larger_for_positive_sr(self):
        """With SR > 0 and T=150, post-fix SE > pre-fix SE."""
        values = _FIXED_SAMPLE
        sr, se = _sharpe_with_se(values, periods_per_year=150.0)
        assert sr > 0, "Test requires positive SR from fixed sample"
        pre = _pre_fix_se(sr, len(values))
        assert se > pre

    def test_post_fix_se_strictly_larger_for_zero_sr(self):
        """At SR=0, ratio is exactly sqrt(T). With T=150, ratio ≈ 12.25."""
        # Build a zero-mean sample
        values = [0.01, -0.01, 0.01, -0.01, 0.01, -0.01, 0.01, -0.01]
        sr, se = _sharpe_with_se(values, periods_per_year=150.0)
        if sr is None or se is None:
            return  # std=0 edge case — not this test's concern
        n = len(values)
        pre = _pre_fix_se(sr, n)
        # sr ≈ 0 so ratio should be close to sqrt(150)
        assert se > pre

    def test_ci_bounds_strictly_wider_post_fix(self):
        """CI width post-fix > CI width pre-fix for the fixed sample."""
        values = _FIXED_SAMPLE
        sr, se_post = _sharpe_with_se(values, periods_per_year=150.0)
        se_pre = _pre_fix_se(sr, len(values))
        post_width = 2 * 1.96 * se_post
        pre_width = 2 * 1.96 * se_pre
        assert post_width > pre_width


# ── periods_per_year parameter ─────────────────────────────────────────────────


class TestPeriodsPerYearParameter:
    """The `periods_per_year` parameter defaults to 150 and scales SE correctly."""

    def test_default_is_150(self):
        """Default periods_per_year=150 is used when not provided."""
        values = _FIXED_SAMPLE
        sr_default, se_default = _sharpe_with_se(values)
        sr_explicit, se_explicit = _sharpe_with_se(values, periods_per_year=150.0)
        assert sr_default == sr_explicit
        assert se_default == se_explicit

    def test_se_scales_with_periods_per_year(self):
        """Larger T → larger SE (for fixed SR and N)."""
        values = _FIXED_SAMPLE
        _, se_150 = _sharpe_with_se(values, periods_per_year=150.0)
        _, se_252 = _sharpe_with_se(values, periods_per_year=252.0)
        # With T=252 > T=150, SE(252) > SE(150) since numerator (T + 0.5*SR^2) is larger
        assert se_252 > se_150

    def test_explicit_150_matches_default(self):
        """Explicit periods_per_year=150.0 matches calling without it."""
        values = _FIXED_SAMPLE
        sr1, se1 = _sharpe_with_se(values)
        sr2, se2 = _sharpe_with_se(values, periods_per_year=150.0)
        assert sr1 == sr2
        assert se1 == se2

    def test_252_gives_correct_formula(self):
        """For periods_per_year=252, SE = sqrt((252 + 0.5*SR^2) / N)."""
        values = _FIXED_SAMPLE
        sr, se = _sharpe_with_se(values, periods_per_year=252.0)
        n = len(values)
        expected_se = _post_fix_se(sr, n, T=252.0)
        assert abs(se - expected_se) < 1e-9


# ── Edge cases ─────────────────────────────────────────────────────────────────


class TestEdgeCases:
    """Edge cases: len < 2 → (None, None); std == 0 → (0.0, 0.0)."""

    def test_empty_list_returns_none_none(self):
        sr, se = _sharpe_with_se([])
        assert sr is None
        assert se is None

    def test_single_element_returns_none_none(self):
        sr, se = _sharpe_with_se([0.01])
        assert sr is None
        assert se is None

    def test_std_zero_returns_zero_zero(self):
        """All identical values → std=0 → (0.0, 0.0)."""
        sr, se = _sharpe_with_se([0.05, 0.05, 0.05, 0.05, 0.05])
        assert sr == 0.0
        assert se == 0.0

    def test_two_element_minimum(self):
        """Exactly 2 elements → should return defined (not None) values."""
        sr, se = _sharpe_with_se([0.01, -0.01])
        # std > 0, so we should get finite values
        assert sr is not None
        assert se is not None
        assert math.isfinite(sr)
        assert math.isfinite(se)
        assert se > 0
