"""IB Gateway status API route (local mode).

Called by: api.app
Calls: config
Owns tables: none (reads ib_shadow_log)
Config keys: live_trading.ib.shadow_mode, live_trading.ib.paper_routing
Tests: none

Endpoints:
    GET /ib/status  - IB Gateway connection and shadow mode status
"""

import datetime
import logging
import sqlite3

from fastapi import APIRouter

from src.config import DB_PATH, load_config
from src.utils.db import connect_db

router = APIRouter(tags=["ib"])
logger = logging.getLogger(__name__)


@router.get("/ib/status")
def ib_status():
    """Return IB Gateway status for the Health page card."""
    try:
        config = load_config()
        ib_cfg = config.get("live_trading", {}).get("ib", {})
        shadow_mode = ib_cfg.get("shadow_mode", False)
        paper_routing = ib_cfg.get("paper_routing", False)

        conn = connect_db(DB_PATH)
        conn.row_factory = sqlite3.Row
        try:
            # Overall shadow log stats
            row = conn.execute(
                "SELECT COUNT(*) as total, "
                "SUM(CASE WHEN ib_connected = 1 THEN 1 ELSE 0 END) as connected, "
                "SUM(CASE WHEN ib_error IS NOT NULL THEN 1 ELSE 0 END) as errors, "
                "MAX(created_at) as last_connection "
                "FROM ib_shadow_log"
            ).fetchone()

            total = row["total"] if row else 0
            connected_count = row["connected"] or 0 if row else 0
            errors = row["errors"] or 0 if row else 0
            last_connection = row["last_connection"] if row else None

            # Today's shadow log stats — `date(created_at)` is ANSI-standard
            # (works on both SQLite and Postgres); we compute today's date in
            # Python and bind it as a parameter, avoiding the SQLite-only
            # current-date literal that PG rejects (PG uses CURRENT_DATE).
            today_iso = datetime.date.today().isoformat()
            today_row = conn.execute(
                "SELECT COUNT(*) as total, "
                "SUM(CASE WHEN ib_connected = 1 THEN 1 ELSE 0 END) as connected "
                "FROM ib_shadow_log WHERE date(created_at) = ?",
                (today_iso,),
            ).fetchone()
            today_total = today_row["total"] if today_row else 0
            today_connected = today_row["connected"] or 0 if today_row else 0

            # IB paper trade count (trades routed to IB from shadow_trades).
            # Quarantined filter ensures compromised April-10-cascade rows and
            # any future data-quality quarantines don't inflate the count.
            ib_trade_row = conn.execute(
                "SELECT COUNT(*) as c FROM shadow_trades "
                "WHERE source = 'ib_paper' AND COALESCE(quarantined, 0) = 0"
            ).fetchone()
            ib_trade_count = ib_trade_row["c"] if ib_trade_row else 0

            # 30-day uptime percentage — compute the cutoff timestamp in
            # Python and bind it as a parameter, avoiding the SQLite-only
            # negative-offset datetime literal that PG rejects.
            cutoff_30d = (
                datetime.datetime.now() - datetime.timedelta(days=30)
            ).isoformat()
            month_row = conn.execute(
                "SELECT COUNT(*) as total, "
                "SUM(CASE WHEN ib_connected = 1 THEN 1 ELSE 0 END) as connected "
                "FROM ib_shadow_log "
                "WHERE created_at >= ?",
                (cutoff_30d,),
            ).fetchone()
            month_total = month_row["total"] if month_row else 0
            month_connected = month_row["connected"] or 0 if month_row else 0
            uptime_30d = round(month_connected / month_total * 100, 1) if month_total > 0 else None

            # Determine gateway connection status from most recent check
            latest_row = conn.execute(
                "SELECT ib_connected FROM ib_shadow_log "
                "ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
            gateway_connected = bool(latest_row["ib_connected"]) if latest_row else False

        finally:
            conn.close()

        return {
            "connected": gateway_connected,
            "shadow_mode": shadow_mode,
            "paper_routing": paper_routing,
            "ib_trade_count": ib_trade_count,
            "last_connection": last_connection,
            "uptime_30d": uptime_30d,
            "total_shadows": total,
            "today_shadows": today_total,
            "today_connected_pct": round(today_connected / today_total * 100, 1) if today_total > 0 else None,
            "errors": errors,
        }
    except Exception as exc:
        logger.error("[API] ib/status failed: %s", exc)
        return {
            "connected": False,
            "shadow_mode": False,
            "paper_routing": False,
            "ib_trade_count": 0,
            "last_connection": None,
            "uptime_30d": None,
            "total_shadows": 0,
            "today_shadows": 0,
            "today_connected_pct": None,
            "errors": 0,
            "error": str(exc),
        }
