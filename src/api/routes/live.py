"""Live ledger API routes (local mode).

Called by: api.app
Calls: none
Owns tables: none (reads shadow_trades WHERE source='live')
Config keys: none
Tests: tests/test_local_routes.py

Endpoints:
    GET /live/trades  - Open + closed live (Alpaca) trades
    GET /live/summary - Account summary (equity, P&L, win rate)

Live trades are a subset of shadow_trades with source='live'. They represent
actual Alpaca broker orders, as opposed to source='paper' which are simulated.
The same shadow_trades table holds both to enable unified reporting while the
source filter separates real money from paper.
"""

import logging
import sqlite3

from fastapi import APIRouter

from src.config import DB_PATH
from src.shadow_trading.exit_reason import outcome_stats_filter_sql
from src.utils.db import connect_db

router = APIRouter(tags=["live"])
logger = logging.getLogger(__name__)


@router.get("/live/trades")
def live_trades():
    """Return live (Alpaca) trades, split by open/closed.

    Open trades are enriched with ``current_price`` + unrealized ``pnl_dollars``
    / ``pnl_pct`` derived from the most recent ``setup_signals.theoretical_entry``
    for each ticker. shadow_trades stores pnl_dollars=NULL while open, which
    previously rendered as $0.00 on the live ledger.
    """
    try:
        conn = connect_db(DB_PATH)
        conn.row_factory = sqlite3.Row
        try:
            open_trades = [dict(r) for r in conn.execute(
                "SELECT * FROM shadow_trades "
                "WHERE source = 'live' AND status = 'open' "
                "AND COALESCE(quarantined, 0) = 0 ORDER BY created_at DESC"
            ).fetchall()]
            closed_trades = [dict(r) for r in conn.execute(
                "SELECT * FROM shadow_trades "
                "WHERE source = 'live' AND status = 'closed' "
                "AND COALESCE(quarantined, 0) = 0 ORDER BY actual_exit_time DESC"
            ).fetchall()]
            for trade in open_trades:
                ticker = trade.get("ticker")
                entry = trade.get("actual_entry_price") or trade.get("entry_price")
                shares = trade.get("actual_shares") or trade.get("planned_shares")
                current = None
                if ticker:
                    try:
                        price_row = conn.execute(
                            "SELECT theoretical_entry FROM setup_signals "
                            "WHERE ticker = ? ORDER BY created_at DESC LIMIT 1",
                            (ticker,),
                        ).fetchone()
                        if price_row and price_row["theoretical_entry"] is not None:
                            current = float(price_row["theoretical_entry"])
                    except (sqlite3.OperationalError, TypeError, ValueError):
                        # setup_signals may not exist in test fixtures, or
                        # the value may not be numeric. Leave current_price
                        # as None rather than aborting the whole endpoint.
                        current = None
                trade["current_price"] = current
                if current is not None and entry is not None:
                    try:
                        entry_f = float(entry)
                        shares_f = float(shares or 0)
                        trade["pnl_dollars"] = round((current - entry_f) * shares_f, 2)
                        trade["pnl_pct"] = round((current - entry_f) / entry_f * 100, 2) if entry_f else None
                    except (TypeError, ValueError, ZeroDivisionError):
                        pass
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
        conn = connect_db(DB_PATH)
        conn.row_factory = sqlite3.Row
        try:
            closed = conn.execute(
                "SELECT pnl_dollars, pnl_pct FROM shadow_trades "
                "WHERE source = 'live' AND status = 'closed' AND COALESCE(quarantined, 0) = 0"
                f" {outcome_stats_filter_sql()}"
            ).fetchall()
            open_count = conn.execute(
                "SELECT COUNT(*) as c FROM shadow_trades "
                "WHERE source = 'live' AND status = 'open' AND COALESCE(quarantined, 0) = 0"
            ).fetchone()

            closed_pnl = sum(
                float(dict(t).get("pnl_dollars", 0) or 0) for t in closed
            )
            wins = [t for t in closed if float(dict(t).get("pnl_dollars", 0) or 0) > 0]
            starting = 100_000
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
        return {"starting_capital": 100_000, "current_equity": 100_000, "error": str(exc)}
