"""White's Reality Check (White 2000).

Authority:
  White, H. (2000). "A Reality Check for Data Snooping."
    Econometrica, 68(5), 1097-1126.
  Politis, D.N. & Romano, J.P. (1994). "The Stationary Bootstrap."
    Journal of the American Statistical Association, 89(428), 1303-1313.

Pure-function module — no I/O, no DB.

Called by: diagnostic writers (promotion gate per audit spec §F-12).
Calls: numpy, src.methods.block_bootstrap.optimal_block_length.
Owns tables: none.
Config keys: none.
Tests: tests/methods/test_white_rc.py.
"""
from __future__ import annotations

import numpy as np

from src.methods.block_bootstrap import optimal_block_length

_MIN_T = 30
_MIN_N = 2
_DEFAULT_N_RESAMPLES = 10000


def _bootstrap_max_stats(
    demeaned: np.ndarray,
    p_end: float,
    n_resamples: int,
    rng: np.random.Generator,
) -> np.ndarray:
    """Stationary bootstrap null distribution of max_k sqrt(T)*mean(col_k).

    Resamples all strategy columns jointly using the same block indices,
    preserving cross-sectional dependence across strategies.
    """
    T, N = demeaned.shape
    boot_max = np.empty(n_resamples, dtype=float)
    for i in range(n_resamples):
        sample = np.empty((T, N), dtype=float)
        pos = 0
        while pos < T:
            start = int(rng.integers(0, T))
            block_len = 1
            while block_len < T - pos and rng.random() > p_end:
                block_len += 1
            block_len = min(block_len, T - pos)
            for j in range(block_len):
                sample[pos + j, :] = demeaned[(start + j) % T, :]
            pos += block_len
        boot_max[i] = float(np.max(np.sqrt(T) * sample.mean(axis=0)))
    return boot_max


def white_rc(
    returns: np.ndarray,
    n_resamples: int = _DEFAULT_N_RESAMPLES,
    seed: int | None = None,
) -> float:
    """White's Reality Check nominal p-value via stationary bootstrap.

    Tests the null hypothesis that the best-performing strategy among N
    competing strategies has zero excess return (no data-snooping advantage).

    The test statistic is V_bar = max_k sqrt(T) * mean(returns_k). The null
    distribution is built by jointly resampling all strategies' de-meaned
    returns with the same block indices (preserving cross-sectional
    dependence), then computing the max statistic on each resample.

    Args:
        returns: (T, N) array. T time samples, N >= 2 strategy returns.
        n_resamples: Number of bootstrap resamples. Default 10000.
        seed: Integer seed for reproducibility. None = non-reproducible.

    Returns:
        Nominal p-value in [0, 1]. The fraction of bootstrap resamples
        whose max statistic equals or exceeds the observed V_bar.

    Raises:
        ValueError: if N < 2 (need at least 2 strategies to compare).
        ValueError: if T < 30 (insufficient data for stationary bootstrap).
    """
    arr = np.asarray(returns, dtype=float)
    if arr.ndim != 2:
        raise ValueError(
            f"returns must be 2-D (T, N); got ndim={arr.ndim}. "
            "Need at least 2 strategies."
        )
    T, N = arr.shape
    if N < _MIN_N:
        raise ValueError(
            f"Need at least 2 strategies to compare; got N={N}."
        )
    if T < _MIN_T:
        raise ValueError(
            f"Insufficient data for stationary bootstrap: need >= {_MIN_T} "
            f"observations, got T={T}."
        )
    v_bar = float(np.max(np.sqrt(T) * arr.mean(axis=0)))
    demeaned = arr - arr.mean(axis=0)
    b = optimal_block_length(arr[:, 0])
    boot_max = _bootstrap_max_stats(
        demeaned, 1.0 / b, n_resamples, np.random.default_rng(seed)
    )
    return float(np.mean(boot_max >= v_bar))
