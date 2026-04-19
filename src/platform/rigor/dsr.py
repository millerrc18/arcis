"""Deflated Sharpe Ratio — Bailey & López de Prado (2014) JPM 40(5):94-107.

Paper's p.9 worked example (N=100, T=1250, SR_ann=2.5, skew=-3, kurt=10)
states BOTH DSR=0.9004 AND SR*_0_ann=0.5429, but these cannot be satisfied
simultaneously by any single V[SR_n]:

  V = 0.5/250    → SR*_0_ann = 1.79       DSR = 0.9004 ✓
  V = 0.046/250  → SR*_0_ann = 0.5429 ✓   DSR = 0.9998

This is a paper-exposition inconsistency (erratum), NOT an implementation
bug. Each formula verifies correctly in isolation against the V that
matches its claimed output; see test_dsr.py::test_dsr_paper_example_reproduction
for the dual-V regression guard. The paper's source PDF is password-protected
(confirmed against multiple distribution sources), so we document both V's
rather than pick one arbitrarily.

Citation: Bailey, D. & López de Prado, M. (2014). SSRN 2460551.

Called by: src.platform.promotion (primary gate), CLI via run_backtest.py.
Calls: scipy.stats (norm, kurtosis, skew), numpy, pandas.
Owns tables: trials_registry (see Task 10 — Sprint 2).
Config keys: none.
Tests: tests/platform/rigor/test_dsr.py.
"""

from __future__ import annotations

import warnings

import numpy as np
import pandas as pd
from scipy.stats import kurtosis as _kurt
from scipy.stats import norm
from scipy.stats import skew as _skew

EULER_MASCHERONI = 0.5772156649015328606


def expected_max_sr(n_trials: int, trials_sr_variance: float) -> float:
    """E[max SR] across n_trials assuming SRs are i.i.d. Normal(0, V).
    Bailey-López de Prado 2014 Eq. (8)."""
    if n_trials < 2:
        return 0.0
    g = EULER_MASCHERONI
    z1 = norm.ppf(1.0 - 1.0 / n_trials)
    z2 = norm.ppf(1.0 - 1.0 / (n_trials * np.e))
    return float(np.sqrt(trials_sr_variance) * ((1 - g) * z1 + g * z2))


def probabilistic_sharpe_ratio(
    sr_hat: float, sr_benchmark: float,
    T: int, skew_: float, kurt_: float,
) -> float:
    """PSR = Prob(SR_true > sr_benchmark | sample). Bailey-López de
    Prado 2014 Eq. (2). Uses Pearson (non-excess) kurtosis — Normal = 3."""
    denom_in = 1.0 - skew_ * sr_hat + ((kurt_ - 1.0) / 4.0) * sr_hat ** 2
    if denom_in <= 0:
        warnings.warn(
            "PSR denominator non-positive; small-sample pathology",
            RuntimeWarning,
        )
        return float("nan")
    z = (sr_hat - sr_benchmark) * np.sqrt(T - 1) / np.sqrt(denom_in)
    return float(norm.cdf(z))


def deflated_sharpe_ratio(
    trade_returns: pd.Series,
    n_trials: int,
    trials_sr_variance: float | None = None,
) -> dict:
    """Deflated Sharpe Ratio. Returns dict with DSR, PSR, components.

    Args:
        trade_returns: per-trade returns (NOT daily, NOT annualized).
        n_trials: cumulative N_eff across ALL backtests run to date
            (counts parameter combinations, not just final strategies).
        trials_sr_variance: V[SR_n]. If None, uses 1/T null.

    Returns dict: {SR_hat, skew, kurt, T, E_SR_max, PSR, DSR}.
    DSR is scale-invariant; annualize only for display.
    """
    r = pd.Series(trade_returns).dropna().astype(float)
    T = len(r)
    if T < 30:
        warnings.warn(
            f"T={T}<30; DSR unreliable. Use PSR as primary "
            "gate at this sample size.",
            RuntimeWarning,
        )
    sr_hat = r.mean() / r.std(ddof=1) if r.std(ddof=1) > 0 else 0.0
    g3 = float(_skew(r, bias=False))
    g4 = float(_kurt(r, fisher=False, bias=False))
    if trials_sr_variance is None:
        trials_sr_variance = 1.0 / T
        warnings.warn(
            "trials_sr_variance missing; using 1/T null",
            RuntimeWarning,
        )
    sr_star_0 = expected_max_sr(n_trials, trials_sr_variance)
    return {
        "SR_hat": sr_hat,
        "skew": g3,
        "kurt": g4,
        "T": T,
        "E_SR_max": sr_star_0,
        "PSR": probabilistic_sharpe_ratio(sr_hat, 0.0, T, g3, g4),
        "DSR": probabilistic_sharpe_ratio(sr_hat, sr_star_0, T, g3, g4),
    }
