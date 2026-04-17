"""Combinatorially Symmetric Cross-Validation (CSCV) + Probability of
Backtest Overfitting (PBO).

Called by: src.platform.promotion (CSCV gate on parameter-swept backtests).
Calls: itertools.combinations, numpy, pandas.
Owns tables: none.
Config keys: none.
Tests: tests/platform/rigor/test_cscv.py.

Authority: Bailey, Borwein, López de Prado & Zhu (2014),
"The Probability of Backtest Overfitting", Journal of Computational
Finance. Also see docs/research/Walk-Forward_Backtesting_Protocol_for_
Small-Sample_Strategies.md §6 for the implementation pattern.

Pure math — no DB access, no side effects. Caller supplies a T×N PnL
matrix (T daily observations × N strategy configs). The module does
NOT run backtests itself.

Known failures (per deep research):
  1. Blind to look-ahead bugs — CSCV assumes your backtest is correct.
  2. Blind to regime shifts outside the sample — splits are symmetric.
  3. Homogeneous-strategy degeneracy (Vojtko-Padyšák 2021) — if all N
     configs are near-identical, PBO becomes uninformative noise.
Treat PBO > 0.5 as reject, but remember it is one filter among many.
"""

from __future__ import annotations

import warnings
from itertools import combinations
from math import log

import numpy as np
import pandas as pd


def _sharpe(series: np.ndarray) -> float:
    """Per-observation Sharpe ratio (no annualization). Returns 0 if std is 0."""
    if series.size == 0:
        return 0.0
    mu = float(series.mean())
    sd = float(series.std(ddof=1)) if series.size > 1 else 0.0
    if sd == 0.0:
        return 0.0
    return mu / sd


def _partition_rows(T: int, S: int) -> list[np.ndarray]:
    """Split T into S contiguous row-index blocks as close to equal as possible."""
    sizes = np.full(S, T // S, dtype=int)
    sizes[: T % S] += 1  # distribute remainder
    edges = np.concatenate([[0], sizes.cumsum()])
    return [np.arange(edges[i], edges[i + 1]) for i in range(S)]


def pbo_from_pnl_matrix(
    pnl_matrix: pd.DataFrame, S: int = 16,
) -> dict:
    """Probability of Backtest Overfitting per Bailey et al. 2014.

    Args:
        pnl_matrix: T rows (daily obs) × N cols (strategy configs).
            Wide form. Missing rows dropped via dropna.
        S: number of partitions. Must be even. Paper canonical = 16.
            If T // S < 16 observations per block, S is reduced with
            a RuntimeWarning.

    Returns dict:
        PBO: fraction of C(S, S/2) splits where IS-best config lands
            below OOS median. PBO > 0.5 indicates overfit.
        logit_distribution: logit-transformed relative OOS ranks of the
            IS-best config across all splits. Centered at zero means
            random; negative-shifted distribution = overfit signature.
        performance_degradation_points: list of (IS_best_sharpe,
            OOS_sharpe_of_same_config) tuples, one per split. Useful
            for plotting the IS→OOS degradation cloud.
    """
    df = pnl_matrix.dropna(how="any").astype(float)
    T, N = df.shape
    if T == 0 or N < 2:
        return {"PBO": float("nan"), "logit_distribution": [],
                "performance_degradation_points": []}

    # Partition adjustment: require at least 16 obs per block
    MIN_OBS_PER_BLOCK = 16
    effective_S = S
    if T // S < MIN_OBS_PER_BLOCK:
        effective_S = max(2, T // MIN_OBS_PER_BLOCK)
        if effective_S % 2 == 1:
            effective_S -= 1
        effective_S = max(2, effective_S)
        warnings.warn(
            f"T={T} with S={S} gives <{MIN_OBS_PER_BLOCK} obs/block; "
            f"reducing to S={effective_S}",
            RuntimeWarning,
        )
    if effective_S % 2 == 1:
        effective_S -= 1
        warnings.warn(f"S must be even; using S={effective_S}", RuntimeWarning)

    values = df.values  # T × N
    blocks = _partition_rows(T, effective_S)

    logits: list[float] = []
    degradation: list[tuple[float, float]] = []
    half = effective_S // 2

    for is_combo in combinations(range(effective_S), half):
        oos_combo = tuple(i for i in range(effective_S) if i not in is_combo)
        is_rows = np.concatenate([blocks[i] for i in is_combo])
        oos_rows = np.concatenate([blocks[i] for i in oos_combo])
        is_data = values[is_rows, :]      # T_is × N
        oos_data = values[oos_rows, :]    # T_oos × N

        # Per-config Sharpe in IS and OOS
        is_sharpes = np.array(
            [_sharpe(is_data[:, j]) for j in range(N)]
        )
        oos_sharpes = np.array(
            [_sharpe(oos_data[:, j]) for j in range(N)]
        )
        best_is = int(np.argmax(is_sharpes))
        degradation.append(
            (float(is_sharpes[best_is]), float(oos_sharpes[best_is]))
        )

        # Relative rank of the IS-best config in OOS
        # rank = count of OOS Sharpes strictly below the IS-best's OOS Sharpe
        target = oos_sharpes[best_is]
        rank = int(np.sum(oos_sharpes < target))
        relative_rank = rank / N
        # Clamp to avoid log(0) / log(inf)
        clamped = min(max(relative_rank, 1.0 / (2 * N)), 1.0 - 1.0 / (2 * N))
        logit = log(clamped / (1.0 - clamped))
        logits.append(logit)

    # PBO = fraction of splits where the IS-winner underperforms the OOS median.
    # A logit < 0 ⇔ relative_rank < 0.5 ⇔ IS-winner is in bottom half OOS.
    pbo = float(np.mean(np.array(logits) < 0.0)) if logits else float("nan")

    return {
        "PBO": pbo,
        "logit_distribution": [float(x) for x in logits],
        "performance_degradation_points": degradation,
    }
