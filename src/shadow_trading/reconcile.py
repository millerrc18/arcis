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

from src.config import DB_PATH
from src.utils.db import connect_db

logger = logging.getLogger(__name__)


def reconcile_live_trades(
    db_path: str = DB_PATH, dry_run: bool = False
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
    with connect_db(db_path) as conn:
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
        from src.journal.store import insert_shadow_trade, close_shadow_trade

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
            # #107: Explicit warning — backfilled positions have no protection
            logger.warning(
                "[RECONCILE] Backfilled %s with stop_price=0, target_1=0 — "
                "MANUAL INTERVENTION NEEDED: set stop-loss and targets",
                ticker,
            )

        # Mark stale records as closed — attempt P&L via yfinance (#108)
        for ticker in stale:
            trade_id = tracked_tickers[ticker]
            pnl_dollars = 0.0
            pnl_pct = 0.0
            exit_price = 0.0

            # Try to fetch last known price for P&L calculation
            try:
                with connect_db(db_path) as conn:
                    entry_row = conn.execute(
                        "SELECT actual_entry_price, entry_price, planned_shares "
                        "FROM shadow_trades WHERE trade_id = ?",
                        (trade_id,),
                    ).fetchone()
                if entry_row:
                    entry_px = float(entry_row["actual_entry_price"] or entry_row["entry_price"] or 0)
                    shares = float(entry_row["planned_shares"] or 1)
                    if entry_px > 0:
                        try:
                            from src.data_ingestion.market_data import fetch_ohlcv
                            data = fetch_ohlcv([ticker], period="5d")
                            if ticker in data and not data[ticker].empty:
                                exit_price = float(data[ticker]["Close"].iloc[-1])
                                pnl_dollars = round((exit_price - entry_px) * shares, 2)
                                pnl_pct = round((exit_price - entry_px) / entry_px * 100, 2)
                        except Exception as _yf_err:
                            logger.debug("[RECONCILE] yfinance lookup failed for stale %s: %s", ticker, _yf_err)
            except Exception as _db_err:
                logger.debug("[RECONCILE] Entry price lookup failed for stale %s: %s", ticker, _db_err)

            close_shadow_trade(
                trade_id=trade_id,
                exit_price=exit_price,
                exit_time=now.isoformat(),
                exit_reason="reconciled_stale",
                pnl_dollars=pnl_dollars,
                pnl_pct=pnl_pct,
                db_path=db_path,
            )
            marked_closed.append(ticker)
            logger.info(
                "[RECONCILE] Marked stale record as closed: %s (trade_id=%s, pnl=%s)",
                ticker, trade_id,
                f"${pnl_dollars:.2f}" if pnl_dollars != 0.0 else "UNKNOWN",
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
    db_path: str = DB_PATH, dry_run: bool = False
) -> dict:
    """Reconcile Alpaca paper positions with local shadow_trades.

    Stale paper trades (in DB but not on Alpaca) are auto-closed with
    exit_reason='reconciled_stale' after a 1-hour safety guard to avoid
    false closures from transient Alpaca API blips.

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
            "marked_closed": [str],
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
    marked_closed = []

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

    # Local has it, Alpaca doesn't → stale
    for ticker, rec in tracked_map.items():
        if ticker not in alpaca_tickers:
            stale.append({
                "ticker": ticker,
                "trade_id": rec["trade_id"],
            })

    if not dry_run:
        from src.journal.store import insert_shadow_trade, close_shadow_trade

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

        # Auto-close stale paper trades with 1-hour safety guard
        for stale_entry in stale:
            ticker = stale_entry["ticker"]
            trade_id = stale_entry["trade_id"]

            # Safety: skip trades less than 1 hour old to avoid false closures
            # from transient Alpaca API blips
            with connect_db(db_path) as conn:
                trade_row = conn.execute(
                    "SELECT actual_entry_price, entry_price, planned_shares, created_at "
                    "FROM shadow_trades WHERE trade_id = ?",
                    (trade_id,),
                ).fetchone()

            if trade_row:
                created_at_str = trade_row["created_at"] or ""
                try:
                    created = datetime.fromisoformat(created_at_str)
                    if (now - created).total_seconds() < 3600:
                        logger.info(
                            "[RECONCILE-PAPER] Skipping recent trade %s (< 1 hour old)",
                            ticker,
                        )
                        continue
                except (ValueError, TypeError):
                    pass

            pnl_dollars = 0.0
            pnl_pct = 0.0
            exit_price = 0.0

            # Try to fetch last known price for P&L calculation
            if trade_row:
                entry_px = float(trade_row["actual_entry_price"] or trade_row["entry_price"] or 0)
                shares = float(trade_row["planned_shares"] or 1)
                if entry_px > 0:
                    try:
                        from src.data_ingestion.market_data import fetch_ohlcv
                        data = fetch_ohlcv([ticker], period="5d")
                        if ticker in data and not data[ticker].empty:
                            exit_price = float(data[ticker]["Close"].iloc[-1])
                            pnl_dollars = round((exit_price - entry_px) * shares, 2)
                            pnl_pct = round((exit_price - entry_px) / entry_px * 100, 2)
                    except Exception as _yf_err:
                        logger.debug(
                            "[RECONCILE-PAPER] yfinance lookup failed for stale %s: %s",
                            ticker, _yf_err,
                        )

            close_shadow_trade(
                trade_id=trade_id,
                exit_price=exit_price,
                exit_time=now.isoformat(),
                exit_reason="reconciled_stale",
                pnl_dollars=pnl_dollars,
                pnl_pct=pnl_pct,
                db_path=db_path,
            )
            marked_closed.append(ticker)
            logger.info(
                "[RECONCILE-PAPER] Auto-closed stale paper trade: %s (trade_id=%s, pnl=%s)",
                ticker, trade_id,
                f"${pnl_dollars:.2f}" if pnl_dollars != 0.0 else "UNKNOWN",
            )

    if stale and not marked_closed:
        logger.warning(
            "[RECONCILE-PAPER] %d stale paper trades detected (skipped — too recent): %s",
            len(stale),
            [s["ticker"] for s in stale],
        )

    # ── Resolve stuck exit_failed / exit_pending trades ──────────────
    # These trades detected an exit condition but failed to submit the
    # exit order.  If the position is gone from Alpaca, the bracket
    # filled — close with estimated P&L.  If still on Alpaca, revert to
    # open so the normal exit logic can retry.
    resolved_closed = []
    resolved_reopened = []
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        stuck = conn.execute(
            "SELECT trade_id, ticker, exit_reason, actual_entry_price, "
            "       entry_price, planned_shares, stop_price, target_1, target_2 "
            "FROM shadow_trades "
            "WHERE source = 'paper' AND status IN ('exit_failed', 'exit_pending')"
        ).fetchall()

    if stuck and not dry_run:
        for row in stuck:
            ticker = row["ticker"]
            trade_id = row["trade_id"]
            if ticker in alpaca_tickers:
                # Position still live — exit detection was premature, revert
                with sqlite3.connect(db_path) as conn:
                    conn.execute(
                        "UPDATE shadow_trades SET status = 'open', exit_reason = NULL "
                        "WHERE trade_id = ?",
                        (trade_id,),
                    )
                resolved_reopened.append(ticker)
                logger.info(
                    "[RECONCILE-PAPER] Reverted premature exit to open: %s", ticker,
                )
            else:
                # Position gone — bracket filled, close with estimated P&L
                entry_px = float(row["actual_entry_price"] or row["entry_price"] or 0)
                shares = float(row["planned_shares"] or 1)
                reason = row["exit_reason"] or "reconciled_stale"

                if reason in ("stop_hit", "stop_loss"):
                    exit_px = float(row["stop_price"] or 0)
                elif reason in ("target_1_hit", "take_profit"):
                    exit_px = float(row["target_1"] or 0)
                elif reason == "target_2_hit":
                    exit_px = float(row["target_2"] or 0)
                else:
                    exit_px = entry_px  # fallback — P&L unknown

                pnl_dollars = round((exit_px - entry_px) * shares, 2) if entry_px > 0 else 0.0
                pnl_pct = round((exit_px - entry_px) / entry_px * 100, 2) if entry_px > 0 else 0.0

                close_shadow_trade(
                    trade_id=trade_id,
                    exit_price=exit_px,
                    exit_time=now.isoformat(),
                    exit_reason=reason,
                    pnl_dollars=pnl_dollars,
                    pnl_pct=pnl_pct,
                    db_path=db_path,
                )
                resolved_closed.append(ticker)
                logger.info(
                    "[RECONCILE-PAPER] Closed stuck %s trade: %s (pnl=$%.2f)",
                    reason, ticker, pnl_dollars,
                )
    elif stuck:
        logger.info(
            "[RECONCILE-PAPER] %d stuck exit_failed/exit_pending trades found (dry_run): %s",
            len(stuck), [dict(r)["ticker"] for r in stuck],
        )

    return {
        "alpaca_count": len(alpaca_positions),
        "local_count": len(tracked),
        "matched": matched,
        "orphaned": orphaned,
        "stale": stale,
        "discrepancies": discrepancies,
        "backfilled": backfilled,
        "marked_closed": marked_closed,
        "resolved_closed": resolved_closed,
        "resolved_reopened": resolved_reopened,
        "error": None,
    }
