"""CUSUM (Cumulative Sum) performance change detection.

Called by: scheduler.watch
Calls: none
Owns tables: none
Config keys: none
Tests: tests/test_change_detector.py

Implements symmetric CUSUM filter (Lopez de Prado, AFML Ch.17)
to detect strategy drift from the paper P&L stream.
"""

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from src.config import DB_PATH

logger = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")


def cusum_detect(pnl_series: list[float], threshold: float = 2.0,
                 drift: float = 0.0) -> dict:
    """Symmetric CUSUM filter for detecting performance regime changes.

    Args:
        pnl_series: List of trade P&L percentages
        threshold: Detection threshold (higher = less sensitive)
        drift: Expected drift (0 = no drift expected)

    Returns:
        Dict with detected change points and current alarm status.
    """
    s_pos, s_neg = 0.0, 0.0
    alarms = []

    for i, pnl in enumerate(pnl_series):
        s_pos = max(0, s_pos + pnl - drift - threshold)
        s_neg = min(0, s_neg + pnl - drift + threshold)

        if s_pos > threshold:
            alarms.append({"index": i, "direction": "positive", "value": round(s_pos, 3)})
            s_pos = 0
        elif s_neg < -threshold:
            alarms.append({"index": i, "direction": "negative", "value": round(s_neg, 3)})
            s_neg = 0

    return {
        "alarms": alarms,
        "current_s_pos": round(s_pos, 3),
        "current_s_neg": round(s_neg, 3),
        "total_positive_alarms": sum(1 for a in alarms if a["direction"] == "positive"),
        "total_negative_alarms": sum(1 for a in alarms if a["direction"] == "negative"),
    }


def check_performance_drift(db_path: str = DB_PATH) -> dict:
    """Run CUSUM on closed trade P&L to detect strategy drift."""
    import sqlite3

    try:
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT pnl_pct FROM shadow_trades WHERE status = 'closed' "
                "AND pnl_pct IS NOT NULL AND COALESCE(quarantined, 0) = 0"
                " ORDER BY actual_exit_time ASC"
            ).fetchall()

        if len(rows) < 10:
            return {"sufficient_data": False, "trade_count": len(rows)}

        pnl_series = [float(r["pnl_pct"]) for r in rows]
        result = cusum_detect(pnl_series)

        recent_20 = pnl_series[-20:] if len(pnl_series) >= 20 else pnl_series
        all_wins = sum(1 for p in pnl_series if p > 0)
        recent_wins = sum(1 for p in recent_20 if p > 0)

        result["sufficient_data"] = True
        result["trade_count"] = len(pnl_series)
        result["overall_win_rate"] = round(all_wins / len(pnl_series), 3)
        result["recent_win_rate"] = round(recent_wins / len(recent_20), 3)
        result["drift_detected"] = any(a["direction"] == "negative" for a in result["alarms"])

        if result["drift_detected"]:
            logger.warning(
                "[CUSUM] Performance drift detected! Recent win rate: %.1f%% vs overall: %.1f%%",
                result["recent_win_rate"] * 100, result["overall_win_rate"] * 100,
            )

        return result
    except Exception as exc:
        logger.error("[CUSUM] Change detection failed: %s", exc)
        return {"error": str(exc), "sufficient_data": False}
