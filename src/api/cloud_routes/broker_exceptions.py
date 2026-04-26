"""Broker exceptions API — two read endpoints for operator observability.

Called by: src.api.app (router registered at /api/broker-exceptions)
Calls: src.utils.db.connect_db
Owns tables: none (reads broker_exceptions, owned by B2.A / Round 5a)
Config keys: none
Tests: tests/api/test_broker_exceptions_route.py

Closes audit finding G1: broker_exceptions rows written by log_and_persist
(src.shadow_trading.broker_exception_logger) were invisible to the operator
until this module added a read surface.

Routes:
  GET /api/broker-exceptions/recent?limit=50&since_hours=24
  GET /api/broker-exceptions/summary
"""
from __future__ import annotations

from contextlib import closing
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends

from src.utils.db import connect_db

router = APIRouter()


# #632 — verify_auth placeholder overridden by cloud_app.py in production.
# No-op so routes load in test/dev mode; mirrors walkforward.py pattern.
def verify_auth() -> None:
    return None


def _fetch_recent_exceptions(
    conn,
    limit: int,
    since_hours: int,
) -> list[dict]:
    """Return up to *limit* broker_exceptions rows newer than *since_hours* ago.

    Rows are ordered newest-first. Returns plain dicts (not sqlite3.Row objects)
    so callers can serialise to JSON without extra conversion.
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

    Connection lifecycle: `connect_db()` returns a raw sqlite3.Connection
    (see src/utils/db.py:35); the caller is responsible for closing it.
    `closing(...)` guarantees `.close()` even if `_fetch_recent_exceptions`
    raises — important because the dashboard auto-refreshes this endpoint
    every 60s and a leaked file handle per call would accumulate quickly.
    """
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

    Connection lifecycle: same rationale as get_recent_exceptions — wrap in
    `closing(connect_db())` so the sqlite3.Connection always gets closed,
    including on exceptions raised from inside the aggregation queries.
    """
    now = datetime.now(timezone.utc)
    cutoff_24h = (now - timedelta(hours=24)).isoformat()
    cutoff_7d = (now - timedelta(days=7)).isoformat()

    with closing(connect_db()) as conn:
        def _count(sql: str, params: tuple) -> int:
            return conn.execute(sql, params).fetchone()[0]

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
