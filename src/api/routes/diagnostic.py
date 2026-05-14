"""Local diagnostic_runs API routes.

Called by: api.app
Calls: src.utils.db.connect_db
Owns tables: none (reads from diagnostic_runs)
Config keys: none
Tests: none

Endpoints:
    GET /diagnostic-runs                       - List recent diagnostic runs
    GET /diagnostic-runs/{run_id}              - Get full row by id
    GET /diagnostic-runs/{run_id}/report       - Markdown report
    GET /diagnostic-runs/{run_id}/plots        - Plot images (base64)

Mirrors cloud_routes/diagnostics.py so the local FastAPI app + Cloudflare-
tunneled halcyonlab.app both serve these endpoints. The local app previously
returned 404 here because the cloud router was not mounted (read-from-PG
runtime was cloud_app-only). Post-Sprint-5 cutover the local DB IS Postgres
when ARCIS_PG_CUTOVER_ENABLED=1, so the connect_db wrapper transparently
routes queries to the right engine.
"""
import json
import logging
import sqlite3
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Response

from src.config import DB_PATH
from src.utils.db import connect_db

router = APIRouter(tags=["diagnostics"])
logger = logging.getLogger(__name__)


@router.get("/diagnostic-runs")
def list_diagnostic_runs(
    limit: int = Query(20, ge=1, le=100),
    type: Optional[str] = None,
    status: Optional[str] = None,
):
    """List recent diagnostic_runs ordered by created_at DESC."""
    clauses = ["1=1"]
    params: list = []
    if type and type != "all":
        clauses.append("diagnostic_type = ?")
        params.append(type)
    if status and status != "all":
        clauses.append("status = ?")
        params.append(status)
    params.append(limit)
    where = " AND ".join(clauses)
    try:
        conn = connect_db(DB_PATH)
        conn.row_factory = sqlite3.Row
        try:
            rows = [dict(r) for r in conn.execute(
                "SELECT run_id, diagnostic_type, status, trigger_source, "
                "triggered_by, cohort_n, started_at, completed_at, "
                "summary_json, created_at FROM diagnostic_runs "
                f"WHERE {where} ORDER BY created_at DESC LIMIT ?",
                tuple(params),
            ).fetchall()]
            return {"runs": rows, "count": len(rows)}
        finally:
            conn.close()
    except Exception as exc:
        logger.error("[API] list_diagnostic_runs failed: %s", exc)
        return {"runs": [], "count": 0, "error": str(exc)}


@router.get("/diagnostic-runs/{run_id}")
def get_diagnostic_run(run_id: str):
    """Fetch the full diagnostic_runs row, minus the heavy report_markdown column."""
    try:
        conn = connect_db(DB_PATH)
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute(
                "SELECT * FROM diagnostic_runs WHERE run_id = ?", (run_id,)
            ).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Run not found")
            payload = dict(row)
            payload.pop("report_markdown", None)
            return payload
        finally:
            conn.close()
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("[API] get_diagnostic_run failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/diagnostic-runs/{run_id}/report")
def get_diagnostic_run_report(run_id: str):
    """Return the markdown report for a completed diagnostic run."""
    try:
        conn = connect_db(DB_PATH)
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute(
                "SELECT report_markdown, status FROM diagnostic_runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Run not found")
            row_d = dict(row)
            if not row_d.get("report_markdown"):
                raise HTTPException(
                    status_code=409,
                    detail=f"Run {run_id} has no report yet (status={row_d.get('status')})",
                )
            return Response(
                content=json.dumps({"markdown": row_d["report_markdown"]}),
                media_type="application/json",
                headers={"Cache-Control": "private, max-age=300"},
            )
        finally:
            conn.close()
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("[API] get_diagnostic_run_report failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/diagnostic-runs/{run_id}/plots")
def get_diagnostic_run_plots(run_id: str):
    """Return base64-encoded plot images attached to the run."""
    try:
        conn = connect_db(DB_PATH)
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute(
                "SELECT run_id FROM diagnostic_runs WHERE run_id = ?", (run_id,)
            ).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Run not found")
            plots = [dict(r) for r in conn.execute(
                "SELECT filename, content_b64, sort_order FROM diagnostic_run_plots "
                "WHERE run_id = ? ORDER BY sort_order",
                (run_id,),
            ).fetchall()]
            return {"plots": plots, "count": len(plots)}
        finally:
            conn.close()
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("[API] get_diagnostic_run_plots failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))
