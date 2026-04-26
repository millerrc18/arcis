"""Regression tests for Sprint 0 Wave 4b KPIS-SE-UNITS.

`src/api/cloud_routes/kpis.py:_sharpe_t_stat_and_ci` previously used the
un-annualized Jobson-Korkie 1981 SE formula

    SE_pre_fix = sqrt((1 + 0.5 * S^2) / N)

while passing in the ANNUALIZED Sharpe (computed via
`canonical_sharpe.rf_adjusted_excess_sharpe` at periods_per_year=252).
That's a units mismatch: the formula wants raw-frequency Sharpe, so the
SE was understated by ≈sqrt(T) and t-stats were inflated.

The corrected form (Lo 2002 annualized-scale change-of-variable):

    SE_post_fix = sqrt((T + 0.5 * S^2) / N)   with T = periods_per_year = 252

This produces a SE ≈ sqrt(T) larger than the pre-fix SE — the inflation
ratio approaches sqrt(252) ≈ 15.87 for small Sharpe (where 1 + 0.5 S^2
≈ 1) and shrinks as |S| grows (the (T + 0.5 S^2) numerator catches up).

These tests pin the dimensional correction:
  1. Direct numeric check against the textbook Lo formula
  2. Pre-fix vs post-fix SE inflation ratio
  3. End-to-end direction: post-fix p-value > pre-fix p-value (positive S)
  4. Periods-per-year parameter is honored (different T → different SE)

Tests: this module.
"""
from __future__ import annotations

import math

import pytest

from src.api.cloud_routes.kpis import _sharpe_t_stat_and_ci, _N_PER_YEAR


# ── Helpers ───────────────────────────────────────────────────────────────────


def _pre_fix_se(sharpe: float, n: int) -> float:
    """Reproduces the buggy un-annualized Jobson-Korkie SE so we can
    show the numerical magnitude of the dimensional mismatch."""
    return math.sqrt((1.0 + 0.5 * sharpe ** 2) / n)


def _post_fix_se(sharpe: float, n: int, T: float = 252.0) -> float:
    """Lo 2002 annualized-scale SE — the corrected formula."""
    return math.sqrt((T + 0.5 * sharpe ** 2) / n)


# ── Direct numeric checks ─────────────────────────────────────────────────────


class TestSeMatchesLoAnnualizedFormula:
    """For specified (S=2.0, N=100), the post-fix SE must match the
    annualization-corrected Lo (2002) formula exactly. No autocorrelation
    correction (returns=None) so we isolate the units fix."""

    def test_se_at_known_input_is_lo_annualized(self):
        S = 2.0
        n = 100
        # _sharpe_t_stat_and_ci returns (t_stat, ci_lower, ci_upper);
        # SE is t_stat = S / SE → SE = S / t_stat. We use that to back
        # out the implementation's SE without touching internals.
        t_stat, ci_lower, ci_upper = _sharpe_t_stat_and_ci(S, n, returns=None)
        impl_se = S / t_stat
        expected_se = _post_fix_se(S, n)
        assert abs(impl_se - expected_se) < 1e-9, (
            f"Implementation SE {impl_se} must equal Lo (2002) annualized "
            f"SE {expected_se} to within 1e-9; diff={abs(impl_se - expected_se)}."
        )

    def test_ci_bounds_use_corrected_se(self):
        """ci_lower / ci_upper = S ± 1.96 * SE_corrected. Pin both."""
        S = 2.0
        n = 100
        t_stat, ci_lower, ci_upper = _sharpe_t_stat_and_ci(S, n, returns=None)
        expected_se = _post_fix_se(S, n)
        expected_lower = S - 1.96 * expected_se
        expected_upper = S + 1.96 * expected_se
        assert abs(ci_lower - expected_lower) < 1e-9
        assert abs(ci_upper - expected_upper) < 1e-9

    @pytest.mark.parametrize(
        "S, n",
        [(0.5, 50), (1.0, 100), (2.0, 250), (-1.5, 75), (0.0, 30)],
    )
    def test_se_matches_corrected_formula_across_grid(self, S, n):
        t_stat, _, _ = _sharpe_t_stat_and_ci(S, n, returns=None)
        if S == 0.0:
            # t_stat = 0 / SE = 0; SE backout undefined — verify directly
            # via ci_upper.
            _, _, ci_upper = _sharpe_t_stat_and_ci(S, n, returns=None)
            impl_se = ci_upper / 1.96
        else:
            impl_se = S / t_stat
        expected_se = _post_fix_se(S, n)
        assert abs(impl_se - expected_se) < 1e-9, (
            f"S={S}, n={n}: impl_se={impl_se}, expected={expected_se}"
        )


# ── Pre-fix vs post-fix dimensional inflation ─────────────────────────────────


class TestPreFixSEUnderstatesByApproxSqrtT:
    """The dimensional correction inflates SE by approximately sqrt(T).
    For S small (e.g. S=2.0), the ratio post/pre ≈ sqrt(T + 0.5*S^2) /
    sqrt(1 + 0.5*S^2). With T=252 and S=2.0, that's sqrt(254) / sqrt(3)
    ≈ 9.20, well above 1.0 — demonstrating the SE was meaningfully
    understated."""

    def test_post_fix_se_strictly_larger_than_pre_fix_for_typical_sharpe(self):
        S = 2.0
        n = 100
        pre = _pre_fix_se(S, n)
        post = _post_fix_se(S, n)
        assert post > pre
        ratio = post / pre
        # sqrt(254)/sqrt(3) ≈ 9.20
        assert 9.0 < ratio < 9.5, (
            f"For S=2.0, n=100: SE inflation ratio post/pre should be ~9.2; "
            f"got {ratio}"
        )

    def test_pre_fix_se_was_inflated_by_about_sqrt_252_at_zero_sharpe(self):
        """At S=0 the pre-fix formula collapses to sqrt(1/n); post-fix to
        sqrt(252/n). The exact ratio is sqrt(252) ≈ 15.87 — this is the
        most extreme dimensional under-statement."""
        n = 100
        pre = _pre_fix_se(0.0, n)
        post = _post_fix_se(0.0, n)
        ratio = post / pre
        assert abs(ratio - math.sqrt(252.0)) < 1e-9

    def test_implementation_matches_post_fix_not_pre_fix(self):
        """The committed _sharpe_t_stat_and_ci must produce the post-fix
        (annualization-corrected) SE — not the pre-fix one."""
        S = 1.5
        n = 80
        t_stat, _, _ = _sharpe_t_stat_and_ci(S, n, returns=None)
        impl_se = S / t_stat
        post = _post_fix_se(S, n)
        pre = _pre_fix_se(S, n)
        assert abs(impl_se - post) < 1e-9
        # And it must clearly NOT match the buggy pre-fix value.
        assert abs(impl_se - pre) > 0.1


# ── Direction of t-stat and p-value after the fix ─────────────────────────────


class TestPostFixPValueIsLargerThanPreFix:
    """Concrete demonstration: with positive S, the post-fix p-value is
    LARGER than the pre-fix p-value (because the corrected SE is larger,
    so |t_stat| is smaller, so the two-sided erfc tail probability is
    larger). This is the central trading-safety improvement the fix
    delivers — fewer false GREENs."""

    @staticmethod
    def _p_value_from_t(t_stat: float) -> float:
        """Two-sided large-N normal p-value (matches kpis._sharpe_p_value)."""
        return math.erfc(abs(t_stat) / math.sqrt(2.0))

    def test_pre_fix_t_stat_is_inflated(self):
        """With S=2.0, n=100: pre-fix t_stat ≈ 13, post-fix t_stat ≈ 1.4."""
        S = 2.0
        n = 100
        pre_t = S / _pre_fix_se(S, n)   # buggy
        post_t = S / _post_fix_se(S, n)  # corrected
        assert pre_t > post_t > 0
        # post-fix t_stat should be ~ pre/sqrt(T+0.5S^2)/(1+0.5S^2)
        # i.e. sqrt(3/254) ratio. Numerically: pre_t ≈ 11.55, post_t ≈ 1.255
        assert 11 < pre_t < 12.5
        assert 1.2 < post_t < 1.3

    def test_post_fix_p_value_strictly_larger_than_pre_fix(self):
        """For positive S the corrected SE shrinks the t-stat and inflates
        the p-value — the trading-safety direction."""
        S = 2.0
        n = 100
        pre_p = self._p_value_from_t(S / _pre_fix_se(S, n))
        post_p = self._p_value_from_t(S / _post_fix_se(S, n))
        assert post_p > pre_p
        # Pre-fix p-value at t≈11.5 is essentially zero (well below 1e-30);
        # post-fix p-value at t≈1.25 is roughly 0.21 — pre-fix was a
        # textbook example of "the answer that's too good to be true".
        assert pre_p < 1e-30
        assert 0.18 < post_p < 0.25

    def test_implementation_matches_post_fix_p_value_direction(self):
        """The committed code must produce the post-fix (large-p) value,
        proving the trading-safety direction is in place."""
        S = 2.0
        n = 100
        t_stat, _, _ = _sharpe_t_stat_and_ci(S, n, returns=None)
        post_t = S / _post_fix_se(S, n)
        assert abs(t_stat - post_t) < 1e-9


# ── periods_per_year parameter is honored ────────────────────────────────────


class TestPeriodsPerYearParameterIsHonored:
    """The fix added an optional `periods_per_year` parameter so non-daily
    callers (intraday=150, weekly=52) can pass the correct annualization
    factor. Default must remain 252 to match the existing daily pipeline."""

    def test_default_is_252(self):
        assert _N_PER_YEAR == 252.0

    def test_se_scales_with_periods_per_year(self):
        S = 1.0
        n = 100
        t_252, _, _ = _sharpe_t_stat_and_ci(S, n, periods_per_year=252.0)
        t_52, _, _ = _sharpe_t_stat_and_ci(S, n, periods_per_year=52.0)
        # Smaller T → smaller SE → larger t_stat
        assert t_52 > t_252

    def test_explicit_252_matches_default(self):
        S = 1.5
        n = 80
        t_default, *_ = _sharpe_t_stat_and_ci(S, n)
        t_explicit, *_ = _sharpe_t_stat_and_ci(S, n, periods_per_year=252.0)
        assert t_default == t_explicit
