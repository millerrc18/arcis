"""Combinatorial Purged Cross-Validation (CPCV).

Authority: López de Prado 2018, §7.4.

Called by: diagnostic writers (none wired as gate per F-12; wiring is T2.04).
Calls: src.analytics.canonical_sharpe.rf_adjusted_excess_sharpe, numpy.
Owns tables: none.
Config keys: none.
Tests: tests/methods/test_cpcv.py.

Pure functions — no I/O, no DB.

Two entry points:
  cpcv(returns, k, embargo, rf_period)
      K-fold purged CV with combinatorial test-fold selection and bilateral
      embargo.  Returns per-fold OOS rf-adjusted Sharpe.

  cpcv_anchored(returns, k, embargo, rf_period)
      Anchored walk-forward variant: each fold's training window is pinned to
      start at index 0 so the window grows monotonically.

Both return a dict:
  {
    "fold_sharpes": list[float | None],   # one per fold
    "fold_indices": list[tuple[np.ndarray, np.ndarray]],  # (train_idx, test_idx)
  }

Raises ValueError on bad inputs.
"""

from __future__ import annotations

from itertools import combinations

import numpy as np

from src.analytics.canonical_sharpe import rf_adjusted_excess_sharpe

_MIN_K = 2
_DEFAULT_K = 5
_DEFAULT_EMBARGO = 10


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _validate_inputs(returns: np.ndarray, k: int, embargo: int) -> None:
    """Raise ValueError if inputs are out-of-spec."""
    if returns.ndim != 1:
        raise ValueError(
            f"returns must be 1-D; got ndim={returns.ndim}",
        )
    if not isinstance(k, int) or k < _MIN_K:
        raise ValueError(f"k must be an integer >= {_MIN_K}; got k={k!r}")
    if not isinstance(embargo, int) or embargo < 0:
        raise ValueError(f"embargo must be a non-negative integer; got embargo={embargo!r}")
    min_len = k * (embargo + 1)
    if len(returns) < min_len:
        raise ValueError(
            f"returns length {len(returns)} too short for k={k} folds and "
            f"embargo={embargo}; need at least {min_len} observations",
        )


def _split_into_folds(T: int, k: int) -> list[np.ndarray]:
    """Split T indices into k contiguous, near-equal folds."""
    sizes = np.full(k, T // k, dtype=int)
    sizes[: T % k] += 1
    edges = np.concatenate([[0], sizes.cumsum()])
    return [np.arange(edges[i], edges[i + 1]) for i in range(k)]


def _apply_embargo(
    train_idx: np.ndarray,
    test_idx: np.ndarray,
    embargo: int,
) -> np.ndarray:
    """Remove from train_idx any index within `embargo` of any test index."""
    if embargo == 0:
        return train_idx
    test_set = set(test_idx.tolist())
    forbidden: set[int] = set()
    for ti in test_set:
        for off in range(-embargo, embargo + 1):
            forbidden.add(ti + off)
    mask = np.array([i not in forbidden for i in train_idx], dtype=bool)
    return train_idx[mask]


def _oos_sharpe(
    returns: np.ndarray,
    test_idx: np.ndarray,
    rf_period: float,
) -> float | None:
    """Compute rf-adjusted OOS Sharpe for the given test indices."""
    oos = returns[test_idx].tolist()
    return rf_adjusted_excess_sharpe(oos, rf_period)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def cpcv(
    returns: np.ndarray,
    k: int = _DEFAULT_K,
    embargo: int = _DEFAULT_EMBARGO,
    rf_period: float = 0.0,
) -> dict:
    """Combinatorial Purged Cross-Validation.

    Generates all C(k, 1) = k folds where each fold uses one partition as the
    OOS test set and the remaining k-1 partitions (minus embargoed observations)
    as the in-sample training set.

    Args:
        returns:    1-D array of per-period returns.
        k:          Number of folds. Must be >= 2. Default 5.
        embargo:    Sessions to drop on both sides of each test observation.
                    Must be >= 0. Default 10.
        rf_period:  Per-period risk-free rate (not annualized). Default 0.0.

    Returns:
        dict with keys:
          "fold_sharpes": list[float | None] of length k.
          "fold_indices": list of (train_idx, test_idx) np.ndarray pairs.

    Raises:
        ValueError: on bad inputs.
    """
    arr = np.asarray(returns, dtype=float)
    _validate_inputs(arr, k, embargo)

    T = len(arr)
    folds = _split_into_folds(T, k)

    fold_sharpes: list[float | None] = []
    fold_indices: list[tuple[np.ndarray, np.ndarray]] = []

    for test_fold_idx in range(k):
        test_idx = folds[test_fold_idx]
        raw_train_idx = np.concatenate(
            [folds[i] for i in range(k) if i != test_fold_idx]
        )
        train_idx = _apply_embargo(raw_train_idx, test_idx, embargo)
        fold_sharpes.append(_oos_sharpe(arr, test_idx, rf_period))
        fold_indices.append((train_idx, test_idx))

    return {"fold_sharpes": fold_sharpes, "fold_indices": fold_indices}


def cpcv_anchored(
    returns: np.ndarray,
    k: int = _DEFAULT_K,
    embargo: int = _DEFAULT_EMBARGO,
    rf_period: float = 0.0,
) -> dict:
    """Anchored walk-forward variant of CPCV.

    Splits T observations into k+1 equal-sized partitions. Fold i (0..k-1)
    tests on partition i+1 and trains on partitions 0..i (minus embargoed
    observations).  Every fold's training window therefore starts at index 0
    and grows monotonically.

    Args:
        returns:    1-D array of per-period returns.
        k:          Number of folds. Must be >= 2. Default 5.
        embargo:    Sessions to drop on both sides of each test observation.
                    Must be >= 0. Default 10.
        rf_period:  Per-period risk-free rate (not annualized). Default 0.0.

    Returns:
        dict with keys:
          "fold_sharpes": list[float | None] of length k.
          "fold_indices": list of (train_idx, test_idx) np.ndarray pairs.

    Raises:
        ValueError: on bad inputs.
    """
    arr = np.asarray(returns, dtype=float)
    _validate_inputs(arr, k, embargo)

    T = len(arr)
    partitions = _split_into_folds(T, k + 1)

    fold_sharpes: list[float | None] = []
    fold_indices: list[tuple[np.ndarray, np.ndarray]] = []

    for fold_i in range(k):
        test_idx = partitions[fold_i + 1]
        raw_train_idx = np.concatenate(partitions[: fold_i + 1])
        train_idx = _apply_embargo(raw_train_idx, test_idx, embargo)
        fold_sharpes.append(_oos_sharpe(arr, test_idx, rf_period))
        fold_indices.append((train_idx, test_idx))

    return {"fold_sharpes": fold_sharpes, "fold_indices": fold_indices}
