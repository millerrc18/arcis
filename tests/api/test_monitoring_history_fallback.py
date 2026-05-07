"""Tests for T3 E7: /api/monitoring/history 200+empty+note fallback.

When system_metrics table is unavailable (e.g. Render Postgres where the table
is local-only with sync_to_postgres=False), the endpoint must return HTTP 200
with {snapshots: [], note: '...'} instead of raising 500 (which Render proxies
may surface as 503).

This mirrors the existing /api/monitoring/snapshot fallback pattern at
analytics.py:967-977.
"""
from __future__ import annotations

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


def _make_client(rows=None, query_side_effect=None):
    app = FastAPI()
    runtime = _make_runtime(rows=rows, query_side_effect=query_side_effect)
    router = create_router(runtime, _make_verify_auth())
    app.include_router(router)
    client = TestClient(app, raise_server_exceptions=False)
    return client, runtime


# ── T3 E7: UndefinedTable fallback (200 + empty + note) ──────────────────────


def test_undefined_table_returns_200():
    """UndefinedTable raises → response must be HTTP 200, not 500/503."""
    try:
        import psycopg2.errors as pg_errors
        exc = pg_errors.UndefinedTable("relation \"system_metrics\" does not exist")
    except ImportError:
        exc = Exception("psycopg2.errors.UndefinedTable: relation \"system_metrics\" does not exist")
    client, _ = _make_client(query_side_effect=exc)
    resp = client.get("/api/monitoring/history")
    assert resp.status_code == 200, (
        f"Expected 200 on UndefinedTable, got {resp.status_code}: {resp.text!r}"
    )


def test_undefined_table_returns_snapshots_empty():
    """UndefinedTable raises → response body must have snapshots=[]."""
    try:
        import psycopg2.errors as pg_errors
        exc = pg_errors.UndefinedTable("relation \"system_metrics\" does not exist")
    except ImportError:
        exc = Exception("psycopg2.errors.UndefinedTable: relation \"system_metrics\" does not exist")
    client, _ = _make_client(query_side_effect=exc)
    resp = client.get("/api/monitoring/history")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, dict), f"Expected dict response, got {type(data).__name__}"
    assert "snapshots" in data, f"Expected 'snapshots' key in response: {data!r}"
    assert data["snapshots"] == [], f"Expected snapshots=[], got {data['snapshots']!r}"


def test_undefined_table_returns_note():
    """UndefinedTable raises → response body must have a non-empty note field."""
    try:
        import psycopg2.errors as pg_errors
        exc = pg_errors.UndefinedTable("relation \"system_metrics\" does not exist")
    except ImportError:
        exc = Exception("psycopg2.errors.UndefinedTable: relation \"system_metrics\" does not exist")
    client, _ = _make_client(query_side_effect=exc)
    resp = client.get("/api/monitoring/history")
    assert resp.status_code == 200
    data = resp.json()
    assert "note" in data, f"Expected 'note' key in response: {data!r}"
    assert isinstance(data["note"], str) and len(data["note"]) > 0, (
        f"Expected non-empty string note, got {data['note']!r}"
    )
    assert "local" in data["note"].lower() or "system_metrics" in data["note"].lower(), (
        f"Note should mention local-only or system_metrics: {data['note']!r}"
    )


def test_generic_exception_returns_200_with_fallback():
    """Any runtime error → HTTP 200 with snapshots=[] and note (not 500/503)."""
    exc = RuntimeError("connection refused")
    client, _ = _make_client(query_side_effect=exc)
    resp = client.get("/api/monitoring/history")
    assert resp.status_code == 200, (
        f"Expected 200 on generic exception, got {resp.status_code}: {resp.text!r}"
    )
    data = resp.json()
    assert "snapshots" in data
    assert data["snapshots"] == []
    assert "note" in data


def test_happy_path_returns_snapshots_non_empty():
    """When system_metrics rows exist, response has snapshots with data."""
    fake_rows = [
        {"timestamp": "2026-05-07T10:00:00", "cpu_pct": 42.0, "snapshot_id": "abc1"},
        {"timestamp": "2026-05-07T10:01:00", "cpu_pct": 55.0, "snapshot_id": "abc2"},
    ]
    client, _ = _make_client(rows=fake_rows)
    resp = client.get("/api/monitoring/history")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, dict), f"Expected dict response, got {type(data).__name__}"
    assert "snapshots" in data, f"Expected 'snapshots' key: {data!r}"
    assert len(data["snapshots"]) == 2, (
        f"Expected 2 snapshots, got {len(data['snapshots'])}"
    )
    assert data["snapshots"][0]["cpu_pct"] == 42.0


def test_happy_path_no_note_on_success():
    """On success (no exception), there should be no 'note' key or note is None/absent."""
    fake_rows = [{"timestamp": "2026-05-07T10:00:00", "cpu_pct": 42.0, "snapshot_id": "xyz"}]
    client, _ = _make_client(rows=fake_rows)
    resp = client.get("/api/monitoring/history")
    assert resp.status_code == 200
    data = resp.json()
    assert "note" not in data or data.get("note") is None, (
        f"Expected no 'note' on happy path, got note={data.get('note')!r}"
    )


def test_note_contains_localhost_url():
    """Fallback note should contain the localhost URL for local viewing."""
    exc = RuntimeError("db not reachable")
    client, _ = _make_client(query_side_effect=exc)
    resp = client.get("/api/monitoring/history")
    data = resp.json()
    assert "localhost" in data.get("note", ""), (
        f"Note should point to localhost URL: {data.get('note')!r}"
    )
