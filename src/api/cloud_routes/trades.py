"""Cloud trade and market routes for packets, journals, and ledgers.

Called by: api.cloud_app
Calls: none
Owns tables: none
Config keys: none
Tests: none

Endpoints:
    GET /api/shadow/open            - Open trades with unrealized P&L (#253)
    GET /api/shadow/closed?days=30  - Closed trades with metrics
    GET /api/shadow/metrics?days=30 - Performance metrics
    GET /api/shadow/account         - Virtual account summary
    GET /api/packets?days=7         - Recent recommendations
    GET /api/live/trades            - Live (Alpaca) trades
    GET /api/live/summary           - Live account summary
    GET /api/scan/latest            - Latest 10 recommendations
    GET /api/review/pending         - Recently closed trades for review
    GET /api/review/scorecard       - Stub (cloud has no local review data)
    GET /api/review/postmortems     - Stub
    GET /api/journal?days=90        - Trade journal with thesis text
    GET /api/signal-zoo?days=7      - Setup signal history
    GET /api/projections/live       - Live projection metrics (Sharpe, win rate)

Unrealized P&L (#253): The cloud API estimates current prices from
setup_signals.theoretical_entry since it has no live market data feed.
This is an approximation — the local API uses actual Alpaca prices.
"""

import statistics
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException


def create_router(runtime, verify_auth):
    """Build the cloud trades router."""
    router = APIRouter()

    @router.get("/api/shadow/open", dependencies=[Depends(verify_auth)])
    def shadow_open():
        """Return open shadow trades with per-trade unrealized P&L.

        Fix for #253: total_unrealized_pnl was hardcoded to 0. Now computes P&L
        for each open trade using the latest signal price for that ticker.
        We query setup_signals (most recent theoretical_entry per ticker) as a
        proxy for current price — no live API call needed.
        """
        try:
            rows = runtime.query(
                "SELECT st.*, r.setup_type, r.market_regime, r.priority_score "
                "FROM shadow_trades st "
                "LEFT JOIN recommendations r ON st.recommendation_id = r.recommendation_id "
                "WHERE st.status = 'open' AND COALESCE(st.quarantined, 0) = 0"
                " ORDER BY st.created_at DESC"
            )
            closed_pnl_row = runtime.query_one(
                "SELECT COALESCE(SUM(pnl_dollars), 0) as total FROM shadow_trades WHERE status = 'closed'"
                " AND COALESCE(quarantined, 0) = 0"
            )
            closed_pnl = closed_pnl_row["total"] if closed_pnl_row else 0
            equity = 100000 + (closed_pnl or 0)

            # Fix for #253: compute unrealized P&L per open trade.
            # Use latest setup_signals.theoretical_entry as price proxy.
            total_unrealized = 0.0
            for trade in rows:
                ticker = trade.get("ticker")
                entry = float(trade.get("actual_entry_price") or trade.get("entry_price") or 0)
                shares = float(trade.get("actual_shares") or trade.get("planned_shares") or 0)
                if not ticker or not entry or not shares:
                    trade["unrealized_pnl"] = None
                    trade["current_price_est"] = None
                    continue
                # Get most recent signal price for this ticker
                price_row = runtime.query_one(
                    "SELECT theoretical_entry FROM setup_signals "
                    "WHERE ticker = %s ORDER BY created_at DESC LIMIT 1",
                    (ticker,),
                )
                if price_row and price_row.get("theoretical_entry"):
                    current = float(price_row["theoretical_entry"])
                    pnl = round((current - entry) * shares, 2)
                    trade["unrealized_pnl"] = pnl
                    trade["current_price_est"] = round(current, 2)
                    total_unrealized += pnl
                else:
                    trade["unrealized_pnl"] = None
                    trade["current_price_est"] = None

            return {
                "trades": rows,
                "open_trades": rows,
                "count": len(rows),
                "open_count": len(rows),
                "account_equity": round(equity, 2),
                "total_unrealized_pnl": round(total_unrealized, 2),
            }
        except HTTPException:
            raise
        except Exception as exc:
            runtime.logger.error("Shadow open error: %s", exc)
            return {
                "trades": [],
                "open_trades": [],
                "count": 0,
                "open_count": 0,
                "account_equity": 100000,
                "total_unrealized_pnl": 0,
                "error": str(exc),
            }

    @router.get("/api/shadow/closed", dependencies=[Depends(verify_auth)])
    def shadow_closed(days: int = 30):
        try:
            cutoff = (datetime.now(runtime.et) - timedelta(days=days)).isoformat()
            rows = runtime.query(
                "SELECT st.*, r.setup_type, r.market_regime, r.priority_score "
                "FROM shadow_trades st "
                "LEFT JOIN recommendations r ON st.recommendation_id = r.recommendation_id "
                "WHERE st.status = 'closed' "
                "AND st.actual_exit_time >= %s AND COALESCE(st.quarantined, 0) = 0"
                " ORDER BY st.actual_exit_time DESC",
                (cutoff,),
            )
            pnls = [row.get("pnl_dollars", 0) or 0 for row in rows]
            wins = [pnl for pnl in pnls if pnl > 0]
            losses = [pnl for pnl in pnls if pnl <= 0]
            total_pnl = sum(pnls)
            metrics = {
                "total_trades": len(rows),
                "win_rate": round(len(wins) / len(rows), 3) if rows else 0,
                "avg_gain": round(sum(wins) / len(wins), 2) if wins else 0,
                "avg_loss": round(sum(losses) / len(losses), 2) if losses else 0,
                "expectancy": round(total_pnl / len(rows), 2) if rows else 0,
                "total_pnl": round(total_pnl, 2),
            }
            return {"trades": rows, "count": len(rows), "days": days, "metrics": metrics}
        except HTTPException:
            raise
        except Exception as exc:
            runtime.logger.error("Shadow closed error: %s", exc)
            return {"trades": [], "count": 0, "metrics": {}, "error": str(exc)}

    @router.get("/api/shadow/metrics", dependencies=[Depends(verify_auth)])
    def shadow_metrics(days: int = 30):
        try:
            cutoff = (datetime.now(runtime.et) - timedelta(days=days)).isoformat()
            rows = runtime.query(
                "SELECT pnl_dollars, pnl_pct FROM shadow_trades "
                "WHERE status = 'closed' AND actual_exit_time >= %s"
                " AND COALESCE(quarantined, 0) = 0",
                (cutoff,),
            )
            if not rows:
                return {"total_trades": 0}

            pnls = [row["pnl_dollars"] or 0 for row in rows]
            wins = [pnl for pnl in pnls if pnl > 0]
            losses = [pnl for pnl in pnls if pnl <= 0]
            total_pnl = sum(pnls)
            return {
                "total_trades": len(rows),
                "wins": len(wins),
                "losses": len(losses),
                "win_rate": round(len(wins) / len(rows), 3) if rows else 0,
                "total_pnl": round(total_pnl, 2),
                "avg_win": round(sum(wins) / len(wins), 2) if wins else 0,
                "avg_loss": round(sum(losses) / len(losses), 2) if losses else 0,
                "expectancy": round(total_pnl / len(rows), 2) if rows else 0,
                "days": days,
            }
        except HTTPException:
            raise
        except Exception as exc:
            runtime.logger.error("Shadow metrics error: %s", exc)
            return {"total_trades": 0, "error": str(exc)}

    @router.get("/api/packets", dependencies=[Depends(verify_auth)])
    def packets(days: int = 7):
        try:
            cutoff = (datetime.now(runtime.et) - timedelta(days=days)).isoformat()
            return runtime.query(
                "SELECT * FROM recommendations WHERE created_at >= %s "
                "AND COALESCE(priority_score, 0) > 0 "
                "ORDER BY created_at DESC",
                (cutoff,),
            )
        except HTTPException:
            raise
        except Exception as exc:
            runtime.logger.error("Packets error: %s", exc)
            return []

    @router.get("/api/live/trades", dependencies=[Depends(verify_auth)])
    def live_trades():
        try:
            open_trades = runtime.query(
                "SELECT * FROM shadow_trades WHERE source = 'live' AND status = 'open'"
                " AND COALESCE(quarantined, 0) = 0 ORDER BY created_at DESC"
            )
            closed_trades = runtime.query(
                "SELECT * FROM shadow_trades WHERE source = 'live' AND status = 'closed'"
                " AND COALESCE(quarantined, 0) = 0 ORDER BY actual_exit_time DESC"
            )
            # Open trades: enrich with current_price + unrealized pnl using the
            # most recent setup_signals.theoretical_entry for each ticker. The
            # live ledger has nothing to show otherwise — pnl_dollars is NULL
            # while the position is open, which previously rendered as $0.00.
            for trade in open_trades:
                ticker = trade.get("ticker")
                entry = trade.get("actual_entry_price") or trade.get("entry_price")
                shares = trade.get("actual_shares") or trade.get("planned_shares")
                current = None
                if ticker:
                    try:
                        price_row = runtime.query_one(
                            "SELECT theoretical_entry FROM setup_signals "
                            "WHERE ticker = %s ORDER BY created_at DESC LIMIT 1",
                            (ticker,),
                        )
                        if price_row and price_row.get("theoretical_entry"):
                            current = float(price_row["theoretical_entry"])
                    except Exception:
                        # Missing setup_signals row or non-numeric value —
                        # leave current_price as None rather than aborting.
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
        except Exception as exc:
            runtime.logger.error("Live trades error: %s", exc)
            return {"open": [], "closed": [], "error": str(exc)}

    @router.get("/api/live/summary", dependencies=[Depends(verify_auth)])
    def live_summary():
        try:
            closed = runtime.query(
                "SELECT pnl_dollars, pnl_pct FROM shadow_trades WHERE source = 'live' AND status = 'closed'"
                " AND COALESCE(quarantined, 0) = 0"
            )
            open_count = runtime.query_one(
                "SELECT COUNT(*) as c FROM shadow_trades WHERE source = 'live' AND status = 'open'"
                " AND COALESCE(quarantined, 0) = 0"
            )
            closed_pnl = sum(trade.get("pnl_dollars", 0) or 0 for trade in closed)
            wins = [trade for trade in closed if float(trade.get("pnl_dollars", 0) or 0) > 0]
            return {
                "starting_capital": 100,
                "current_equity": round(100 + closed_pnl, 2),
                "total_pnl": round(closed_pnl, 2),
                "total_pnl_pct": round((closed_pnl / 100) * 100, 2),
                "open_positions": open_count["c"] if open_count else 0,
                "closed_trades": len(closed),
                "win_rate": round(len(wins) / len(closed), 3) if closed else None,
            }
        except Exception as exc:
            runtime.logger.error("Live summary error: %s", exc)
            return {"starting_capital": 100, "current_equity": 100, "error": str(exc)}

    @router.get("/api/shadow/account", dependencies=[Depends(verify_auth)])
    def shadow_account():
        try:
            # Fix for #266: select same columns as shadow_open for consistent P&L computation
            open_trades = runtime.query(
                "SELECT ticker, actual_entry_price, entry_price, actual_shares, planned_shares, pnl_dollars FROM shadow_trades WHERE status = 'open'"
                " AND COALESCE(quarantined, 0) = 0"
            )
            closed_trades = runtime.query(
                "SELECT pnl_dollars, pnl_pct FROM shadow_trades WHERE status = 'closed'"
                " AND COALESCE(quarantined, 0) = 0"
            )
            closed_pnl = sum(trade.get("pnl_dollars", 0) or 0 for trade in closed_trades)
            # Fix for #266: use actual values with fallback, matching shadow_open
            open_alloc = sum(
                float(trade.get("actual_entry_price") or trade.get("entry_price") or 0)
                * float(trade.get("actual_shares") or trade.get("planned_shares") or 0)
                for trade in open_trades
            )
            wins = [trade for trade in closed_trades if float(trade.get("pnl_dollars", 0) or 0) > 0]
            losses = [trade for trade in closed_trades if float(trade.get("pnl_dollars", 0) or 0) <= 0]

            # Fix for #253: compute unrealized P&L for open trades
            unrealized = 0.0
            for trade in open_trades:
                ticker = trade.get("ticker")
                entry = float(trade.get("actual_entry_price") or trade.get("entry_price") or 0)
                shares = float(trade.get("actual_shares") or trade.get("planned_shares") or 0)
                if ticker and entry and shares:
                    price_row = runtime.query_one(
                        "SELECT theoretical_entry FROM setup_signals "
                        "WHERE ticker = %s ORDER BY created_at DESC LIMIT 1",
                        (ticker,),
                    )
                    if price_row and price_row.get("theoretical_entry"):
                        unrealized += (float(price_row["theoretical_entry"]) - entry) * shares

            return {
                "starting_capital": 100000,
                "equity": 100000 + closed_pnl,
                "cash": 100000 + closed_pnl - open_alloc,
                "open_positions": len(open_trades),
                "closed_pnl": round(closed_pnl, 2),
                "unrealized_pnl": round(unrealized, 2),
                "win_rate": round(len(wins) / len(closed_trades), 3) if closed_trades else None,
                "total_closed": len(closed_trades),
                "wins": len(wins),
                "losses": len(losses),
            }
        except Exception as exc:
            runtime.logger.error("[API] shadow_account failed: %s", exc, exc_info=True)
            return {"starting_capital": 100000, "equity": 100000, "error": str(exc)}

    @router.get("/api/scan/latest", dependencies=[Depends(verify_auth)])
    def scan_latest():
        try:
            latest = runtime.query(
                "SELECT * FROM recommendations ORDER BY created_at DESC LIMIT 10"
            )
            return {"recommendations": latest, "count": len(latest)}
        except Exception as exc:
            runtime.logger.error("[API] scan_latest failed: %s", exc, exc_info=True)
            return {"recommendations": [], "count": 0, "error": str(exc)}

    @router.get("/api/review/pending", dependencies=[Depends(verify_auth)])
    def review_pending():
        try:
            return runtime.query(
                "SELECT * FROM shadow_trades WHERE status = 'closed' "
                "AND (exit_reason IS NOT NULL) AND COALESCE(quarantined, 0) = 0"
                " ORDER BY actual_exit_time DESC LIMIT 20"
            )
        except Exception as exc:
            runtime.logger.error("[API] review_pending failed: %s", exc, exc_info=True)
            return []

    @router.get("/api/review/scorecard", dependencies=[Depends(verify_auth)])
    def review_scorecard(weeks: int = 4):
        # Fix for #265: return proper not-implemented response
        return {"status": "not_implemented", "message": "Available in Phase 2"}

    @router.get("/api/review/postmortems", dependencies=[Depends(verify_auth)])
    def review_postmortems():
        # Fix for #265: return proper not-implemented response
        return {"status": "not_implemented", "message": "Available in Phase 2"}

    @router.get("/api/journal", dependencies=[Depends(verify_auth)])
    def trade_journal(days: int = 90):
        try:
            cutoff = (datetime.now(runtime.et) - timedelta(days=days)).isoformat()
            rows = runtime.query(
                "SELECT st.*, r.thesis_text, r.setup_type "
                "FROM shadow_trades st LEFT JOIN recommendations r "
                "ON st.recommendation_id = r.recommendation_id "
                "WHERE st.status = 'closed' AND st.actual_exit_time >= %s "
                "AND COALESCE(st.quarantined, 0) = 0 "
                "ORDER BY st.actual_exit_time DESC",
                (cutoff,),
            )
            return {"trades": rows, "count": len(rows)}
        except Exception as exc:
            return {"trades": [], "count": 0, "error": str(exc)}

    @router.get("/api/signal-zoo", dependencies=[Depends(verify_auth)])
    def signal_zoo(days: int = 7):
        try:
            cutoff = (datetime.now(runtime.et) - timedelta(days=days)).isoformat()
            rows = runtime.query(
                "SELECT * FROM setup_signals WHERE created_at >= %s ORDER BY created_at DESC",
                (cutoff,),
            )
            for row in rows:
                runtime.parse_json_fields(row, ["features_json"])
            return {"signals": rows, "count": len(rows)}
        except Exception as exc:
            runtime.logger.error("[API] signal_zoo failed: %s", exc, exc_info=True)
            return {"signals": [], "count": 0, "error": str(exc)}

    @router.get("/api/projections/live", dependencies=[Depends(verify_auth)])
    def projections_live():
        try:
            closed = runtime.query(
                "SELECT pnl_dollars, pnl_pct FROM shadow_trades "
                "WHERE status = 'closed' AND pnl_pct IS NOT NULL "
                "AND COALESCE(quarantined, 0) = 0 "
                "ORDER BY actual_exit_time ASC"
            )
            if not closed:
                return {"trades": 0}

            pnl_pcts = [float(row.get("pnl_pct", 0) or 0) for row in closed]
            pnl_dollars = [float(row.get("pnl_dollars", 0) or 0) for row in closed]
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
                "trades": len(closed),
                "winRate": round(len(wins) / len(closed), 3),
                "sharpe": round(sharpe, 3),
                "profitFactor": round(pf, 2),
                "maxDD": round(max_dd, 1),
                "netPnl": round(sum(pnl_dollars), 2),
                "avgReturn": round(avg_return, 3),
            }
        except Exception as exc:
            return {"trades": 0, "error": str(exc)}

    return router
