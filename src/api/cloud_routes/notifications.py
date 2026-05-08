"""Notifications health endpoint — /api/notifications/health.

Called by: src.api.app (local runtime), src.api.cloud_app (Render production)
Calls: src.config.DB_PATH, src.utils.db.connect_db (local), psycopg2 (Render)
Owns tables: none (reads notifications_sent, notifications_dedup)
Config keys: DATABASE_URL env var (Postgres routing)
Tests: tests/api/test_notifications_health.py

Returns last-24h notification aggregates: success_rate, fail_count,
dedup_hits, oldest_unack_alert.

DUAL-MODE (mirrors `src/api/cloud_routes/kpis_compute.py:_fetch_closed_trades`):
- Local dev (DATABASE_URL unset) → SQLite via connect_db()
- Render production (DATABASE_URL set) → Postgres via psycopg2

T15 revision (Option A — Sprint 4 plan §Task 15 follow-up): notifications_sent
and notifications_dedup have sync_to_postgres=True so they are mirrored to
Render Postgres by render_sync.py. The endpoint reads whichever backend is
authoritative for the current process (local SQLite vs Render Postgres),
keeping the cockpit health widget functional in both environments.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends

logger = logging.getLogger(__name__)

router = APIRouter()


def verify_auth() -> None:  # noqa: D401  # placeholder, overridden in cloud_app prod
    """Local placeholder; cloud_app.dependency_overrides[verify_auth] swaps in real auth."""
    return None


def _query_sent_rows_postgres(database_url: str, since_iso: str) -> list[dict]:
    """Read notifications_sent rows from Render Postgres."""
    import psycopg2
    import psycopg2.extras
    with psycopg2.connect(database_url) as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT status, error_msg, sent_at FROM notifications_sent"
                " WHERE sent_at >= %s AND status != 'heartbeat'",
                (since_iso,),
            )
            return list(cur.fetchall())


def _query_sent_rows_sqlite(since_iso: str) -> list[dict]:
    """Read notifications_sent rows from local SQLite."""
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


def _query_sent_rows(since_iso: str) -> list[dict]:
    """Return rows from notifications_sent newer than since_iso (dual-mode)."""
    database_url = os.environ.get("DATABASE_URL", "")
    try:
        if database_url:
            return _query_sent_rows_postgres(database_url, since_iso)
        return _query_sent_rows_sqlite(since_iso)
    except Exception:
        logger.debug("[NOTIFICATIONS_HEALTH] _query_sent_rows failed", exc_info=True)
        return []


def _query_dedup_hits_postgres(database_url: str, since_iso: str) -> int:
    """Count dedup rows in Render Postgres within the 24h window."""
    import psycopg2
    with psycopg2.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM notifications_dedup WHERE sent_at >= %s",
                (since_iso,),
            )
            row = cur.fetchone()
            return int(row[0]) if row else 0


def _query_dedup_hits_sqlite(since_iso: str) -> int:
    """Count dedup rows in local SQLite within the 24h window."""
    from src.config import DB_PATH
    from src.utils.db import connect_db
    conn = connect_db(DB_PATH)
    try:
        row = conn.execute(
            "SELECT COUNT(*) FROM notifications_dedup WHERE sent_at >= ?",
            (since_iso,),
        ).fetchone()
        return int(row[0]) if row else 0
    finally:
        conn.close()


def _query_dedup_hits(since_iso: str) -> int:
    """Count dedup rows that were active within the last 24h window (dual-mode)."""
    database_url = os.environ.get("DATABASE_URL", "")
    try:
        if database_url:
            return _query_dedup_hits_postgres(database_url, since_iso)
        return _query_dedup_hits_sqlite(since_iso)
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


@router.get("/notifications/health", dependencies=[Depends(verify_auth)])
def get_notifications_health() -> dict:
    """Return last-24h notification health aggregates."""
    return _compute_health()
