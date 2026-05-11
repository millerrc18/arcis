"""Maintenance utilities for the pending_commands queue.

Called by: src.api.cloud_routes.commands, src.api.routes.logs (admin endpoints)
Calls: src.utils.db
Owns tables: pending_commands (writer for status='expired' transitions)
Config keys: ARCIS_PG_CUTOVER_ENABLED (indirectly via connect_db routing)
Tests: see expire_stale_commands tests in tests/test_pending_commands_maintenance.py

Relocated from src/sync/render_sync.py during SP5 §J5/§J6 Phase 3-revised T7+
fix-up. render_sync.py was deleted as part of the one-DB cutover; this
utility was the only function in render_sync still in active use post-cutover.
"""

from __future__ import annotations

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from src.utils.db import connect_db

logger = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")


def expire_stale_commands(database_url: str = "") -> int:
    """Mark pending_commands rows whose expires_at has elapsed as 'expired'.

    Returns count of rows expired this cycle (0 is the steady-state).

    Post Phase 3-revised cutover: uses `connect_db()` which routes to PG when
    `ARCIS_PG_CUTOVER_ENABLED=1` is set on the NSSM service env, otherwise
    SQLite. The `database_url` argument is retained for backward compatibility
    with existing cloud_routes endpoint callers but is no longer consulted
    directly — the cutover gate is the canonical routing signal.
    """
    del database_url  # retained for caller-API compat; routing is via gate.
    now = datetime.now(ET).isoformat()
    try:
        with connect_db() as conn:
            cur = conn.execute(
                "UPDATE pending_commands SET status = 'expired' "
                "WHERE status = 'pending' AND expires_at IS NOT NULL "
                "AND expires_at < ?",
                (now,),
            )
            count = cur.rowcount or 0
            conn.commit()
            if count > 0:
                logger.info("Expired %d stale pending_commands rows", count)
            return count
    except Exception as exc:
        logger.error(
            "expire_stale_commands failed: %s", exc,
            extra={"ctx": {"event": "maintenance_error",
                           "table": "pending_commands",
                           "error": str(exc)}},
        )
        return 0
