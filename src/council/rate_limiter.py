"""Council parameter rate-limiting logic.

Called by: council/protocol.py
Calls: council/constants.py
Owns tables: none
Config keys: none
Tests: none
"""

import logging
import sqlite3
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from src.config import DB_PATH
from src.council.constants import PARAMETER_BOUNDS, PARAMETER_DEFAULTS, RATE_LIMITS

logger = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")


def _clip_to_bounds(param: str, value: float) -> float:
    """Clamp a numeric council parameter to its hard-coded safe bounds."""
    bounds = PARAMETER_BOUNDS.get(param)
    if not bounds:
        return value
    return max(bounds[0], min(bounds[1], value))


def _weekly_baseline(param: str, db_path: str) -> float:
    """Return the effective council value from roughly one week ago, if present."""
    baseline = PARAMETER_DEFAULTS.get(param, 1.0)
    week_ago = (datetime.now(ET) - timedelta(days=7)).isoformat()
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT applied_value FROM council_parameter_log "
            "WHERE parameter_name = ? AND attribution_start <= ? "
            "ORDER BY attribution_start DESC LIMIT 1",
            (param, week_ago),
        ).fetchone()
        if row:
            baseline = float(row[0])
    return baseline


def apply_rate_limiters(
    recommended: dict,
    current: dict,
    db_path: str = DB_PATH,
) -> dict:
    """Apply daily and weekly cumulative council rate limits."""
    applied = {}
    rate_limited = False

    for param, recommended_value in recommended.items():
        if param == "scan_aggressiveness":
            applied[param] = recommended_value
            continue

        current_value = float(current.get(param, PARAMETER_DEFAULTS.get(param, 1.0)))
        next_value = _clip_to_bounds(param, float(recommended_value))

        max_daily = max(abs(current_value) * RATE_LIMITS["max_daily_change_pct"], 0.05)
        if abs(next_value - current_value) > max_daily:
            next_value = current_value + max_daily if next_value > current_value else current_value - max_daily
            rate_limited = True
            logger.info("[COUNCIL] Daily rate limit on %s: clipped to %.3f", param, next_value)

        try:
            baseline = _weekly_baseline(param, db_path)
            max_weekly = abs(baseline) * RATE_LIMITS["max_weekly_change_pct"]
            if abs(next_value - baseline) > max_weekly:
                next_value = baseline + max_weekly if next_value > baseline else baseline - max_weekly
                rate_limited = True
                logger.info(
                    "[COUNCIL] Weekly rate limit on %s: clipped to %.3f (baseline=%.3f)",
                    param,
                    next_value,
                    baseline,
                )
        except Exception as exc:
            logger.debug("[COUNCIL] Weekly rate limit check failed: %s", exc)

        applied[param] = round(_clip_to_bounds(param, next_value), 3)

    applied["_rate_limited"] = rate_limited
    return applied
