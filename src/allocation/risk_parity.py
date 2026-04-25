"""Risk-parity capital allocator — pure-function module.

Implements inverse-volatility weighting (the standard baseline for equal risk
contribution) with no live-trading wiring.

Formula
-------
    sigma_i = std(returns_i, ddof=1) * sqrt(252)   # annualized vol
    w_i     = (1 / sigma_i) / sum_j(1 / sigma_j)   # inverse-vol weight
    w_i    *= target                                 # scale to leverage target

Edge-case behavior (documented choices)
---------------------------------------
* Empty input           → ValueError("empty")
* < 2 observations      → ValueError("insufficient") — std requires ddof=1
* Zero-variance series  → ValueError("zero variance") — 1/0 would send all
                          capital to that strategy, masking the degenerate
                          input instead of surfacing it.
* NaN in any series     → propagates through std; callers should clean their
                          data before calling. No silent NaN-handling here.

Called by: T2.12b allocator wiring (deferred — no current consumers).
Calls: math (stdlib only — no numpy/pandas dependency).
Owns tables: none.
Config keys: none.
Tests: tests/allocation/test_risk_parity.py.
"""
from __future__ import annotations

import math
from typing import Mapping, Sequence

PERIODS_PER_YEAR = 252


def _annualized_vol(returns: Sequence[float]) -> float:
    n = len(returns)
    if n < 2:
        raise ValueError(
            f"insufficient history: need at least 2 observations, got {n}"
        )
    mean = sum(returns) / n
    variance = sum((r - mean) ** 2 for r in returns) / (n - 1)
    if variance == 0.0:
        raise ValueError(
            "zero variance: cannot apply inverse-vol formula to a flat return series"
        )
    return math.sqrt(variance * PERIODS_PER_YEAR)


def allocate_risk_parity(
    return_series: Mapping[str, Sequence[float]],
    *,
    target: float = 1.0,
) -> dict[str, float]:
    """Compute inverse-volatility risk-parity weights.

    Parameters
    ----------
    return_series:
        Mapping from strategy ID to its sequence of per-period returns.
    target:
        Desired sum of all weights (default 1.0 = fully invested;
        values > 1.0 represent leverage).

    Returns
    -------
    dict[strategy_id, weight] where sum(weights.values()) == target.

    Raises
    ------
    ValueError
        If return_series is empty, any series has < 2 observations, or any
        series has zero variance.
    """
    if not return_series:
        raise ValueError("empty: return_series must contain at least one strategy")

    inv_vols: dict[str, float] = {}
    for sid, returns in return_series.items():
        vol = _annualized_vol(list(returns))
        inv_vols[sid] = 1.0 / vol

    total_inv_vol = sum(inv_vols.values())
    return {sid: (iv / total_inv_vol) * target for sid, iv in inv_vols.items()}
