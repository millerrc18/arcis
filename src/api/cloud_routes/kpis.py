"""5-KPI hero strip endpoint — FastAPI router + orchestrator.

Resolves: R1 (three Sharpe formulas), S1 (wrong question), S2 (no traffic
light), G6 (Stage-2 progress bar), G3 (instrumentation_version distribution).

Single endpoint returning all 5 canonical KPIs + N + as_of timestamp.
Color rules per docs/audits/2026-04-27-trading-readiness/track-1.5-DECISIONS.md
Decision 4.

Called by: api.app (router registered at /api/kpis)
Calls: src.api.cloud_routes.kpis_compute (all numeric helpers), src.analytics.canonical_sharpe,
  src.analytics.instrumentation_filter, src.data_ingestion.risk_free_rate, src.journal.store
Owns tables: none
Config keys: none
Tests: tests/api/test_kpis.py

Numeric helpers live in kpis_compute.py (Sprint 0.B Wave B2.4, issue #696).
The orchestrator (get_kpis) lives here so test patches on
src.api.cloud_routes.kpis.* resolve correctly.
"""
from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timezone

from fastapi import APIRouter, Depends

from src.analytics import kpis_compute as _analytics_kpis
from src.analytics.instrumentation_filter import filter_fully_instrumented
from src.api.cohort_meta import meta_entry
from src.config import DB_PATH

_log = logging.getLogger(__name__)

_GATE_PROPOSAL_ZERO_SHAPE: dict[str, dict[str, int]] = {
    "1d": {"promote": 0, "reject": 0, "defer": 0, "unknown": 0},
    "7d": {"promote": 0, "reject": 0, "defer": 0, "unknown": 0},
    "30d": {"promote": 0, "reject": 0, "defer": 0, "unknown": 0},
}

router = APIRouter()


# #632 — verify_auth is injected at mount time from cloud_app.py via
# FastAPI's dependency_overrides. Placeholder is a no-op so routes load
# in test/dev mode; cloud_app overrides it with the real bearer-token
# check in prod. Same pattern as walkforward.py / broker_exceptions.py.
def verify_auth() -> None:  # noqa: D401  # placeholder, overridden in prod
    """Default kpis auth dep — no-op until cloud_app overrides it."""
    return None


# Import all compute helpers into kpis namespace so test patches on
# src.api.cloud_routes.kpis.<helper> resolve to these names.
from src.api.cloud_routes.kpis_compute import (  # noqa: E402, F401
    N_MINIMUM_TRL,
    _RF_PERIOD,
    _N_PER_YEAR,
    _fetch_closed_trades,
    _parse_iso_date,
    _compute_per_trade_rf,
    _fetch_spy_returns_for_trades,
    _sample_autocorrelation,
    _lo_2002_autocorr_factor,
    _sharpe_t_stat_and_ci,
    _sharpe_p_value,
    _kpi_status_rf_sharpe,
    _kpi_status_spy_sharpe,
    _kpi_status_win_rate,
    _decision_matrix_state,
    _decision_to_css,
    _compute_rf_adjusted_kpi,
    _compute_spy_relative_kpi,
    _compute_win_rate_kpi,
    _compute_stage_traffic_light,
    _compute_promotion_gate_kpi,
    _compute_instrumentation_pct,
)


@router.get("/kpis/gate-proposals", dependencies=[Depends(verify_auth)])
def get_gate_proposal_kpis() -> dict:
    """Return methodology gate-proposal counts by decision over 1d/7d/30d windows.

    Reads strategy_promotion_events filtered by triggered_by='gate_proposal'
    via src.analytics.kpis_compute.get_gate_proposal_counts. operator_confirm
    rows are excluded (real promotion transitions, not gate-proposal observations).

    Returns the canonical zero shape and logs a warning if the table is missing
    (fresh deployments before the first daily run) so the dashboard does not
    show an error card.
    """
    try:
        return _analytics_kpis.get_gate_proposal_counts(DB_PATH)
    except sqlite3.OperationalError as exc:
        _log.warning(
            "[gate-proposals] strategy_promotion_events not yet available: %s; "
            "returning zero shape", exc,
        )
        return _GATE_PROPOSAL_ZERO_SHAPE


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
    rf_per_trade, rf_used_fred = _compute_per_trade_rf(instrumented)
    _kpi_meta = meta_entry("kpi.canonical", n_trades)
    return {
        "n_trades": n_trades,
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
        "_meta": {
            "rf_adjusted_excess_sharpe": _kpi_meta,
            "spy_relative_sharpe": _kpi_meta,
            "win_rate": _kpi_meta,
            "stage_traffic_light": _kpi_meta,
            "promotion_gate": _kpi_meta,
        },
    }
