"""Shared freshness-proxy health check for collector SYSTEMs.

`table_freshness_health` mirrors the proxy pattern in
`src.shadow_trading.reconcile_state._most_recent_reconcile_touch`: it reads
`MAX(ts_col)` from a collector's owned table and maps the result to a
`{status, detail, last_updated_at?}` dict. All DB dependencies are lazy-
imported inside the function so the registration host stays import-light,
and every failure mode (missing DB, missing table) degrades to a status
dict rather than raising — the health-executes test runs in a bare,
unconfigured worktree.

`table`/`ts_col` are code-controlled constants supplied by the collector
metadata table, so the f-string SELECT has no SQL-injection surface.

Called by: src.data_collection.capability_registration (health closures)
Calls: src.config.DB_PATH, src.utils.db.connect_db (lazy)
Owns tables: none (reads each collector's owned table)
Config keys: none
Tests: tests/data_collection/test_capability_health.py
"""
from __future__ import annotations

from typing import Any


def table_freshness_health(
    table: str,
    ts_col: str,
    stale_after_minutes: int,
    cadence_label: str,
) -> dict[str, Any]:
    """Report a collector's health from the freshness of its owned table.

    Args:
        table: Collector-owned table name (code-controlled constant).
        ts_col: Timestamp column to take ``MAX()`` of (code-controlled).
        stale_after_minutes: Age threshold; rows older than this are stale.
        cadence_label: Human-readable cadence used in detail strings.

    Returns:
        ``{"status": "ok"|"degraded"|"down", "detail": str}`` plus
        ``"last_updated_at"`` when a row exists. Never raises:

        - DB unconstructable / unconfigured -> ``down``
        - table missing / not migrated      -> ``down``
        - table empty                       -> ``degraded``
        - newest row older than threshold   -> ``degraded``
        - fresh row                         -> ``ok``
    """
    from src.config import DB_PATH
    from src.utils.db import DBOperationalError, connect_db

    try:
        conn = connect_db(DB_PATH)
    except Exception as exc:  # bare-env: DB path missing / unconstructable
        return {"status": "down", "detail": f"db unavailable: {exc}"}

    try:
        row = conn.execute(f"SELECT MAX({ts_col}) FROM {table}").fetchone()
    except DBOperationalError as exc:  # table missing / not migrated
        return {"status": "down", "detail": f"{table} unavailable: {exc}"}
    finally:
        conn.close()

    last = (row or (None,))[0]
    if last is None:
        return {
            "status": "degraded",
            "detail": f"{table} empty - collector has not run",
        }

    age_minutes = _age_minutes(last)
    if age_minutes is not None and age_minutes > stale_after_minutes:
        return {
            "status": "degraded",
            "detail": (
                f"{table} stale - newest row at {last} "
                f"({age_minutes:.0f} min old, {cadence_label})"
            ),
            "last_updated_at": last,
        }
    return {
        "status": "ok",
        "detail": f"last row at {last} ({cadence_label})",
        "last_updated_at": last,
    }


def _age_minutes(last: Any) -> float | None:
    """Minutes between ``last`` (ISO string or epoch) and now (UTC).

    Returns None when ``last`` cannot be parsed, so an unparseable value
    is treated as "present" (ok) rather than spuriously stale.
    """
    from datetime import datetime, timezone

    if isinstance(last, (int, float)):
        try:
            parsed = datetime.fromtimestamp(float(last), tz=timezone.utc)
        except (ValueError, OSError, OverflowError):
            return None
    else:
        text = str(last).strip().replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    delta = datetime.now(timezone.utc) - parsed
    return delta.total_seconds() / 60.0
