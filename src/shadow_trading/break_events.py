"""Break-event writer for reconciliation_breaks table.

Called by: src.shadow_trading.reconcile (at detection sites, before backfill)
Calls: src.utils.db.connect_db
Owns tables: reconciliation_breaks (write path)
Config keys: none
Tests: tests/api/test_break_events.py

Design law #9 — break evidence must survive auto-backfill of shadow_trades.
record_break() is called at DETECTION time, before the reconciler's auto-heal
logic runs, so the row is written even when the subsequent backfill/repair
erases the original discrepancy from shadow_trades.

Emission is best-effort / non-blocking: any exception inside record_break()
is caught, logged, and swallowed — a write failure NEVER propagates into the
reconciliation flow.

get_break_events() is the read helper for T6 (the HTTP endpoint) and tests.
Rows are ordered newest-first; each row contains created_at/detected_at so
callers can derive age without additional computation.
"""

import logging
from datetime import datetime, timezone

from src.utils.db import connect_db

logger = logging.getLogger(__name__)


def record_break(
    break_type: str,
    symbol: str,
    magnitude: float | None = None,
    desk: str | None = None,
    source: str | None = None,
    detail: str | None = None,
) -> None:
    """Insert one row into reconciliation_breaks.

    Best-effort: any exception is caught and logged, never re-raised.
    Called at the DETECTION point in the reconciler, before backfill/repair.

    Args:
        break_type: Category of break — 'orphan', 'stale', 'qty_mismatch',
            'marked_closed', or any future break category.
        symbol: Ticker symbol of the affected position.
        magnitude: Dollar or share magnitude of the break (optional).
        desk: Trading desk ('swing', 'research_*', etc.) if known.
        source: 'paper' or 'live' if known.
        detail: Human-readable detail string for audit trail (optional).
    """
    try:
        now_iso = datetime.now(timezone.utc).isoformat()
        with connect_db() as conn:
            conn.execute(
                """
                INSERT INTO reconciliation_breaks
                    (created_at, break_type, symbol, magnitude,
                     desk, source, detail, detected_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (now_iso, break_type, symbol, magnitude,
                 desk, source, detail, now_iso),
            )
    except Exception as exc:
        logger.warning(
            "[BREAK-EVENTS] record_break failed (best-effort, non-blocking): "
            "break_type=%s symbol=%s — %s",
            break_type, symbol, exc,
        )


def get_break_events(
    since: str | None = None,
    limit: int = 200,
) -> list[dict]:
    """Return retained break events ordered newest-first.

    Args:
        since: ISO timestamp string. When provided, only rows with
            created_at > since are returned. Supports age-over-time
            queries for the break-rate chart (design law #9).
        limit: Maximum number of rows to return (default 200).

    Returns:
        List of dicts with all reconciliation_breaks columns:
        id, created_at, break_type, symbol, magnitude, desk,
        source, detail, detected_at. Ordered newest-first.
        Age is derivable as ``now - created_at`` or ``now - detected_at``.
    """
    if since is not None:
        sql = (
            "SELECT id, created_at, break_type, symbol, magnitude, "
            "desk, source, detail, detected_at "
            "FROM reconciliation_breaks "
            "WHERE created_at > ? "
            "ORDER BY created_at DESC, id DESC "
            "LIMIT ?"
        )
        params = (since, limit)
    else:
        sql = (
            "SELECT id, created_at, break_type, symbol, magnitude, "
            "desk, source, detail, detected_at "
            "FROM reconciliation_breaks "
            "ORDER BY created_at DESC, id DESC "
            "LIMIT ?"
        )
        params = (limit,)

    with connect_db() as conn:
        rows = conn.execute(sql, params).fetchall()

    return [dict(r) for r in rows]
