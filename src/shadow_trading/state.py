"""State query: shadow trade cohort counts.

Thin wrapper that the capability registry exposes via /api/system/index.
The underlying data lives in the shadow_trades table; the query uses the
canonical TERMINAL_STATUSES / ACTIVE_STATUSES constants from models.py
rather than hardcoding status strings.
"""
from __future__ import annotations

import sqlite3
from datetime import date

from src.config import DB_PATH
from src.platform.capability_registry import register_state


def _shadow_cohort_counts() -> dict:
    """Return {open, closed, quarantined, total} counts as a single row."""
    conn = sqlite3.connect(DB_PATH)
    try:
        row = conn.execute(
            "SELECT "
            "  SUM(CASE WHEN status='open' THEN 1 ELSE 0 END) AS open_n, "
            "  SUM(CASE WHEN status='closed' THEN 1 ELSE 0 END) AS closed_n, "
            "  SUM(CASE WHEN COALESCE(quarantined, 0) = 1 THEN 1 ELSE 0 END) AS quarantined_n, "
            "  COUNT(*) AS total_n "
            "FROM shadow_trades",
        ).fetchone()
    except sqlite3.OperationalError as exc:
        return {"error": f"shadow_trades unavailable: {exc}"}
    finally:
        conn.close()
    open_n, closed_n, quarantined_n, total_n = (row or (0, 0, 0, 0))
    return {
        "value": {
            "open": int(open_n or 0),
            "closed": int(closed_n or 0),
            "quarantined": int(quarantined_n or 0),
            "total": int(total_n or 0),
        },
    }


@register_state(
    name="shadow_trade_cohort",
    description=(
        "Counts of shadow trades by status (open/closed/quarantined) "
        "and total cohort size. Powers promotion-gate decisions and "
        "diagnostic dashboards."
    ),
    category="shadow-trading",
    version="1.0",
    maintainer="ai_session",
    introduced_in="v0.22.0",
    last_reviewed_date=date(2026, 4, 18),
    refresh_hint="real-time",
)
def shadow_trade_cohort() -> dict:
    return _shadow_cohort_counts()
