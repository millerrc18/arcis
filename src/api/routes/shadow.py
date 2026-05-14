"""Shadow trading API routes.

Called by: api.app
Calls: config, journal.store, services.shadow_service, shadow_trading.executor
Owns tables: none
Config keys: none
Tests: none

Endpoints:
    GET  /shadow/open                - Open shadow (paper + live) trades
    GET  /shadow/closed?days=30      - Closed trades with metrics
    GET  /shadow/account             - Virtual account summary
    GET  /shadow/metrics?days=30     - Trade performance metrics
    GET  /shadow/desks               - Distinct desk values for the dropdown
    GET  /shadow/sharpe-attribution  - Alpha vs SPY beta (raw + excess Sharpe)
    POST /shadow/close/{ticker}      - Manually close a position

"Shadow" trading means paper trading that shadows what real trading would do.
The close endpoint handles both paper (instant close) and live (Alpaca broker
exit order) trades. For live trades, it submits the exit order and either
records the fill or marks the trade as exit_pending if not immediately filled.
"""
import logging
import sqlite3

from fastapi import APIRouter, Depends, Query

from src.api.cloud_routes.trades import _build_attribution_payload
from src.api.local_auth import verify_local_token
from src.config import DB_PATH, load_config
from src.services.shadow_service import get_shadow_status, get_shadow_history, get_shadow_account
from src.shadow_trading.exit_reason import coerce_exit_reason
from src.utils.db import connect_db

router = APIRouter(tags=["shadow"])
logger = logging.getLogger(__name__)


@router.get("/shadow/open")
def open_trades():
    config = load_config()
    return get_shadow_status(config)


def _normalize_win_rate_to_decimal(metrics: dict) -> dict:
    """Convert win_rate from percent (50.0) to decimal (0.5) at API boundary.

    compute_shadow_metrics() returns win_rate as percent because scorecard
    text templates render `{win_rate:.0f}%` directly. The frontend, on the
    other hand, universally multiplies by 100 when displaying (matching the
    cloud_routes convention where win_rate is a decimal fraction). Without
    this conversion, /shadow renders `WIN RATE 5000.0%`. The percent form
    stays the internal canonical for scorecard/tests; the decimal form is
    the API canonical for any frontend consumer.
    """
    if metrics and "win_rate" in metrics:
        wr = metrics["win_rate"]
        if wr is not None and wr > 1:
            metrics["win_rate"] = round(wr / 100, 3)
    return metrics


@router.get("/shadow/closed")
def closed_trades(days: int = 30):
    result = get_shadow_history(days=days)
    if "metrics" in result:
        result["metrics"] = _normalize_win_rate_to_decimal(result["metrics"])
    return result


@router.get("/shadow/account")
def account():
    try:
        return get_shadow_account()
    except Exception as e:
        return {"error": str(e)}


@router.get("/shadow/metrics")
def metrics(days: int = 30):
    result = get_shadow_history(days=days)
    return _normalize_win_rate_to_decimal(result.get("metrics", {}))


@router.get("/shadow/desks")
def shadow_desks():
    """Return distinct desk values for the dashboard desk-filter dropdown.

    Always includes 'swing' and 'all'; any non-swing desks present in
    shadow_trades are appended. Mirrors cloud_routes/trades.py:shadow_desks
    so the local FastAPI app + Cloudflare-tunneled halcyonlab.app both serve
    this endpoint (was 404 prior to Sprint 6 follow-up).
    """
    try:
        conn = connect_db(DB_PATH)
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                "SELECT DISTINCT desk FROM shadow_trades "
                "WHERE desk IS NOT NULL AND desk != 'swing' "
                "ORDER BY desk"
            ).fetchall()
            research_desks = [r["desk"] for r in rows]
            return ["swing", "all"] + research_desks
        finally:
            conn.close()
    except Exception as exc:
        logger.error("[API] shadow_desks failed: %s", exc)
        return ["swing", "all"]


@router.get("/shadow/sharpe-attribution")
def shadow_sharpe_attribution(desk: str | None = Query(None)):
    """SD#41 REVISED primary metric: alpha vs SPY beta.

    Returns raw Sharpe + excess Sharpe with 95% CIs + t-statistic.
    Default desk filter is 'swing' (matches cloud_routes/trades.py default).
    Mirrors cloud_routes/trades.py:sharpe_attribution so the local FastAPI app
    + Cloudflare-tunneled halcyonlab.app both serve this endpoint (was 404).
    """
    try:
        conn = connect_db(DB_PATH)
        conn.row_factory = sqlite3.Row
        try:
            # Default to swing-only when no desk specified — matches cloud convention.
            if desk is None or desk == "swing":
                where = "desk = ?"
                params = ("swing",)
            elif desk == "all":
                where = "1=1"
                params = ()
            else:
                where = "desk = ?"
                params = (desk,)
            rows = [dict(r) for r in conn.execute(
                "SELECT pnl_pct, spy_return_over_hold, excess_return "
                "FROM shadow_trades "
                f"WHERE actual_exit_time IS NOT NULL AND pnl_pct IS NOT NULL "
                f"AND COALESCE(quarantined, 0) = 0 AND {where}",
                params,
            ).fetchall()]
            if not rows or len(rows) < 2:
                return {"error": "insufficient_data", "n_trades": len(rows)}
            return _build_attribution_payload(rows)
        finally:
            conn.close()
    except Exception as exc:
        logger.error("[API] sharpe-attribution failed: %s", exc)
        return {"error": str(exc)}


@router.post("/shadow/close/{ticker}", dependencies=[Depends(verify_local_token)])
def close_trade(ticker: str, reason: str = "manual"):
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from src.journal.store import (
        get_open_shadow_trades, close_shadow_trade,
        update_recommendation, update_shadow_trade,
    )
    from src.shadow_trading.executor import (
        _get_current_price_safe,
        _is_filled_status,
        _is_pending_status,
        _submit_exit_order,
    )

    ticker = ticker.upper()
    reason = coerce_exit_reason(reason, ticker=ticker)
    ET = ZoneInfo("America/New_York")
    open_trades_list = get_open_shadow_trades()
    trade = next((t for t in open_trades_list if t["ticker"] == ticker), None)

    if not trade:
        return {"error": f"No open shadow trade found for {ticker}"}

    entry = trade.get("actual_entry_price") or trade.get("entry_price", 0)
    current = _get_current_price_safe(ticker) or entry
    now = datetime.now(ET)

    entry_time_str = trade.get("actual_entry_time") or trade.get("created_at", "")
    try:
        entry_time = datetime.fromisoformat(entry_time_str)
        days_held = (now - entry_time).days
    except (ValueError, TypeError):
        days_held = 0

    shares = trade.get("planned_shares", 1)
    # Live trades require broker interaction; paper trades are closed
    # locally by writing the exit directly to SQLite.
    if trade.get("source") == "live" or trade.get("alpaca_order_id"):
        try:
            broker_result = _submit_exit_order(trade, shares)
        except Exception as exc:
            return {"error": f"Broker exit failed — trade remains open ({exc})"}

        status = broker_result.get("status") if isinstance(broker_result, dict) else None
        if _is_filled_status(status):
            fill_price = broker_result.get("filled_avg_price")
            if fill_price is not None:
                current = float(fill_price)
        elif _is_pending_status(status):
            update_shadow_trade(
                trade["trade_id"],
                {"status": "exit_pending", "exit_reason": reason, "duration_days": days_held},
            )
            return {
                "ticker": ticker,
                "status": "exit_pending",
                "broker_order_id": broker_result.get("order_id"),
                "message": "Broker exit submitted but not yet filled",
            }
        else:
            return {"error": "Broker exit failed — trade remains open"}

    pnl_dollars = (current - entry) * shares
    pnl_pct = ((current - entry) / entry * 100) if entry > 0 else 0

    close_shadow_trade(
        trade["trade_id"],
        exit_price=current,
        exit_time=now.isoformat(),
        exit_reason=reason,
        pnl_dollars=round(pnl_dollars, 2),
        pnl_pct=round(pnl_pct, 2),
    )
    update_shadow_trade(trade["trade_id"], {"duration_days": days_held})

    rec_id = trade.get("recommendation_id")
    if rec_id:
        update_recommendation(rec_id, {
            "shadow_exit_price": current,
            "shadow_exit_time": now.isoformat(),
            "shadow_pnl_dollars": round(pnl_dollars, 2),
            "shadow_pnl_pct": round(pnl_pct, 2),
            "shadow_duration_days": days_held,
            "thesis_success": 1 if pnl_dollars > 0 else 0,
        })

    return {
        "ticker": ticker,
        "exit_reason": reason,
        "pnl_dollars": round(pnl_dollars, 2),
        "pnl_pct": round(pnl_pct, 2),
        "days_held": days_held,
    }
