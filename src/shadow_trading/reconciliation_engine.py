"""Reconciliation primitives and post-trade state checks.

Houses the trade-state reconciliation primitives extracted from
``executor.py`` during the Phase 5 PR-C T10 refactor:

  - ``quarantine_trade``: atomic terminal-state quarantine for a shadow row.
  - ``_count_live_open_positions``: DB-direct open-position count used by
    the hard governor cap.
  - Milestone notifiers: ``_check_open_milestones``,
    ``_check_close_milestones``, ``_check_loss_streak``.
  - Sector concentration alarm: ``_check_sector_exposure`` (+ its
    in-process TTL cache).
  - OHLCV helper used by the mean-reversion exit path:
    ``_get_recent_ohlcv_safe``.

These pieces share a single responsibility: reconcile the *current
shadow-ledger state* (counts, milestones, streaks, exposure) against
configured thresholds or external broker reality. They are deliberately
import-light so the orchestrator (``executor.py``) and the order-lifecycle
loop (``order_lifecycle.py``) can both pull from here without circular
risk.

The public surface is re-exported from ``executor`` for backward-compat:
test/script patches at ``src.shadow_trading.executor.<name>`` continue to
intercept these helpers because ``executor`` re-binds them at module top.

Called by: shadow_trading.executor (re-export), shadow_trading.order_lifecycle
Calls: config, notifications, shadow_trading._status_sql, shadow_trading.exit_reason, utils.db
Owns tables: none (reads shadow_trades via _count_live_open_positions)
Config keys: bootcamp, loss_streak_alert_threshold, max_open_positions, risk, sector_exposure_pct, shadow_trading
Tests: tests/test_expanded_notifications.py, tests/test_executor_import.py
"""

import logging
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from src.config import DB_PATH
from src.utils.db import _scalar
from src.shadow_trading._status_sql import (
    active_in_clause,
    terminal_in_clause,
)
from src.shadow_trading.exit_reason import coerce_exit_reason
from src.notifications import safe_send

logger = logging.getLogger(__name__)

# #756 — TTL cache for yfinance sector lookups in _check_sector_exposure.
# Keyed by ticker; value is (sector_str, expiry_timestamp).
# TTL of 3600s (1 hour) prevents repeated outbound calls per scan cycle.
_sector_cache: dict[str, tuple[str, float]] = {}
_SECTOR_CACHE_TTL_S = 3600


def _count_live_open_positions(db_path: str) -> int:
    """Count all non-quarantined open/exit_pending shadow trades regardless of source.

    Returns a fresh count straight from SQLite so every entry path (shadow,
    live, any future router) agrees.  Used by the hard governor cap.
    """
    from src.shadow_trading import executor as _exec

    _a_frag, _a_params = active_in_clause()
    with _exec.connect_db(db_path) as conn:
        row = conn.execute(
            "SELECT COUNT(*) FROM shadow_trades "
            f"WHERE status IN ({_a_frag}) "
            "AND COALESCE(quarantined, 0) = 0",
            _a_params,
        ).fetchone()
    return int(row[0] or 0)


def quarantine_trade(trade_id: str, reason: str, db_path: str = DB_PATH, ticker: str = "") -> None:
    """Atomically quarantine a shadow trade.

    Sets status='quarantined', quarantined=1, exit_reason=reason, and updated_at
    in a single UPDATE so all downstream consumers (position counters, analytics,
    reconciler duplicate checks) see a consistent terminal state.

    #626 — standardized atomic quarantine replaces ad-hoc exit_reason text edits
    that left quarantined=0, causing the trade to still count against position limits.
    """
    # Late-binding via executor: tests patch ``src.shadow_trading.executor.connect_db``
    # to inject in-memory connections. Resolving against ``_exec.connect_db`` keeps
    # that patch path live now that ``quarantine_trade`` itself lives in this module.
    from src.shadow_trading import executor as _exec

    now_str = datetime.now(ZoneInfo("America/New_York")).isoformat()
    coerced_reason = coerce_exit_reason(reason, ticker=ticker)
    with _exec.connect_db(db_path) as conn:
        conn.execute(
            "UPDATE shadow_trades SET status='quarantined', quarantined=1, "
            "exit_reason=?, updated_at=? WHERE trade_id=?",
            (coerced_reason, now_str, trade_id),
        )
        conn.commit()
    logger.info("[QUARANTINE] Trade %s quarantined: %s", trade_id[:8], reason)


def _check_open_milestones(db_path: str = DB_PATH,
                           source: str = "paper") -> None:
    """Check for trade open milestones and send notifications."""
    from src.shadow_trading import executor as _exec

    try:
        with _exec.connect_db(db_path) as conn:
            # Count total opened trades for this source
            _row = conn.execute(
                "SELECT COUNT(*) FROM shadow_trades WHERE COALESCE(source,'paper') = ?"
                " AND COALESCE(quarantined, 0) = 0",
                (source,),
            ).fetchone()
            total = _scalar(_row)

            label = "live" if source == "live" else "paper"

            if total == 1:
                safe_send(
                    "milestone",
                    milestone=f"First {label} trade opened!",
                    detail=f"Your trading journey begins. Track progress in the Shadow Ledger.",
                )
    except Exception as e:
        logger.debug("[MILESTONE] Open milestone check failed: %s", e)


def _check_close_milestones(db_path: str = DB_PATH) -> None:
    """Check for trade close milestones and send notifications."""
    from src.shadow_trading import executor as _exec

    try:
        _t_frag_m, _t_params_m = terminal_in_clause()
        with _exec.connect_db(db_path) as conn:

            _row = conn.execute(
                f"SELECT COUNT(*) FROM shadow_trades WHERE status IN ({_t_frag_m})"
                " AND COALESCE(quarantined, 0) = 0",
                _t_params_m,
            ).fetchone()
            closed_total = _scalar(_row)

            _row = conn.execute(
                f"SELECT COUNT(*) FROM shadow_trades WHERE status IN ({_t_frag_m}) AND pnl_dollars > 0"
                " AND COALESCE(quarantined, 0) = 0",
                _t_params_m,
            ).fetchone()
            wins = _scalar(_row)
            losses = closed_total - wins

            # Check milestone thresholds
            milestones = {1: "1st trade closed!", 10: "10th closed trade!",
                          25: "25th closed trade!", 50: "50th closed trade — Phase 1 gate!"}
            if closed_total in milestones:
                win_rate = wins / closed_total if closed_total > 0 else 0

                avg_row = conn.execute(
                    "SELECT AVG(pnl_dollars) as expectancy, AVG(duration_days) as avg_hold "
                    f"FROM shadow_trades WHERE status IN ({_t_frag_m}) AND COALESCE(quarantined, 0) = 0",
                    _t_params_m,
                ).fetchone()
                expectancy = avg_row["expectancy"] or 0
                avg_hold = avg_row["avg_hold"] or 0

                if closed_total == 50:
                    detail = (
                        f"🎉 Phase 1 gate reached!\n"
                        f"Current win rate: {win_rate:.0%} ({wins}W / {losses}L)\n"
                        f"Avg hold: {avg_hold:.1f} days | Expectancy: ${expectancy:+.2f}/trade"
                    )
                elif closed_total == 1:
                    detail = "Your first completed trade. Many more to come."
                else:
                    remaining = 50 - closed_total
                    detail = (
                        f"{remaining} more to Phase 1 gate (50 trades).\n"
                        f"Current win rate: {win_rate:.0%} ({wins}W / {losses}L)\n"
                        f"Avg hold: {avg_hold:.1f} days | Expectancy: ${expectancy:+.2f}/trade"
                    )
                safe_send("milestone", milestone=milestones[closed_total], detail=detail)

            # First profitable trade
            if wins == 1:
                first_win = conn.execute(
                    "SELECT ticker, pnl_dollars, pnl_pct FROM shadow_trades "
                    f"WHERE status IN ({_t_frag_m}) AND pnl_dollars > 0 AND COALESCE(quarantined, 0) = 0 "
                    "ORDER BY actual_exit_time ASC LIMIT 1",
                    _t_params_m,
                ).fetchone()
                if first_win:
                    safe_send(
                        "milestone",
                        milestone="First profitable trade!",
                        detail=f"{first_win['ticker']}: ${first_win['pnl_dollars']:+.2f} ({first_win['pnl_pct']:+.1f}%)",
                    )

            # First live profit
            _row = conn.execute(
                "SELECT COUNT(*) FROM shadow_trades "
                f"WHERE status IN ({_t_frag_m}) AND source='live' AND pnl_dollars > 0"
                " AND COALESCE(quarantined, 0) = 0",
                _t_params_m,
            ).fetchone()
            live_wins = _scalar(_row)
            if live_wins == 1:
                first_live_win = conn.execute(
                    "SELECT ticker, pnl_dollars, pnl_pct FROM shadow_trades "
                    f"WHERE status IN ({_t_frag_m}) AND source='live' AND pnl_dollars > 0 "
                    "AND COALESCE(quarantined, 0) = 0 "
                    "ORDER BY actual_exit_time ASC LIMIT 1",
                    _t_params_m,
                ).fetchone()
                if first_live_win:
                    safe_send(
                        "milestone",
                        milestone="First live trade profit!",
                        detail=f"{first_live_win['ticker']}: ${first_live_win['pnl_dollars']:+.2f} ({first_live_win['pnl_pct']:+.1f}%)",
                    )

            # 3 consecutive wins
            last_3 = conn.execute(
                f"SELECT pnl_dollars FROM shadow_trades WHERE status IN ({_t_frag_m})"
                " AND COALESCE(quarantined, 0) = 0 "
                "ORDER BY actual_exit_time DESC LIMIT 3",
                _t_params_m,
            ).fetchall()
            if len(last_3) == 3 and all(float(r["pnl_dollars"] or 0) > 0 for r in last_3):
                last_4 = conn.execute(
                    f"SELECT pnl_dollars FROM shadow_trades WHERE status IN ({_t_frag_m})"
                    " AND COALESCE(quarantined, 0) = 0 "
                    "ORDER BY actual_exit_time DESC LIMIT 4",
                    _t_params_m,
                ).fetchall()
                # Only alert if the 4th-most-recent was NOT a win (to avoid repeat alerts)
                if len(last_4) < 4 or float(last_4[3]["pnl_dollars"] or 0) <= 0:
                    safe_send(
                        "milestone",
                        milestone="3 consecutive wins!",
                        detail="Hot streak! Keep the discipline.",
                    )

            # Best single trade P&L
            best_ever = conn.execute(
                "SELECT ticker, pnl_dollars, pnl_pct FROM shadow_trades "
                f"WHERE status IN ({_t_frag_m}) AND COALESCE(quarantined, 0) = 0"
                " ORDER BY pnl_dollars DESC LIMIT 1",
                _t_params_m,
            ).fetchone()
            # The most recent closed trade
            latest = conn.execute(
                "SELECT ticker, pnl_dollars FROM shadow_trades "
                f"WHERE status IN ({_t_frag_m}) AND COALESCE(quarantined, 0) = 0"
                " ORDER BY actual_exit_time DESC LIMIT 1",
                _t_params_m,
            ).fetchone()
            if (best_ever and latest and closed_total > 1
                    and best_ever["ticker"] == latest["ticker"]
                    and float(best_ever["pnl_dollars"] or 0) == float(latest["pnl_dollars"] or 0)
                    and float(best_ever["pnl_dollars"] or 0) > 0):
                safe_send(
                    "milestone",
                    milestone="New best trade!",
                    detail=f"{best_ever['ticker']}: ${best_ever['pnl_dollars']:+.2f} ({best_ever['pnl_pct']:+.1f}%)",
                )

    except Exception as e:
        logger.warning("[MILESTONE] Close milestone check failed: %s", e)


def _check_loss_streak(db_path: str = DB_PATH) -> None:
    """Check for consecutive losses and alert at 3+."""
    from src.shadow_trading import executor as _exec

    try:
        _t_frag_ls, _t_params_ls = terminal_in_clause()
        with _exec.connect_db(db_path) as conn:
            recent = conn.execute(
                "SELECT ticker, pnl_dollars, pnl_pct FROM shadow_trades "
                f"WHERE status IN ({_t_frag_ls}) AND COALESCE(quarantined, 0) = 0"
                " ORDER BY actual_exit_time DESC LIMIT 10",
                _t_params_ls,
            ).fetchall()

        if len(recent) >= 3:
            # Count consecutive losses from most recent
            streak = 0
            streak_trades = []
            for r in recent:
                if float(r["pnl_dollars"] or 0) < 0:
                    streak += 1
                    streak_trades.append((r["ticker"], r["pnl_pct"]))
                else:
                    break

            if streak >= 3:
                # Only alert if this is exactly the streak boundary (3rd, 4th, etc.)
                # Check if streak was already 3+ before this trade
                prev_streak = 0
                for r in recent[1:]:
                    if float(r["pnl_dollars"] or 0) < 0:
                        prev_streak += 1
                    else:
                        break

                # Alert on first crossing of 3, or every additional loss after
                if streak == 3 or (streak > 3 and prev_streak < streak):
                    max_dd = min(float(r["pnl_pct"] or 0) for r in recent[:streak])

                    # Historical max streak
                    with _exec.connect_db(db_path) as conn:
                        all_closed = conn.execute(
                            f"SELECT pnl_dollars FROM shadow_trades WHERE status IN ({_t_frag_ls})"
                            " AND COALESCE(quarantined, 0) = 0 "
                            "ORDER BY actual_exit_time ASC",
                            _t_params_ls,
                        ).fetchall()
                    max_streak = 0
                    current = 0
                    for r in all_closed:
                        if float(r["pnl_dollars"] or 0) < 0:
                            current += 1
                            max_streak = max(max_streak, current)
                        else:
                            current = 0

                    safe_send(
                        "streak_alert",
                        streak_length=streak,
                        recent_trades=streak_trades[:5],
                        max_drawdown_pct=max_dd,
                        risk_governor_status="NORMAL",
                        historical_max_streak=max_streak,
                    )
    except Exception as e:
        logger.warning("[STREAK] Loss streak check failed: %s", e)


def _check_sector_exposure(db_path: str = DB_PATH) -> None:
    """Check sector concentration after each trade open."""
    from src.shadow_trading import executor as _exec

    try:
        _a_frag_se, _a_params_se = active_in_clause()
        with _exec.connect_db(db_path) as conn:
            open_trades = conn.execute(
                f"SELECT ticker FROM shadow_trades WHERE status IN ({_a_frag_se})"
                " AND COALESCE(quarantined, 0) = 0",
                _a_params_se,
            ).fetchall()

        if len(open_trades) >= 3:
            # Get sector for each ticker (best-effort from recommendations)
            sectors: dict[str, list[str]] = {}
            with _exec.connect_db(db_path) as conn:
                for trade in open_trades:
                    ticker = trade["ticker"]
                    rec = conn.execute(
                        "SELECT setup_type FROM recommendations WHERE ticker = ? "
                        "ORDER BY created_at DESC LIMIT 1",
                        (ticker,),
                    ).fetchone()
                    # Use setup_type as a proxy; in practice, sector info would come from features
                    sector = "Unknown"
                    _now = time.time()
                    _cached = _sector_cache.get(ticker)
                    if _cached and _cached[1] > _now:
                        sector = _cached[0]
                    else:
                        try:
                            import yfinance as yf
                            info = yf.Ticker(ticker).info
                            sector = info.get("sector", "Unknown")
                            _sector_cache[ticker] = (sector, _now + _SECTOR_CACHE_TTL_S)
                        except Exception as e:
                            logger.debug("[EXPOSURE] yfinance sector lookup failed for %s: %s", ticker, e)
                    sectors.setdefault(sector, []).append(ticker)

            total_positions = len(open_trades)
            limit_pct = 30.0
            for sector, tickers in sectors.items():
                if sector == "Unknown":
                    continue
                exposure_pct = (len(tickers) / total_positions) * 100
                if exposure_pct > limit_pct and len(tickers) >= 3:
                    safe_send(
                        "exposure_alert",
                        sector=sector, count=len(tickers), tickers=tickers,
                        exposure_pct=exposure_pct, limit_pct=limit_pct,
                    )
    except Exception as e:
        logger.debug("[EXPOSURE] Sector exposure check failed: %s", e)


def _get_recent_ohlcv_safe(ticker: str, days: int = 10):
    """Fetch recent OHLCV for a ticker (for MR exit checks). Returns DataFrame or None."""
    try:
        import yfinance as yf
        data = yf.download(ticker, period=f"{days}d", progress=False)
        if data is not None and not data.empty:
            return data
    except Exception as e:
        logger.debug("[OHLCV] yfinance fetch failed for %s: %s", ticker, e)
    return None
