"""Local API routes for revenue projection analytics.

Called by: api.app
Calls: src.utils.db.connect_db, src.analytics.canonical_sharpe.raw_sharpe
Owns tables: none (reads shadow_trades)
Config keys: none
Tests: tests/api/test_route_parity.py, tests/api/test_projections.py

Endpoints:
    GET /projections/live  - Live projection metrics (Sharpe, win rate, drawdown)
"""

import logging
import sqlite3
import statistics
from contextlib import closing

from fastapi import APIRouter

from src.analytics.canonical_sharpe import raw_sharpe
from src.config import DB_PATH
from src.utils.db import connect_db

router = APIRouter(tags=["projections"])
logger = logging.getLogger(__name__)


@router.get("/projections/live")
def projections_live():
    try:
        # PR #690 B4: closing() guarantees conn.close() — sqlite3 __exit__ only
        # commits/rolls back, it does not release the file handle.
        with closing(connect_db(DB_PATH)) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT pnl_dollars, pnl_pct FROM shadow_trades "
                "WHERE status = 'closed' AND pnl_pct IS NOT NULL "
                "AND COALESCE(quarantined, 0) = 0 "
                "ORDER BY actual_exit_time ASC"
            ).fetchall()

        if not rows:
            return {"trades": 0}

        pnl_pcts = [float(r["pnl_pct"] or 0) for r in rows]
        pnl_dollars = [float(r["pnl_dollars"] or 0) for r in rows]
        wins = [pnl for pnl in pnl_dollars if pnl > 0]
        losses = [pnl for pnl in pnl_dollars if pnl <= 0]
        avg_return = statistics.mean(pnl_pcts) if pnl_pcts else 0
        # PR #690 B5: replace non-canonical (mean/std with no annualization) with
        # canonical_sharpe.raw_sharpe — single source of truth per F-2/Track-1.5.
        # raw_sharpe returns None when undefined (n<2 or zero variance); we coerce
        # to 0.0 to preserve the response contract (numeric `sharpe` field).
        # TODO(I1): when src.data_ingestion.risk_free_rate is wired across all 6
        # rf-deferred sites (kpis.py, stage1_baseline_recompute.py, cpcv.py,
        # promotion_gate.py, mc_permutation.py, block_bootstrap.py) swap to
        # rf_adjusted_excess_sharpe with a per-trade rf vector.
        sharpe = raw_sharpe(pnl_pcts) or 0.0

        cumulative = 100000
        peak = cumulative
        max_dd = 0
        for pnl in pnl_dollars:
            cumulative += pnl
            peak = max(peak, cumulative)
            dd = (peak - cumulative) / peak * 100 if peak > 0 else 0
            max_dd = max(max_dd, dd)

        pf = abs(sum(wins) / sum(losses)) if losses and sum(losses) != 0 else 0
        return {
            "trades": len(rows),
            "winRate": round(len(wins) / len(rows), 3),
            "sharpe": round(sharpe, 3),
            "profitFactor": round(pf, 2),
            "maxDD": round(max_dd, 1),
            "netPnl": round(sum(pnl_dollars), 2),
            "avgReturn": round(avg_return, 3),
        }
    except Exception as exc:
        logger.error("[API] projections/live failed: %s", exc)
        return {"trades": 0, "error": str(exc)}
