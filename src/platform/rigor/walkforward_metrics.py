"""Per-window and regime-conditional metrics for walk-forward (R6).

Called by: src.platform.rigor.walkforward_runner.
Calls: numpy, src.analytics.canonical_sharpe, src.diagnostics.bootstrap.bootstrap_ci.
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

F-2 (Sprint 0/4b WALKFORWARD-CANONICAL): the per-window Sharpe + the
inner-loop bootstrap Sharpe both used a parallel sqrt(252) implementation
instead of routing through src.analytics.canonical_sharpe. The math was
equivalent (same mean / stdev(ddof=1) * sqrt(252) shape) but the parallel
formula is precisely what the F-2 audit closed: any future tweak to the
canonical formula (e.g. ddof / annualization-factor change) would silently
diverge here. Both call sites now delegate to canonical_sharpe.raw_sharpe.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Iterable, Sequence

import numpy as np

from src.analytics.canonical_sharpe import (
    PERIODS_PER_YEAR as CANONICAL_PERIODS_PER_YEAR,
    raw_sharpe as _canonical_raw_sharpe,
    rf_adjusted_excess_sharpe as _canonical_excess_sharpe,
)
from src.diagnostics.bootstrap import bootstrap_ci

# Kept for backward-compat with tests / runner; the source of truth for
# the value lives in src.analytics.canonical_sharpe.PERIODS_PER_YEAR.
ANNUALIZATION_FACTOR = float(CANONICAL_PERIODS_PER_YEAR)

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
    # SP-WF-004 (Sprint 6 Wave B T3): excess-Sharpe gate fields.
    # None when excess_sharpe_min was not supplied (default backward-compat path).
    excess_sharpe: float | None = None
    passes_excess_sharpe: bool | None = None
    excess_sharpe_fail_reason: str | None = None


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
    """Annualized per-trade Sharpe (252-scaled).

    F-2 (Sprint 0/4b WALKFORWARD-CANONICAL): delegates to
    `src.analytics.canonical_sharpe.raw_sharpe` so all Sharpe computations
    flow through a single source of truth. Mathematically identical to the
    prior parallel implementation (`mean / std(ddof=1) * sqrt(252)`); the
    routing closes the F-2 anti-pattern (any future change to the canonical
    formula now propagates here automatically).

    Walk-forward callers expect 0.0 (not None) when Sharpe is undefined —
    we preserve that contract at the API surface.
    """
    if pnls.size < 2:
        return 0.0
    s = _canonical_raw_sharpe([float(x) for x in pnls])
    return 0.0 if s is None else s


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

    F-2 (Sprint 0/4b WALKFORWARD-CANONICAL): each resample's Sharpe is now
    computed via `compute_sharpe` (which routes through
    `canonical_sharpe.raw_sharpe`) instead of the parallel inline
    `mean / std * sqrt(252)` formula.
    """
    if pnls.size < 2:
        return float("inf")
    rng = np.random.default_rng(seed)
    n = pnls.size
    boot_sharpes = np.empty(n_resamples)
    for i in range(n_resamples):
        sample = rng.choice(pnls, size=n, replace=True)
        # Route through compute_sharpe → canonical_sharpe.raw_sharpe so any
        # future formula tweak flows through one site only.
        boot_sharpes[i] = compute_sharpe(sample)
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
    excess_sharpe_min: float | None = None,
    rf_period: float = 0.0,
) -> WindowMetrics:
    """Compute the full WindowMetrics bundle for one OOS window's trades.

    SP-WF-004 (Sprint 6 Wave B T3): when excess_sharpe_min is set, also
    computes rf-adjusted excess Sharpe via canonical_sharpe.rf_adjusted_excess_sharpe
    and gates the result against the threshold. Default None = no excess-Sharpe
    check (backward-compat path; raw Sharpe threshold still applies via the runner).
    """
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

    # SP-WF-004 excess-Sharpe gate (additive — None default preserves existing behavior).
    excess_sharpe: float | None = None
    passes_excess_sharpe: bool | None = None
    excess_sharpe_fail_reason: str | None = None
    if excess_sharpe_min is not None:
        es = _canonical_excess_sharpe([float(x) for x in pnls], rf_period)
        excess_sharpe = es if es is not None else 0.0
        if excess_sharpe >= excess_sharpe_min:
            passes_excess_sharpe = True
        else:
            passes_excess_sharpe = False
            excess_sharpe_fail_reason = "excess_sharpe_below_min"

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
        excess_sharpe=excess_sharpe,
        passes_excess_sharpe=passes_excess_sharpe,
        excess_sharpe_fail_reason=excess_sharpe_fail_reason,
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
