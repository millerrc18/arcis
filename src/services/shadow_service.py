"""Shadow trading service.

Called by: api.routes.shadow, api.cloud_routes.trades, cli.commands
Calls: journal.store, shadow_trading.alpaca_adapter, shadow_trading.executor, shadow_trading.metrics
Owns tables: none
Config keys: shadow_trading
Tests: tests/test_services.py, tests/api/test_trades_route_timeout.py
"""
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")


def compute_timeout_status(duration_days, timeout_days) -> dict:
    """Return timeout progress_pct and status for a trade.

    Args:
        duration_days: Days the trade has been held (int or None).
        timeout_days: Operative timeout threshold in days (int or None).

    Returns:
        Dict with keys timeout_progress_pct (float|None) and timeout_status (str).
        Statuses: 'unknown' (any None), 'on_track' (<80%), 'approaching' (80–<100%),
        'overdue' (>=100%). progress_pct is capped at 999.0.
    """
    if timeout_days is None or duration_days is None:
        return {"timeout_progress_pct": None, "timeout_status": "unknown"}
    pct = round(100.0 * duration_days / timeout_days, 1)
    if pct >= 100.0:
        status = "overdue"
    elif pct >= 80.0:
        status = "approaching"
    else:
        status = "on_track"
    return {"timeout_progress_pct": min(pct, 999.0), "timeout_status": status}


def get_shadow_status(config: dict) -> dict:
    """Get all open shadow trades with current prices and P&L."""
    from src.journal.store import get_open_shadow_trades
    from src.shadow_trading.executor import _get_current_price_safe

    timeout = config.get("shadow_trading", {}).get("timeout_days", 15)
    open_trades = get_open_shadow_trades()

    trades = []
    total_unrealized = 0.0

    for t in open_trades:
        entry = float(t.get("actual_entry_price") or t.get("entry_price") or 0)
        current = _get_current_price_safe(t["ticker"])
        pnl = None
        pnl_pct = None
        if current and entry > 0:
            pnl = current - entry
            pnl_pct = pnl / entry * 100
            total_unrealized += pnl * float(t.get("planned_shares") or 1)

        op_timeout = t.get("timeout_days") or timeout
        timeout_info = compute_timeout_status(t.get("duration_days"), op_timeout)
        trades.append({
            "trade_id": t["trade_id"],
            "recommendation_id": t.get("recommendation_id"),
            "ticker": t["ticker"],
            "direction": t.get("direction", "long"),
            "status": t.get("status", "open"),
            "entry_price": entry,
            "current_price": current,
            "stop_price": float(t.get("stop_price") or 0),
            "target_1": float(t.get("target_1") or 0),
            "target_2": float(t.get("target_2") or 0),
            "planned_shares": float(t.get("planned_shares") or 1),
            "pnl_dollars": round(pnl, 2) if pnl is not None else None,
            "pnl_pct": round(pnl_pct, 2) if pnl_pct is not None else None,
            "max_favorable_excursion": t.get("max_favorable_excursion"),
            "max_adverse_excursion": t.get("max_adverse_excursion"),
            "duration_days": t.get("duration_days"),
            "timeout_days": op_timeout,
            "llm_timeout_days": t.get("llm_timeout_days"),
            "timeout_progress_pct": timeout_info["timeout_progress_pct"],
            "timeout_status": timeout_info["timeout_status"],
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
    except Exception as _acct_err:
        # Route through log_and_persist so the failure appears in
        # BrokerExceptionsPanel (PR #690 O1). Account-info probe failure is
        # non-fatal — equity/buying_power surface as None.
        from src.shadow_trading.broker_exception_logger import log_and_persist
        log_and_persist(
            ticker="(all)",
            operation="fetch_account",
            broker="alpaca_paper",
            exc=_acct_err,
            recoverable=True,
        )

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
        op_timeout = t.get("timeout_days") or 15
        timeout_info = compute_timeout_status(t.get("duration_days"), op_timeout)
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
            "timeout_days": op_timeout,
            "llm_timeout_days": t.get("llm_timeout_days"),
            "timeout_progress_pct": timeout_info["timeout_progress_pct"],
            "timeout_status": timeout_info["timeout_status"],
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
