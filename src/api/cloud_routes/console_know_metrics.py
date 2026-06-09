"""Pure track-record / rigor metric-envelope helpers for the KNOW region.

Called by: src.api.cloud_routes.console_know (track-record + rigor-metrics).
Calls: src.methods.psr (psr / dsr — pure helpers, wrapped not reimplemented),
       src.evaluation.statistics / src.evaluation.metrics (profit_factor /
       expectancy — pure helpers, wrapped),
       src.utils.db (connect_db — read-only n_trials for the Deflated Sharpe).
Owns tables: none (pure consumer / wrapper).
Config keys: none.
Tests: tests/api/test_console_know.py.

Each helper wraps an EXISTING pure metric into the canonical envelope
{value, n, as_of, cohort, unit, state} (design law #1 — never recompute the
math here). When the math cannot be computed honestly (too few observations,
missing multiple-testing context, undefined ratio) the envelope degrades to an
explicit no_data state with value=None — never a fabricated number (law #4).
This module is split out of console_know.py to keep that router under the
400-line guardrail; the patch-at-binding-site for psr_fn / dsr_fn / _sum_n_trials
lives HERE.
"""
from __future__ import annotations

import logging

from src.evaluation.metrics import expectancy as expectancy_fn
from src.evaluation.statistics import profit_factor as profit_factor_fn
from src.methods.psr import dsr as dsr_fn
from src.methods.psr import psr as psr_fn
from src.utils.db import connect_db

_log = logging.getLogger(__name__)


def equity_curve(trades: list[dict]) -> list[dict] | None:
    """Best-effort cumulative equity curve from closed trades (None if unavailable).

    Cumulative product of (1 + per-trade return), ordered by exit time. Returns
    None when no trade carries an exit time — emptiness is honest, not a flat
    line implying a real curve.
    """
    dated = [t for t in trades if t.get("actual_exit_time")]
    if not dated:
        return None
    dated = sorted(dated, key=lambda t: t["actual_exit_time"])
    equity = 1.0
    curve: list[dict] = []
    for t in dated:
        equity *= (1.0 + float(t.get("pnl_pct") or 0) / 100.0)
        curve.append({"t": t["actual_exit_time"], "equity": round(equity, 6)})
    return curve


def psr_envelope(returns: list[float], as_of: str | None) -> dict:
    """Wrap the pure psr() helper into the canonical envelope (law #1).

    psr() raises ValueError below 5 observations; that degrades to no_data with
    value=None rather than a fabricated probability.
    """
    n = len(returns)
    try:
        value = psr_fn(returns)
    except Exception as exc:  # noqa: BLE001 — too-few-obs / source issue -> no_data
        _log.debug("[console-know] psr unavailable: %s", exc)
        return {"value": None, "n": n, "as_of": as_of,
                "cohort": "kpi.canonical", "unit": "probability", "state": "no_data"}
    return {"value": round(float(value), 4), "n": n, "as_of": as_of,
            "cohort": "kpi.canonical", "unit": "probability", "state": "ok"}


def sum_n_trials() -> int:
    """Total trials tested = SUM(n_params_searched) over trials_registry (read-only).

    Bailey-López de Prado counts EVERY parameter combination as a trial, so this
    sums n_params_searched rather than COUNT(*) (which undercounts — a 10-point
    sweep is 10 trials, not 1). Returns 0 when the registry is empty or the
    source raises, which the DSR envelope reads as an honest no_data context.
    """
    conn = connect_db()
    try:
        row = conn.execute(
            "SELECT COALESCE(SUM(n_params_searched), 0) FROM trials_registry"
        ).fetchone()
    finally:
        conn.close()
    return int(row[0]) if row is not None else 0


def dsr_envelope(returns: list[float], n_trials: int, as_of: str | None) -> dict:
    """Wrap the pure dsr() helper into the canonical envelope (law #1).

    dsr() deflates PSR for the multiple-testing across n_trials strategies. It
    raises ValueError below 5 observations; n_trials < 1 means there is no
    honest multiple-testing context. Either degrades to no_data with value=None
    rather than a fabricated probability (law #4).
    """
    n = len(returns)
    if n_trials < 1:
        return {"value": None, "n": n, "as_of": as_of,
                "cohort": "kpi.canonical", "unit": "probability", "state": "no_data"}
    try:
        value = dsr_fn(returns, n_trials)
    except Exception as exc:  # noqa: BLE001 — too-few-obs / source issue -> no_data
        _log.debug("[console-know] dsr unavailable: %s", exc)
        return {"value": None, "n": n, "as_of": as_of,
                "cohort": "kpi.canonical", "unit": "probability", "state": "no_data"}
    return {"value": round(float(value), 4), "n": n, "as_of": as_of,
            "cohort": "kpi.canonical", "unit": "probability", "state": "ok"}


def profit_factor_envelope(trades: list[dict], as_of: str | None) -> dict:
    """Wrap the pure profit_factor() helper into the canonical envelope (law #1)."""
    if not trades:
        return {"value": None, "n": 0, "as_of": as_of,
                "cohort": "trades.all_closed", "unit": "ratio", "state": "no_data"}
    wins = sum(float(t.get("pnl_dollars") or 0) for t in trades
               if (t.get("pnl_dollars") or 0) > 0)
    losses = sum(float(t.get("pnl_dollars") or 0) for t in trades
                 if (t.get("pnl_dollars") or 0) < 0)
    pf = profit_factor_fn(wins, losses)
    # Undefined / no-loss inf is not a real ratio -> no_data (never a sentinel).
    if pf in (float("inf"), 0.0) and losses == 0:
        state, value = "no_data", None
    else:
        state, value = "ok", round(float(pf), 4)
    return {"value": value, "n": len(trades), "as_of": as_of,
            "cohort": "trades.all_closed", "unit": "ratio", "state": state}


def expectancy_envelope(trades: list[dict], as_of: str | None) -> dict:
    """Wrap the pure expectancy() helper into the canonical envelope (law #1)."""
    if not trades:
        return {"value": None, "n": 0, "as_of": as_of,
                "cohort": "trades.all_closed", "unit": "usd", "state": "no_data"}
    value = expectancy_fn(float(t.get("pnl_dollars") or 0) for t in trades)
    return {"value": round(float(value), 4), "n": len(trades), "as_of": as_of,
            "cohort": "trades.all_closed", "unit": "usd", "state": "ok"}
