"""Fama-French 3 + Momentum factor-model alpha regression.

Called by: Stage-3 diagnostic writers (none wired as gate per task spec T2.16a).
Calls: numpy.
Owns tables: none.
Config keys: none.
Tests: tests/methods/test_factor_alpha_core.py.

Pure-function module.  Input `returns` MUST already be excess returns
(strategy return minus the contemporaneous risk-free rate).  This function
does NOT subtract rf internally — that is the caller's responsibility.

OLS is implemented via numpy.linalg.lstsq (pseudo-inverse) because
statsmodels is not in requirements.txt.  t-statistics are derived from
the residual covariance matrix.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

_FACTOR_COLS = ["MKT", "SMB", "HML", "MOM"]
_N_PARAMS = 5  # intercept + 4 factor loadings
_MIN_OBS = _N_PARAMS + 1  # need at least k+2 for 1 df_resid


def factor_alpha(
    returns: pd.Series,
    factors: pd.DataFrame,
) -> dict:
    """Run a Fama-French 3+momentum OLS regression and return fit statistics.

    The function aligns `returns` and `factors` on the intersection of their
    indices before fitting.  Any dates present in one but not the other are
    silently dropped; the returned `n_obs` reflects the aligned count.

    Args:
        returns: Daily excess returns (already minus rf) as a pandas Series
            indexed by date.  Caller must subtract the risk-free rate before
            passing.
        factors: DataFrame with columns ["MKT", "SMB", "HML", "MOM"], indexed
            by date, containing the contemporaneous factor returns.

    Returns:
        A dict with keys:
            alpha        (float) — annualized-in-spirit daily intercept
            alpha_t_stat (float) — t-statistic for alpha (H0: alpha == 0)
            betas        (dict)  — {"MKT": float, "SMB": float,
                                    "HML": float, "MOM": float}
            r_squared    (float) — coefficient of determination in [0, 1]
            n_obs        (int)   — number of aligned observations used

    Raises:
        ValueError: if n_obs (after alignment) <= k+1 where k=4 factors,
            i.e. there are fewer than 6 usable observations.
    """
    common_idx = returns.index.intersection(factors.index)
    y = returns.loc[common_idx].values.astype(float)
    F = factors.loc[common_idx, _FACTOR_COLS].values.astype(float)

    n = len(y)
    if n <= _N_PARAMS:
        raise ValueError(
            f"n_obs={n} is too small for OLS with {_N_PARAMS} parameters "
            f"(need n_obs > {_N_PARAMS}).  "
            "Either more observations are required or the index intersection "
            "is too narrow."
        )

    X = np.column_stack([np.ones(n), F])

    coeffs, _, _, _ = np.linalg.lstsq(X, y, rcond=None)

    alpha = float(coeffs[0])
    betas = {col: float(coeffs[i + 1]) for i, col in enumerate(_FACTOR_COLS)}

    y_hat = X @ coeffs
    residuals = y - y_hat
    ss_res = float(residuals @ residuals)
    y_mean = y.mean()
    ss_tot = float((y - y_mean) @ (y - y_mean))
    r_squared = float(1.0 - ss_res / ss_tot) if ss_tot > 0.0 else 0.0
    r_squared = max(0.0, min(1.0, r_squared))

    df_resid = n - _N_PARAMS
    sigma2 = ss_res / df_resid
    xtx_inv = np.linalg.pinv(X.T @ X)
    var_coeffs = sigma2 * xtx_inv
    se_alpha = float(np.sqrt(max(var_coeffs[0, 0], 0.0)))
    alpha_t_stat = float(alpha / se_alpha) if se_alpha > 0.0 else 0.0

    return {
        "alpha": alpha,
        "alpha_t_stat": alpha_t_stat,
        "betas": betas,
        "r_squared": r_squared,
        "n_obs": int(n),
    }
