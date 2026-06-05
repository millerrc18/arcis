"""KNOW-region endpoints for the Founder Console (P3-T3).

Called by: src.api.app (router registered at /api/console/know/*)
Calls: src.console.fund_ladder (generate_fund_ladder — verbatim),
       src.console.system_map (generate_system_map — verbatim),
       src.metrics.registry (headline stats — law #1, never recompute Sharpe),
       src.api.cloud_routes.kpis_compute (_fetch_closed_trades — trade source),
       src.methods.psr (psr — pure helper, wrapped not reimplemented),
       src.evaluation.statistics / src.evaluation.metrics (profit_factor /
       expectancy — pure helpers, wrapped),
       src.tools.tradingstate.core (open positions — #134 canonical book),
       src.evaluation.cto_report (_compute_confidence_calibration — REUSED join),
       src.journal.store (closed trades + recommendations for calibration)
Owns tables: none (pure consumer / orchestrator)
Config keys: none
Tests: tests/api/test_console_know.py

This router FETCHES data and passes it to registered metrics / existing pure
helpers; it NEVER computes Sharpe / PSR / win-rate / calibration math inline
(design law #1). A source that raises degrades to an explicit unknown/no_data
state and is NEVER rendered green (design law #4). LAW #8: read-only — no
execution path is touched. Headline stats with no genuine single-source helper
are OMITTED and listed in `unavailable` (honest, never an ad-hoc inline number).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends

from src.api.cloud_routes.kpis_compute import _fetch_closed_trades
from src.console.fund_ladder import generate_fund_ladder
from src.console.system_map import generate_system_map
from src.evaluation.cto_report import _compute_confidence_calibration
from src.evaluation.metrics import expectancy as expectancy_fn
from src.evaluation.statistics import profit_factor as profit_factor_fn
from src.methods.psr import psr as psr_fn
from src.metrics import registry as metric_registry
from src.tools.tradingstate.core import state as tradingstate_state

_log = logging.getLogger(__name__)

router = APIRouter()

# Headline stats with no genuine single-source helper for a track-record number.
# dsr requires an n_trials multiple-testing context (with n_trials=1 it collapses
# to psr); there is no honest standalone source, so it is omitted (law #1).
_UNAVAILABLE_STATS: tuple[str, ...] = ("dsr",)


def verify_auth() -> None:
    """Local placeholder; app.dependency_overrides[verify_auth] swaps in real auth."""
    return None


def _now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _unknown_envelope(as_of: str | None = None) -> dict:
    """An honest "unavailable" envelope: a missing source is unknown, never green."""
    return {
        "value": None, "n": 0, "as_of": as_of,
        "cohort": None, "unit": None, "state": "unknown",
    }


def _latest_close_time(trades: list[dict]) -> str | None:
    """Return the newest actual_exit_time across trades, or None (honest as_of)."""
    times = [t.get("actual_exit_time") for t in trades if t.get("actual_exit_time")]
    return max(times) if times else None


# ── /api/console/know/ladder ─────────────────────────────────────────────────

@router.get("/console/know/ladder", dependencies=[Depends(verify_auth)])
def get_know_ladder() -> dict:
    """Return the derived 6-phase fund ladder VERBATIM from the T1 service."""
    return generate_fund_ladder()


# ── /api/console/know/system-map ─────────────────────────────────────────────

@router.get("/console/know/system-map", dependencies=[Depends(verify_auth)])
def get_know_system_map() -> dict:
    """Return the derived system-map summary VERBATIM from the T2 service."""
    return generate_system_map()


# ── /api/console/know/track-record ───────────────────────────────────────────

def _equity_curve(trades: list[dict]) -> list[dict] | None:
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


def _psr_envelope(returns: list[float], as_of: str | None) -> dict:
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


def _profit_factor_envelope(trades: list[dict], as_of: str | None) -> dict:
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


def _expectancy_envelope(trades: list[dict], as_of: str | None) -> dict:
    """Wrap the pure expectancy() helper into the canonical envelope (law #1)."""
    if not trades:
        return {"value": None, "n": 0, "as_of": as_of,
                "cohort": "trades.all_closed", "unit": "usd", "state": "no_data"}
    value = expectancy_fn(float(t.get("pnl_dollars") or 0) for t in trades)
    return {"value": round(float(value), 4), "n": len(trades), "as_of": as_of,
            "cohort": "trades.all_closed", "unit": "usd", "state": "ok"}


@router.get("/console/know/track-record", dependencies=[Depends(verify_auth)])
def get_know_track_record() -> dict:
    """Audit-grade headline stats THROUGH the metric registry + pure helpers.

    Registry-sourced: rf_adjusted_sharpe / excess_sharpe_vs_spy / win_rate /
    max_drawdown / closed_trade_count. Pure-helper-wrapped: psr / profit_factor /
    expectancy. dsr is omitted (no honest single-source) and listed in
    `unavailable`. A failing trade source degrades every metric to unknown — never
    a green reading (law #4).
    """
    unavailable = list(_UNAVAILABLE_STATS)
    try:
        trades = _fetch_closed_trades()
    except Exception as exc:  # noqa: BLE001 — fail-closed: unknown, never green
        _log.warning("[console-know] trade source unavailable: %s", exc)
        metric_ids = (
            "rf_adjusted_sharpe", "excess_sharpe_vs_spy", "win_rate",
            "max_drawdown", "closed_trade_count", "psr", "profit_factor",
            "expectancy",
        )
        return {
            "metrics": {mid: _unknown_envelope() for mid in metric_ids},
            "unavailable": unavailable,
            "equity_curve": None,
            "cto_report_link": "/api/cto-report",
            "as_of": _now_utc_iso(),
        }

    returns = [float(t.get("pnl_pct") or 0) / 100.0 for t in trades]
    spy_with_data = [t for t in trades if t.get("spy_return_over_hold") is not None]
    spy_aligned = [float(t.get("pnl_pct") or 0) / 100.0 for t in spy_with_data]
    spy_returns = [float(t.get("spy_return_over_hold") or 0) for t in spy_with_data]
    as_of = _latest_close_time(trades) or _now_utc_iso()

    metrics = {
        "rf_adjusted_sharpe": metric_registry.compute_metric(
            "rf_adjusted_sharpe", returns=returns,
        ),
        "excess_sharpe_vs_spy": metric_registry.compute_metric(
            "excess_sharpe_vs_spy", returns=spy_aligned,
            spy_returns=spy_returns, as_of=as_of,
        ),
        "win_rate": metric_registry.compute_metric("win_rate", trades=trades),
        "max_drawdown": metric_registry.compute_metric(
            "max_drawdown", returns=returns, as_of=as_of,
        ),
        "closed_trade_count": metric_registry.compute_metric(
            "closed_trade_count", trades=trades, as_of=as_of,
        ),
        "psr": _psr_envelope(returns, as_of),
        "profit_factor": _profit_factor_envelope(trades, as_of),
        "expectancy": _expectancy_envelope(trades, as_of),
    }
    return {
        "metrics": metrics,
        "unavailable": unavailable,
        "equity_curve": _equity_curve(trades),
        "cto_report_link": "/api/cto-report",
        "as_of": as_of,
    }


# ── /api/console/know/ledgers ────────────────────────────────────────────────

def _open_rows() -> list[dict]:
    """Open positions from the canonical TradingState source (#134 paper book)."""
    snapshot = tradingstate_state()
    positions = snapshot.get("open_positions")
    return list(positions) if positions else []


def _filter_rows(rows: list[dict], q: str | None, limit: int | None) -> list[dict]:
    """Case-insensitive ticker search + limit (server-side)."""
    out = rows
    if q:
        needle = q.lower()
        out = [r for r in out if needle in str(r.get("ticker") or "").lower()]
    if limit is not None and limit >= 0:
        out = out[:limit]
    return out


@router.get("/console/know/ledgers", dependencies=[Depends(verify_auth)])
def get_know_ledgers(
    status: str = "all", q: str | None = None, limit: int = 500,
) -> dict:
    """Open / closed trade ledger with server-side ticker search + limit.

    Closed rows come from _fetch_closed_trades; open rows from the canonical
    TradingState source. A source that raises degrades to an empty-rows
    unknown/no_data state — never a silently-empty 'all good' list (law #4).
    """
    rows: list[dict] = []
    degraded = False
    if status in ("closed", "all"):
        try:
            rows.extend(_fetch_closed_trades())
        except Exception as exc:  # noqa: BLE001 — degrade, never fabricate
            _log.warning("[console-know] closed-trade source unavailable: %s", exc)
            degraded = True
    if status in ("open", "all"):
        try:
            rows.extend(_open_rows())
        except Exception as exc:  # noqa: BLE001 — degrade, never fabricate
            _log.warning("[console-know] open-position source unavailable: %s", exc)
            degraded = True

    if degraded:
        return {"rows": [], "n": 0, "status": status,
                "as_of": _now_utc_iso(), "state": "unknown"}

    filtered = _filter_rows(rows, q, limit)
    return {
        "rows": filtered,
        "n": len(filtered),
        "status": status,
        "as_of": _now_utc_iso(),
        "state": "ok",
    }


# ── /api/console/know/calibration ────────────────────────────────────────────

def _load_closed_for_calibration() -> list:
    """Closed trades for the calibration join (same source cto_report uses)."""
    from src.journal.store import get_closed_shadow_trades
    return get_closed_shadow_trades(days=3650)


def _load_recommendations_for_calibration() -> list:
    """Recommendations for the calibration join (same source cto_report uses)."""
    from src.journal.store import get_recommendations_in_period
    return get_recommendations_in_period(days=3650)


# _compute_confidence_calibration band keys -> frozen bucket confidence_band.
_BAND_KEYS: tuple[str, ...] = ("8-10", "5-7", "1-4")


@router.get("/console/know/calibration", dependencies=[Depends(verify_auth)])
def get_know_calibration() -> dict:
    """Recommendation-confidence -> outcome calibration via the REUSED join.

    Delegates the recommendation_id->shadow_trades join + band math entirely to
    src.evaluation.cto_report._compute_confidence_calibration (not reimplemented).
    Fail-closed: if the join yields nothing, state='no_data' with EMPTY buckets
    (NOT zero-filled bands). A source that raises -> state='unknown' (law #4).
    """
    try:
        closed = _load_closed_for_calibration()
        recommendations = _load_recommendations_for_calibration()
    except Exception as exc:  # noqa: BLE001 — fail-closed, never green
        _log.warning("[console-know] calibration source unavailable: %s", exc)
        return {
            "buckets": [],
            "join_source": "recommendations.recommendation_id->shadow_trades",
            "as_of": _now_utc_iso(),
            "state": "unknown",
        }

    calib = _compute_confidence_calibration(closed, recommendations)

    # No joined rows -> honest empty trail, not zero-filled bands.
    if calib.get("total_with_conviction", 0) == 0:
        return {
            "buckets": [],
            "join_source": "recommendations.recommendation_id->shadow_trades",
            "as_of": _now_utc_iso(),
            "state": "no_data",
        }

    by_band = calib.get("by_conviction_band", {})
    buckets: list[dict] = []
    for band in _BAND_KEYS:
        cell = by_band.get(band) or {}
        n = cell.get("trades", 0)
        buckets.append({
            "confidence_band": band,
            "n": n,
            "win_rate": cell.get("win_rate") if n else None,
            "avg_excess_return": cell.get("avg_pnl") if n else None,
            "state": "ok" if n else "no_data",
        })
    return {
        "buckets": buckets,
        "join_source": "recommendations.recommendation_id->shadow_trades",
        "as_of": _now_utc_iso(),
        "state": "ok",
    }
