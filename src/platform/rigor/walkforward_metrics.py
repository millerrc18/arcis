"""Per-window and regime-conditional metrics for walk-forward (R6).

Called by: src.platform.rigor.walkforward_runner.
Calls: numpy, src.diagnostics.bootstrap.bootstrap_ci.
Owns tables: none.
Config keys: none.
Tests: tests/platform/rigor/test_walkforward_metrics.py.

Computes the raw values the runner needs to drive criterion 1–5 evaluation:

  - per-window Sharpe (annualized to 252 trading days unless overridden)
  - pooled Sharpe across all OOS trades
  - per-window max drawdown from trade-level returns
  - VIX tier bucket assignment (low/medium/high) for criterion 5
  - per-window bootstrap SE sanity check (consumed by walkforward_power)

We annualize with n=252 to match the existing project convention in
src/api/cloud_routes/trades.py._sharpe_with_se (150 there is market-hours
based for intraday; we use 252 for daily walk-forward trades).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Iterable, Sequence

import numpy as np

from src.diagnostics.bootstrap import bootstrap_ci

ANNUALIZATION_FACTOR = 252.0

# VIX bucket thresholds — match the dashboard/regime-diagnostic convention.
VIX_LOW_MAX = 15.0
VIX_MEDIUM_MAX = 25.0


@dataclass
class WindowMetrics:
    """All computed metrics for one OOS window."""

    window_index: int
    n_trades: int
    mean_pnl_pct: float
    std_pnl_pct: float
    sharpe: float
    max_drawdown_pct: float
    parametric_se: float
    bootstrap_se: float
    heavy_tail_flag: bool
    vix_tiers_represented: set[str]


def _pnl_array(trades: Iterable[Any]) -> np.ndarray:
    """Extract pnl_pct values, skipping None. Trades accept dataclass or dict."""
    out: list[float] = []
    for t in trades:
        val = getattr(t, "pnl_pct", None)
        if val is None and isinstance(t, dict):
            val = t.get("pnl_pct")
        if val is None:
            continue
        out.append(float(val))
    return np.asarray(out, dtype=float)


def compute_sharpe(pnls: np.ndarray) -> float:
    """Annualized per-trade Sharpe. Matches
    src/api/cloud_routes/trades.py._sharpe_with_se structure but with
    daily (252) annualization."""
    if pnls.size < 2:
        return 0.0
    mean = float(np.mean(pnls))
    std = float(np.std(pnls, ddof=1))
    if std == 0.0:
        return 0.0
    return (mean / std) * math.sqrt(ANNUALIZATION_FACTOR)


def compute_max_drawdown(pnls: np.ndarray) -> float:
    """Max drawdown from cumulative-return series built from trade pnl_pcts.
    Returns a non-negative fraction (e.g., 0.15 = 15%). We compound returns
    in trade order — the runner is expected to supply trades sorted by
    entry_date."""
    if pnls.size == 0:
        return 0.0
    equity = np.cumprod(1.0 + pnls)
    peak = np.maximum.accumulate(equity)
    drawdown = (peak - equity) / peak
    return float(np.max(drawdown))


def compute_parametric_se(sharpe: float, n: int) -> float:
    """Lo 2002 parametric SE of the annualized Sharpe estimator.

    Lo's raw-frequency formula is SE(SR_raw) = sqrt((1 + 0.5 * SR_raw^2) / N).
    For annualized Sharpe SR_ann = SR_raw * sqrt(T) with T=252, applying
    the change-of-variable:
        SE(SR_ann) = sqrt(T) * SE(SR_raw) = sqrt((T + 0.5 * SR_ann^2) / N).

    This keeps the parametric SE directly comparable to compute_bootstrap_se,
    which bootstraps the annualized Sharpe statistic. Without the T factor,
    the heavy-tail flag would fire unconditionally on clean Gaussian data
    (because the raw-scale parametric value is ~15x smaller than the
    annualized-scale bootstrap value, even for perfectly Gaussian returns).
    """
    if n <= 1:
        return float("inf")
    return math.sqrt(
        (ANNUALIZATION_FACTOR + 0.5 * sharpe * sharpe) / n
    )


def compute_bootstrap_se(
    pnls: np.ndarray, n_resamples: int, seed: int,
) -> float:
    """Bootstrap SE of the annualized Sharpe statistic itself. We resample
    trades with replacement, compute Sharpe on each resample, and return
    the standard deviation of the resulting Sharpe distribution. This is
    directly comparable to the parametric Lo (2002) SE(Sharpe).

    We deliberately do NOT use bootstrap_ci here because bootstrap_ci
    bootstraps the MEAN, not the Sharpe. Sharpe = (mean/std) * sqrt(252)
    — resampling changes BOTH numerator and denominator, so std(mean_boot)
    under-estimates variability of Sharpe itself, particularly for
    heavy-tailed distributions where resamples perturb std sharply. The
    heavy-tail flag (R6) depends on catching exactly that perturbation.
    """
    if pnls.size < 2:
        return float("inf")
    rng = np.random.default_rng(seed)
    n = pnls.size
    boot_sharpes = np.empty(n_resamples)
    for i in range(n_resamples):
        sample = rng.choice(pnls, size=n, replace=True)
        std = np.std(sample, ddof=1)
        if std == 0.0:
            boot_sharpes[i] = 0.0
        else:
            boot_sharpes[i] = (
                np.mean(sample) / std * math.sqrt(ANNUALIZATION_FACTOR)
            )
    return float(np.std(boot_sharpes, ddof=1))


def vix_tier_of(vix: float | None) -> str | None:
    """Bucket a VIX value into 'low' / 'medium' / 'high'. None if no VIX."""
    if vix is None:
        return None
    try:
        v = float(vix)
    except (TypeError, ValueError):
        return None
    if v < VIX_LOW_MAX:
        return "low"
    if v < VIX_MEDIUM_MAX:
        return "medium"
    return "high"


def _tiers_in(trades: Iterable[Any]) -> set[str]:
    tiers = set()
    for t in trades:
        vix = getattr(t, "vix_at_entry", None)
        if vix is None and isinstance(t, dict):
            vix = t.get("vix_at_entry")
        tier = vix_tier_of(vix)
        if tier is not None:
            tiers.add(tier)
    return tiers


def compute_window_metrics(
    trades: Sequence[Any],
    window_index: int,
    heavy_tail_se_ratio: float = 1.5,
    bootstrap_resamples: int = 10_000,
    random_seed: int = 42,
) -> WindowMetrics:
    """Compute the full WindowMetrics bundle for one OOS window's trades."""
    pnls = _pnl_array(trades)
    sharpe = compute_sharpe(pnls)
    mdd = compute_max_drawdown(pnls)
    mean = float(np.mean(pnls)) if pnls.size else 0.0
    std = float(np.std(pnls, ddof=1)) if pnls.size >= 2 else 0.0
    param_se = compute_parametric_se(sharpe, pnls.size)
    boot_se = compute_bootstrap_se(pnls, bootstrap_resamples, random_seed)
    heavy_tail = False
    if math.isfinite(param_se) and math.isfinite(boot_se) and param_se > 0:
        heavy_tail = boot_se > heavy_tail_se_ratio * param_se
    tiers = _tiers_in(trades)
    return WindowMetrics(
        window_index=window_index,
        n_trades=int(pnls.size),
        mean_pnl_pct=mean,
        std_pnl_pct=std,
        sharpe=sharpe,
        max_drawdown_pct=mdd,
        parametric_se=param_se,
        bootstrap_se=boot_se,
        heavy_tail_flag=heavy_tail,
        vix_tiers_represented=tiers,
    )


def compute_pooled_sharpe(window_trades: Sequence[Sequence[Any]]) -> float:
    """Sharpe over the concatenation of all window trade lists (OOS only)."""
    flat = []
    for w in window_trades:
        flat.extend(w)
    return compute_sharpe(_pnl_array(flat))


def distinct_tier_count(windows_metrics: Iterable[WindowMetrics]) -> int:
    """Criterion 5 input: count of distinct VIX tiers across windows."""
    tiers = set()
    for m in windows_metrics:
        tiers.update(m.vix_tiers_represented)
    return len(tiers)
