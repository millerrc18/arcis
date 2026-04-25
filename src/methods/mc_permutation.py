"""Monte Carlo permutation test for the null hypothesis of no edge.

Called by: diagnostic writers (gate method per audit spec §F-12).
Calls: src.analytics.canonical_sharpe.
Owns tables: none.
Config keys: none.
Tests: tests/methods/test_mc_permutation.py.

Null hypothesis: trade-direction labels carry no predictive information.
Test statistic: annualized rf-adjusted excess Sharpe (rf=0, i.e. raw
  annualized Sharpe) on the signed PnL series (returns * directions).

Procedure:
  1. Compute observed statistic on (returns * directions).
  2. For each permutation, shuffle directions, recompute statistic.
  3. p-value = fraction of permuted statistics >= observed.

Pure-function module. No global state.
"""
from __future__ import annotations

import random
from typing import Sequence

from src.analytics.canonical_sharpe import rf_adjusted_excess_sharpe

_DEFAULT_N_PERMUTATIONS = 1000


def mc_permutation_pvalue(
    returns: Sequence[float],
    directions: Sequence[int],
    n_permutations: int = _DEFAULT_N_PERMUTATIONS,
    seed: int | None = None,
) -> float:
    """Empirical p-value from a Monte Carlo permutation test.

    Shuffles trade-direction labels and recomputes the test statistic
    (annualized Sharpe of signed returns) to build a null distribution.
    Returns the fraction of permuted statistics >= the observed statistic.

    Args:
        returns: Per-trade returns (raw, not yet sign-adjusted).
        directions: Trade directions; each element must be +1 or -1.
        n_permutations: Number of shuffles to draw. Default 1000.
        seed: Optional RNG seed for reproducibility.

    Returns:
        Empirical p-value in [0.0, 1.0].

    Raises:
        ValueError: if len(returns) <= 1, lengths differ, or the observed
            statistic is undefined (zero-variance after sign-adjustment).
    """
    rets = list(returns)
    dirs = list(directions)

    if len(rets) != len(dirs):
        raise ValueError(
            f"returns and directions must have equal length; "
            f"got {len(rets)} and {len(dirs)}"
        )
    if len(rets) <= 1:
        raise ValueError(
            f"Need at least 2 trades; got {len(rets)}"
        )

    def _statistic(d: list[int]) -> float | None:
        signed = [r * di for r, di in zip(rets, d)]
        return rf_adjusted_excess_sharpe(signed, rf_period=0.0)

    observed = _statistic(dirs)
    if observed is None:
        raise ValueError(
            "Observed test statistic is undefined (zero variance in signed returns)"
        )

    rng = random.Random(seed)
    perm_dirs = dirs[:]
    count_ge = 0
    for _ in range(n_permutations):
        rng.shuffle(perm_dirs)
        stat = _statistic(perm_dirs)
        if stat is not None and stat >= observed:
            count_ge += 1

    return float(count_ge / n_permutations)
