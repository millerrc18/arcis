"""Graceful global PAUSE engine for the operator console (design D10).

Called by: src.scheduler.watch (scan gate), src.shadow_trading.executor
    (new-trade gate), console HTTP endpoints (T5 — not here)
Calls: src.utils.db.connect_db, src.utils.activity_logger.log_activity
Owns tables: console_pause_state (read + write path)
Config keys: none
Tests: tests/test_console_pause.py

GRACEFUL PAUSE — distinct from the risk governor's hard kill switch.

  Graceful pause BLOCKS new autonomous actions (scan/recommend/execute) while
  KEEPING positions, monitoring, and reconciliation RUNNING. The governor's
  kill switch (src/risk/governor.py) is a SEPARATE mechanism backed by a halt
  FILE; this engine is backed by the console_pause_state DB table and never
  touches the governor's halt file or logic.

State lives in the single-row ``console_pause_state`` table (id=1 always;
UPDATE in-place, never INSERT a second row). Every set/clear is audit-logged
to the activity_log via ``log_activity`` for the operator trail.

``is_paused()`` is the cheap boolean read used by the scan / executor gates —
a single-row SELECT.
"""

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from src.utils.activity_logger import SYSTEM_EVENT, log_activity
from src.utils.db import connect_db

logger = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")


def set_pause(reason: str, source: str) -> None:
    """Engage the graceful pause (upsert console_pause_state id=1, is_paused=1).

    Args:
        reason: Human-readable reason for the pause (operator trail).
        source: Origin of the pause request ('cli', 'api', 'dashboard', ...).

    Audit-logs the set via activity_log. Positions / monitoring / reconcile
    keep running — this only blocks NEW autonomous actions at their gates.
    """
    now_iso = datetime.now(ET).isoformat()
    with connect_db() as conn:
        conn.execute(
            """
            INSERT INTO console_pause_state
                (id, is_paused, paused_at, paused_by, reason,
                 resumed_at, updated_at)
            VALUES (1, 1, ?, ?, ?, NULL, ?)
            ON CONFLICT (id) DO UPDATE SET
                is_paused = 1,
                paused_at = EXCLUDED.paused_at,
                paused_by = EXCLUDED.paused_by,
                reason = EXCLUDED.reason,
                resumed_at = NULL,
                updated_at = EXCLUDED.updated_at
            """,
            (now_iso, source, reason, now_iso),
        )
    logger.warning("[PAUSE] Graceful pause ENGAGED by %s: %s", source, reason)
    log_activity(
        SYSTEM_EVENT,
        f"Graceful PAUSE engaged by {source}: {reason}",
        {"action": "pause_set", "source": source, "reason": reason},
    )


def clear_pause(source: str) -> None:
    """Clear the graceful pause (upsert console_pause_state id=1, is_paused=0).

    Args:
        source: Origin of the resume request ('cli', 'api', 'dashboard', ...).

    Audit-logs the clear via activity_log.
    """
    now_iso = datetime.now(ET).isoformat()
    with connect_db() as conn:
        conn.execute(
            """
            INSERT INTO console_pause_state
                (id, is_paused, paused_at, paused_by, reason,
                 resumed_at, updated_at)
            VALUES (1, 0, NULL, NULL, NULL, ?, ?)
            ON CONFLICT (id) DO UPDATE SET
                is_paused = 0,
                resumed_at = EXCLUDED.resumed_at,
                updated_at = EXCLUDED.updated_at
            """,
            (now_iso, now_iso),
        )
    logger.warning("[PAUSE] Graceful pause CLEARED by %s", source)
    log_activity(
        SYSTEM_EVENT,
        f"Graceful PAUSE cleared by {source}",
        {"action": "pause_clear", "source": source},
    )


def read_pause_state() -> dict:
    """Return the canonical pause state as a dict.

    Returns a dict with keys: is_paused (bool), paused_at, paused_by, reason,
    resumed_at, updated_at. When no row exists yet (never paused), returns the
    not-paused default with all timestamp/metadata fields None.
    """
    with connect_db() as conn:
        row = conn.execute(
            "SELECT is_paused, paused_at, paused_by, reason, "
            "resumed_at, updated_at "
            "FROM console_pause_state WHERE id = 1"
        ).fetchone()
    if row is None:
        return {
            "is_paused": False,
            "paused_at": None,
            "paused_by": None,
            "reason": None,
            "resumed_at": None,
            "updated_at": None,
        }
    return {
        "is_paused": bool(row["is_paused"]),
        "paused_at": row["paused_at"],
        "paused_by": row["paused_by"],
        "reason": row["reason"],
        "resumed_at": row["resumed_at"],
        "updated_at": row["updated_at"],
    }


def is_paused() -> bool:
    """Cheap boolean read of the graceful-pause state (single-row SELECT).

    Used by the scan / executor gates. Fail-CLOSED (operator decision
    2026-06-05): if the state row can't be READ at all (DB error, table
    missing), returns True so a paused desk can never silently RESUME
    autonomous trading on a transient DB glitch — the spec's "make divergence
    loud / never silent-green" principle (§1.3). Skipping a scan cycle is cheap
    and reversible; trading the operator paused is not. A loud WARNING is
    logged so the skip is visible, not silent.

    Note: a successfully-read EMPTY table (row is None — no pause ever set) is
    the legitimate not-paused default and returns False; only an actual read
    FAILURE fails closed.
    """
    try:
        with connect_db() as conn:
            row = conn.execute(
                "SELECT is_paused FROM console_pause_state WHERE id = 1"
            ).fetchone()
    except Exception as exc:
        logger.warning(
            "[PAUSE] is_paused read FAILED — failing CLOSED (treating as paused, "
            "skipping autonomous action this cycle): %s", exc
        )
        return True
    if row is None:
        return False
    return bool(row["is_paused"])
