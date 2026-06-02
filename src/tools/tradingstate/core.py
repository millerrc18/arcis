"""TradingState Python API — single-shot snapshot of current trading-day state.

Called by: src/tools/tradingstate/__init__.py, src/tools/tradingstate/__main__.py (Task 7)
Calls: src.tools._db.pg_connect, src.tools._safety.{safe_op,prod_guard},
       src.tools._config.load_arcis_config, src.tools.tradingstate.queries
Owns tables: none (read-only: shadow_trades, recommendations, audit_reports, schedule_metrics)
Config keys: paths.db_canonical (SQLite fallback path)
Tests: tests/tools/test_tradingstate_integration.py
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

import psycopg2
import psycopg2.errors

logger = logging.getLogger(__name__)

from src.tools._config import load_arcis_config
from src.tools._db import DBHelperError
from src.utils.db import DBError, DBOperationalError
from src.tools._safety import prod_guard, safe_op
from src.tools.tradingstate.queries import (
    GPU_METRICS_PG,
    GPU_METRICS_SQLITE,
    OPEN_POSITIONS_PG,
    OPEN_POSITIONS_SQLITE,
    RECENT_AUDIT_PG,
    RECENT_AUDIT_SQLITE,
)

_STALE_THRESHOLD = timedelta(hours=36)

# audit_reports.created_at is written by the auditor as
# datetime.now(America/New_York).isoformat() (registry type TEXT). When a NAIVE
# value reaches us (a naive 'timestamp' PG column, or an ISO string without an
# offset), it represents ET wall-clock — interpret it in ET, NOT UTC, or during
# EDT a fresh verdict reads ~4h old -> false stale (governor-verdict-freshness).
_AUDIT_TZ = ZoneInfo("America/New_York")

# Connection-level failures that trigger SQLite fallback.
_PG_CONNECT_ERRORS = (psycopg2.OperationalError, DBHelperError)


class TradingStateError(RuntimeError):
    """Raised when both PG and SQLite backends are unavailable."""


def _build_audit_dict(audit_row: Optional[dict]) -> Optional[dict]:
    """Convert audit_reports row → output dict with stale flag computed against UTC now."""
    if audit_row is None:
        return None

    created_at = audit_row["created_at"]

    # psycopg2 returns timezone-aware datetime for TIMESTAMPTZ; SQLite returns str.
    # If the SQLite-stored string is not ISO-parseable (corrupt or hand-edited
    # row), we MUST NOT silently substitute datetime.now() (which would yield
    # stale=False and make the operator see "fresh audit" when the row is
    # actually broken — fail-quiet pattern called out in
    # feedback_strict_rigor_no_handwave). Instead: log a WARNING and treat as
    # stale, so the operator sees "stale=True" which prompts them to inspect.
    if isinstance(created_at, str):
        try:
            created_at_dt = datetime.fromisoformat(created_at)
        except ValueError:
            logger.warning(
                "tradingstate: unparseable audit_reports.created_at=%r "
                "(audit_id=%s) — treating as stale to surface corruption to operator",
                created_at,
                audit_row.get("audit_id"),
            )
            return {
                "audit_id": audit_row["audit_id"],
                "created_at": created_at,
                "overall_assessment": audit_row["overall_assessment"],
                "stale": True,
            }
        if created_at_dt.tzinfo is None:
            created_at_dt = created_at_dt.replace(tzinfo=_AUDIT_TZ)
    else:
        created_at_dt = created_at
        if created_at_dt.tzinfo is None:
            created_at_dt = created_at_dt.replace(tzinfo=_AUDIT_TZ)

    stale = (datetime.now(timezone.utc) - created_at_dt) > _STALE_THRESHOLD

    return {
        "audit_id": audit_row["audit_id"],
        "created_at": created_at,
        "overall_assessment": audit_row["overall_assessment"],
        "stale": stale,
    }


def _build_gpu_health(metrics_rows: list) -> dict:
    """Pivot schedule_metrics rows → gpu_health dict.

    Missing rows yield None — None means 'not yet measured'; False means 'measured failing'.
    """
    metrics = {row["metric_name"]: row["metric_value"] for row in metrics_rows}
    ollama_ok = bool(metrics["gpu_health_ollama_ok"]) if "gpu_health_ollama_ok" in metrics else None
    training_ok = (
        bool(metrics["gpu_health_training_ok"]) if "gpu_health_training_ok" in metrics else None
    )
    return {
        "ollama_ok": ollama_ok,
        "training_ok": training_ok,
        "metric_date": date.today().isoformat(),
    }


def _pg_snapshot(dsn: str) -> tuple:
    """Execute all 3 queries inside a single REPEATABLE READ connection (DA2 snapshot consistency).

    Returns (positions, audit_row, metrics_rows, errors) where errors is a dict of
    structured error envelopes for any field whose table was missing (UndefinedTable).
    Any other psycopg2 error is re-raised unchanged.
    """
    from src.tools._db import pg_connect

    errors: dict = {}
    positions = None
    audit_row = None
    metrics_rows = []

    with pg_connect(dsn, read_only=True, isolation_level="REPEATABLE READ") as (conn, cur):
        try:
            cur.execute(OPEN_POSITIONS_PG)
            positions = [dict(row) for row in cur.fetchall()]
        except psycopg2.errors.UndefinedTable as exc:
            errors["open_positions"] = {
                "error_type": type(exc).__name__,
                "error_message": str(exc).strip(),
                "table_name": "shadow_trades",
            }
            conn.rollback()

        try:
            cur.execute(RECENT_AUDIT_PG)
            audit_row_raw = cur.fetchone()
            audit_row = dict(audit_row_raw) if audit_row_raw is not None else None
        except psycopg2.errors.UndefinedTable as exc:
            errors["most_recent_audit"] = {
                "error_type": type(exc).__name__,
                "error_message": str(exc).strip(),
                "table_name": "audit_reports",
            }
            conn.rollback()

        try:
            cur.execute(GPU_METRICS_PG)
            metrics_rows = [dict(row) for row in cur.fetchall()]
        except psycopg2.errors.UndefinedTable as exc:
            errors["gpu_health"] = {
                "error_type": type(exc).__name__,
                "error_message": str(exc).strip(),
                "table_name": "schedule_metrics",
            }
            conn.rollback()

    return positions, audit_row, metrics_rows, errors


def _sqlite_snapshot(sqlite_path: Path) -> tuple:
    """Execute all 3 queries against SQLite (snapshot-isolation via SQLite MVCC).

    Returns (positions, audit_row, metrics_rows, errors) where errors is a dict of
    structured error envelopes for any field whose table was missing (no such table).
    Other OperationalError types are re-raised unchanged.
    """
    errors: dict = {}
    positions = None
    audit_row = None
    metrics_rows = []

    with sqlite3.connect(str(sqlite_path), timeout=5) as sconn:
        sconn.row_factory = sqlite3.Row
        cur = sconn.cursor()

        try:
            cur.execute(OPEN_POSITIONS_SQLITE)
            positions = [dict(r) for r in cur.fetchall()]
        except DBOperationalError as exc:
            if "no such table" in str(exc).lower():
                errors["open_positions"] = {
                    "error_type": type(exc).__name__,
                    "error_message": str(exc),
                    "table_name": "shadow_trades",
                }
            else:
                raise

        try:
            cur.execute(RECENT_AUDIT_SQLITE)
            audit_raw = cur.fetchone()
            audit_row = dict(audit_raw) if audit_raw is not None else None
        except DBOperationalError as exc:
            if "no such table" in str(exc).lower():
                errors["most_recent_audit"] = {
                    "error_type": type(exc).__name__,
                    "error_message": str(exc),
                    "table_name": "audit_reports",
                }
            else:
                raise

        try:
            cur.execute(GPU_METRICS_SQLITE)
            metrics_rows = [dict(r) for r in cur.fetchall()]
        except DBOperationalError as exc:
            if "no such table" in str(exc).lower():
                errors["gpu_health"] = {
                    "error_type": type(exc).__name__,
                    "error_message": str(exc),
                    "table_name": "schedule_metrics",
                }
            else:
                raise

    return positions, audit_row, metrics_rows, errors


@safe_op(name="tradingstate", mutates=False)
@prod_guard(dsn_param="dsn")
def state(
    *,
    dsn: Optional[str] = None,
    sqlite_path: Optional[Path] = None,
) -> dict:
    """Return a single-shot snapshot of current trading-day state.

    Returns:
        {
          'as_of_et': ISO-8601 timestamp (US/Eastern),
          'open_positions': [{'ticker','trade_id','source','status','entry_price',
                              'entry_time','thesis_text','quarantined'}, ...],
          'most_recent_audit': {'audit_id','created_at','overall_assessment','stale': bool} | None,
          'gpu_health': {'ollama_ok': bool|None, 'training_ok': bool|None, 'metric_date': YYYY-MM-DD},
          'data_source': 'pg' | 'sqlite_fallback',
        }

    Raises:
        TradingStateError: when both PG and SQLite are unavailable.
        ProdGuardError: when dsn matches a production signature (inner @prod_guard).
    """
    resolved_dsn = dsn
    if resolved_dsn is None:
        cfg = load_arcis_config()
        resolved_dsn = cfg.pg.test_dsn

    snapshot_errors: dict = {}

    try:
        positions, audit_row, metrics_rows, snapshot_errors = _pg_snapshot(resolved_dsn)
        data_source = "pg"
    except _PG_CONNECT_ERRORS:
        try:
            cfg = load_arcis_config()
            sqlite_path_resolved = sqlite_path if sqlite_path is not None else cfg.paths.db_canonical
            positions, audit_row, metrics_rows, snapshot_errors = _sqlite_snapshot(
                sqlite_path_resolved
            )
            data_source = "sqlite_fallback"
        except (*DBError, FileNotFoundError, OSError) as sqlite_exc:
            raise TradingStateError(
                f"both PG and SQLite unavailable: {sqlite_exc}"
            ) from sqlite_exc

    as_of_et = datetime.now(ZoneInfo("US/Eastern")).isoformat()

    result = {
        "as_of_et": as_of_et,
        "open_positions": positions,
        "most_recent_audit": _build_audit_dict(audit_row),
        "gpu_health": _build_gpu_health(metrics_rows),
        "data_source": data_source,
    }
    if snapshot_errors:
        result["errors"] = snapshot_errors
    return result
