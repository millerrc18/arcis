"""Tests for C1 + O8: /api/monitoring/history shape + error-path behavior.

C1 verified that the cloud route returns a bare array (not {snapshots: [...]})
to match what the frontend expects.

O8 (PR #690 review): the C1 fix changed the failure path from
{snapshots: [], error: str(exc)} to bare [], which silently masked DB
failures as "no monitoring data exists". The error path now raises 500 so
the frontend's error boundary can fire.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
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


def test_monitoring_history_returns_array_not_dict():
    """Cloud route must return a bare array, not {snapshots: [...]}."""
    client, _ = _make_client(rows=[])
    resp = client.get("/api/monitoring/history")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list), f"Expected list, got {type(data).__name__}: {data!r}"


def test_monitoring_history_returns_array_with_rows():
    """Rows are returned as list elements, not wrapped in a key."""
    fake_row = {"timestamp": "2026-04-25T10:00:00", "cpu_pct": 42.0}
    rows = [fake_row]
    client, _ = _make_client(rows=rows)
    resp = client.get("/api/monitoring/history")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) == 1
    assert data[0]["cpu_pct"] == 42.0


def test_monitoring_history_no_snapshots_key():
    """Response must not contain a 'snapshots' key (old broken shape)."""
    client, _ = _make_client(rows=[])
    resp = client.get("/api/monitoring/history")
    assert resp.status_code == 200
    data = resp.json()
    assert not isinstance(data, dict) or "snapshots" not in data


# ── PR #690 O8: error-path tests ──────────────────────────────────────────


def test_monitoring_history_db_error_raises_500():
    """O8: DB failures must surface as HTTP 500, not silent empty array.

    The C1 fix (success-path bare array) inadvertently changed the failure
    path from {snapshots: [], error: str(exc)} to bare [], which silently
    masked DB failures as "no monitoring data". Frontend can't distinguish
    "no monitoring data exists" from "fetch failed" if we return 200 [].
    """
    db_error = RuntimeError("simulated DB outage: connection refused")
    client, _ = _make_client(
        query_side_effect=db_error,
        raise_server_exceptions=False,  # let HTTPException become a 500 response
    )
    resp = client.get("/api/monitoring/history")
    assert resp.status_code == 500, (
        f"Expected 500 on DB error, got {resp.status_code}: {resp.text!r}"
    )


def test_monitoring_history_db_error_includes_detail():
    """O8: 500 response detail must contain the underlying error message."""
    err_msg = "simulated DB outage: connection refused"
    db_error = RuntimeError(err_msg)
    client, _ = _make_client(
        query_side_effect=db_error,
        raise_server_exceptions=False,
    )
    resp = client.get("/api/monitoring/history")
    assert resp.status_code == 500
    body = resp.json()
    # FastAPI HTTPException puts the message in the "detail" field
    assert "detail" in body, f"Expected 'detail' in response: {body!r}"
    assert err_msg in str(body["detail"]), (
        f"Expected error message in detail, got {body['detail']!r}"
    )


def test_monitoring_history_db_error_logs_warning():
    """O8: error-path logs at WARNING with exc_info=True before raising."""
    db_error = RuntimeError("logging-check failure")
    client, runtime = _make_client(
        query_side_effect=db_error,
        raise_server_exceptions=False,
    )
    resp = client.get("/api/monitoring/history")
    assert resp.status_code == 500
    assert runtime.logger.warning.called, (
        "Expected a logger.warning call on the error path"
    )
    # exc_info=True must be present so traceback gets captured
    _, call_kwargs = runtime.logger.warning.call_args
    assert call_kwargs.get("exc_info") is True, (
        f"Expected exc_info=True kwarg on logger.warning, got {call_kwargs!r}"
    )
