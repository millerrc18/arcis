"""Reconcile Alpaca live positions with shadow_trades database.

Detects orphaned positions (on Alpaca but not in DB) and stale records
(in DB but not on Alpaca). Backfills missing records and marks stale ones.
"""

import logging
import sqlite3
from datetime import datetime
from uuid import uuid4
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)


def reconcile_live_trades(
    db_path: str = "ai_research_desk.sqlite3", dry_run: bool = False
) -> dict:
    """Reconcile Alpaca live positions with local shadow_trades.

    Args:
        db_path: Path to SQLite database
        dry_run: If True, report discrepancies but don't modify DB

    Returns:
        {
            "alpaca_positions": int,
            "tracked_positions": int,
            "orphaned": [str],
            "stale": [str],
            "backfilled": [str],
            "marked_closed": [str],
        }
    """
    from src.shadow_trading.alpaca_adapter import get_live_positions

    et = ZoneInfo("America/New_York")
    now = datetime.now(et)

    # Get Alpaca positions
    alpaca_positions = get_live_positions()
    alpaca_tickers = {p["symbol"]: p for p in alpaca_positions}

    # Get tracked live trades
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        tracked = conn.execute(
            "SELECT trade_id, ticker FROM shadow_trades "
            "WHERE source = 'live' AND status = 'open'"
        ).fetchall()
    tracked_tickers = {r["ticker"]: r["trade_id"] for r in tracked}

    # Find discrepancies
    orphaned = [t for t in alpaca_tickers if t not in tracked_tickers]
    stale = [t for t in tracked_tickers if t not in alpaca_tickers]

    backfilled = []
    marked_closed = []

    if not dry_run:
        from src.journal.store import insert_shadow_trade

        # Backfill orphaned positions
        for ticker in orphaned:
            pos = alpaca_tickers[ticker]
            trade_data = {
                "trade_id": str(uuid4()),
                "ticker": ticker,
                "direction": "long",
                "status": "open",
                "source": "live",
                "entry_price": float(pos.get("avg_entry_price", 0)),
                "actual_entry_price": float(pos.get("avg_entry_price", 0)),
                "planned_shares": float(pos.get("qty", 0)),
                "planned_allocation": float(pos.get("market_value", 0)),
                "actual_entry_time": now.isoformat(),
                "created_at": now.isoformat(),
                "updated_at": now.isoformat(),
                "order_type": "reconciled",
                "recommendation_id": None,
                "stop_price": 0,
                "target_1": 0,
                "target_2": 0,
                "max_favorable_excursion": 0,
                "max_adverse_excursion": 0,
            }
            insert_shadow_trade(trade_data, db_path)
            backfilled.append(ticker)
            logger.info(
                "[RECONCILE] Backfilled orphaned position: %s (%.4f shares @ $%.2f)",
                ticker,
                float(pos.get("qty", 0)),
                float(pos.get("avg_entry_price", 0)),
            )

        # Mark stale records as closed
        for ticker in stale:
            trade_id = tracked_tickers[ticker]
            with sqlite3.connect(db_path) as conn:
                conn.execute(
                    "UPDATE shadow_trades SET status = 'closed', "
                    "exit_reason = 'reconciled_stale', updated_at = ? "
                    "WHERE trade_id = ?",
                    (now.isoformat(), trade_id),
                )
            marked_closed.append(ticker)
            logger.info(
                "[RECONCILE] Marked stale record as closed: %s (trade_id=%s)",
                ticker,
                trade_id,
            )

    return {
        "alpaca_positions": len(alpaca_positions),
        "tracked_positions": len(tracked),
        "orphaned": orphaned,
        "stale": stale,
        "backfilled": backfilled,
        "marked_closed": marked_closed,
    }
