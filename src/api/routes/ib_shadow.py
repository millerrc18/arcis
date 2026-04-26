"""Local API routes for IB shadow mode comparison data.

Called by: api.app
Calls: src.utils.db.connect_db
Owns tables: none (reads ib_shadow_log)
Config keys: none
Tests: tests/api/test_route_parity.py

Endpoints:
    GET /ib-shadow/summary  - Shadow mode KPI summary (rates, counts)
    GET /ib-shadow/log      - Paginated shadow log entries
    GET /ib-shadow/health   - Shadow mode status
"""

import logging
import sqlite3
from contextlib import closing

from fastapi import APIRouter

from src.config import DB_PATH
from src.utils.db import connect_db

router = APIRouter(tags=["ib_shadow"])
logger = logging.getLogger(__name__)


@router.get("/ib-shadow/summary")
def ib_shadow_summary():
    try:
        # PR #690 B4: closing() guarantees conn.close() — sqlite3 __exit__ only
        # commits/rolls back, it does not release the file handle.
        with closing(connect_db(DB_PATH)) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT COUNT(*) as total, "
                "SUM(CASE WHEN ib_connected = 1 THEN 1 ELSE 0 END) as connected, "
                "SUM(CASE WHEN ib_contract_valid = 1 THEN 1 ELSE 0 END) as valid, "
                "SUM(CASE WHEN ib_would_accept = 1 THEN 1 ELSE 0 END) as accepted, "
                "SUM(CASE WHEN ib_error IS NOT NULL THEN 1 ELSE 0 END) as errors, "
                "MAX(created_at) as last_at "
                "FROM ib_shadow_log"
            ).fetchone()
        if not row or not row["total"]:
            return {
                "total_shadows": 0,
                "ib_connected_pct": 0,
                "ib_contract_valid_pct": 0,
                "ib_would_accept_pct": 0,
                "last_shadow_at": None,
                "errors": 0,
                "shadow_mode_enabled": False,
            }
        total = row["total"]
        return {
            "total_shadows": total,
            "ib_connected_pct": round((row["connected"] or 0) / total * 100, 1),
            "ib_contract_valid_pct": round((row["valid"] or 0) / total * 100, 1),
            "ib_would_accept_pct": round((row["accepted"] or 0) / total * 100, 1),
            "last_shadow_at": row["last_at"],
            "errors": row["errors"] or 0,
            "shadow_mode_enabled": True,
        }
    except Exception as exc:
        logger.error("[API] ib-shadow summary failed: %s", exc)
        return {"total_shadows": 0, "error": str(exc)}


@router.get("/ib-shadow/log")
def ib_shadow_log(limit: int = 50):
    try:
        # PR #690 B4: closing() guarantees conn.close() — sqlite3 __exit__ only
        # commits/rolls back, it does not release the file handle.
        with closing(connect_db(DB_PATH)) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT shadow_id, created_at, ticker, quantity, entry_price, "
                "stop_price, target_price, ib_connected, ib_contract_valid, "
                "ib_buying_power, ib_would_accept, ib_error, alpaca_fill_price "
                "FROM ib_shadow_log ORDER BY created_at DESC LIMIT ?",
                (min(limit, 200),),
            ).fetchall()
            total_row = conn.execute(
                "SELECT COUNT(*) as total FROM ib_shadow_log"
            ).fetchone()
        return {
            "entries": [dict(r) for r in rows],
            "total": total_row["total"] if total_row else 0,
        }
    except Exception as exc:
        logger.error("[API] ib-shadow log failed: %s", exc)
        return {"entries": [], "total": 0, "error": str(exc)}


@router.get("/ib-shadow/health")
def ib_shadow_health():
    try:
        # PR #690 B4: closing() guarantees conn.close() — sqlite3 __exit__ only
        # commits/rolls back, it does not release the file handle.
        with closing(connect_db(DB_PATH)) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT COUNT(*) as total FROM ib_shadow_log"
            ).fetchone()
        has_data = (row["total"] or 0) > 0 if row else False
        return {
            "shadow_mode_enabled": has_data,
            "total_shadows": row["total"] if row else 0,
        }
    except Exception as exc:
        logger.error("[API] ib-shadow health failed: %s", exc)
        return {"shadow_mode_enabled": False, "error": str(exc)}
