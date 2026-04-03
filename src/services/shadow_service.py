"""Shadow trading service.

Called by: api.routes.shadow, cli.commands
Calls: journal.store, shadow_trading.alpaca_adapter, shadow_trading.executor, shadow_trading.metrics
Owns tables: none
Config keys: shadow_trading
Tests: tests/test_services.py
"""
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")


def get_shadow_status(config: dict) -> dict:
    """Get all open shadow trades with current prices and P&L."""
    from src.journal.store import get_open_shadow_trades
    from src.shadow_trading.executor import _get_current_price_safe

    timeout = config.get("shadow_trading", {}).get("timeout_days", 15)
    open_trades = get_open_shadow_trades()

    trades = []
    total_unrealized = 0.0

    for t in open_trades:
        entry = t.get("actual_entry_price") or t.get("entry_price", 0)
        current = _get_current_price_safe(t["ticker"])
        pnl = None
        pnl_pct = None
        if current and entry > 0:
            pnl = current - entry
            pnl_pct = pnl / entry * 100
            total_unrealized += pnl * (t.get("planned_shares", 1))

        trades.append({
            "trade_id": t["trade_id"],
            "recommendation_id": t.get("recommendation_id"),
            "ticker": t["ticker"],
            "direction": t.get("direction", "long"),
            "status": t.get("status", "open"),
            "entry_price": entry,
            "current_price": current,
            "stop_price": t.get("stop_price", 0),
            "target_1": t.get("target_1", 0),
            "target_2": t.get("target_2", 0),
            "planned_shares": t.get("planned_shares", 1),
            "pnl_dollars": round(pnl, 2) if pnl is not None else None,
            "pnl_pct": round(pnl_pct, 2) if pnl_pct is not None else None,
            "max_favorable_excursion": t.get("max_favorable_excursion"),
            "max_adverse_excursion": t.get("max_adverse_excursion"),
            "duration_days": t.get("duration_days"),
            "timeout_days": timeout,
            "exit_reason": t.get("exit_reason"),
            "earnings_adjacent": bool(t.get("earnings_adjacent", 0)),
            "strategy_type": t.get("strategy_type", "pullback"),
            "created_at": t.get("created_at", ""),
        })

    account_equity = None
    account_buying_power = None
    try:
        from src.shadow_trading.alpaca_adapter import get_account_info
        acct = get_account_info()
        account_equity = acct.get("equity")
        account_buying_power = acct.get("buying_power")
    except Exception:
        pass

    return {
        "open_trades": trades,
        "open_count": len(trades),
        "total_unrealized_pnl": round(total_unrealized, 2) if trades else None,
        "account_equity": account_equity,
        "account_buying_power": account_buying_power,
    }


def get_shadow_history(days: int = 30) -> dict:
    """Get closed shadow trades with metrics."""
    from src.journal.store import get_closed_shadow_trades
    from src.shadow_trading.metrics import compute_shadow_metrics

    closed = get_closed_shadow_trades(days=days)
    metrics = compute_shadow_metrics(closed) if closed else {
        "total_trades": 0, "wins": 0, "losses": 0, "win_rate": 0,
        "avg_gain": 0, "avg_loss": 0, "expectancy": 0, "total_pnl": 0,
    }

    trades = []
    for t in closed:
        trades.append({
            "trade_id": t["trade_id"],
            "recommendation_id": t.get("recommendation_id"),
            "ticker": t["ticker"],
            "direction": t.get("direction", "long"),
            "status": "closed",
            "entry_price": t.get("actual_entry_price") or t.get("entry_price", 0),
            "stop_price": t.get("stop_price", 0),
            "target_1": t.get("target_1", 0),
            "target_2": t.get("target_2", 0),
            "planned_shares": t.get("planned_shares", 1),
            "pnl_dollars": t.get("pnl_dollars"),
            "pnl_pct": t.get("pnl_pct"),
            "max_favorable_excursion": t.get("max_favorable_excursion"),
            "max_adverse_excursion": t.get("max_adverse_excursion"),
            "duration_days": t.get("duration_days"),
            "timeout_days": 15,
            "exit_reason": t.get("exit_reason"),
            "earnings_adjacent": bool(t.get("earnings_adjacent", 0)),
            "strategy_type": t.get("strategy_type", "pullback"),
            "created_at": t.get("created_at", ""),
        })

    return {"trades": trades, "metrics": metrics}


def get_shadow_account() -> dict:
    """Get Alpaca paper account info."""
    from src.shadow_trading.alpaca_adapter import get_account_info, get_all_positions
    acct = get_account_info()
    positions = get_all_positions()
    return {"account": acct, "positions": positions}
