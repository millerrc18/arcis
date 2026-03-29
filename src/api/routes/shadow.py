"""Shadow trading API routes."""
from fastapi import APIRouter
from src.config import load_config
from src.services.shadow_service import get_shadow_status, get_shadow_history, get_shadow_account

router = APIRouter(tags=["shadow"])


@router.get("/shadow/open")
def open_trades():
    config = load_config()
    return get_shadow_status(config)


@router.get("/shadow/closed")
def closed_trades(days: int = 30):
    return get_shadow_history(days=days)


@router.get("/shadow/account")
def account():
    try:
        return get_shadow_account()
    except Exception as e:
        return {"error": str(e)}


@router.get("/shadow/metrics")
def metrics(days: int = 30):
    result = get_shadow_history(days=days)
    return result.get("metrics", {})


@router.post("/shadow/close/{ticker}")
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
