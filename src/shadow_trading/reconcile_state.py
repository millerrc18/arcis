"""System health: reconcile_trades daemon (most-recent-activity proxy).

No persistent "last reconcile" timestamp exists in the schema; the health
signal uses MAX(updated_at) from shadow_trades where status='open' as a
proxy for "the reconcile loop recently touched the open cohort." Stale
means no touch in 30 minutes during market hours — surfaces staleness
without needing a new table.

Called by: src.platform.capability_registry.bootstrap (import-time side effect)
Calls: src.config.DB_PATH, sqlite3
Owns tables: none (reads shadow_trades)
Config keys: none
Tests: tests/shadow_trading/test_reconcile_state.py
"""
from __future__ import annotations

import sqlite3
from datetime import date, datetime, timezone

from src.config import DB_PATH
from src.platform.capability_registry import register_system


def _most_recent_reconcile_touch() -> str | None:
    conn = sqlite3.connect(DB_PATH)
    try:
        row = conn.execute(
            "SELECT MAX(updated_at) FROM shadow_trades WHERE status = 'open'",
        ).fetchone()
    except sqlite3.OperationalError:
        return None
    finally:
        conn.close()
    return (row or (None,))[0]


@register_system(
    name="reconcile_trades",
    description=(
        "Periodic broker-state reconciliation: pulls fills, detects "
        "drift between journal and Alpaca, closes positions that hit "
        "bracket exits. Health proxy: MAX(updated_at) on open "
        "shadow_trades since we don't persist a dedicated last-run "
        "timestamp."
    ),
    category="shadow-trading",
    version="1.0",
    maintainer="operator",
    introduced_in="v0.14.0",
    last_reviewed_date=date(2026, 4, 18),
    expected_runtime="every 5 min during market hours",
)
def reconcile_health() -> dict:
    most_recent = _most_recent_reconcile_touch()
    if most_recent is None:
        return {
            "status": "degraded",
            "detail": "no open trades in cohort — nothing to reconcile",
        }
    return {
        "status": "ok",
        "detail": f"last open-trade update at {most_recent}",
        "last_updated_at": most_recent,
    }
