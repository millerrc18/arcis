"""Canonical Sharpe ratio formulas — single source of truth for F-2.

Audit spec §F-2 (CRITICAL): the codebase had six-plus duplicated Sharpe
implementations across journal/, platform/, evaluation/, and api/ surfaces,
each with subtle differences (annualization factor, ddof, gating). This
module supplies the three canonical flavors — all 252-scaled by default,
all using sample stdev (ddof=1) by default — and the legacy sites delegate
here.

Three flavors:
  raw_sharpe(returns)                 — straight per-period series
  spy_relative_sharpe(r, spy_r)       — diff-on-diff vs SPY benchmark
  rf_adjusted_excess_sharpe(r, rf)    — subtract a per-period rf rate

Plus the parametric `compute_sharpe(returns, periods_per_year=252, ddof=1)`
introduced for Sprint-0 wave-4a SHARPE-CONSOLIDATION-EVAL: legacy callers
in cto_report (150 trades/yr), system rolling-Sharpe snapshots (150),
model_monitor (per-trade), evaluation.statistics (per-trade gate, ddof=0),
and simulation.engine (52 weekly, ddof=0) all delegate here. The
`periods_per_year` parameter accommodates non-252 conventions; the `ddof`
parameter accommodates legacy ddof=0 (population) callers that would
silently change behavior on a ddof=1 swap (gate threshold preservation,
np.std default parity).

All return None when the series is empty, has too few observations
(n <= ddof), or has zero variance. None is the project convention for
"Sharpe undefined"; callers that need a numeric fallback (e.g. dashboard
0.0, or model_monitor's regression-comparison arithmetic) wrap accordingly.

## Sortino flavors — which to use

This module provides `compute_sortino_mar` (Sprint-0 wave-4a, PR #718).
The codebase also has `src.platform.metrics.compute_sortino`. They differ
in the downside-deviation divisor:

  compute_sortino_mar(returns, mar=0)          [this module]
    Divisor: RMS of (r - mar) over the downside subset only, i.e.
      sqrt(sum(min(r, mar)^2) / len(downside)).
    Use when: matching the legacy cto_report._compute_fund_metrics formula
      or any MAR-gated Sortino where the threshold is non-zero. This is the
      canonical form for cto_report / fund-level periodic reporting.

  src.platform.metrics.compute_sortino(returns)
    Divisor: sample stdev (ddof=1) of the downside subset only, i.e.
      stdev([r for r in returns if r < 0]).
    Use when: per-trade risk-adjusted stats, model evaluation gates, or
      any context that expects a sample-stdev-of-negatives divisor rather
      than RMS. This is the canonical form for per-trade platform.metrics
      callers.

Cross-references: `src.platform.metrics.compute_sortino`,
  `src.analytics.canonical_sharpe.compute_sortino_mar`.

Called by: src.journal.stats, src.platform.metrics, src.api.routes.system,
  src.evaluation.cto_report, src.evaluation.model_monitor,
  src.evaluation.statistics, src.simulation.engine,
  src.api.cloud_routes.analytics.
Calls: math (no numpy dep — keeps this module callable from pure-Python
  code paths like journal/stats.py).
Owns tables: none.
Config keys: none.
Tests: tests/test_canonical_sharpe.py,
  tests/evaluation/test_sharpe_canonical_routing.py,
  tests/test_b2_5_methodology.py.
"""
from __future__ import annotations

import math
from typing import Sequence

PERIODS_PER_YEAR = 252


def _annualized_sharpe(
    series: Sequence[float],
    periods_per_year: int = PERIODS_PER_YEAR,
    ddof: int = 1,
) -> float | None:
    """mean / stdev(ddof=ddof) * sqrt(periods_per_year). None when undefined.

    Defaults match the historical canonical: ddof=1 (sample stdev) and
    periods_per_year=252. Override `ddof` only for backward-compat with
    callers that documented np.std default (ddof=0) behavior; override
    `periods_per_year` for non-daily conventions (52 weekly, 150 trades/yr,
    1 per-trade un-annualized).
    """
    n = len(series)
    if n <= ddof:
        return None
    mean = sum(series) / n
    var = sum((x - mean) ** 2 for x in series) / (n - ddof)
    sd = var ** 0.5
    if sd == 0.0:
        return None
    return (mean / sd) * math.sqrt(periods_per_year)


def compute_sharpe(
    returns: Sequence[float],
    periods_per_year: int = PERIODS_PER_YEAR,
    ddof: int = 1,
) -> float | None:
    """Annualized Sharpe = mean(returns)/std(returns, ddof=ddof) * sqrt(periods_per_year).

    Public canonical entry-point used by the six legacy Sharpe sites
    consolidated by Sprint-0 wave-4a. None when undefined (empty series,
    n <= ddof, zero variance). Callers that contractually return a numeric
    sentinel (e.g. 0.0) on degenerate inputs wrap the None at the call
    site — canonical does not implicitly substitute.

    Returns:
        Annualized Sharpe, or None when undefined.
    """
    return _annualized_sharpe(list(returns), periods_per_year=periods_per_year, ddof=ddof)


def raw_sharpe(returns: Sequence[float]) -> float | None:
    """Annualized raw Sharpe = mean(returns)/std(returns, ddof=1)*sqrt(252)."""
    return _annualized_sharpe(list(returns))


def spy_relative_sharpe(
    returns: Sequence[float], spy_returns: Sequence[float],
) -> float | None:
    """Annualized SPY-relative Sharpe on the per-period (returns-spy_returns)
    diff series. Inputs must be aligned and equal-length."""
    if len(returns) != len(spy_returns):
        return None
    diff = [r - s for r, s in zip(returns, spy_returns)]
    return _annualized_sharpe(diff)


def rf_adjusted_excess_sharpe(
    returns: Sequence[float], rf_period: float,
) -> float | None:
    """Annualized rf-adjusted Sharpe on the (returns - rf_period) series.
    rf_period is a per-period (not annualized) risk-free rate."""
    diff = [r - rf_period for r in returns]
    return _annualized_sharpe(diff)


def compute_sortino_mar(
    returns: Sequence[float],
    periods_per_year: int = PERIODS_PER_YEAR,
    mar: float = 0.0,
) -> float | None:
    """Sortino with MAR threshold (default 0): mean / RMS(downside) * sqrt(periods_per_year).

    Distinct from `src.platform.metrics.compute_sortino` (which uses
    stdev-of-downside-subset divisor). This MAR-based variant matches the
    legacy `cto_report._compute_fund_metrics` formula:

        downside_dev = sqrt(sum(min(r, mar)^2) / len(downside_subset))
        sortino = mean(r) / downside_dev * sqrt(periods_per_year)

    Returns None when there are no downside observations or when the
    downside RMS is zero. Callers that contractually return 0 / 'inf' on
    these paths must wrap.
    """
    if not returns:
        return None
    downside = [r for r in returns if r < mar]
    if not downside:
        return None
    # RMS of (r - mar) on downside-only subset; equivalent to RMS(r) when mar=0
    downside_dev = (sum((r - mar) ** 2 for r in downside) / len(downside)) ** 0.5
    if downside_dev == 0.0:
        return None
    mean_r = sum(returns) / len(returns)
    return (mean_r / downside_dev) * math.sqrt(periods_per_year)
