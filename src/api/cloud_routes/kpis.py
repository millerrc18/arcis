"""5-KPI hero strip endpoint — single source of truth for the Dashboard hero.

Resolves: R1 (three Sharpe formulas), S1 (wrong question), S2 (no traffic
light), G6 (Stage-2 progress bar), G3 (instrumentation_version distribution).

Single endpoint returning all 5 canonical KPIs + N + as_of timestamp.
Color rules per docs/audits/2026-04-27-trading-readiness/track-1.5-DECISIONS.md
Decision 4.

Called by: api.app (router registered at /api/kpis)
Calls: src.analytics.canonical_sharpe, src.analytics.instrumentation_filter,
  src.data_ingestion.risk_free_rate, src.journal.store
Owns tables: none
Config keys: none
Tests: tests/api/test_kpis.py
"""
from __future__ import annotations

import datetime as _dt
import logging
import math
from datetime import datetime, timezone
from typing import Any

import numpy as np
from fastapi import APIRouter, Depends

from src.analytics.canonical_sharpe import rf_adjusted_excess_sharpe, spy_relative_sharpe
from src.analytics.instrumentation_filter import filter_fully_instrumented

logger = logging.getLogger(__name__)

router = APIRouter()


# #632 — verify_auth is injected at mount time from cloud_app.py via
# FastAPI's dependency_overrides. Placeholder is a no-op so routes load
# in test/dev mode; cloud_app overrides it with the real bearer-token
# check in prod. Same pattern as walkforward.py / broker_exceptions.py.
def verify_auth() -> None:  # noqa: D401  # placeholder, overridden in prod
    """Default kpis auth dep — no-op until cloud_app overrides it."""
    return None


N_MINIMUM_TRL = 150
# Fallback per-trading-day rf rate used when FRED is unreachable.
# (≈2.52% annualized / 252; mirrors scripts/stage1_baseline_recompute.py
# RF_PERIOD_CONSTANT — keep them in lockstep.)
_RF_PERIOD = 0.0001
_N_PER_YEAR = 252.0


# ── Helpers ───────────────────────────────────────────────────────────────────

def _fetch_closed_trades() -> list[dict]:
    from src.journal.store import get_closed_shadow_trades
    return get_closed_shadow_trades(days=3650)


def _parse_iso_date(iso_str: str | None) -> _dt.date | None:
    """Best-effort ISO -> date. Returns None on any parse failure.

    shadow_trades stores actual_entry_time / actual_exit_time as ISO strings
    (e.g. '2026-04-23T10:00:00-04:00'). We only need the date portion for
    rf rate lookup; an unparseable string falls through to the placeholder.
    """
    if not iso_str or not isinstance(iso_str, str):
        return None
    try:
        return _dt.date.fromisoformat(iso_str[:10])
    except (TypeError, ValueError):
        return None


def _compute_per_trade_rf(trades: list[dict]) -> tuple[list[float], bool]:
    """Return (per_trade_rf_vec, used_fred) for a list of trade dicts.

    Per-trade rf = per_trading_day_rf(entry_date) * trading_days_in_hold.
    Falls back to the flat `_RF_PERIOD` placeholder for any trade whose
    FRED lookup or date parse fails (logged WARNING). The boolean flag
    indicates whether AT LEAST one trade got a real FRED rate, which the
    caller surfaces in the API response so the operator can see whether
    the rf wiring is live for this query.

    rf is annualized; canonical_sharpe._annualized_sharpe applies the
    sqrt(252) factor on the per-period diff series, so we want a rf value
    that matches the per-trade return scale — i.e. cumulative rf return
    over the holding period. numpy.busday_count gives us trading days
    inclusive of weekends/holidays (np uses Mon-Fri default, no NYSE
    calendar — close enough for an SE-driving constant; the audit-spec
    deferral is the proper NYSE calendar).
    """
    from src.data_collection.errors import CollectorConfigError
    from src.data_ingestion.risk_free_rate import get_rf_rate

    rfs: list[float] = []
    used_fred = False
    for t in trades:
        entry = _parse_iso_date(t.get("actual_entry_time"))
        exit_ = _parse_iso_date(t.get("actual_exit_time"))
        if entry is None or exit_ is None:
            rfs.append(_RF_PERIOD)
            continue
        # busday_count expects half-open [start, end). For a same-day trade
        # we want at least one trading day of rf accrual.
        end_excl = exit_ + _dt.timedelta(days=1) if exit_ >= entry else exit_
        try:
            hold_days = int(np.busday_count(entry, end_excl))
        except (TypeError, ValueError):
            hold_days = 1
        hold_days = max(1, hold_days)
        try:
            per_day = get_rf_rate(entry)
        except CollectorConfigError as exc:
            logger.warning(
                "[KPI_RF_FALLBACK] FRED API key missing — using placeholder "
                "rf=%s (trade=%s): %s",
                _RF_PERIOD, t.get("trade_id") or "?", exc,
            )
            rfs.append(_RF_PERIOD * hold_days)
            continue
        except Exception as exc:  # noqa: BLE001  — network/HTTP/KeyError fallthrough
            logger.warning(
                "[KPI_RF_FALLBACK] FRED fetch failed — using placeholder "
                "rf=%s (trade=%s, entry=%s): %s",
                _RF_PERIOD, t.get("trade_id") or "?", entry, exc,
                exc_info=True,
            )
            rfs.append(_RF_PERIOD * hold_days)
            continue
        used_fred = True
        rfs.append(per_day * hold_days)
    return rfs, used_fred


def _fetch_spy_returns_for_trades(trades: list[dict]) -> list[float]:
    """Extract per-trade SPY returns from the spy_return_over_hold column.

    Filters out trades where spy_return_over_hold is None so the returned
    list only contains trades with real SPY data. Returns [] when no trades
    have SPY data (caller will produce status='unknown' for SPY-relative KPI).
    """
    return [
        float(t["spy_return_over_hold"])
        for t in trades
        if t.get("spy_return_over_hold") is not None
    ]


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
    returns: list[float],
    rf_period: float | list[float] = _RF_PERIOD,
) -> dict[str, Any]:
    """Compute the rf-adjusted excess Sharpe KPI.

    `rf_period` accepts either:
      - a scalar (legacy / fallback path; same value subtracted from every
        return — preserves existing test surface), or
      - a list[float] aligned 1:1 with `returns` (per-trade rf, T2.10 wiring
        path; produced by `_compute_per_trade_rf`).
    """
    n = len(returns)
    if isinstance(rf_period, (list, tuple)):
        if len(rf_period) != n:
            return {"value": None, "p_value": None, "ci_lower": None,
                    "ci_upper": None, "status": "unknown"}
        excess = [r - rf for r, rf in zip(returns, rf_period)]
        S = rf_adjusted_excess_sharpe(excess, 0.0)
    else:
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
    returns: list[float],
    rf_period: float | list[float] = _RF_PERIOD,
) -> dict[str, Any]:
    n = len(returns)
    if n < 2:
        return {"status": "unknown", "S": None, "t_stat": None,
                "ci_lower": None, "decision_matrix_state": "HALT"}
    if isinstance(rf_period, (list, tuple)):
        if len(rf_period) != n:
            return {"status": "unknown", "S": None, "t_stat": None,
                    "ci_lower": None, "decision_matrix_state": "HALT"}
        excess = [r - rf for r, rf in zip(returns, rf_period)]
        S = rf_adjusted_excess_sharpe(excess, 0.0)
    else:
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

@router.get("/kpis", dependencies=[Depends(verify_auth)])
def get_kpis() -> dict:
    """Return all 5 canonical KPIs for the Dashboard hero strip."""
    raw_trades = _fetch_closed_trades()
    instrumented = filter_fully_instrumented(raw_trades)
    n_trades = len(instrumented)
    returns = [float(t.get("pnl_pct") or 0) / 100.0 for t in instrumented]
    spy_with_data = [t for t in instrumented if t.get("spy_return_over_hold") is not None]
    spy_returns = _fetch_spy_returns_for_trades(spy_with_data)
    spy_aligned_returns = [float(t.get("pnl_pct") or 0) / 100.0 for t in spy_with_data]

    # T2.10: per-trade rf from FRED DTB3. Falls back to _RF_PERIOD per trade
    # on FRED failure (network down, missing key, KeyError) — see
    # _compute_per_trade_rf for the WARNING log path.
    rf_per_trade, rf_used_fred = _compute_per_trade_rf(instrumented)

    return {
        "n_trades": n_trades,
        # PR #690 I4: rf_adjusted_excess_sharpe is computed on ALL
        # instrumented trades (n_total); spy_relative_sharpe is computed
        # only on the subset that has spy_return_over_hold populated
        # (n_spy). Frontend captions need to label each card with its
        # own N — see frontend/src/components/dashboard/KPIStrip.jsx.
        "n_total": n_trades,
        "n_spy": len(spy_with_data),
        "n_minimum_trl": N_MINIMUM_TRL,
        "as_of": datetime.now(timezone.utc).isoformat(),
        "instrumentation_pct": _compute_instrumentation_pct(raw_trades),
        "rf_adjusted_excess_sharpe": _compute_rf_adjusted_kpi(returns, rf_per_trade),
        "spy_relative_sharpe": _compute_spy_relative_kpi(spy_aligned_returns, spy_returns),
        "win_rate": _compute_win_rate_kpi(instrumented),
        "stage_traffic_light": _compute_stage_traffic_light(returns, rf_per_trade),
        "promotion_gate": _compute_promotion_gate_kpi(n_trades, returns),
        "rf_source": "fred_dtb3" if rf_used_fred else "placeholder",
    }
