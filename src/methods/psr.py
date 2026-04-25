"""Probabilistic Sharpe Ratio, Deflated Sharpe Ratio, and MinTRL.

Authority: Bailey & López de Prado (2012) "The Sharpe Ratio Efficient Frontier".
           Bailey & López de Prado (2014) "The Deflated Sharpe Ratio" JPM 40(5).

Pure functions — no I/O, no DB.

Called by: src.methods.promotion_gate.
Calls:
  src.platform.rigor.dsr.probabilistic_sharpe_ratio (PSR computation),
  src.platform.rigor.dsr.deflated_sharpe_ratio (DSR + E[max SR]),
  src.evaluation.statistics.minimum_track_record_length (MinTRL).
Owns tables: none.
Config keys: none.
Tests: tests/methods/test_psr.py.

Three public functions:
  psr(returns, sr_benchmark=0.0) -> float
      Prob(true SR > sr_benchmark | sample). Uses sample SR, skew, kurtosis.
  dsr(returns, n_trials, sr_benchmark=0.0) -> float
      Deflated SR — PSR adjusted for multiple-testing across n_trials strategies.
  mintrl(returns, alpha=0.05) -> int
      Minimum track-record length: observations needed for significance at alpha.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.stats import kurtosis as _kurt
from scipy.stats import skew as _skew

from src.platform.rigor.dsr import (
    deflated_sharpe_ratio as _canonical_dsr,
    probabilistic_sharpe_ratio as _canonical_psr,
)
from src.evaluation.statistics import (
    minimum_track_record_length as _canonical_mintrl,
)

_MIN_N = 5


def _extract_stats(returns: list | np.ndarray) -> tuple[float, int, float, float]:
    """Compute (sr_hat, T, skew, kurt_pearson) from a returns array.

    sr_hat  — sample Sharpe (mean / std, ddof=1), not annualized.
    T       — number of observations.
    skew    — bias-corrected sample skewness.
    kurt    — Pearson (non-excess) kurtosis; Normal = 3.

    Raises:
        ValueError: if T < 5 (too few observations for reliable statistics).
    """
    arr = np.asarray(returns, dtype=float)
    arr = arr[~np.isnan(arr)]
    T = len(arr)
    if T < _MIN_N:
        raise ValueError(
            f"psr/dsr/mintrl require at least {_MIN_N} observations; got {T}"
        )
    std = float(arr.std(ddof=1))
    sr_hat = float(arr.mean() / std) if std > 0 else 0.0
    skew_ = float(_skew(arr, bias=False))
    kurt_ = float(_kurt(arr, fisher=False, bias=False))  # Pearson (Normal=3)
    return sr_hat, T, skew_, kurt_


def psr(returns: list | np.ndarray, sr_benchmark: float = 0.0) -> float:
    """Probabilistic Sharpe Ratio.

    Probability that the true (population) Sharpe ratio exceeds sr_benchmark
    given the sample. Uses Bailey-López de Prado (2012) Eq. (2) with
    bias-corrected skewness and Pearson (non-excess) kurtosis.

    Args:
        returns:      1-D array-like of per-period returns. Minimum 5 obs.
        sr_benchmark: Benchmark SR to test against. Default 0.0.

    Returns:
        Probability in (0, 1) that the true SR exceeds sr_benchmark.

    Raises:
        ValueError: if len(returns) < 5.
    """
    sr_hat, T, skew_, kurt_ = _extract_stats(returns)
    return _canonical_psr(sr_hat, sr_benchmark, T, skew_, kurt_)


def dsr(
    returns: list | np.ndarray,
    n_trials: int,
    sr_benchmark: float = 0.0,
) -> float:
    """Deflated Sharpe Ratio.

    PSR adjusted for the multiple-testing inherent in trying n_trials
    strategies. Uses expected maximum SR across n_trials as the effective
    benchmark (Bailey-López de Prado 2014).

    When n_trials == 1, E[max SR] = 0 and DSR == PSR (no penalty).

    Args:
        returns:      1-D array-like of per-period returns. Minimum 5 obs.
        n_trials:     Total number of strategies tried (cumulative). Must be >= 1.
        sr_benchmark: Floor benchmark (added to E[max SR]). Default 0.0.

    Returns:
        Probability in (0, 1) that the true SR exceeds the multi-test-adjusted
        benchmark.

    Raises:
        ValueError: if len(returns) < 5.
    """
    _extract_stats(returns)
    result = _canonical_dsr(
        trade_returns=pd.Series(returns),
        n_trials=n_trials,
    )
    return float(result["DSR"])


def mintrl(returns: list | np.ndarray, alpha: float = 0.05) -> int:
    """Minimum Track Record Length.

    The minimum number of observations needed for the PSR to exceed
    (1 - alpha) confidence that the true SR is above 0, given the sample's
    SR, skewness, and kurtosis.

    Args:
        returns: 1-D array-like of per-period returns. Minimum 5 obs.
        alpha:   Significance level. Default 0.05 (95% confidence).

    Returns:
        Minimum observation count as a positive integer.

    Raises:
        ValueError: if len(returns) < 5.
    """
    sr_hat, _T, skew_, kurt_ = _extract_stats(returns)
    confidence = 1.0 - alpha
    return _canonical_mintrl(
        observed_sr=sr_hat,
        benchmark_sr=0.0,
        skew=skew_,
        kurtosis=kurt_,
        confidence=confidence,
    )
