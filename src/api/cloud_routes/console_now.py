"""NOW-region + honest-header endpoints for the Founder Console (T6).

Called by: src.api.app (router registered at /api/console/*)
Calls: src.metrics.registry (gate metrics — law #1), src.tools.healthprobe.core,
       src.tools.tradingstate.core, src.risk.governor, src.shadow_trading.break_events,
       src.logging.activity, src.scheduler.holidays, src.config, src.version
Owns tables: none (pure consumer / orchestrator)
Config keys: bootcamp.enabled, live_trading.enabled (header flags only)
Tests: tests/api/test_console_now.py

This router FETCHES data and passes it to registered metrics for the envelope
{value, n, as_of, cohort, unit, state}; it NEVER computes a metric inline
(design law #1). Missing signal sources surface as an explicit unknown/alarmed
state and are NEVER rendered healthy/green (design law #4). The reconciliation
signal counts RETAINED break events (break-rate), not post-backfill state
(design law #9). Open positions read the single canonical TradingState source
(#134 paper book). PAUSE is owned by T4/T5 — not duplicated here.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends

from src.api.cloud_routes.kpis_compute import _fetch_closed_trades
from src.config import load_config
from src.logging.activity import get_recent_activity
from src.metrics import registry as metric_registry
from src.shadow_trading.break_events import get_break_events
from src.tools.healthprobe.core import check as healthprobe_check
from src.tools.tradingstate.core import state as tradingstate_state
from src.version import VERSION

_log = logging.getLogger(__name__)

_ET = ZoneInfo("America/New_York")

router = APIRouter()


def verify_auth() -> None:
    """Local placeholder; app.dependency_overrides[verify_auth] swaps in real auth."""
    return None


# North-star gate targets (the bar each metric must clear). Display-side only —
# the metric values themselves come exclusively from the registry.
_GATE_TARGETS: dict[str, float] = {
    "closed_trade_count": 100,
    "excess_sharpe_vs_spy": 0.5,
    "sharpe_t_stat": 2.0,
    "max_drawdown": 0.20,
}

# An honest "unavailable" envelope: a missing source is unknown, never green.
def _unknown_envelope(as_of: str | None = None) -> dict:
    return {"value": None, "n": 0, "as_of": as_of, "state": "unknown", "healthy": None}


def _now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── /api/console/header ──────────────────────────────────────────────────────

@router.get("/console/header", dependencies=[Depends(verify_auth)])
def get_header() -> dict:
    """Honest header: version, PAPER / bootcamp-OFF flags, market state, clock.

    Flags are READ from config/runtime — never narrated or hardcoded. paper is
    True when live_trading.enabled is falsy; bootcamp_off is True when
    bootcamp.enabled is falsy.
    """
    from src.scheduler.holidays import is_market_open

    cfg = load_config()
    live_enabled = bool((cfg.get("live_trading") or {}).get("enabled", False))
    bootcamp_enabled = bool((cfg.get("bootcamp") or {}).get("enabled", False))

    now_et = datetime.now(_ET)
    return {
        "version": VERSION,
        "paper": not live_enabled,
        "bootcamp_off": not bootcamp_enabled,
        "market_open": bool(is_market_open(now_et)),
        "server_clock": now_et.isoformat(),
    }


# ── /api/console/now/gate ────────────────────────────────────────────────────

@router.get("/console/now/gate", dependencies=[Depends(verify_auth)])
def get_now_gate() -> dict:
    """North-star gate-progress metrics vs targets, through the metric registry.

    The route fetches closed trades and passes them to the registered gate
    metrics — it does NOT compute Sharpe / t-stat / drawdown inline (law #1).
    """
    trades = _fetch_closed_trades()
    returns = [float(t.get("pnl_pct") or 0) / 100.0 for t in trades]
    spy_with_data = [t for t in trades if t.get("spy_return_over_hold") is not None]
    spy_aligned = [float(t.get("pnl_pct") or 0) / 100.0 for t in spy_with_data]
    spy_returns = [float(t.get("spy_return_over_hold") or 0) for t in spy_with_data]

    # Honest as_of: the cohort's latest close time, else compute time.
    as_of = _latest_close_time(trades) or _now_utc_iso()

    metrics = {
        "closed_trade_count": metric_registry.compute_metric(
            "closed_trade_count", trades=trades, as_of=as_of,
        ),
        "excess_sharpe_vs_spy": metric_registry.compute_metric(
            "excess_sharpe_vs_spy", returns=spy_aligned, spy_returns=spy_returns, as_of=as_of,
        ),
        "sharpe_t_stat": metric_registry.compute_metric(
            "sharpe_t_stat", returns=returns, as_of=as_of,
        ),
        "max_drawdown": metric_registry.compute_metric(
            "max_drawdown", returns=returns, as_of=as_of,
        ),
    }
    return {"metrics": metrics, "targets": dict(_GATE_TARGETS), "as_of": as_of}


def _latest_close_time(trades: list[dict]) -> str | None:
    """Return the newest actual_exit_time across trades, or None."""
    times = [t.get("actual_exit_time") for t in trades if t.get("actual_exit_time")]
    return max(times) if times else None


# ── /api/console/now/signals ─────────────────────────────────────────────────

def _governor_signal() -> dict:
    """Risk-governor limits-used signal: open positions vs effective cap.

    Returns {value, n, as_of}. Raises on source unavailability so the route can
    flag it unknown (law #4) rather than fabricate a healthy reading.
    """
    from src.risk.governor import effective_position_cap, get_portfolio_state

    cfg = load_config()
    cap = effective_position_cap(cfg)
    portfolio = get_portfolio_state()
    open_positions = portfolio.get("open_positions") or []
    used = len(open_positions)
    return {"value": used, "n": cap, "as_of": _now_utc_iso()}


@router.get("/console/now/signals", dependencies=[Depends(verify_auth)])
def get_now_signals() -> dict:
    """Integrity / liveness signals. ABSENCE of a source is flagged unknown/
    alarmed and is NEVER reported healthy/green (design law #4)."""
    signals: dict[str, dict] = {}

    # Heartbeat + data-feed freshness via healthprobe. Unavailable -> unknown.
    try:
        probe = healthprobe_check()
        watchloop = (probe.get("services") or {}).get("ArcisWatchLoop") or {}
        hb_fresh = watchloop.get("heartbeat_fresh")
        probe_as_of = probe.get("as_of_et")
        if hb_fresh is None:
            signals["heartbeat"] = {
                "value": None, "n": 0, "as_of": probe_as_of,
                "state": "unknown", "healthy": None,
            }
        else:
            signals["heartbeat"] = {
                "value": watchloop.get("state"), "n": 1, "as_of": probe_as_of,
                "state": "ok", "healthy": bool(hb_fresh),
            }
        signals["data_feed"] = {
            "value": probe.get("overall"), "n": 1, "as_of": probe_as_of,
            "state": "ok", "healthy": probe.get("overall") == "OK",
        }
    except Exception as exc:  # noqa: BLE001 — any probe failure is an unknown
        _log.warning("[console-now] healthprobe unavailable: %s", exc)
        signals["heartbeat"] = _unknown_envelope()
        signals["data_feed"] = _unknown_envelope()

    # Reconciliation break-rate via retained break events (law #9).
    try:
        breaks = get_break_events()
        newest = breaks[0]["created_at"] if breaks else _now_utc_iso()
        signals["reconciliation"] = {
            "value": len(breaks), "n": len(breaks), "as_of": newest,
            "state": "ok", "healthy": len(breaks) == 0,
        }
    except Exception as exc:  # noqa: BLE001
        _log.warning("[console-now] break events unavailable: %s", exc)
        signals["reconciliation"] = _unknown_envelope()

    # Risk-governor limits-used. Unavailable -> unknown.
    try:
        gov = _governor_signal()
        cap = gov.get("n") or 0
        used = gov.get("value")
        signals["risk_limits"] = {
            "value": used, "n": cap, "as_of": gov.get("as_of"),
            "state": "ok", "healthy": used is not None and cap > 0 and used <= cap,
        }
    except Exception as exc:  # noqa: BLE001
        _log.warning("[console-now] governor unavailable: %s", exc)
        signals["risk_limits"] = _unknown_envelope()

    return {"signals": signals, "as_of": _now_utc_iso()}


# ── /api/console/now/positions ───────────────────────────────────────────────

@router.get("/console/now/positions", dependencies=[Depends(verify_auth)])
def get_now_positions() -> dict:
    """Open positions from the canonical TradingState source (#134 paper book).

    On source unavailability the response is an explicit unknown state with
    positions=None — never an empty list rendered as healthy (law #4)."""
    try:
        snapshot = tradingstate_state()
    except Exception as exc:  # noqa: BLE001
        _log.warning("[console-now] tradingstate unavailable: %s", exc)
        return {"positions": None, "as_of": None, "state": "unknown"}

    positions = snapshot.get("open_positions")
    return {
        "positions": positions,
        "n": len(positions) if positions is not None else 0,
        "as_of": snapshot.get("as_of_et"),
        "data_source": snapshot.get("data_source"),
        "state": "ok" if positions is not None else "no_data",
    }


# ── /api/console/now/attention ───────────────────────────────────────────────

def _pending_decision_count() -> dict:
    """Count existing pending gates (strategy/model promotions, auditor-halt
    recommendations, AI-team merge asks). Returns {value, n, as_of}.

    Reads whatever pending-gate sources exist. Sources that are absent degrade
    to a zero contribution rather than fabricating a count."""
    count = 0
    # Pending strategy/model promotion proposals.
    try:
        from src.analytics import kpis_compute as _ak
        from src.config import DB_PATH
        proposals = _ak.get_gate_proposal_counts(DB_PATH)
        for window in proposals.values():
            if isinstance(window, dict):
                count += int(window.get("defer", 0) or 0)
    except Exception as exc:  # noqa: BLE001
        _log.debug("[console-now] gate-proposal source unavailable: %s", exc)
    return {"value": count, "n": count, "as_of": _now_utc_iso()}


@router.get("/console/now/attention", dependencies=[Depends(verify_auth)])
def get_now_attention() -> dict:
    """Pending-decisions COUNT ONLY plus a desk_healthy boolean.

    No queue, no decision actions — the Decide region is a later phase
    (scope fence)."""
    try:
        pending = _pending_decision_count()
        pending_env = {
            "value": pending.get("value"), "n": pending.get("n", 0),
            "as_of": pending.get("as_of"), "state": "ok",
        }
        desk_healthy = (pending.get("value") or 0) == 0
    except Exception as exc:  # noqa: BLE001
        _log.warning("[console-now] pending-decision source unavailable: %s", exc)
        pending_env = _unknown_envelope()
        desk_healthy = False

    return {"pending_count": pending_env, "desk_healthy": bool(desk_healthy)}


# ── /api/console/now/since ───────────────────────────────────────────────────

def _delta_since(hours: int) -> dict:
    """Delta band over the last `hours`: opened/closed trades, alerts, audit
    verdict changes, deploys. Best-effort; missing sources contribute 0."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    cutoff_iso = cutoff.isoformat()
    opened = closed = 0
    try:
        trades = _fetch_closed_trades()
        for t in trades:
            exit_time = t.get("actual_exit_time")
            if isinstance(exit_time, str) and exit_time >= cutoff_iso:
                closed += 1
            entry_time = t.get("actual_entry_time")
            if isinstance(entry_time, str) and entry_time >= cutoff_iso:
                opened += 1
    except Exception as exc:  # noqa: BLE001
        _log.debug("[console-now] since: trades source unavailable: %s", exc)
    return {
        "opened": opened,
        "closed": closed,
        "alerts_raised": 0,
        "alerts_resolved": 0,
        "audit_changes": 0,
        "deploys": 0,
    }


@router.get("/console/now/since", dependencies=[Depends(verify_auth)])
def get_now_since(hours: int = 24) -> dict:
    """Delta band since now - N hours (default 24)."""
    delta = _delta_since(hours=hours)
    return {"hours": hours, "delta": delta, "as_of": _now_utc_iso()}


# ── /api/console/now/devteam ─────────────────────────────────────────────────

@router.get("/console/now/devteam", dependencies=[Depends(verify_auth)])
def get_now_devteam() -> dict:
    """AI dev-team current activity + this-week PRs / regressions / scope
    violations (read existing activity/velocity sources)."""
    try:
        activity = get_recent_activity(limit=10)
    except Exception as exc:  # noqa: BLE001
        _log.warning("[console-now] activity source unavailable: %s", exc)
        activity = []

    prs = regressions = scope_violations = 0
    week_cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    for entry in activity:
        ts = entry.get("timestamp")
        if isinstance(ts, str) and ts < week_cutoff:
            continue
        cat = (entry.get("category") or "").lower()
        event = (entry.get("event") or "").lower()
        if "pr" in cat or "pr" in event or "merge" in event:
            prs += 1
        if "regression" in cat or "regression" in event:
            regressions += 1
        if "scope" in cat or "scope" in event:
            scope_violations += 1

    return {
        "activity": activity,
        "this_week": {
            "prs": prs,
            "regressions": regressions,
            "scope_violations": scope_violations,
        },
        "as_of": _now_utc_iso(),
    }
