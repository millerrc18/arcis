"""Derived Phase 1->6 fund-ladder generator for the Founder Console (P3-T1).

Called by: src.api.cloud_routes (KNOW-region route, T3 — later)
Calls: src.console.gate_targets (GATE_TARGETS — single-source thresholds),
       src.metrics.registry (compute_metric — law #1, never recompute Sharpe),
       src.api.cloud_routes.kpis_compute (_fetch_closed_trades — the trade source),
       src.version (VERSION fallback)
Owns tables: none (pure derived read)
Config keys: none
Tests: tests/test_fund_ladder.py

This module derives the fund ladder from machine-readable sources ONLY
(design law #7). The PHASE_LADDER constant is the machine-readable STRUCTURE —
AUM targets and the gate-metric target keys per phase. The per-phase LIVE
progress numbers are COMPUTED from the metric registry; they are NEVER
hand-typed (the spec's anti-goal — the roadmap drifted because it was
hand-maintained).

Fail-closed: if a source is unavailable the affected gate is state='unknown'
and the envelope carries generation_ok=False + failed_sources=[...]. We NEVER
serve a silently stale snapshot and NEVER fabricate a number. Phases beyond the
current one show their targets with state='pending' (legitimate emptiness,
distinct from a measured zero).
"""
from __future__ import annotations

import logging
import subprocess

from src.api.cloud_routes.kpis_compute import _fetch_closed_trades
from src.console.gate_targets import GATE_TARGETS
from src.metrics import registry as metric_registry
from src.version import VERSION

_log = logging.getLogger(__name__)

# The four north-star gate metrics every phase must clear (single-source keys
# from GATE_TARGETS). Listed once; each phase references this same set so the
# STRUCTURE — not a typed progress number — is what's declared per phase.
_GATE_METRIC_IDS: tuple[str, ...] = (
    "closed_trade_count",
    "excess_sharpe_vs_spy",
    "sharpe_t_stat",
    "max_drawdown",
)

# Machine-readable spec: the 6 phases with AUM targets + gate-metric keys.
# This is STRUCTURE only — no live progress counts live here (law #7).
PHASE_LADDER: list[dict] = [
    {"phase": 1, "name": "Proof", "aum_target": "$100", "gate_metrics": _GATE_METRIC_IDS},
    {"phase": 2, "name": "Seed", "aum_target": "$1K", "gate_metrics": _GATE_METRIC_IDS},
    {"phase": 3, "name": "Pilot", "aum_target": "$5K", "gate_metrics": _GATE_METRIC_IDS},
    {"phase": 4, "name": "Scale", "aum_target": "$25K", "gate_metrics": _GATE_METRIC_IDS},
    {"phase": 5, "name": "Growth", "aum_target": "$100K", "gate_metrics": _GATE_METRIC_IDS},
    {"phase": 6, "name": "Fund", "aum_target": "$500K+", "gate_metrics": _GATE_METRIC_IDS},
]


def _source_sha() -> str:
    """Short git SHA via subprocess; fall back to VERSION when git is unavailable."""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=5, check=True,
        )
        sha = out.stdout.strip()
        if sha:
            return sha
    except Exception as exc:  # noqa: BLE001 — any git failure -> version fallback
        _log.debug("[fund-ladder] git rev-parse unavailable: %s", exc)
    return VERSION


def _latest_close_time(trades: list[dict]) -> str | None:
    """Return the newest actual_exit_time across trades, or None (honest as_of)."""
    times = [t.get("actual_exit_time") for t in trades if t.get("actual_exit_time")]
    return max(times) if times else None


def _compute_current_gates() -> tuple[dict[str, dict], list[str]]:
    """Compute the current-phase gate envelopes from real sources (law #1/#7).

    Returns (gates_by_id, failed_sources). On source unavailability every gate
    degrades to state='unknown' with value=None (fail-closed) and the trade
    source is recorded in failed_sources — never a fabricated number.
    """
    try:
        trades = _fetch_closed_trades()
    except Exception as exc:  # noqa: BLE001 — fail-closed, do not raise
        _log.warning("[fund-ladder] trade source unavailable: %s", exc)
        gates = {mid: _unknown_gate(mid) for mid in _GATE_METRIC_IDS}
        return gates, ["closed_trades"]

    returns = [float(t.get("pnl_pct") or 0) / 100.0 for t in trades]
    spy_with_data = [t for t in trades if t.get("spy_return_over_hold") is not None]
    spy_aligned = [float(t.get("pnl_pct") or 0) / 100.0 for t in spy_with_data]
    spy_returns = [float(t.get("spy_return_over_hold") or 0) for t in spy_with_data]
    as_of = _latest_close_time(trades)

    gates = {
        "closed_trade_count": metric_registry.compute_metric(
            "closed_trade_count", trades=trades, as_of=as_of,
        ),
        "excess_sharpe_vs_spy": metric_registry.compute_metric(
            "excess_sharpe_vs_spy", returns=spy_aligned,
            spy_returns=spy_returns, as_of=as_of,
        ),
        "sharpe_t_stat": metric_registry.compute_metric(
            "sharpe_t_stat", returns=returns, as_of=as_of,
        ),
        "max_drawdown": metric_registry.compute_metric(
            "max_drawdown", returns=returns, as_of=as_of,
        ),
    }
    return gates, []


def _unknown_gate(metric_id: str) -> dict:
    """An honest fail-closed gate: unknown, value=None, never green/fabricated."""
    return {
        "metric_id": metric_id,
        "value": None,
        "target": GATE_TARGETS.get(metric_id),
        "n": 0,
        "as_of": None,
        "cohort": None,
        "unit": None,
        "state": "unknown",
    }


def _pending_gate(metric_id: str) -> dict:
    """A legitimate-emptiness gate for phases beyond the current one.

    state='pending' with value=None is distinct from a measured zero; the
    target is still shown so the bar is visible.
    """
    return {
        "metric_id": metric_id,
        "value": None,
        "target": GATE_TARGETS.get(metric_id),
        "n": 0,
        "as_of": None,
        "cohort": None,
        "unit": None,
        "state": "pending",
    }


def _gate_from_envelope(metric_id: str, env: dict) -> dict:
    """Map a registry envelope onto the frozen gate shape (adds metric_id+target)."""
    return {
        "metric_id": metric_id,
        "value": env.get("value"),
        "target": GATE_TARGETS.get(metric_id),
        "n": env.get("n", 0),
        "as_of": env.get("as_of"),
        "cohort": env.get("cohort"),
        "unit": env.get("unit"),
        "state": env.get("state", "unknown"),
    }


def _gate_met(gate: dict) -> bool:
    """True only when a gate has a real value clearing its target.

    max_drawdown is a ceiling (lower is better); the rest are floors. A gate
    that is unknown / no_data / pending is NOT met (fail-closed).
    """
    if gate["state"] != "ok" or gate["value"] is None or gate["target"] is None:
        return False
    if gate["metric_id"] == "max_drawdown":
        return gate["value"] <= gate["target"]
    return gate["value"] >= gate["target"]


def _progress(gates: list[dict]) -> float | None:
    """Fraction of the phase's gates currently met, or None if none are scorable.

    Returns None (not 0.0) when every gate is unknown — emptiness is not a
    measured zero (fail-closed honesty).
    """
    scorable = [g for g in gates if g["state"] in {"ok", "no_data"}]
    if not scorable:
        return None
    met = sum(1 for g in scorable if _gate_met(g))
    return round(met / len(scorable), 4)


def generate_fund_ladder() -> dict:
    """Build the derived 6-phase fund ladder envelope (the frozen T3 shape).

    The current phase's gates are computed from real sources; later phases are
    pending. Fail-closed: a broken source yields generation_ok=False +
    failed_sources and unknown gates, never an exception or a fabricated number.
    """
    current_gates, failed_sources = _compute_current_gates()
    all_met = bool(current_gates) and all(
        _gate_met(_gate_from_envelope(mid, current_gates[mid]))
        for mid in _GATE_METRIC_IDS
    )

    # Derived current phase: the lowest phase whose gates are not all met. With a
    # single live gate-target set (Phase-1 bar), this stays at Phase 1 until the
    # gates clear — derived from live state, never hand-typed.
    current_phase = 2 if all_met else 1

    ladder: list[dict] = []
    for spec in PHASE_LADDER:
        phase_no = spec["phase"]
        if phase_no < current_phase:
            gates = [_gate_from_envelope(mid, current_gates[mid])
                     for mid in spec["gate_metrics"]]
            status = "complete"
            progress = _progress(gates)
        elif phase_no == current_phase:
            gates = [_gate_from_envelope(mid, current_gates[mid])
                     for mid in spec["gate_metrics"]]
            status = "active"
            progress = _progress(gates)
        else:
            gates = [_pending_gate(mid) for mid in spec["gate_metrics"]]
            status = "pending"
            progress = None
        ladder.append({
            "phase": phase_no,
            "name": spec["name"],
            "aum_target": spec["aum_target"],
            "status": status,
            "gates": gates,
            "progress": progress,
        })

    gate_times = [g.get("as_of") for g in (current_gates or {}).values() if g.get("as_of")]
    as_of = max(gate_times) if gate_times else _now_iso()
    return {
        "ladder": ladder,
        "current_phase": current_phase,
        "generation_ok": not failed_sources,
        "failed_sources": failed_sources,
        "source_sha": _source_sha(),
        "as_of": as_of,
    }


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()
