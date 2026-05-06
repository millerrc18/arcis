"""Pure compute helpers for the 5-KPI hero strip — no FastAPI dependencies.

Called by: api.cloud_routes.kpis
Calls: src.analytics.canonical_sharpe, src.data_ingestion.risk_free_rate,
  src.methods.promotion_gate; src.journal.store.get_closed_shadow_trades
  (local SQLite path); psycopg2 (Render Postgres path).
Owns tables: none
Config keys: DATABASE_URL env var (Postgres routing)
Tests: tests/api/test_kpis.py

Extracted from kpis.py during Sprint 0.B Wave B2.4 (issue #696) to bring
kpis.py under the 400-line file-size guardrail. Contains all numeric/compute
functions; kpis.py keeps only the FastAPI router surface.

#87: _fetch_closed_trades is dual-mode. On Render (DATABASE_URL set) it
queries Postgres directly so the cloud dashboard sees synced shadow_trades
rows. Locally (DATABASE_URL unset) it goes through journal.store, which
opens a SQLite connection. Without this branch the cloud KPI strip read
from an empty SQLite file on Render and the dashboard showed n_trades=0.
"""
from __future__ import annotations

import datetime as _dt
import logging
import math
import os
from typing import Any

import numpy as np

from src.analytics.canonical_sharpe import rf_adjusted_excess_sharpe, spy_relative_sharpe
from src.journal.store import get_closed_shadow_trades

logger = logging.getLogger(__name__)

N_MINIMUM_TRL = 150
_RF_PERIOD = 0.0001
_N_PER_YEAR = 252.0


def _fetch_closed_trades_from_postgres(database_url: str, days: int) -> list[dict]:
    """Read closed shadow_trades rows from Render Postgres.

    Mirrors the SQL in journal.store.get_closed_shadow_trades but issues it
    against Postgres with `%s` placeholders. Returns plain dicts so callers
    don't need a sqlite3.Row → dict conversion step.
    """
    from datetime import datetime, timedelta, timezone
    import psycopg2
    import psycopg2.extras
    from src.shadow_trading.exit_reason import outcome_stats_filter_sql
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    sql = (
        "SELECT * FROM shadow_trades WHERE status = 'closed' "
        "AND actual_exit_time >= %s "
        "AND COALESCE(quarantined, 0) = 0 "
        f"{outcome_stats_filter_sql()} "
        "ORDER BY actual_exit_time DESC"
    )
    with psycopg2.connect(database_url) as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, (cutoff,))
            return [dict(r) for r in cur.fetchall()]


def _fetch_closed_trades() -> list[dict]:
    """Return closed shadow_trades rows from the last 10 years.

    Cloud (Render): DATABASE_URL set → reads Postgres directly. Local dev:
    DATABASE_URL unset → goes through journal.store (SQLite). Both branches
    return the same row shape so downstream KPI compute helpers stay
    backend-agnostic.
    """
    database_url = os.environ.get("DATABASE_URL", "")
    if database_url:
        return _fetch_closed_trades_from_postgres(database_url, days=3650)
    return get_closed_shadow_trades(days=3650)


def _parse_iso_date(iso_str: str | None) -> _dt.date | None:
    """Best-effort ISO -> date. Returns None on any parse failure."""
    if not iso_str or not isinstance(iso_str, str):
        return None
    try:
        return _dt.date.fromisoformat(iso_str[:10])
    except (TypeError, ValueError):
        return None


def _compute_per_trade_rf(trades: list[dict]) -> tuple[list[float], bool]:
    """Return (per_trade_rf_vec, used_fred) for a list of trade dicts."""
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
        except Exception as exc:  # noqa: BLE001
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
    """Extract per-trade SPY returns from the spy_return_over_hold column."""
    return [
        float(t["spy_return_over_hold"])
        for t in trades
        if t.get("spy_return_over_hold") is not None
    ]


def _sample_autocorrelation(series: list[float], k: int) -> float:
    """Return the k-th sample autocorrelation of `series`."""
    n = len(series)
    if n <= k or k < 1:
        return 0.0
    mean = sum(series) / n
    deviations = [x - mean for x in series]
    denom = sum(d * d for d in deviations)
    if denom == 0.0:
        return 0.0
    numerator = sum(deviations[t] * deviations[t - k] for t in range(k, n))
    return numerator / denom


def _lo_2002_autocorr_factor(series: list[float], q: int = 4) -> float:
    """Lo 2002 autocorrelation-correction factor for Sharpe SE."""
    n = len(series)
    if n <= 1 or q < 1:
        return 1.0
    q_eff = min(q, n - 1)
    inner = 0.0
    for k in range(1, q_eff + 1):
        weight = 1.0 - (k / q_eff) if q_eff > 0 else 0.0
        rho_k = _sample_autocorrelation(series, k)
        inner += weight * rho_k
    factor_squared = 1.0 + 2.0 * inner
    if factor_squared <= 0.0:
        return 1.0
    return math.sqrt(factor_squared)


def _sharpe_t_stat_and_ci(
    sharpe: float,
    n: int,
    returns: list[float] | None = None,
    periods_per_year: float = _N_PER_YEAR,
) -> tuple[float, float, float]:
    """Return (t_stat, ci_lower, ci_upper) for a Sharpe value given n."""
    if n < 2:
        return float("nan"), float("nan"), float("nan")
    se = math.sqrt((periods_per_year + 0.5 * sharpe ** 2) / n)
    if returns is not None and len(returns) >= 2:
        se *= _lo_2002_autocorr_factor(list(returns), q=4)
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
    if S >= 0 and t_stat >= 1.5 and ci_lower > -0.2:
        return "GREEN"
    if S >= 0:
        return "HOLD"
    return "HALT"


def _decision_to_css(state: str) -> str:
    return {"GREEN": "green", "HOLD": "amber", "HALT": "red"}.get(state, "unknown")


def _compute_rf_adjusted_kpi(
    returns: list[float],
    rf_period: float | list[float] = _RF_PERIOD,
) -> dict[str, Any]:
    """Compute the rf-adjusted excess Sharpe KPI."""
    n = len(returns)
    if isinstance(rf_period, (list, tuple)):
        if len(rf_period) != n:
            return {"value": None, "p_value": None, "ci_lower": None,
                    "ci_upper": None, "status": "unknown"}
        excess = [r - rf for r, rf in zip(returns, rf_period)]
        S = rf_adjusted_excess_sharpe(excess, 0.0)
        diff_series_for_lo = excess
    else:
        S = rf_adjusted_excess_sharpe(returns, rf_period)
        diff_series_for_lo = [r - rf_period for r in returns]
    if S is None:
        return {"value": None, "p_value": None, "ci_lower": None, "ci_upper": None,
                "status": "unknown"}
    t_stat, ci_lower, ci_upper = _sharpe_t_stat_and_ci(
        S, n, returns=diff_series_for_lo,
    )
    p = _sharpe_p_value(t_stat, n)
    return {
        "value": round(S, 4),
        "p_value": p,
        "ci_lower": round(ci_lower, 4) if not math.isnan(ci_lower) else None,
        "ci_upper": round(ci_upper, 4) if not math.isnan(ci_upper) else None,
        "status": _kpi_status_rf_sharpe(S, p),
        "se_assumes_iid": False,
        "se_method": "lo_2002_autocorr_corrected_q4",
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
    diff_series = [r - s for r, s in zip(returns, spy_returns)]
    t_stat, ci_lower, ci_upper = _sharpe_t_stat_and_ci(
        S, n, returns=diff_series,
    )
    p = _sharpe_p_value(t_stat, n)
    return {
        "value": round(S, 4),
        "p_value": p,
        "ci_lower": round(ci_lower, 4) if not math.isnan(ci_lower) else None,
        "ci_upper": round(ci_upper, 4) if not math.isnan(ci_upper) else None,
        "status": _kpi_status_spy_sharpe(S, p, ci_lower if not math.isnan(ci_lower) else None),
        "se_assumes_iid": False,
        "se_method": "lo_2002_autocorr_corrected_q4",
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
        diff_series_for_lo = excess
    else:
        S = rf_adjusted_excess_sharpe(returns, rf_period)
        diff_series_for_lo = [r - rf_period for r in returns]
    if S is None:
        return {"status": "unknown", "S": None, "t_stat": None,
                "ci_lower": None, "decision_matrix_state": "HALT"}
    t_stat, ci_lower, _ = _sharpe_t_stat_and_ci(
        S, n, returns=diff_series_for_lo,
    )
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
    dates: list | None = None,
    directions: list[int] | None = None,
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
        gate_result = promotion_gate(returns, n_trials=1, dates=dates, directions=directions)
        votes_passed = sum(1 for v in gate_result.get("votes", {}).values() if v)
        decision = gate_result.get("decision", "defer")
        status = "green" if decision == "promote" else "red" if decision == "reject" else "blue"
        caption = f"{votes_passed}/5 methods passed"
        return {"votes_passed": votes_passed, "votes_total": 5, "status": status,
                "caption": caption}
    except Exception as exc:  # noqa: BLE001
        logger.warning("[KPI_PROMOTION_GATE_ERROR] %s", exc, exc_info=True)
        return {**base, "status": "error", "caption": "Promotion gate error — see logs"}


def _compute_instrumentation_pct(trades: list[dict]) -> float | None:
    if not trades:
        return None
    v3_count = sum(1 for t in trades if t.get("instrumentation_version") == 3)
    return round(100.0 * v3_count / len(trades), 1)


