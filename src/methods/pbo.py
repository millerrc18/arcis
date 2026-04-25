"""Probability of Backtest Overfitting (PBO).

Called by: diagnostic writers (none wired as gate per F-12).
Calls: itertools.combinations, numpy.
Owns tables: none.
Config keys: none.
Tests: tests/methods/test_pbo.py.

Authority: Bailey, Borwein, López de Prado & Zhu (2014),
"The Probability of Backtest Overfitting", Journal of Computational
Finance.

Pure function. Input: a returns matrix of shape (T, N) where T is the
number of time samples and N is the number of strategy variants.
Output: a single scalar in [0, 1] estimating the probability that the
in-sample best strategy lands below the median out-of-sample.

This module is a sibling of src.platform.rigor.cscv. The CSCV module
returns a richer dict (PBO + logit distribution + degradation cloud)
on a pandas DataFrame. This module returns the bare scalar on a numpy
array, which is what the diagnostic writers want.

Diagnostic only — per audit spec §F-12, the promotion gate is ≥4 of 5
GATING methods (CPCV, block bootstrap, MC permutation, PSR, White RC).
PBO is reported alongside but does NOT gate.
"""

from __future__ import annotations

from itertools import combinations

import numpy as np

_MIN_T = 8
_MIN_N = 2
_DEFAULT_S = 16


def _sharpe_columns(block: np.ndarray) -> np.ndarray:
    """Per-observation Sharpe of each column of `block` (no annualization).
    Returns a 1-D array of length block.shape[1]. Columns with zero std
    map to 0.0."""
    n = block.shape[0]
    if n == 0:
        return np.zeros(block.shape[1])
    mu = block.mean(axis=0)
    if n < 2:
        return np.zeros(block.shape[1])
    sd = block.std(axis=0, ddof=1)
    out = np.zeros_like(mu)
    nz = sd > 0.0
    out[nz] = mu[nz] / sd[nz]
    return out


def _partition_rows(T: int, S: int) -> list[np.ndarray]:
    """Split T into S contiguous row-index blocks as close to equal as
    possible."""
    sizes = np.full(S, T // S, dtype=int)
    sizes[: T % S] += 1
    edges = np.concatenate([[0], sizes.cumsum()])
    return [np.arange(edges[i], edges[i + 1]) for i in range(S)]


def pbo(returns: np.ndarray, S: int = _DEFAULT_S) -> float:
    """Probability of Backtest Overfitting per Bailey et al. 2014.

    Args:
        returns: (T, N) array. T time samples, N strategy variants.
        S: number of CSCV partitions. Must be even and >= 2. Default 16.

    Returns:
        A single scalar in [0, 1]. Higher values indicate that the
        in-sample best strategy tends to land in the bottom half
        out-of-sample — the overfitting signature.

    Raises:
        ValueError: if T < 8, N < 2, returns is not 2-D, or S is not
            an even integer >= 2.
    """
    arr = np.asarray(returns, dtype=float)
    if arr.ndim != 2:
        raise ValueError(
            f"returns must be 2-D (T, N); got ndim={arr.ndim}",
        )
    T, N = arr.shape
    if T < _MIN_T:
        raise ValueError(f"T must be >= {_MIN_T}; got T={T}")
    if N < _MIN_N:
        raise ValueError(f"N must be >= {_MIN_N}; got N={N}")
    if not isinstance(S, int) or S < 2 or S % 2 != 0:
        raise ValueError(f"S must be an even integer >= 2; got S={S!r}")

    blocks = _partition_rows(T, S)
    half = S // 2
    below_median = 0
    total = 0
    all_idx = set(range(S))
    for is_combo in combinations(range(S), half):
        oos_combo = tuple(all_idx.difference(is_combo))
        is_rows = np.concatenate([blocks[i] for i in is_combo])
        oos_rows = np.concatenate([blocks[i] for i in oos_combo])
        is_sharpes = _sharpe_columns(arr[is_rows, :])
        oos_sharpes = _sharpe_columns(arr[oos_rows, :])
        best_is = int(np.argmax(is_sharpes))
        rank = int(np.sum(oos_sharpes < oos_sharpes[best_is]))
        relative_rank = rank / N
        if relative_rank < 0.5:
            below_median += 1
        total += 1

    if total == 0:
        # unreachable given S>=2 guard, but keep defensive.
        raise ValueError("no CSCV splits generated; check S vs T")
    return float(below_median / total)
