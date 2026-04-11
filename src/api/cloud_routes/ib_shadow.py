"""Cloud API routes for IB shadow mode comparison data.

Called by: api.cloud_app
Calls: none
Owns tables: none (reads ib_shadow_log)
Config keys: none
Tests: none

Endpoints:
    GET /api/ib-shadow/summary  - Shadow mode KPI summary (rates, counts)
    GET /api/ib-shadow/log      - Paginated shadow log entries
    GET /api/ib-shadow/health   - Shadow mode status
"""

from fastapi import APIRouter, Depends


def create_router(runtime, verify_auth):
    """Build the IB shadow mode router."""
    router = APIRouter()

    @router.get("/api/ib-shadow/summary", dependencies=[Depends(verify_auth)])
    def ib_shadow_summary():
        try:
            row = runtime.query_one(
                "SELECT COUNT(*) as total, "
                "SUM(CASE WHEN ib_connected = 1 THEN 1 ELSE 0 END) as connected, "
                "SUM(CASE WHEN ib_contract_valid = 1 THEN 1 ELSE 0 END) as valid, "
                "SUM(CASE WHEN ib_would_accept = 1 THEN 1 ELSE 0 END) as accepted, "
                "SUM(CASE WHEN ib_error IS NOT NULL THEN 1 ELSE 0 END) as errors, "
                "MAX(created_at) as last_at "
                "FROM ib_shadow_log"
            )
            if not row or not row.get("total"):
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
            runtime.logger.error("[API] ib-shadow summary failed: %s", exc)
            return {"total_shadows": 0, "error": str(exc)}

    @router.get("/api/ib-shadow/log", dependencies=[Depends(verify_auth)])
    def ib_shadow_log(limit: int = 50):
        try:
            entries = runtime.query(
                "SELECT shadow_id, created_at, ticker, quantity, entry_price, "
                "stop_price, target_price, ib_connected, ib_contract_valid, "
                "ib_buying_power, ib_would_accept, ib_error, alpaca_fill_price "
                "FROM ib_shadow_log ORDER BY created_at DESC LIMIT %s",
                (min(limit, 200),),
            )
            total_row = runtime.query_one(
                "SELECT COUNT(*) as total FROM ib_shadow_log"
            )
            return {
                "entries": entries,
                "total": total_row["total"] if total_row else 0,
            }
        except Exception as exc:
            runtime.logger.error("[API] ib-shadow log failed: %s", exc)
            return {"entries": [], "total": 0, "error": str(exc)}

    @router.get("/api/ib-shadow/health", dependencies=[Depends(verify_auth)])
    def ib_shadow_health():
        try:
            # Cloud API doesn't have local config access. Infer shadow mode
            # status from whether any shadow log entries exist.
            row = runtime.query_one(
                "SELECT COUNT(*) as total FROM ib_shadow_log"
            )
            has_data = (row["total"] or 0) > 0 if row else False
            return {
                "shadow_mode_enabled": has_data,
                "total_shadows": row["total"] if row else 0,
            }
        except Exception as exc:
            runtime.logger.error("[API] ib-shadow health failed: %s", exc)
            return {"shadow_mode_enabled": False, "error": str(exc)}

    return router
