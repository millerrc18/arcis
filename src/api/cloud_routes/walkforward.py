"""/api/walkforward/* endpoints — walk-forward validation dashboard data.

Called by: frontend/src/pages/WalkforwardResults.jsx.
Calls: none (direct SQLite reads).
Owns tables: reads walkforward_results, walkforward_trades.
Tests: tests/api/test_walkforward_routes.py.

Single-mode SQLite (Render resources stopped 2026-05-18; post-cutover).
Exposes:
    GET  /api/walkforward/runs               list runs (latest per strategy)
    GET  /api/walkforward/runs/{run_id}      single-run metadata
    GET  /api/walkforward/runs/{run_id}/windows   per-window breakdown
    GET  /api/walkforward/runs/{run_id}/trades    per-trade drill-down

The three-state outcome (PASS / FAIL / INCONCLUSIVE) is preserved
end-to-end: outcome_state is a top-level field on every run response and
the dashboard uses it to color-code rows. INCONCLUSIVE_POWER and
INCONCLUSIVE_DATA counts are surfaced separately so the dashboard can
show the INCONCLUSIVE_POWER badge distinct from INSUFFICIENT_DATA.
"""

from __future__ import annotations

import logging
import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Query

from src.config import DB_PATH
from src.utils.db import connect_db

logger = logging.getLogger(__name__)

router = APIRouter()


# #632 — verify_auth is injected at mount time from cloud_app.py via
# FastAPI's dependency_overrides to avoid a circular import (cloud_app
# imports this module, this module needs cloud_app's verify_auth). The
# placeholder is a no-op so routes still load in test/dev mode; cloud_app
# overrides it with the real bearer-token check in prod. Mirrors the
# pattern used by src/api/cloud_routes/platform.py.
def verify_auth() -> None:  # noqa: D401  # placeholder, overridden in prod
    """Default walkforward auth dep — no-op until cloud_app overrides it."""
    return None


def _read_rows(sql: str, params: tuple = ()) -> list[dict]:
    conn = connect_db(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()


def _read_one(sql: str, params: tuple = ()) -> dict | None:
    rows = _read_rows(sql, params)
    return rows[0] if rows else None


@router.get("/api/walkforward/runs", dependencies=[Depends(verify_auth)])
async def list_runs(
    limit: int = Query(50, ge=1, le=200),
    strategy_id: str | None = None,
    outcome_state: str | None = None,
) -> dict:
    """Return walk-forward runs ordered by recency. Optional filters by
    strategy_id and outcome_state (PASS / FAIL / INCONCLUSIVE)."""
    where = ["1=1"]
    params: list = []
    if strategy_id:
        where.append("strategy_id = ?")
        params.append(strategy_id)
    if outcome_state and outcome_state != "all":
        where.append("outcome_state = ?")
        params.append(outcome_state)
    params.append(limit)
    where_sql = " AND ".join(where)
    rows = _read_rows(
        f"SELECT run_id, strategy_id, outcome_state, reason, pooled_sharpe, "
        f"pooled_mde, heavy_tail_flag, heavy_tail_window_count, n_windows, "
        f"n_windows_pass, n_windows_fail, n_windows_inconclusive_data, "
        f"n_windows_inconclusive_power, n_windows_inconclusive_duration, "
        f"derived_from_source_type, effective_universe_size, "
        f"max_drawdown_pct, vix_tier_coverage, "
        f"gate_version, excess_sharpe_min_used, created_at "
        f"FROM walkforward_results WHERE {where_sql} "
        f"ORDER BY created_at DESC LIMIT ?",
        tuple(params),
    )
    return {"runs": rows, "count": len(rows)}


@router.get("/api/walkforward/runs/{run_id}", dependencies=[Depends(verify_auth)])
async def get_run(run_id: str) -> dict:
    row = _read_one(
        "SELECT * FROM walkforward_results WHERE run_id = ?", (run_id,),
    )
    if not row:
        raise HTTPException(
            status_code=404, detail=f"walkforward run {run_id!r} not found",
        )
    return row


@router.get("/api/walkforward/runs/{run_id}/windows", dependencies=[Depends(verify_auth)])
async def get_run_windows(run_id: str) -> dict:
    """Per-window breakdown for a given run: counts of trades, per-window
    Sharpe / MDE / bootstrap_SE, VIX-tier coverage. Derived from the
    walkforward_trades rows aggregated per window_index."""
    run = _read_one(
        "SELECT run_id, outcome_state FROM walkforward_results "
        "WHERE run_id = ?", (run_id,),
    )
    if not run:
        raise HTTPException(
            status_code=404, detail=f"walkforward run {run_id!r} not found",
        )
    windows = _read_rows(
        "SELECT window_index, "
        "COUNT(*) AS n_trades, "
        "MAX(sharpe_observed) AS sharpe, "
        "MAX(mde_value) AS mde, "
        "MAX(bootstrap_se) AS bootstrap_se, "
        "COUNT(DISTINCT vix_tier) AS distinct_vix_tiers "
        "FROM walkforward_trades WHERE run_id = ? AND is_in_is_window = 0 "
        "GROUP BY window_index ORDER BY window_index",
        (run_id,),
    )
    return {
        "run_id": run_id,
        "outcome_state": run["outcome_state"],
        "windows": windows,
        "count": len(windows),
    }


@router.get("/api/walkforward/runs/{run_id}/trades", dependencies=[Depends(verify_auth)])
async def get_run_trades(
    run_id: str,
    window_index: int | None = None,
    limit: int = Query(500, ge=1, le=2000),
) -> dict:
    """Individual trade rows for a run. Optional filter by window_index.
    Returns costed OOS trades (is_in_is_window = 0)."""
    run = _read_one(
        "SELECT run_id FROM walkforward_results WHERE run_id = ?", (run_id,),
    )
    if not run:
        raise HTTPException(
            status_code=404, detail=f"walkforward run {run_id!r} not found",
        )
    where = ["run_id = ?", "is_in_is_window = 0"]
    params: list = [run_id]
    if window_index is not None:
        where.append("window_index = ?")
        params.append(window_index)
    params.append(limit)
    trades = _read_rows(
        "SELECT trade_id, window_index, ticker, entry_date, exit_date, "
        "pnl_pct, excess_return, exit_reason, hold_days, vix_at_entry, "
        "vix_tier, purged, embargoed, sharpe_observed, bootstrap_se, "
        "mde_value "
        f"FROM walkforward_trades WHERE {' AND '.join(where)} "
        "ORDER BY entry_date ASC LIMIT ?",
        tuple(params),
    )
    return {"trades": trades, "count": len(trades)}
