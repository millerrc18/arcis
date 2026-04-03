"""Live ledger API routes (local mode).

Called by: api.app
Calls: none
Owns tables: none (reads shadow_trades WHERE source='live')
Config keys: none
Tests: tests/test_local_routes.py
"""

import logging
import sqlite3

from fastapi import APIRouter

from src.config import DB_PATH

router = APIRouter(tags=["live"])
logger = logging.getLogger(__name__)


@router.get("/live/trades")
def live_trades():
    """Return live (Alpaca) trades, split by open/closed."""
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        try:
            open_trades = [dict(r) for r in conn.execute(
                "SELECT * FROM shadow_trades "
                "WHERE source = 'live' AND status = 'open' "
                "ORDER BY created_at DESC"
            ).fetchall()]
            closed_trades = [dict(r) for r in conn.execute(
                "SELECT * FROM shadow_trades "
                "WHERE source = 'live' AND status = 'closed' "
                "ORDER BY actual_exit_time DESC"
            ).fetchall()]
            return {"open": open_trades, "closed": closed_trades}
        finally:
            conn.close()
    except Exception as exc:
        logger.error("Live trades error: %s", exc)
        return {"open": [], "closed": [], "error": str(exc)}


@router.get("/live/summary")
def live_summary():
    """Return live account summary."""
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        try:
            closed = conn.execute(
                "SELECT pnl_dollars, pnl_pct FROM shadow_trades "
                "WHERE source = 'live' AND status = 'closed'"
            ).fetchall()
            open_count = conn.execute(
                "SELECT COUNT(*) as c FROM shadow_trades "
                "WHERE source = 'live' AND status = 'open'"
            ).fetchone()

            closed_pnl = sum(
                (dict(t).get("pnl_dollars", 0) or 0) for t in closed
            )
            wins = [t for t in closed if (dict(t).get("pnl_dollars", 0) or 0) > 0]
            starting = 100
            return {
                "starting_capital": starting,
                "current_equity": round(starting + closed_pnl, 2),
                "total_pnl": round(closed_pnl, 2),
                "total_pnl_pct": round((closed_pnl / starting) * 100, 2) if starting else 0,
                "open_positions": open_count["c"] if open_count else 0,
                "closed_trades": len(closed),
                "win_rate": round(len(wins) / len(closed), 3) if closed else None,
            }
        finally:
            conn.close()
    except Exception as exc:
        logger.error("Live summary error: %s", exc)
        return {"starting_capital": 100, "current_equity": 100, "error": str(exc)}
