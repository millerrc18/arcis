"""Notifications health endpoint — /api/notifications/health.

Called by: src.api.cloud_app (router registered at /api)
Calls: src.config.DB_PATH, src.utils.db.connect_db
Owns tables: none (reads notifications_sent, notifications_dedup)
Config keys: none
Tests: tests/api/test_notifications_health.py

Returns last-24h notification aggregates: success_rate, fail_count,
dedup_hits, oldest_unack_alert.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter

logger = logging.getLogger(__name__)

router = APIRouter()


def _query_sent_rows(since_iso: str) -> list[dict]:
    """Return rows from notifications_sent newer than since_iso. Uses SQLite."""
    try:
        from src.config import DB_PATH
        from src.utils.db import connect_db
        conn = connect_db(DB_PATH)
        try:
            rows = conn.execute(
                "SELECT status, error_msg, sent_at FROM notifications_sent"
                " WHERE sent_at >= ? AND status != 'heartbeat'",
                (since_iso,),
            ).fetchall()
            return [{"status": r[0], "error_msg": r[1], "sent_at": r[2]} for r in rows]
        finally:
            conn.close()
    except Exception:
        logger.debug("[NOTIFICATIONS_HEALTH] _query_sent_rows failed", exc_info=True)
        return []


def _query_dedup_hits(since_iso: str) -> int:
    """Count dedup rows that were active within the last 24h window."""
    try:
        from src.config import DB_PATH
        from src.utils.db import connect_db
        conn = connect_db(DB_PATH)
        try:
            row = conn.execute(
                "SELECT COUNT(*) FROM notifications_dedup WHERE sent_at >= ?",
                (since_iso,),
            ).fetchone()
            return row[0] if row else 0
        finally:
            conn.close()
    except Exception:
        logger.debug("[NOTIFICATIONS_HEALTH] _query_dedup_hits failed", exc_info=True)
        return 0


def _compute_health() -> dict:
    """Compute last-24h notification health aggregates."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    since_iso = cutoff.isoformat()

    rows = _query_sent_rows(since_iso)
    total = len(rows)
    failed = sum(1 for r in rows if r["status"] == "failed")
    ok_count = sum(1 for r in rows if r["status"] == "ok")

    if total > 0:
        success_rate = ok_count / total
    else:
        success_rate = 1.0

    dedup_hits = _query_dedup_hits(since_iso)

    oldest_unack_alert: str | None = None
    failed_rows = [r for r in rows if r["status"] == "failed"]
    if failed_rows:
        try:
            oldest_unack_alert = min(r["sent_at"] for r in failed_rows)
        except Exception:
            oldest_unack_alert = None

    return {
        "success_rate": round(success_rate, 4),
        "fail_count": failed,
        "dedup_hits": dedup_hits,
        "oldest_unack_alert": oldest_unack_alert,
    }


@router.get("/notifications/health")
def get_notifications_health() -> dict:
    """Return last-24h notification health aggregates."""
    return _compute_health()
