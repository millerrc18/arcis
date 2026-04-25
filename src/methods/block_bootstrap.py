"""Stationary block bootstrap confidence interval for rf-adjusted excess Sharpe.

Authority:
  Politis, D.N. & Romano, J.P. (1994). "The Stationary Bootstrap."
    Journal of the American Statistical Association, 89(428), 1303-1313.
  Politis, D.N. & White, H. (2004). "Automatic Block-Length Selection for
    the Dependent Bootstrap." Econometric Reviews, 23(1), 53-70.

Pure-function module — no I/O, no DB.

Called by: diagnostic writers (T2.04 promotion gate — wired separately).
Calls: numpy.
Owns tables: none.
Config keys: none.
Tests: tests/methods/test_block_bootstrap.py.
"""
from __future__ import annotations

import math

import numpy as np

_MIN_T = 30
_DEFAULT_N_RESAMPLES = 10000
_CI_LEVEL = 0.95
_PERIODS_PER_YEAR = 252


def _rf_adjusted_sharpe(series: np.ndarray, rf_period: float) -> float:
    """Annualized rf-adjusted Sharpe on a 1-D series. Returns 0.0 when undefined."""
    excess = series - rf_period
    n = len(excess)
    if n < 2:
        return 0.0
    mean = excess.mean()
    sd = excess.std(ddof=1)
    if sd == 0.0:
        return 0.0
    return float((mean / sd) * math.sqrt(_PERIODS_PER_YEAR))


def optimal_block_length(series: np.ndarray) -> int:
    """Politis-White (2004) automatic block-length selection.

    Computes the optimal expected block length b* for the stationary
    bootstrap using the spectral density and autocorrelation estimate
    approach of Politis & White (2004), equation (9):

        b* = ( 2 * G_hat^2 / D_hat )^(1/3) * N^(1/3)

    where G_hat is a lag-weighted sum of autocovariances and D_hat is
    related to the spectral variance. A simplified, bandwidth-truncated
    estimator is used here; see the paper for the full derivation.

    Args:
        series: 1-D array of returns of length T.

    Returns:
        Optimal expected block length as a positive integer (minimum 1).
    """
    arr = np.asarray(series, dtype=float)
    n = len(arr)
    arr = arr - arr.mean()

    # Bandwidth for lag selection (Andrews 1991 style, sqrt heuristic)
    m = max(1, int(math.floor(math.sqrt(n))))

    # Compute autocovariances at lags 0..m
    gamma = np.array([
        float(np.dot(arr[k:], arr[: n - k])) / n
        for k in range(m + 1)
    ])

    gamma0 = gamma[0]
    if gamma0 == 0.0:
        return 1

    # G_hat = sum_{k=-m}^{m} |k| * gamma_k  (acov at lag k, symmetric)
    G_hat = 2.0 * sum(abs(k) * gamma[k] for k in range(1, m + 1))

    # D_hat = 4/3 * (sum_{k=-m}^{m} gamma_k)^2  (Politis-White eq. 9 simplified)
    spectral0 = gamma[0] + 2.0 * sum(gamma[1:])
    D_hat = (4.0 / 3.0) * (spectral0 ** 2)

    if D_hat <= 0.0:
        return 1

    b_star_float = ((2.0 * G_hat ** 2) / D_hat) ** (1.0 / 3.0) * (n ** (1.0 / 3.0))
    b_star = max(1, int(round(b_star_float)))
    # Cap at N/4 to avoid degenerate blocks
    b_star = min(b_star, max(1, n // 4))
    return b_star


def block_bootstrap_ci(
    returns: np.ndarray,
    rf_period: float,
    n_resamples: int = _DEFAULT_N_RESAMPLES,
    seed: int | None = None,
) -> tuple[float, float]:
    """Stationary block bootstrap 95% CI of the rf-adjusted excess Sharpe ratio.

    Implements the Politis-Romano (1994) stationary bootstrap: blocks start
    at uniformly random positions and have geometrically distributed lengths
    with expected length equal to the Politis-White (2004) optimal block.

    Args:
        returns: 1-D array of per-period returns (length T >= 30).
        rf_period: Per-period (not annualized) risk-free rate.
        n_resamples: Number of bootstrap resamples. Default 10000.
        seed: Integer seed for reproducibility. None = non-reproducible.

    Returns:
        (lower, upper) — the 2.5th and 97.5th percentile of the bootstrap
        distribution of the rf-adjusted annualized Sharpe ratio, giving the
        95% confidence interval.

    Raises:
        ValueError: if len(returns) < 30 (insufficient data).
    """
    arr = np.asarray(returns, dtype=float)
    n = len(arr)
    if n < _MIN_T:
        raise ValueError(
            f"Insufficient data for stationary bootstrap: need >= {_MIN_T} "
            f"observations, got {n}."
        )

    b = optimal_block_length(arr)
    # Geometric distribution parameter: P(block ends) = 1/b
    p_end = 1.0 / b

    rng = np.random.default_rng(seed)
    boot_sharpes = np.empty(n_resamples, dtype=float)

    for i in range(n_resamples):
        sample = np.empty(n, dtype=float)
        pos = 0
        while pos < n:
            start = int(rng.integers(0, n))
            # Geometric block length (at least 1)
            block_len = 1
            while block_len < n - pos and rng.random() > p_end:
                block_len += 1
            block_len = min(block_len, n - pos)
            for j in range(block_len):
                sample[pos + j] = arr[(start + j) % n]
            pos += block_len
        boot_sharpes[i] = _rf_adjusted_sharpe(sample, rf_period)

    alpha = 1.0 - _CI_LEVEL
    lo = float(np.percentile(boot_sharpes, 100.0 * alpha / 2.0))
    hi = float(np.percentile(boot_sharpes, 100.0 * (1.0 - alpha / 2.0)))
    return (lo, hi)
