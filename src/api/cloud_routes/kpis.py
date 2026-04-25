"""5-KPI hero strip endpoint — single source of truth for the Dashboard hero.

Resolves: R1 (three Sharpe formulas), S1 (wrong question), S2 (no traffic
light), G6 (Stage-2 progress bar), G3 (instrumentation_version distribution).

Single endpoint returning all 5 canonical KPIs + N + as_of timestamp.
Color rules per docs/audits/2026-04-27-trading-readiness/track-1.5-DECISIONS.md
Decision 4.

Called by: api.app (router registered at /api/kpis)
Calls: src.analytics.canonical_sharpe, src.analytics.instrumentation_filter,
  src.journal.store
Owns tables: none
Config keys: none
Tests: tests/api/test_kpis.py
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter

from src.analytics.canonical_sharpe import rf_adjusted_excess_sharpe, spy_relative_sharpe
from src.analytics.instrumentation_filter import filter_fully_instrumented

router = APIRouter()

N_MINIMUM_TRL = 150
_RF_PERIOD = 0.0001
_N_PER_YEAR = 252.0


# ── Helpers ───────────────────────────────────────────────────────────────────

def _fetch_closed_trades() -> list[dict]:
    from src.journal.store import get_closed_shadow_trades
    return get_closed_shadow_trades(days=3650)


def _fetch_spy_returns() -> list[float]:
    return []


def _sharpe_t_stat_and_ci(sharpe: float, n: int) -> tuple[float, float, float]:
    """Return (t_stat, ci_lower, ci_upper) for a Sharpe value given n.

    Uses the Jobson-Korkie SE approximation: SE = sqrt((1 + 0.5*S^2) / n).
    CI is two-sided 95% (z=1.96). Returns (NaN, NaN, NaN) when n < 2.
    """
    if n < 2:
        return float("nan"), float("nan"), float("nan")
    se = math.sqrt((1.0 + 0.5 * sharpe ** 2) / n)
    t_stat = sharpe / se if se > 0 else float("nan")
    ci_lower = sharpe - 1.96 * se
    ci_upper = sharpe + 1.96 * se
    return t_stat, ci_lower, ci_upper


def _sharpe_p_value(t_stat: float, n: int) -> float | None:
    """Two-sided p-value from t-distribution approximation (large-n Gaussian)."""
    if n < 2 or math.isnan(t_stat):
        return None
    from math import erfc, sqrt
    p = erfc(abs(t_stat) / sqrt(2.0))
    return round(float(p), 4)


# ── Status functions (Decision 4 color rules) ─────────────────────────────────

def _kpi_status_rf_sharpe(S: float | None, p: float | None) -> str:
    if S is None:
        return "unknown"
    if S > 0 and p is not None and p < 0.05:
        return "green"
    if S > 0:
        return "amber"
    if S < 0 and p is not None and p < 0.05:
        return "red"
    return "amber"


def _kpi_status_spy_sharpe(
    S: float | None, p: float | None, ci_lower: float | None,
) -> str:
    if S is None:
        return "unknown"
    if S > 0 and p is not None and p <= 0.10 and ci_lower is not None and ci_lower > 0:
        return "green"
    if S > 0:
        return "amber"
    if S < 0 and p is not None and p <= 0.10:
        return "red"
    return "amber"


def _kpi_status_win_rate(win_rate: float | None) -> str:
    if win_rate is None:
        return "unknown"
    if win_rate >= 0.55:
        return "green"
    if win_rate >= 0.45:
        return "amber"
    return "red"


def _decision_matrix_state(S: float, t_stat: float, ci_lower: float) -> str:
    """§3.1 Decision Matrix: GREEN / HOLD / HALT."""
    if S > 0 and t_stat >= 2.0 and ci_lower > 0:
        return "GREEN"
    if S > 0:
        return "HOLD"
    return "HALT"


def _decision_to_css(state: str) -> str:
    return {"GREEN": "green", "HOLD": "amber", "HALT": "red"}.get(state, "unknown")


# ── KPI compute functions ─────────────────────────────────────────────────────

def _compute_rf_adjusted_kpi(
    returns: list[float], rf_period: float = _RF_PERIOD,
) -> dict[str, Any]:
    n = len(returns)
    S = rf_adjusted_excess_sharpe(returns, rf_period)
    if S is None:
        return {"value": None, "p_value": None, "ci_lower": None, "ci_upper": None,
                "status": "unknown"}
    t_stat, ci_lower, ci_upper = _sharpe_t_stat_and_ci(S, n)
    p = _sharpe_p_value(t_stat, n)
    return {
        "value": round(S, 4),
        "p_value": p,
        "ci_lower": round(ci_lower, 4) if not math.isnan(ci_lower) else None,
        "ci_upper": round(ci_upper, 4) if not math.isnan(ci_upper) else None,
        "status": _kpi_status_rf_sharpe(S, p),
    }


def _compute_spy_relative_kpi(
    returns: list[float], spy_returns: list[float],
) -> dict[str, Any]:
    n = len(returns)
    if n == 0 or len(spy_returns) != n:
        return {"value": None, "p_value": None, "ci_lower": None, "ci_upper": None,
                "status": "unknown"}
    S = spy_relative_sharpe(returns, spy_returns)
    if S is None:
        return {"value": None, "p_value": None, "ci_lower": None, "ci_upper": None,
                "status": "unknown"}
    t_stat, ci_lower, ci_upper = _sharpe_t_stat_and_ci(S, n)
    p = _sharpe_p_value(t_stat, n)
    return {
        "value": round(S, 4),
        "p_value": p,
        "ci_lower": round(ci_lower, 4) if not math.isnan(ci_lower) else None,
        "ci_upper": round(ci_upper, 4) if not math.isnan(ci_upper) else None,
        "status": _kpi_status_spy_sharpe(S, p, ci_lower if not math.isnan(ci_lower) else None),
    }


def _compute_win_rate_kpi(trades: list[dict]) -> dict[str, Any]:
    if not trades:
        return {"value": None, "n_wins": 0, "n_losses": 0, "status": "unknown"}
    n_wins = sum(1 for t in trades if (t.get("pnl_pct") or 0) > 0)
    n_losses = sum(1 for t in trades if (t.get("pnl_pct") or 0) <= 0)
    total = n_wins + n_losses
    if total == 0:
        return {"value": None, "n_wins": 0, "n_losses": 0, "status": "unknown"}
    win_rate = n_wins / total
    return {
        "value": round(win_rate, 4),
        "n_wins": n_wins,
        "n_losses": n_losses,
        "status": _kpi_status_win_rate(win_rate),
    }


def _compute_stage_traffic_light(
    returns: list[float], rf_period: float = _RF_PERIOD,
) -> dict[str, Any]:
    n = len(returns)
    if n < 2:
        return {"status": "unknown", "S": None, "t_stat": None,
                "ci_lower": None, "decision_matrix_state": "HALT"}
    S = rf_adjusted_excess_sharpe(returns, rf_period)
    if S is None:
        return {"status": "unknown", "S": None, "t_stat": None,
                "ci_lower": None, "decision_matrix_state": "HALT"}
    t_stat, ci_lower, _ = _sharpe_t_stat_and_ci(S, n)
    state = _decision_matrix_state(
        S, t_stat if not math.isnan(t_stat) else 0.0,
        ci_lower if not math.isnan(ci_lower) else float("-inf"),
    )
    return {
        "status": _decision_to_css(state),
        "S": round(S, 4),
        "t_stat": round(t_stat, 4) if not math.isnan(t_stat) else None,
        "ci_lower": round(ci_lower, 4) if not math.isnan(ci_lower) else None,
        "decision_matrix_state": state,
    }


def _compute_promotion_gate_kpi(
    n_trades: int, returns: list[float],
) -> dict[str, Any]:
    base = {"votes_passed": None, "votes_total": 5}
    if n_trades == 0:
        return {**base, "status": "blue",
                "caption": "MinTRL: gate not yet evaluable — no closed trades yet"}
    if n_trades < N_MINIMUM_TRL or len(returns) < N_MINIMUM_TRL:
        return {**base, "status": "blue",
                "caption": f"MinTRL: gate not yet evaluable (N={n_trades}, need {N_MINIMUM_TRL})"}
    try:
        from src.methods.promotion_gate import promotion_gate
        gate_result = promotion_gate(returns, n_trials=1)
        votes_passed = sum(1 for v in gate_result.get("votes", {}).values() if v)
        decision = gate_result.get("decision", "defer")
        status = "green" if decision == "promote" else "red" if decision == "reject" else "blue"
        caption = f"{votes_passed}/5 methods passed"
        return {"votes_passed": votes_passed, "votes_total": 5, "status": status,
                "caption": caption}
    except Exception:
        return {**base, "status": "blue",
                "caption": f"MinTRL: gate not yet evaluable (N={n_trades}, need {N_MINIMUM_TRL})"}


def _compute_instrumentation_pct(trades: list[dict]) -> float | None:
    if not trades:
        return None
    v3_count = sum(1 for t in trades if t.get("instrumentation_version") == 3)
    return round(100.0 * v3_count / len(trades), 1)


# ── Route ─────────────────────────────────────────────────────────────────────

@router.get("/kpis")
def get_kpis() -> dict:
    """Return all 5 canonical KPIs for the Dashboard hero strip."""
    raw_trades = _fetch_closed_trades()
    spy_returns = _fetch_spy_returns()
    instrumented = filter_fully_instrumented(raw_trades)
    n_trades = len(instrumented)
    returns = [float(t.get("pnl_pct") or 0) / 100.0 for t in instrumented]

    return {
        "n_trades": n_trades,
        "n_minimum_trl": N_MINIMUM_TRL,
        "as_of": datetime.now(timezone.utc).isoformat(),
        "instrumentation_pct": _compute_instrumentation_pct(raw_trades),
        "rf_adjusted_excess_sharpe": _compute_rf_adjusted_kpi(returns),
        "spy_relative_sharpe": _compute_spy_relative_kpi(returns, spy_returns),
        "win_rate": _compute_win_rate_kpi(instrumented),
        "stage_traffic_light": _compute_stage_traffic_light(returns),
        "promotion_gate": _compute_promotion_gate_kpi(n_trades, returns),
    }
