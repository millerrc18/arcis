"""Combinatorial Purged Cross-Validation (CPCV).

Authority: López de Prado 2018, §7.4.

Called by: diagnostic writers (none wired as gate per F-12; wiring is T2.04).
Calls: src.analytics.canonical_sharpe.rf_adjusted_excess_sharpe, numpy.
  cpcv_with_fred_rf / cpcv_anchored_with_fred_rf additionally call
  src.methods._rf_vector.compute_per_period_rf_vector (FRED DTB3 wiring,
  Sprint-0 Wave-3b RF-WIRING).
Owns tables: none.
Config keys: none.
Tests: tests/methods/test_cpcv.py.

Pure functions — no I/O, no DB (the *_with_fred_rf siblings DO perform
network I/O via the FRED adapter; treat them as effectful).

Four entry points:
  cpcv(returns, k, embargo, rf_period)
      K-fold purged CV with combinatorial test-fold selection and bilateral
      embargo.  Returns per-fold OOS rf-adjusted Sharpe. `rf_period` is a
      scalar; legacy callers may pass 0.0 to skip rf adjustment.

  cpcv_anchored(returns, k, embargo, rf_period)
      Anchored walk-forward variant: each fold's training window is pinned to
      start at index 0 so the window grows monotonically.

  cpcv_with_fred_rf(returns, dates, k, embargo)
      Sprint-0 Wave-3b RF-WIRING sibling: takes a list of per-period dates
      (length must equal len(returns)), pulls the FRED DTB3 per-period rf
      via src.methods._rf_vector.compute_per_period_rf_vector, pre-subtracts
      it from `returns` so each fold's OOS Sharpe is computed against the
      real time-varying rate. Returns the same dict shape as `cpcv` plus
      a `used_fred` boolean so callers can distinguish a real-rf run from a
      placeholder fallback.

  cpcv_anchored_with_fred_rf(returns, dates, k, embargo)
      Same FRED wiring layered onto the anchored walk-forward variant.

The non-`*_with_fred_rf` entry points return:
  {
    "fold_sharpes": list[float | None],   # one per fold
    "fold_indices": list[tuple[np.ndarray, np.ndarray]],  # (train_idx, test_idx)
  }

The `*_with_fred_rf` entry points additionally include `"used_fred": bool`.

Raises ValueError on bad inputs.
"""

from __future__ import annotations

import datetime as _dt
from itertools import combinations
from typing import Sequence

import numpy as np

from src.analytics.canonical_sharpe import rf_adjusted_excess_sharpe

_MIN_K = 2
_DEFAULT_K = 5
_DEFAULT_EMBARGO = 10


class EmbargoZeroError(ValueError):
    """Raised when embargo collapses to zero leakage protection.

    Sprint-0 Wave-5b PROMOTION-GATE-METHODOLOGY (operator Q6=A): silent
    embargo decrement to 0 silently disables leakage protection. Callers
    must treat this as a hard failure rather than a degraded run.
    """


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
    """Remove from train_idx any index within `embargo` of any test index.

    Sprint-0 Wave-5b PROMOTION-GATE-METHODOLOGY (operator Q6=A):
    post-embargo, the resulting train_idx must be non-empty AND embargo > 0
    when the caller is the promotion gate (which auto-shrinks embargo to fit
    the series). The embargo==0 short-circuit retains the original CPCV API
    contract for direct callers (they may legitimately request an unembargoed
    run), but if embargo>0 was requested and the resulting train set is empty,
    we raise EmbargoZeroError so the caller cannot silently proceed with no
    leakage protection.
    """
    if embargo == 0:
        # Direct callers (not the promotion gate) may request embargo=0
        # explicitly. Still verify that train_idx is not empty — empty
        # train_idx would silently yield zero in-sample observations.
        if len(train_idx) == 0:
            raise EmbargoZeroError(
                "Empty train_idx after embargo=0 — no observations remain "
                "for in-sample fitting (the test fold consumed everything)."
            )
        return train_idx
    test_set = set(test_idx.tolist())
    forbidden: set[int] = set()
    for ti in test_set:
        for off in range(-embargo, embargo + 1):
            forbidden.add(ti + off)
    mask = np.array([i not in forbidden for i in train_idx], dtype=bool)
    out = train_idx[mask]
    if len(out) == 0:
        raise EmbargoZeroError(
            f"Embargo of {embargo} consumed every train index — no leakage-safe "
            f"in-sample observations remain (n_test={len(test_idx)}, "
            f"n_train_pre_embargo={len(train_idx)})."
        )
    return out


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


# ---------------------------------------------------------------------------
# FRED-aware sibling helpers (Sprint-0 Wave-3b RF-WIRING)
#
# These wrappers fetch a per-period rf vector from FRED DTB3 (with placeholder
# fallback per-index on failure), pre-subtract it from `returns`, and call
# the underlying scalar-rf function with rf_period=0.0 — keeping the legacy
# function signatures unchanged while giving callers that know the trade
# date range a one-line path to a real-rf run.
# ---------------------------------------------------------------------------

def _excess_returns_via_fred_rf(
    returns: np.ndarray,
    dates: Sequence[_dt.date],
) -> tuple[np.ndarray, bool]:
    """Return (returns - rf_vec, used_fred). Length-aligned to `returns`."""
    from src.methods._rf_vector import compute_per_period_rf_vector

    if len(dates) != len(returns):
        raise ValueError(
            f"len(dates)={len(dates)} must equal len(returns)={len(returns)}"
        )
    rf_vec, used_fred = compute_per_period_rf_vector(list(dates))
    rf_arr = np.asarray(rf_vec, dtype=float)
    return returns - rf_arr, used_fred


def cpcv_with_fred_rf(
    returns: np.ndarray,
    dates: Sequence[_dt.date],
    k: int = _DEFAULT_K,
    embargo: int = _DEFAULT_EMBARGO,
) -> dict:
    """FRED-aware sibling of `cpcv`.

    Pulls per-period rf via `src.methods._rf_vector.compute_per_period_rf_vector`,
    pre-subtracts it from `returns`, and runs the standard `cpcv` with
    rf_period=0.0 (since the rf adjustment is already baked into the series).

    Args:
        returns: 1-D array of per-period returns.
        dates:   Per-period `datetime.date`s. Must have len == len(returns).
        k:       Number of folds. Default 5.
        embargo: Bilateral embargo. Default 10.

    Returns:
        dict with `fold_sharpes`, `fold_indices`, and `used_fred`.

    Raises:
        ValueError: if len(dates) != len(returns), or any cpcv input failure.
    """
    arr = np.asarray(returns, dtype=float)
    excess, used_fred = _excess_returns_via_fred_rf(arr, dates)
    result = cpcv(excess, k=k, embargo=embargo, rf_period=0.0)
    result["used_fred"] = used_fred
    return result


def cpcv_anchored_with_fred_rf(
    returns: np.ndarray,
    dates: Sequence[_dt.date],
    k: int = _DEFAULT_K,
    embargo: int = _DEFAULT_EMBARGO,
) -> dict:
    """FRED-aware sibling of `cpcv_anchored`.

    See `cpcv_with_fred_rf` for the wiring; the only difference is the
    underlying call is `cpcv_anchored` rather than `cpcv`.
    """
    arr = np.asarray(returns, dtype=float)
    excess, used_fred = _excess_returns_via_fred_rf(arr, dates)
    result = cpcv_anchored(excess, k=k, embargo=embargo, rf_period=0.0)
    result["used_fred"] = used_fred
    return result
