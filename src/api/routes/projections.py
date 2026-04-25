"""Local API routes for revenue projection analytics.

Called by: api.app
Calls: src.utils.db.connect_db
Owns tables: none (reads shadow_trades)
Config keys: none
Tests: tests/api/test_route_parity.py

Endpoints:
    GET /projections/live  - Live projection metrics (Sharpe, win rate, drawdown)
"""

import logging
import sqlite3
import statistics

from fastapi import APIRouter

from src.config import DB_PATH
from src.utils.db import connect_db

router = APIRouter(tags=["projections"])
logger = logging.getLogger(__name__)


@router.get("/projections/live")
def projections_live():
    try:
        with connect_db(DB_PATH) as conn:
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
        std_return = statistics.stdev(pnl_pcts) if len(pnl_pcts) > 1 else 1
        sharpe = avg_return / std_return if std_return > 0 else 0

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
