"""Power analysis for regime diagnostic.

Computes minimum detectable effect (MDE) at 80% power for:
- Cell-level one-sample t-tests (mean excess-Sharpe)
- Regression slope (excess_return ~ vix_at_entry)

Called by: diagnostics.analyses, diagnostics.report
Calls: scipy.stats
Owns tables: none
Config keys: none
Tests: tests/diagnostics/test_regime_diagnostic.py
"""

from __future__ import annotations

from scipy import stats
import numpy as np


def cell_mde(
    n: int,
    std: float,
    alpha: float = 0.05,
    power: float = 0.80,
) -> float:
    """Minimum detectable effect for a one-sample t-test on the mean.

    Returns MDE in the same units as std (e.g., percent if std is in percent).
    Uses the non-central t-distribution.
    """
    if n < 2:
        return float("inf")
    df = n - 1
    t_crit = stats.t.ppf(1 - alpha / 2, df)
    z_beta = stats.norm.ppf(power)
    ncp = t_crit + z_beta
    mde = ncp * std / np.sqrt(n)
    return float(mde)


def regression_slope_mde(
    n: int,
    x_std: float,
    y_std: float,
    alpha: float = 0.05,
    power: float = 0.80,
) -> float:
    """Minimum detectable slope for simple OLS regression.

    Returns MDE in units of y per unit of x (e.g., % excess return per
    VIX point). Assumes residual std approx y_std (conservative; true residual
    std is lower if there's a real relationship).
    """
    if n < 3:
        return float("inf")
    df = n - 2
    t_crit = stats.t.ppf(1 - alpha / 2, df)
    z_beta = stats.norm.ppf(power)
    ncp = t_crit + z_beta
    se_slope = y_std / (x_std * np.sqrt(n - 2))
    return float(ncp * se_slope)
