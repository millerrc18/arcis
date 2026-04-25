"""Canonical Sharpe ratio formulas — single source of truth for F-2.

Audit spec §F-2 (CRITICAL): the codebase had six-plus duplicated Sharpe
implementations across journal/, platform/, evaluation/, and api/ surfaces,
each with subtle differences (annualization factor, ddof, gating). This
module supplies the three canonical flavors — all 252-scaled, all using
sample stdev (ddof=1) — and the legacy sites delegate here.

Three flavors:
  raw_sharpe(returns)                 — straight per-period series
  spy_relative_sharpe(r, spy_r)       — diff-on-diff vs SPY benchmark
  rf_adjusted_excess_sharpe(r, rf)    — subtract a per-period rf rate

All return None when the series is empty, has only one observation, or
has zero variance. None is the project convention for "Sharpe undefined";
callers that need a fallback (e.g. dashboard 0.0) wrap accordingly.

Called by: src.journal.stats, src.platform.metrics, eventually
  src.api.cloud_routes.trades, src.evaluation.cto_report,
  src.platform.rigor.cscv (rename only — kept scale-invariant).
Calls: math (no numpy dep — keeps this module callable from pure-Python
  code paths like journal/stats.py).
Owns tables: none.
Config keys: none.
Tests: tests/test_canonical_sharpe.py.
"""
from __future__ import annotations

import math
from typing import Sequence

PERIODS_PER_YEAR = 252


def _annualized_sharpe(series: Sequence[float]) -> float | None:
    """mean / stdev(ddof=1) * sqrt(252). None when undefined."""
    n = len(series)
    if n < 2:
        return None
    mean = sum(series) / n
    var = sum((x - mean) ** 2 for x in series) / (n - 1)
    sd = var ** 0.5
    if sd == 0.0:
        return None
    return (mean / sd) * math.sqrt(PERIODS_PER_YEAR)


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
