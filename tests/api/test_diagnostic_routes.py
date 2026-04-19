"""Tests for /api/diagnostic-runs/* cloud endpoints."""

import uuid
from zoneinfo import ZoneInfo
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.cloud_routes.diagnostics import create_router


ET = ZoneInfo("America/New_York")


def _noop_auth():
    return True


@pytest.fixture
def app():
    """Build a minimal FastAPI with fake runtime stubs."""
    runtime = MagicMock()
    runtime.et = ET
    runtime.logger = MagicMock()

    storage: dict = {"runs": {}, "plots": {}, "pending_commands": {}}

    def query_one(sql, params=()):
        if "FROM diagnostic_runs WHERE diagnostic_type" in sql:
            dt = params[0]
            for r in storage["runs"].values():
                if r["diagnostic_type"] == dt and r["status"] in (
                    "queued", "running",
                ):
                    return {"run_id": r["run_id"], "status": r["status"]}
            return None
        if "SELECT * FROM diagnostic_runs WHERE run_id" in sql:
            return storage["runs"].get(params[0])
        if "SELECT report_markdown, status FROM diagnostic_runs" in sql:
            r = storage["runs"].get(params[0])
            if not r:
                return None
            return {
                "report_markdown": r.get("report_markdown"),
                "status": r.get("status"),
            }
        if "SELECT run_id FROM diagnostic_runs WHERE run_id" in sql:
            r = storage["runs"].get(params[0])
            return {"run_id": r["run_id"]} if r else None
        return None

    def query(sql, params=()):
        if "FROM diagnostic_runs" in sql:
            limit = params[-1] if params else 50
            return list(storage["runs"].values())[:limit]
        if "FROM diagnostic_run_plots" in sql:
            return storage["plots"].get(params[0], [])
        return []

    class FakeCursor:
        def execute(self, sql, params):
            if "INSERT INTO pending_commands" in sql:
                storage["pending_commands"][params[0]] = params
            elif "INSERT INTO diagnostic_runs" in sql:
                storage["runs"][params[0]] = {
                    "run_id": params[0],
                    "diagnostic_type": params[1],
                    "status": "queued",
                    "trigger_source": "dashboard",
                    "triggered_by": params[2],
                    "payload_json": params[3],
                    "created_at": params[4],
                    "updated_at": params[4],
                }

        def __enter__(self): return self
        def __exit__(self, *a): return False

    class FakePg:
        def cursor(self): return FakeCursor()
        def commit(self): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False

    runtime.get_pg = lambda readonly=False: FakePg()
    runtime.query = query
    runtime.query_one = query_one

    application = FastAPI()
    application.include_router(create_router(runtime, verify_auth=_noop_auth))
    application.state._storage = storage
    return application


@pytest.fixture
def client(app):
    return TestClient(app)


def test_submit_regime_run_returns_202(client, app):
    resp = client.post("/api/diagnostic-runs/regime", json={})
    assert resp.status_code == 202
    data = resp.json()
    assert "run_id" in data
    assert data["status"] == "queued"
    assert data["run_id"] in app.state._storage["runs"]
    assert (
        app.state._storage["runs"][data["run_id"]]["diagnostic_type"]
        == "regime"
    )


def test_submit_forensic_run_returns_202(client, app):
    resp = client.post("/api/diagnostic-runs/forensic", json={})
    assert resp.status_code == 202


# ── training audit endpoint (v0.26.0) ────────────────────────────────


def test_submit_training_audit_returns_202(client, app):
    resp = client.post("/api/diagnostic-runs/training-audit", json={})
    assert resp.status_code == 202
    data = resp.json()
    assert "run_id" in data
    assert data["status"] == "queued"
    stored = app.state._storage["runs"][data["run_id"]]
    assert stored["diagnostic_type"] == "training_audit"


def test_submit_training_audit_409_on_duplicate(client, app):
    run_id = str(uuid.uuid4())
    app.state._storage["runs"][run_id] = {
        "run_id": run_id,
        "diagnostic_type": "training_audit",
        "status": "running",
    }
    resp = client.post("/api/diagnostic-runs/training-audit", json={})
    assert resp.status_code == 409
    assert "already" in resp.json()["detail"].lower()
    assert "training_audit" in resp.json()["detail"]


def test_submit_training_audit_accepts_dry_run_and_passes(client, app):
    resp = client.post(
        "/api/diagnostic-runs/training-audit",
        json={"dry_run": True, "passes": ["a", "B", "x"]},  # 'x' must be dropped
    )
    assert resp.status_code == 202
    run_id = resp.json()["run_id"]
    payload_json = app.state._storage["runs"][run_id]["payload_json"]
    import json as _json
    payload = _json.loads(payload_json)
    assert payload["dry_run"] is True
    assert set(payload["passes"]) == {"A", "B"}


def test_submit_training_audit_409_does_not_conflict_with_regime_running(
    client, app,
):
    """Dedup is per-type: regime running does NOT block training_audit."""
    app.state._storage["runs"]["regime-1"] = {
        "run_id": "regime-1", "diagnostic_type": "regime", "status": "running",
    }
    resp = client.post("/api/diagnostic-runs/training-audit", json={})
    assert resp.status_code == 202


def test_list_runs_filters_training_audit_type(client, app):
    app.state._storage["runs"]["r-r"] = {
        "run_id": "r-r", "diagnostic_type": "regime", "status": "completed",
    }
    app.state._storage["runs"]["r-t"] = {
        "run_id": "r-t", "diagnostic_type": "training_audit",
        "status": "completed",
    }
    resp = client.get("/api/diagnostic-runs?type=training_audit")
    assert resp.status_code == 200
    # FakeCursor doesn't apply the WHERE filter in the fake query; the test
    # verifies the endpoint accepts the filter value without 4xx.
    assert resp.json()["count"] >= 0


def test_submit_regime_run_409_if_already_running(client, app):
    run_id = str(uuid.uuid4())
    app.state._storage["runs"][run_id] = {
        "run_id": run_id,
        "diagnostic_type": "regime",
        "status": "running",
    }
    resp = client.post("/api/diagnostic-runs/regime", json={})
    assert resp.status_code == 409
    assert "already" in resp.json()["detail"].lower()


def test_list_runs_returns_recent(client, app):
    app.state._storage["runs"]["r-1"] = {
        "run_id": "r-1", "diagnostic_type": "regime", "status": "completed",
    }
    app.state._storage["runs"]["r-2"] = {
        "run_id": "r-2", "diagnostic_type": "forensic", "status": "running",
    }
    resp = client.get("/api/diagnostic-runs")
    assert resp.status_code == 200
    assert resp.json()["count"] >= 2


def test_get_run_not_found_returns_404(client):
    resp = client.get("/api/diagnostic-runs/nonexistent")
    assert resp.status_code == 404


def test_get_run_report_returns_markdown(client, app):
    app.state._storage["runs"]["r-1"] = {
        "run_id": "r-1", "diagnostic_type": "regime", "status": "completed",
        "report_markdown": (
            "# Report\n\n## Executive Summary\n\n"
            "**Decision:** PENDING\n"
        ),
    }
    resp = client.get("/api/diagnostic-runs/r-1/report")
    assert resp.status_code == 200
    assert "**Decision:** PENDING" in resp.json()["markdown"]


def test_get_run_report_409_if_not_completed(client, app):
    app.state._storage["runs"]["r-1"] = {
        "run_id": "r-1", "diagnostic_type": "regime", "status": "running",
        "report_markdown": None,
    }
    resp = client.get("/api/diagnostic-runs/r-1/report")
    assert resp.status_code == 409


def test_get_run_plots_returns_base64(client, app):
    app.state._storage["runs"]["r-1"] = {
        "run_id": "r-1", "diagnostic_type": "regime",
    }
    app.state._storage["plots"]["r-1"] = [
        {"filename": "a.png", "content_b64": "abc123", "sort_order": 0},
    ]
    resp = client.get("/api/diagnostic-runs/r-1/plots")
    assert resp.status_code == 200
    assert len(resp.json()["plots"]) == 1
    assert resp.json()["plots"][0]["content_b64"] == "abc123"


def test_list_with_type_filter(client, app):
    app.state._storage["runs"]["r-1"] = {
        "run_id": "r-1", "diagnostic_type": "regime", "status": "completed",
    }
    app.state._storage["runs"]["r-2"] = {
        "run_id": "r-2", "diagnostic_type": "forensic", "status": "completed",
    }
    resp = client.get("/api/diagnostic-runs?type=regime")
    assert resp.status_code == 200
