"""Cloud routes for diagnostic runs: POST to kick off, GET to list/inspect.

Endpoints (all under /api/diagnostic-runs):
    POST  /regime            - Submit a regime diagnostic run
    POST  /forensic          - Submit a forensic audit run
    GET   /                  - List runs (filterable by type, status)
    GET   /{run_id}          - Single run metadata (minus the heavy markdown)
    GET   /{run_id}/report   - Full markdown report text
    GET   /{run_id}/plots    - Base64 PNG plots for a run

Called by: api.cloud_app (via include_router)
Calls: sync.render_sync (indirectly via pending_commands insert)
Owns tables: diagnostic_runs, diagnostic_run_plots (API writes queued rows;
             running/completed transitions happen on the local machine
             and propagate back via render_sync)
Config keys: none
Tests: tests/api/test_diagnostic_routes.py
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel


class RegimePayload(BaseModel):
    exclude_quarantined: bool = False
    bootstrap_n: int | None = None


class ForensicPayload(BaseModel):
    pass


def _command_name_for(diagnostic_type: str) -> str:
    return {
        "regime": "run-regime-diagnostic",
        "forensic": "run-forensic-audit",
    }[diagnostic_type]


def create_router(runtime, verify_auth):
    """Build the /api/diagnostic-runs/* router."""
    router = APIRouter()

    def _check_dedup(diagnostic_type: str) -> None:
        """Raise 409 if a run of the same type is queued or running."""
        existing = runtime.query_one(
            "SELECT run_id, status FROM diagnostic_runs "
            "WHERE diagnostic_type = %s AND status IN ('queued', 'running') "
            "ORDER BY created_at DESC LIMIT 1",
            (diagnostic_type,),
        )
        if existing:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"A {diagnostic_type} diagnostic is already "
                    f"{existing['status']} (run_id={existing['run_id']})"
                ),
            )

    def _submit_diagnostic(
        diagnostic_type: str, payload: dict, triggered_by: str,
    ) -> dict:
        """Atomically insert both diagnostic_runs(queued) and pending_commands."""
        run_id = str(uuid.uuid4())
        now = datetime.now(runtime.et)
        expires_at = (now + timedelta(minutes=5)).isoformat()
        payload_with_run_id = {**payload, "run_id": run_id}
        payload_json = json.dumps(payload_with_run_id)

        try:
            with runtime.get_pg(readonly=False) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "INSERT INTO diagnostic_runs "
                        "(run_id, diagnostic_type, status, trigger_source, "
                        "triggered_by, payload_json, created_at, updated_at) "
                        "VALUES (%s, %s, 'queued', 'dashboard', %s, %s, %s, %s)",
                        (run_id, diagnostic_type, triggered_by,
                         payload_json, now.isoformat(), now.isoformat()),
                    )
                    cur.execute(
                        "INSERT INTO pending_commands "
                        "(command_id, command_type, command_name, payload_json, "
                        "status, priority, created_at, expires_at, created_by) "
                        "VALUES (%s, 'diagnostic', %s, %s, 'pending', 5, %s, %s, %s)",
                        (run_id, _command_name_for(diagnostic_type),
                         payload_json, now.isoformat(), expires_at,
                         triggered_by),
                    )
                    conn.commit()
        except HTTPException:
            raise
        except Exception as exc:
            runtime.logger.error("Diagnostic submission failed: %s", exc)
            raise HTTPException(
                status_code=503, detail="Database unavailable",
            )

        return {"run_id": run_id, "command_id": run_id, "status": "queued"}

    @router.post("/api/diagnostic-runs/regime",
                 dependencies=[Depends(verify_auth)], status_code=202)
    def submit_regime(body: RegimePayload):
        _check_dedup("regime")
        return _submit_diagnostic(
            "regime",
            body.model_dump(exclude_none=True),
            triggered_by="dashboard",
        )

    @router.post("/api/diagnostic-runs/forensic",
                 dependencies=[Depends(verify_auth)], status_code=202)
    def submit_forensic(body: ForensicPayload | None = None):
        _check_dedup("forensic")
        payload = body.model_dump(exclude_none=True) if body else {}
        return _submit_diagnostic(
            "forensic", payload, triggered_by="dashboard",
        )

    @router.get("/api/diagnostic-runs", dependencies=[Depends(verify_auth)])
    def list_runs(
        limit: int = 20,
        type: str | None = None,
        status: str | None = None,
    ):
        limit = min(max(limit, 1), 100)
        clauses: list[str] = ["1=1"]
        params: list = []
        if type and type != "all":
            clauses.append("diagnostic_type = %s")
            params.append(type)
        if status and status != "all":
            clauses.append("status = %s")
            params.append(status)
        params.append(limit)
        where = " AND ".join(clauses)
        runs = runtime.query(
            f"SELECT run_id, diagnostic_type, status, trigger_source, "
            f"triggered_by, cohort_n, started_at, completed_at, "
            f"summary_json, created_at FROM diagnostic_runs "
            f"WHERE {where} ORDER BY created_at DESC LIMIT %s",
            tuple(params),
        )
        return {"runs": runs, "count": len(runs)}

    @router.get("/api/diagnostic-runs/{run_id}",
                dependencies=[Depends(verify_auth)])
    def get_run(run_id: str):
        row = runtime.query_one(
            "SELECT * FROM diagnostic_runs WHERE run_id = %s", (run_id,),
        )
        if not row:
            raise HTTPException(status_code=404, detail="Run not found")
        # Strip the heavy field from the single-run response body; the
        # dashboard fetches the markdown separately via /report.
        if isinstance(row, dict):
            row.pop("report_markdown", None)
        return row

    @router.get("/api/diagnostic-runs/{run_id}/report",
                dependencies=[Depends(verify_auth)])
    def get_run_report(run_id: str):
        row = runtime.query_one(
            "SELECT report_markdown, status FROM diagnostic_runs "
            "WHERE run_id = %s",
            (run_id,),
        )
        if not row:
            raise HTTPException(status_code=404, detail="Run not found")
        if not row.get("report_markdown"):
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Run {run_id} has no report yet "
                    f"(status={row.get('status')})"
                ),
            )
        return Response(
            content=json.dumps({"markdown": row["report_markdown"]}),
            media_type="application/json",
            headers={"Cache-Control": "private, max-age=300"},
        )

    @router.get("/api/diagnostic-runs/{run_id}/plots",
                dependencies=[Depends(verify_auth)])
    def get_run_plots(run_id: str):
        row = runtime.query_one(
            "SELECT run_id FROM diagnostic_runs WHERE run_id = %s",
            (run_id,),
        )
        if not row:
            raise HTTPException(status_code=404, detail="Run not found")
        plots = runtime.query(
            "SELECT filename, content_b64, sort_order FROM diagnostic_run_plots "
            "WHERE run_id = %s ORDER BY sort_order",
            (run_id,),
        )
        return {"plots": plots, "count": len(plots)}

    return router
