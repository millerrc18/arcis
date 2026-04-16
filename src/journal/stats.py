"""Closed-trade performance stats for Telegram + dashboard surfaces.

Provides a single source of truth for "how are we doing" numbers so the
pre-market / midday / post-close Telegram pulses, the dashboard, and
ad-hoc ops queries all agree.

Windows are anchored on `actual_exit_time` so "today's PnL" only counts
trades that closed today (not trades opened today that are still open).
All stats come from `shadow_trades` where `status != 'open'` AND
`quarantined = 0`.

Called by: notifications.telegram (notify_trading_stats_update),
  scheduler.watch_handlers (maybe_stats_pulse)
Calls: none
Owns tables: none (reads shadow_trades)
Config keys: none
Tests: tests/journal/test_stats.py
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from src.config import DB_PATH

ET = ZoneInfo("America/New_York")


def compute_window_stats(db_path: str = DB_PATH, days: int | None = None,
                         today_only: bool = False) -> dict:
    """Compute stats for trades closed within the window.

    Args:
        db_path: SQLite path override (tests use a tmp file).
        days: look back this many days from now. None + today_only=False
            means "all time".
        today_only: restrict to trades closed today (ET calendar day).

    Returns dict with:
        count, wins, losses, win_rate, avg_pnl_pct, median_pnl_pct,
        total_pnl_dollars, avg_excess_return, best_pct, worst_pct,
        excess_sharpe (trade-count-scaled, None if < 10 trades).
    """
    where_clauses = ["status != 'open'", "COALESCE(quarantined, 0) = 0",
                     "actual_exit_time IS NOT NULL"]
    params: list = []

    if today_only:
        today_et = datetime.now(ET).date().isoformat()
        where_clauses.append("DATE(actual_exit_time) = ?")
        params.append(today_et)
    elif days is not None:
        cutoff = (datetime.now(ET) - timedelta(days=days)).isoformat()
        where_clauses.append("actual_exit_time >= ?")
        params.append(cutoff)

    sql = (
        "SELECT pnl_pct, pnl_dollars, excess_return "
        "FROM shadow_trades WHERE " + " AND ".join(where_clauses)
    )
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(sql, params).fetchall()

    pnl_pcts = [r[0] for r in rows if r[0] is not None]
    pnl_dollars = [r[1] for r in rows if r[1] is not None]
    excess = [r[2] for r in rows if r[2] is not None]

    count = len(rows)
    wins = sum(1 for p in pnl_pcts if p > 0)
    losses = sum(1 for p in pnl_pcts if p <= 0)
    return {
        "count": count,
        "wins": wins,
        "losses": losses,
        "win_rate": (wins / len(pnl_pcts)) if pnl_pcts else None,
        "avg_pnl_pct": (sum(pnl_pcts) / len(pnl_pcts)) if pnl_pcts else None,
        "median_pnl_pct": sorted(pnl_pcts)[len(pnl_pcts) // 2] if pnl_pcts else None,
        "total_pnl_dollars": sum(pnl_dollars) if pnl_dollars else 0.0,
        "avg_excess_return": (sum(excess) / len(excess)) if excess else None,
        "best_pct": max(pnl_pcts) if pnl_pcts else None,
        "worst_pct": min(pnl_pcts) if pnl_pcts else None,
        "excess_sharpe": _trade_sharpe(excess) if len(excess) >= 10 else None,
    }


def _trade_sharpe(excess: list[float]) -> float | None:
    """Per-trade excess-return Sharpe (unannualized, informational only).

    Matches the "trade-count-scaled Sharpe" convention used across the
    dashboard — this is `mean(excess) / stdev(excess) * sqrt(n)` over
    the supplied list. Phase 1→2 gate uses excess-Sharpe ≥ 0.5 at
    t ≥ 2.0 over 150 OOS trades (SD#41 REVISED).
    """
    if len(excess) < 2:
        return None
    n = len(excess)
    mean = sum(excess) / n
    variance = sum((x - mean) ** 2 for x in excess) / (n - 1)
    stdev = variance ** 0.5
    if stdev == 0:
        return None
    return (mean / stdev) * (n ** 0.5)


def compute_all_window_stats(db_path: str = DB_PATH) -> dict:
    """Compute stats for all 4 standard pulse windows.

    Returns:
        {"today": {...}, "7d": {...}, "30d": {...}, "all_time": {...}}
    """
    return {
        "today": compute_window_stats(db_path, today_only=True),
        "7d": compute_window_stats(db_path, days=7),
        "30d": compute_window_stats(db_path, days=30),
        "all_time": compute_window_stats(db_path),
    }
