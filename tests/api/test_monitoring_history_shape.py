"""Tests for C1: /api/monitoring/history shape fix.

Verifies that the cloud route returns a bare array (not {snapshots: [...]})
to match what the frontend expects.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.cloud_routes.analytics import create_router


def _make_runtime(rows=None):
    runtime = MagicMock()
    runtime.logger = MagicMock()
    runtime.query.return_value = rows if rows is not None else []
    return runtime


def _make_verify_auth():
    def verify_auth():
        return True
    return verify_auth


def _make_client(rows=None):
    app = FastAPI()
    router = create_router(_make_runtime(rows=rows), _make_verify_auth())
    app.include_router(router)
    return TestClient(app, raise_server_exceptions=True)


def test_monitoring_history_returns_array_not_dict():
    """Cloud route must return a bare array, not {snapshots: [...]}."""
    client = _make_client(rows=[])
    resp = client.get("/api/monitoring/history")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list), f"Expected list, got {type(data).__name__}: {data!r}"


def test_monitoring_history_returns_array_with_rows():
    """Rows are returned as list elements, not wrapped in a key."""
    fake_row = {"timestamp": "2026-04-25T10:00:00", "cpu_pct": 42.0}
    rows = [fake_row]
    client = _make_client(rows=rows)
    resp = client.get("/api/monitoring/history")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) == 1
    assert data[0]["cpu_pct"] == 42.0


def test_monitoring_history_no_snapshots_key():
    """Response must not contain a 'snapshots' key (old broken shape)."""
    client = _make_client(rows=[])
    resp = client.get("/api/monitoring/history")
    assert resp.status_code == 200
    data = resp.json()
    assert not isinstance(data, dict) or "snapshots" not in data
