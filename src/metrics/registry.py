"""Metric Registry — single source of truth for console metrics (design law #1).

Every console metric is DEFINED and COMPUTED exactly once here. The Founder
Console is a pure consumer: it never recomputes Sharpe/PSR/win-rate math and
never reads a raw metric value off a sentinel. This module is the metric-side
analogue of src/schema/registry.py (the table single-source).

The Sharpe / SPY-relative / win-rate math is NOT reimplemented here — it is
wrapped read-only from the existing pure compute helpers in
src.api.cloud_routes.kpis_compute, with cohort labels pulled from
src.api.cohort_meta. Each wrapped compute returns the canonical envelope::

    {value, n, as_of, cohort, unit, state}

where state ∈ {ok, no_data, sentinel}. Sentinel placeholders (999 / -1 / NaN
/ ±inf) and missing data surface as a `state` flag and a None `value` — they
NEVER leak through as a raw number (design laws #2/#3, backend origin).

Called by: src.metrics (re-export); console read routes (T6, later)
Calls: src.api.cloud_routes.kpis_compute, src.api.cohort_meta
Owns tables: none
Config keys: none
Tests: tests/test_metric_registry.py
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Callable

from src.api.cohort_meta import COHORT_LABELS
from src.api.cloud_routes import kpis_compute

# Integer/float placeholder sentinels that must never reach the console as a
# raw value. NaN / ±inf are detected separately (they are not equality-stable).
_SENTINEL_VALUES = (999, -1)


@dataclass
class MetricDef:
    """Definition of a single console metric.

    id: stable registry key. label: human-readable name. compute: a zero-or-
    kwargs callable returning either a raw-result dict (with at least a
    `value` key) or a full canonical envelope. cohort: COHORT_LABELS key.
    window: time-window label (e.g. "all", "30d"). unit: e.g. "ratio",
    "pct", "usd". fmt: display format string for the console.
    """

    id: str
    label: str
    compute: Callable[..., dict]
    cohort: str
    window: str
    unit: str
    fmt: str


REGISTRY: dict[str, MetricDef] = {}


def register(metric: MetricDef) -> None:
    """Register a MetricDef, rejecting duplicate ids."""
    if metric.id in REGISTRY:
        raise ValueError(f"duplicate metric id: {metric.id!r}")
    REGISTRY[metric.id] = metric


def _is_sentinel(value: Any) -> bool:
    """Return True if value is a sentinel placeholder that must not leak."""
    if value is None:
        return False
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return True
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value in _SENTINEL_VALUES
    return False


def _envelope(metric: MetricDef, raw: dict) -> dict:
    """Coerce a raw compute result into the canonical envelope.

    Honours an already-canonical envelope (one carrying a `state` key) and
    otherwise derives state from the raw `value`: None -> no_data, sentinel
    placeholder -> sentinel, anything else -> ok.
    """
    if "state" in raw:
        return raw
    value = raw.get("value")
    n = raw.get("n", 0)
    as_of = raw.get("as_of")
    if value is None:
        state = "no_data"
    elif _is_sentinel(value):
        state = "sentinel"
        value = None
    else:
        state = "ok"
    return {
        "value": value,
        "n": n,
        "as_of": as_of,
        "cohort": metric.cohort,
        "unit": metric.unit,
        "state": state,
    }


def compute_metric(metric_id: str, **kwargs: Any) -> dict:
    """Compute a single registered metric and return its canonical envelope."""
    metric = REGISTRY[metric_id]
    raw = metric.compute(**kwargs)
    return _envelope(metric, raw)


def compute_all(**per_metric_kwargs: dict) -> dict[str, dict]:
    """Compute every registered metric, passing per-metric kwargs by id.

    per_metric_kwargs maps a metric id to the kwargs dict for that metric's
    compute. Metrics with no entry are computed with no kwargs.
    """
    out: dict[str, dict] = {}
    for metric_id in REGISTRY:
        kwargs = per_metric_kwargs.get(metric_id, {})
        out[metric_id] = compute_metric(metric_id, **kwargs)
    return out


# ---------------------------------------------------------------------------
# Built-in metrics — thin wrappers over the legacy kpis_compute helpers so the
# registry becomes the single owner. The math lives in kpis_compute; we only
# add the canonical envelope + cohort/n bookkeeping.
# ---------------------------------------------------------------------------


def _wrap_rf_adjusted_sharpe(returns: list | None = None) -> dict:
    returns = returns or []
    if not returns:
        return {"value": None, "n": 0}
    raw = kpis_compute._compute_rf_adjusted_kpi(returns)
    return {"value": raw.get("value"), "n": len(returns)}


def _wrap_spy_relative_sharpe(
    returns: list | None = None, spy_returns: list | None = None,
) -> dict:
    returns = returns or []
    spy_returns = spy_returns or []
    if not returns:
        return {"value": None, "n": 0}
    raw = kpis_compute._compute_spy_relative_kpi(returns, spy_returns)
    return {"value": raw.get("value"), "n": len(returns)}


def _wrap_win_rate(trades: list | None = None) -> dict:
    trades = trades or []
    if not trades:
        return {"value": None, "n": 0}
    raw = kpis_compute._compute_win_rate_kpi(trades)
    n = raw.get("n_wins", 0) + raw.get("n_losses", 0)
    return {"value": raw.get("value"), "n": n}


register(MetricDef(
    id="rf_adjusted_sharpe",
    label="Risk-free-adjusted excess Sharpe",
    compute=_wrap_rf_adjusted_sharpe,
    cohort="kpi.canonical",
    window="all",
    unit="ratio",
    fmt="{:.2f}",
))

register(MetricDef(
    id="spy_relative_sharpe",
    label="SPY-relative Sharpe",
    compute=_wrap_spy_relative_sharpe,
    cohort="kpi.canonical",
    window="all",
    unit="ratio",
    fmt="{:.2f}",
))

register(MetricDef(
    id="win_rate",
    label="Win rate",
    compute=_wrap_win_rate,
    cohort="trades.all_closed",
    window="all",
    unit="ratio",
    fmt="{:.1%}",
))

# Touch COHORT_LABELS so the cohort dependency is real (single-source proof:
# every metric cohort must be a known taxonomy key).
for _m in REGISTRY.values():
    if _m.cohort not in COHORT_LABELS:
        raise ValueError(f"unknown cohort {_m.cohort!r} for metric {_m.id!r}")
