"""Reconcile Alpaca positions with shadow_trades database.

Called by: cli.commands, scheduler.watch
Calls: journal.store, shadow_trading.alpaca_adapter
Owns tables: none
Config keys: none
Tests: tests/test_reconcile.py

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


def reconcile_paper_trades(
    db_path: str = "ai_research_desk.sqlite3", dry_run: bool = False
) -> dict:
    """Reconcile Alpaca paper positions with local shadow_trades.

    Unlike reconcile_live_trades, stale paper trades are NOT auto-closed —
    they are only flagged for manual review.

    Args:
        db_path: Path to SQLite database
        dry_run: If True, report discrepancies but don't modify DB

    Returns:
        {
            "alpaca_count": int,
            "local_count": int,
            "matched": int,
            "orphaned": [{"ticker": str, "qty": float, "avg_price": float}],
            "stale": [{"ticker": str, "trade_id": str}],
            "discrepancies": [{"ticker": str, "issue": str}],
            "backfilled": [str],
            "error": str | None,
        }
    """
    try:
        from src.shadow_trading.alpaca_adapter import get_all_positions

        alpaca_positions = get_all_positions()
    except Exception as e:
        logger.warning("[RECONCILE-PAPER] Alpaca API unreachable: %s", e)
        return {
            "alpaca_count": 0,
            "local_count": 0,
            "matched": 0,
            "orphaned": [],
            "stale": [],
            "discrepancies": [],
            "backfilled": [],
            "error": str(e),
        }

    et = ZoneInfo("America/New_York")
    now = datetime.now(et)

    alpaca_tickers = {p["symbol"]: p for p in alpaca_positions}

    # Get tracked paper trades
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        tracked = conn.execute(
            "SELECT trade_id, ticker, planned_shares FROM shadow_trades "
            "WHERE source = 'paper' AND status = 'open'"
        ).fetchall()
    tracked_map = {r["ticker"]: dict(r) for r in tracked}

    orphaned = []
    stale = []
    discrepancies = []
    matched = 0
    backfilled = []

    # Alpaca has it, local doesn't → orphaned
    for ticker, pos in alpaca_tickers.items():
        if ticker not in tracked_map:
            orphaned.append({
                "ticker": ticker,
                "qty": float(pos.get("qty", 0)),
                "avg_price": float(pos.get("avg_entry_price", 0)),
            })
        else:
            # Both have it — check qty
            local_qty = float(tracked_map[ticker].get("planned_shares", 0))
            alpaca_qty = float(pos.get("qty", 0))
            if abs(local_qty - alpaca_qty) > 0.001:
                discrepancies.append({
                    "ticker": ticker,
                    "issue": f"qty mismatch: local={local_qty}, alpaca={alpaca_qty}",
                })
            else:
                matched += 1

    # Local has it, Alpaca doesn't → stale (do NOT auto-close)
    for ticker, rec in tracked_map.items():
        if ticker not in alpaca_tickers:
            stale.append({
                "ticker": ticker,
                "trade_id": rec["trade_id"],
            })

    if not dry_run:
        from src.journal.store import insert_shadow_trade

        for orph in orphaned:
            trade_data = {
                "trade_id": str(uuid4()),
                "ticker": orph["ticker"],
                "direction": "long",
                "status": "open",
                "source": "paper",
                "entry_price": orph["avg_price"],
                "actual_entry_price": orph["avg_price"],
                "planned_shares": orph["qty"],
                "planned_allocation": orph["qty"] * orph["avg_price"],
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
            backfilled.append(orph["ticker"])
            logger.info(
                "[RECONCILE-PAPER] Backfilled orphaned position: %s (%.4f shares @ $%.2f)",
                orph["ticker"],
                orph["qty"],
                orph["avg_price"],
            )

    if stale:
        logger.warning(
            "[RECONCILE-PAPER] %d stale paper trades (not auto-closed): %s",
            len(stale),
            [s["ticker"] for s in stale],
        )

    return {
        "alpaca_count": len(alpaca_positions),
        "local_count": len(tracked),
        "matched": matched,
        "orphaned": orphaned,
        "stale": stale,
        "discrepancies": discrepancies,
        "backfilled": backfilled,
        "error": None,
    }
