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


def _coerce_float(value) -> float | None:
    """Coerce a SQLite-returned value to float. Returns None on None or bad input.

    Defensive guard for #195: after a DB recovery, REAL columns sometimes
    return as TEXT, which breaks downstream numeric comparisons (p > 0 etc.).
    """
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _build_window_filter(
    days: int | None, today_only: bool,
) -> tuple[list[str], list]:
    """Build the WHERE-clause fragments + params for compute_window_stats."""
    where_clauses = [
        "status != 'open'",
        "COALESCE(quarantined, 0) = 0",
        "actual_exit_time IS NOT NULL",
    ]
    params: list = []
    if today_only:
        # WHY substr(.., 1, 10) instead of DATE(actual_exit_time):
        # SQLite's DATE() converts ISO timestamps with timezone offsets to UTC
        # before extracting the date — so a 2026-04-23T20:41-04:00 ET timestamp
        # becomes 2026-04-24 (UTC), and "today in ET" stops matching after
        # ~8pm ET. actual_exit_time is always written in ET-localized ISO
        # form, so the first 10 chars are the ET date directly.
        where_clauses.append("substr(actual_exit_time, 1, 10) = ?")
        params.append(datetime.now(ET).date().isoformat())
    elif days is not None:
        where_clauses.append("actual_exit_time >= ?")
        params.append((datetime.now(ET) - timedelta(days=days)).isoformat())
    return where_clauses, params


def compute_window_stats(db_path: str = DB_PATH, days: int | None = None,
                         today_only: bool = False) -> dict:
    """Compute stats for trades closed within the window.

    days=None + today_only=False means "all time". Returns dict with
    count, wins, losses, win_rate, avg_pnl_pct, median_pnl_pct,
    total_pnl_dollars, avg_excess_return, best_pct, worst_pct,
    excess_sharpe (trade-count-scaled, None if < 10 trades).
    """
    where_clauses, params = _build_window_filter(days, today_only)
    sql = (
        "SELECT pnl_pct, pnl_dollars, excess_return "
        "FROM shadow_trades WHERE " + " AND ".join(where_clauses)
    )
    # #590 — connect_db applies busy_timeout=30s
    from src.utils.db import connect_db
    with connect_db(db_path) as conn:
        rows = conn.execute(sql, params).fetchall()

    # SQLite REAL columns can return as TEXT after a DB recovery (#195),
    # which makes downstream `p > 0` compare str to int and raise TypeError.
    # Coerce at read-time so every downstream consumer sees clean floats.
    pnl_pcts = [f for f in (_coerce_float(r[0]) for r in rows) if f is not None]
    pnl_dollars = [f for f in (_coerce_float(r[1]) for r in rows) if f is not None]
    excess = [f for f in (_coerce_float(r[2]) for r in rows) if f is not None]

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
