"""Broker exceptions API — two read endpoints for operator observability.

Called by: src.api.app (router registered at /api/broker-exceptions)
Calls: src.utils.db.connect_db (local SQLite); psycopg2 (Render Postgres)
Owns tables: none (reads broker_exceptions, owned by B2.A / Round 5a)
Config keys: DATABASE_URL env var (Postgres routing)
Tests: tests/api/test_broker_exceptions_route.py

Closes audit finding G1: broker_exceptions rows written by log_and_persist
(src.shadow_trading.broker_exception_logger) were invisible to the operator
until this module added a read surface.

#87: Cloud Postgres equivalent. When DATABASE_URL is set (Render), reads via
psycopg2 from the synced broker_exceptions table; otherwise falls back to the
local SQLite DB. Mirrors the dual-mode pattern from walkforward.py /
platform.py.

Routes:
  GET /api/broker-exceptions/recent?limit=50&since_hours=24
  GET /api/broker-exceptions/summary
"""
from __future__ import annotations

import os
from contextlib import closing
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends

from src.utils.db import _scalar, connect_db

router = APIRouter()


# #632 — verify_auth placeholder overridden by cloud_app.py in production.
# No-op so routes load in test/dev mode; mirrors walkforward.py pattern.
def verify_auth() -> None:
    return None


def _read_rows(sql: str, params: tuple = ()) -> list[dict]:
    """Run a read-only query against Postgres (DATABASE_URL set) or SQLite.

    Mirrors src/api/cloud_routes/walkforward.py::_read_rows. SQL is written
    with `?` placeholders (SQLite style); they are rewritten to `%s` before
    being sent to psycopg2. This keeps a single SQL string in the route
    code while letting the same query run on either backend.
    """
    database_url = os.environ.get("DATABASE_URL", "")
    if database_url:
        import psycopg2
        import psycopg2.extras
        pg_sql = sql.replace("?", "%s")
        with psycopg2.connect(database_url) as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(pg_sql, params)
                rows = cur.fetchall()
                return [dict(r) for r in rows]
    # Local SQLite path — preserves the closing(...) connection-leak guard
    # from PR #690 B4 so the dashboard auto-refresh doesn't accumulate handles.
    with closing(connect_db()) as conn:
        cursor = conn.execute(sql, params)
        cols = [d[0] for d in cursor.description]
        return [dict(zip(cols, row)) for row in cursor.fetchall()]


def _read_scalar(sql: str, params: tuple = ()) -> int:
    """Read a single COUNT(*) value. Returns 0 when no row is returned."""
    rows = _read_rows(sql, params)
    if not rows:
        return 0
    first = rows[0]
    # COUNT(*) column name varies (`COUNT(*)`, `count`, etc.). Take the first
    # value regardless of key.
    return int(next(iter(first.values())))


def _fetch_recent_exceptions(
    conn,
    limit: int,
    since_hours: int,
) -> list[dict]:
    """Return up to *limit* broker_exceptions rows newer than *since_hours* ago.

    Rows are ordered newest-first. Returns plain dicts (not sqlite3.Row objects)
    so callers can serialise to JSON without extra conversion. Operates on a
    SQLite connection — used by the local fallback path and unit tests that
    pass an in-memory SQLite connection.
    """
    cutoff = (
        datetime.now(timezone.utc) - timedelta(hours=since_hours)
    ).isoformat()
    cursor = conn.execute(
        """
        SELECT id, ticker, operation, broker, timestamp, exception_class,
               exception_message, traceback, recoverable, created_at,
               correlation_id, retry_count, outcome
          FROM broker_exceptions
         WHERE timestamp >= ?
         ORDER BY timestamp DESC
         LIMIT ?
        """,
        (cutoff, limit),
    )
    cols = [d[0] for d in cursor.description]
    return [dict(zip(cols, row)) for row in cursor.fetchall()]


@router.get("/broker-exceptions/recent", dependencies=[Depends(verify_auth)])
def get_recent_exceptions(limit: int = 50, since_hours: int = 24) -> dict:
    """Return recent broker exception rows, newest-first.

    On Render (DATABASE_URL set) reads from Postgres via _read_rows.
    Otherwise opens a local SQLite connection through connect_db(); the
    closing(...) wrapper prevents the file-handle leak from PR #690 B4
    that the dashboard's 60s auto-refresh would otherwise compound.
    """
    if os.environ.get("DATABASE_URL", ""):
        cutoff = (
            datetime.now(timezone.utc) - timedelta(hours=since_hours)
        ).isoformat()
        rows = _read_rows(
            """
            SELECT id, ticker, operation, broker, timestamp, exception_class,
                   exception_message, traceback, recoverable, created_at,
                   correlation_id, retry_count, outcome
              FROM broker_exceptions
             WHERE timestamp >= ?
             ORDER BY timestamp DESC
             LIMIT ?
            """,
            (cutoff, limit),
        )
        return {
            "rows": rows,
            "count": len(rows),
            "limit": limit,
            "since_hours": since_hours,
        }
    with closing(connect_db()) as conn:
        rows = _fetch_recent_exceptions(conn, limit=limit, since_hours=since_hours)
    return {
        "rows": rows,
        "count": len(rows),
        "limit": limit,
        "since_hours": since_hours,
    }


@router.get("/broker-exceptions/summary", dependencies=[Depends(verify_auth)])
def get_summary() -> dict:
    """Return aggregate counts: by broker, by operation, 24h/7d totals, alert count.

    On Render (DATABASE_URL set) all five queries route through _read_rows /
    _read_scalar to Postgres. Otherwise falls back to a local SQLite
    connection wrapped in closing() to keep the PR #690 B4 leak-fix.
    """
    now = datetime.now(timezone.utc)
    cutoff_24h = (now - timedelta(hours=24)).isoformat()
    cutoff_7d = (now - timedelta(days=7)).isoformat()

    if os.environ.get("DATABASE_URL", ""):
        total_24h = _read_scalar(
            "SELECT COUNT(*) AS count FROM broker_exceptions WHERE timestamp >= ?",
            (cutoff_24h,),
        )
        total_7d = _read_scalar(
            "SELECT COUNT(*) AS count FROM broker_exceptions WHERE timestamp >= ?",
            (cutoff_7d,),
        )
        alert_count = _read_scalar(
            "SELECT COUNT(*) AS count FROM broker_exceptions "
            "WHERE outcome = 'alert_qty_mismatch'",
        )
        broker_rows = _read_rows(
            "SELECT broker, COUNT(*) AS count FROM broker_exceptions GROUP BY broker"
        )
        by_broker = {r["broker"]: r["count"] for r in broker_rows}
        op_rows = _read_rows(
            "SELECT operation, COUNT(*) AS count FROM broker_exceptions "
            "GROUP BY operation"
        )
        by_operation = {r["operation"]: r["count"] for r in op_rows}
        return {
            "total_24h": total_24h,
            "total_7d": total_7d,
            "alert_qty_mismatch_count": alert_count,
            "by_broker": by_broker,
            "by_operation": by_operation,
        }

    with closing(connect_db()) as conn:
        def _count(sql: str, params: tuple) -> int:
            row = conn.execute(sql, params).fetchone()
            return _scalar(row)

        total_24h = _count(
            "SELECT COUNT(*) FROM broker_exceptions WHERE timestamp >= ?",
            (cutoff_24h,),
        )
        total_7d = _count(
            "SELECT COUNT(*) FROM broker_exceptions WHERE timestamp >= ?",
            (cutoff_7d,),
        )
        alert_count = _count(
            "SELECT COUNT(*) FROM broker_exceptions WHERE outcome = 'alert_qty_mismatch'",
            (),
        )

        broker_rows = conn.execute(
            "SELECT broker, COUNT(*) FROM broker_exceptions GROUP BY broker",
        ).fetchall()
        by_broker = {r[0]: r[1] for r in broker_rows}

        op_rows = conn.execute(
            "SELECT operation, COUNT(*) FROM broker_exceptions GROUP BY operation",
        ).fetchall()
        by_operation = {r[0]: r[1] for r in op_rows}

    return {
        "total_24h": total_24h,
        "total_7d": total_7d,
        "alert_qty_mismatch_count": alert_count,
        "by_broker": by_broker,
        "by_operation": by_operation,
    }
