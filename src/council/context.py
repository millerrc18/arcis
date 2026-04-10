"""Shared council context assembly from current repo schemas.

Called by: council/protocol.py
Calls: council/agents.py, evaluation/hshs_live.py
Owns tables: none
Config keys: none
Tests: none
"""

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from src.config import DB_PATH

logger = logging.getLogger(__name__)

ET = ZoneInfo("America/New_York")


def build_shared_context(db_path: str = DB_PATH) -> str:
    """Build a concise shared market context for all agents."""
    from src.council.agents import _query_db

    parts = [f"Session date: {datetime.now(ET).strftime('%Y-%m-%d %H:%M ET')}"]

    try:
        recs = _query_db(
            "SELECT COUNT(*) as count, AVG(priority_score) as avg_score "
            "FROM recommendations WHERE created_at >= datetime('now', '-1 day')",
            db_path=db_path,
        )
        if recs:
            summary = recs[0]
            parts.append(
                f"Today's scan: {summary.get('count', 0)} candidates, "
                f"avg score {summary.get('avg_score', 0):.1f}"
            )
    except Exception as e:
        logger.debug("context: recommendations query failed: %s", e)

    try:
        open_positions = _query_db(
            "SELECT COUNT(*) as n FROM shadow_trades WHERE status = 'open'"
            " AND COALESCE(quarantined, 0) = 0",
            db_path=db_path,
        )
        if open_positions:
            parts.append(f"Open positions: {open_positions[0]['n']}")
    except Exception as e:
        logger.debug("context: open positions query failed: %s", e)

    try:
        from src.evaluation.hshs_live import compute_hshs

        hshs = compute_hshs(db_path)
        dimensions = hshs.get("dimensions", {})
        parts.append(
            f"System Health (HSHS): {hshs.get('hshs', 0):.1f}/100 "
            f"(P={dimensions.get('performance', 0):.0f} "
            f"M={dimensions.get('model_quality', 0):.0f} "
            f"D={dimensions.get('data_asset', 0):.0f} "
            f"F={dimensions.get('flywheel_velocity', 0):.0f} "
            f"C={dimensions.get('defensibility', 0):.0f})"
        )
    except Exception as e:
        logger.debug("context: HSHS computation failed: %s", e)

    try:
        import sqlite3 as sqlite

        with sqlite.connect(db_path) as conn:
            row = conn.execute(
                "SELECT current_regime, last_total_score FROM traffic_light_state WHERE id = 1"
            ).fetchone()
            if row:
                parts.append(f"Traffic Light: {row[0]} (score {row[1]}/6)")
    except Exception as e:
        logger.debug("context: traffic light query failed: %s", e)

    try:
        vix = _query_db(
            "SELECT vix FROM vix_term_structure ORDER BY collected_date DESC LIMIT 1",
            db_path=db_path,
        )
        if vix:
            parts.append(f"VIX: {vix[0]['vix']:.1f}")
    except Exception as e:
        logger.debug("context: VIX query failed: %s", e)

    return "\n".join(parts) if parts else "No shared context available."
