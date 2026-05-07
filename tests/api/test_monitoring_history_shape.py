"""Tests for C1 + O8 → T3: /api/monitoring/history shape + error-path behavior.

T3 (Sprint 3 E7): changed the success shape from bare array to
{snapshots: [...]} and changed the error path from raise-500 to
200+{snapshots:[], note:'...'} to avoid 503 on Render (system_metrics
is local-only with sync_to_postgres=False). The O8 tests below have
been updated to reflect the new contract — see
tests/api/test_monitoring_history_fallback.py for the T3-specific
error-path tests.
"""
from __future__ import annotations

from unittest.mock import MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.cloud_routes.analytics import create_router


def _make_runtime(rows=None, query_side_effect=None):
    runtime = MagicMock()
    runtime.logger = MagicMock()
    if query_side_effect is not None:
        runtime.query.side_effect = query_side_effect
    else:
        runtime.query.return_value = rows if rows is not None else []
    return runtime


def _make_verify_auth():
    def verify_auth():
        return True
    return verify_auth


def _make_client(rows=None, query_side_effect=None, raise_server_exceptions=True):
    app = FastAPI()
    runtime = _make_runtime(rows=rows, query_side_effect=query_side_effect)
    router = create_router(runtime, _make_verify_auth())
    app.include_router(router)
    client = TestClient(app, raise_server_exceptions=raise_server_exceptions)
    return client, runtime


def test_monitoring_history_returns_dict_with_snapshots():
    """T3: success path returns {snapshots: [...]} (not bare array)."""
    client, _ = _make_client(rows=[])
    resp = client.get("/api/monitoring/history")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, dict), f"Expected dict, got {type(data).__name__}: {data!r}"
    assert "snapshots" in data, f"Expected 'snapshots' key: {data!r}"


def test_monitoring_history_returns_snapshots_with_rows():
    """T3: rows land in data['snapshots'], not top-level array."""
    fake_row = {"timestamp": "2026-04-25T10:00:00", "cpu_pct": 42.0}
    rows = [fake_row]
    client, _ = _make_client(rows=rows)
    resp = client.get("/api/monitoring/history")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, dict)
    assert len(data["snapshots"]) == 1
    assert data["snapshots"][0]["cpu_pct"] == 42.0


def test_monitoring_history_has_snapshots_key():
    """T3: response contains 'snapshots' key on success."""
    client, _ = _make_client(rows=[])
    resp = client.get("/api/monitoring/history")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, dict) and "snapshots" in data


# ── T3 E7: error path (supersedes O8 raise-500 behavior) ────────────────────


def test_monitoring_history_db_error_returns_200():
    """T3: DB errors return HTTP 200 with fallback note (not 500/503)."""
    db_error = RuntimeError("simulated DB outage: connection refused")
    client, _ = _make_client(
        query_side_effect=db_error,
        raise_server_exceptions=False,
    )
    resp = client.get("/api/monitoring/history")
    assert resp.status_code == 200, (
        f"Expected 200 on DB error, got {resp.status_code}: {resp.text!r}"
    )


def test_monitoring_history_db_error_snapshots_empty():
    """T3: DB errors return snapshots=[] in the fallback response."""
    db_error = RuntimeError("simulated DB outage: connection refused")
    client, _ = _make_client(
        query_side_effect=db_error,
        raise_server_exceptions=False,
    )
    resp = client.get("/api/monitoring/history")
    body = resp.json()
    assert body.get("snapshots") == [], f"Expected snapshots=[], got {body!r}"


def test_monitoring_history_db_error_logs_warning():
    """T3: error-path still logs at WARNING with exc_info=True."""
    db_error = RuntimeError("logging-check failure")
    client, runtime = _make_client(
        query_side_effect=db_error,
        raise_server_exceptions=False,
    )
    resp = client.get("/api/monitoring/history")
    assert resp.status_code == 200
    assert runtime.logger.warning.called, (
        "Expected a logger.warning call on the error path"
    )
    _, call_kwargs = runtime.logger.warning.call_args
    assert call_kwargs.get("exc_info") is True, (
        f"Expected exc_info=True kwarg on logger.warning, got {call_kwargs!r}"
    )
