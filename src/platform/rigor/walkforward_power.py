"""Power analysis / MDE gate for walk-forward (R6 criterion 2).

Called by: src.platform.rigor.walkforward_runner.
Calls: src.diagnostics.power.cell_mde, src.platform.rigor.walkforward_metrics.
Owns tables: none.
Config keys: none.
Tests: tests/platform/rigor/test_walkforward_power.py.

The MDE (minimum detectable effect) for a Sharpe statistic at a given
sample size answers: "how much would the true Sharpe need to exceed
0 for us to detect it at alpha=0.05, power=80%?" — put simply, "how
much noise room is there?"

R6 decision rule per window:
  - If MDE ≤ 0.3: window has enough power to distinguish Sharpe ≥ 0.3
    from zero. Observed Sharpe ≥ 0.3 → criterion-2 passes; else fails.
  - If MDE > 0.3: window is underpowered — outcome INCONCLUSIVE_POWER,
    NOT FAIL. This is the trap the forensic audit exposed — reporting
    "Sharpe = 0.4 on N=30" as validation when 0.4 is noise.

Newey-West lag = max holding period. For a strategy with up to 21-day
holds, autocorrelation can span up to 21 trades. N_effective is reduced
accordingly via the Newey-West deflator:
    N_eff = N / (1 + 2 * sum_{k=1..L} rho_k * (L - k + 1) / L)
(truncated sum, non-negative lower bound). If autocovariance is modest
(typical for per-trade returns from distinct tickers), N_eff ≈ N.

Heavy-tail handling per R6: if the metrics bundle flags heavy-tail,
the SE used for MDE is the bootstrap SE rather than the parametric one.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence

import numpy as np
from scipy import stats

from src.platform.rigor.walkforward_metrics import (
    ANNUALIZATION_FACTOR,
    WindowMetrics,
)


@dataclass
class PowerResult:
    window_index: int
    observed_sharpe: float
    mde: float
    effective_n: int
    se_used: float
    heavy_tail_flag: bool
    passes_power_gate: bool  # True if MDE <= mde_max
    passes_sharpe_gate: bool  # True if observed_sharpe >= sharpe_min


def newey_west_deflator(
    pnls: np.ndarray, max_lag: int,
) -> float:
    """Return the deflator D such that N_eff = N / D.

    D = 1 + 2 · sum_{k=1..L} (rho_k · (L - k + 1) / L)

    We clip D to [1.0, 10.0]: D < 1 indicates negative autocorrelation
    (conservative — we do NOT inflate N above observed); D > 10 would
    imply N_eff < N/10, which is too aggressive for gate computation.
    """
    if pnls.size < 3 or max_lag <= 0:
        return 1.0
    L = min(max_lag, pnls.size - 1)
    demeaned = pnls - np.mean(pnls)
    variance = np.sum(demeaned * demeaned)
    if variance == 0.0:
        return 1.0
    deflator = 1.0
    for k in range(1, L + 1):
        cov_k = np.sum(demeaned[:-k] * demeaned[k:])
        rho_k = cov_k / variance
        weight = (L - k + 1) / L
        deflator += 2.0 * rho_k * weight
    return float(np.clip(deflator, 1.0, 10.0))


def effective_n(n: int, deflator: float) -> int:
    """N_effective = N / D, rounded down, clamped to >=1."""
    if n <= 0:
        return 0
    return max(1, int(math.floor(n / deflator)))


def compute_mde(
    sharpe: float,
    n_effective: int,
    se_used: float,
    alpha: float = 0.05,
    power: float = 0.80,
) -> float:
    """Minimum detectable Sharpe at (alpha, power) given observed SE.

    Uses the non-central-t derivation from src/diagnostics/power.cell_mde,
    adapted so `std` is the provided SE (already on the annualized Sharpe
    scale). The returned MDE is in annualized-Sharpe units — directly
    comparable to the SHARPE_MIN threshold and the MDE_MAX threshold.

    We intentionally do NOT import cell_mde from diagnostics.power here
    because that function asks for a `std` input and derives SE as
    std/sqrt(n); our SE is already computed on the Sharpe scale.
    """
    if n_effective < 2 or not math.isfinite(se_used):
        return float("inf")
    df = n_effective - 1
    t_crit = stats.t.ppf(1 - alpha / 2, df)
    z_beta = stats.norm.ppf(power)
    ncp = t_crit + z_beta
    return float(ncp * se_used)


def evaluate_window_power(
    metrics: WindowMetrics,
    max_hold_days: int,
    pnls: np.ndarray,
    sharpe_min: float = 0.3,
    mde_max: float = 0.3,
    alpha: float = 0.05,
    power: float = 0.80,
) -> PowerResult:
    """Combine metrics with Newey-West + heavy-tail handling to produce a
    PowerResult for one window."""
    deflator = newey_west_deflator(pnls, max_hold_days)
    n_eff = effective_n(metrics.n_trades, deflator)
    se_used = (
        metrics.bootstrap_se if metrics.heavy_tail_flag
        else metrics.parametric_se
    )
    mde = compute_mde(metrics.sharpe, n_eff, se_used, alpha, power)
    return PowerResult(
        window_index=metrics.window_index,
        observed_sharpe=metrics.sharpe,
        mde=mde,
        effective_n=n_eff,
        se_used=se_used,
        heavy_tail_flag=metrics.heavy_tail_flag,
        passes_power_gate=(math.isfinite(mde) and mde <= mde_max),
        passes_sharpe_gate=(metrics.sharpe >= sharpe_min),
    )


def count_power_states(
    power_results: Sequence[PowerResult],
    min_trades_per_window: int,
    n_trades_per_window: Sequence[int],
) -> dict:
    """Categorize every window into one of PASS / FAIL / INCONCLUSIVE_POWER
    / INCONCLUSIVE_DATA.

    Returns a dict {window_index: state}. Criteria 1+2 only — the final
    state machine combines with criteria 3–5 in the runner.
    """
    states: dict[int, str] = {}
    for pr, n in zip(power_results, n_trades_per_window):
        if n < min_trades_per_window:
            states[pr.window_index] = "INCONCLUSIVE_DATA"
        elif not pr.passes_power_gate:
            states[pr.window_index] = "INCONCLUSIVE_POWER"
        elif pr.passes_sharpe_gate:
            states[pr.window_index] = "PASS"
        else:
            states[pr.window_index] = "FAIL"
    return states
