"""Tests for /api/commands/expire-stale cloud endpoint (#54 Tier 1.E).

Mirrors the local-mode endpoint in src/api/routes/logs.py. The cloud version
must:
1. Require auth (verify_auth in dependencies)
2. Return 0 permissively when DATABASE_URL is unset (button-safe in any deploy)
3. Call src.commands.maintenance.expire_stale_commands when DATABASE_URL is set
4. Wrap helper exceptions as HTTP 500 with detail
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi import Depends, FastAPI, HTTPException
from fastapi.testclient import TestClient

from src.api.cloud_routes.commands import create_router


def _noop_auth():
    return True


def _denying_auth():
    raise HTTPException(status_code=401, detail="unauthorized")


@pytest.fixture
def runtime_stub():
    runtime = MagicMock()
    runtime.logger = MagicMock()
    return runtime


@pytest.fixture
def client(runtime_stub):
    app = FastAPI()
    app.include_router(create_router(runtime_stub, _noop_auth))
    return TestClient(app)


def test_expire_stale_no_database_url(client, monkeypatch):
    """When DATABASE_URL is empty, return permissive {expired: 0, note: ...}."""
    monkeypatch.setenv("DATABASE_URL", "")
    resp = client.post("/api/commands/expire-stale")
    assert resp.status_code == 200
    body = resp.json()
    assert body["expired"] == 0
    assert "DATABASE_URL not configured" in body["note"]


def test_expire_stale_calls_helper_when_database_url_set(client, monkeypatch):
    """When DATABASE_URL is set, route calls expire_stale_commands and returns count."""
    monkeypatch.setenv("DATABASE_URL", "postgresql://test")
    with patch("src.commands.maintenance.expire_stale_commands", return_value=7) as mock_helper:
        resp = client.post("/api/commands/expire-stale")
    assert resp.status_code == 200
    assert resp.json() == {"expired": 7}
    mock_helper.assert_called_once_with("postgresql://test")


def test_expire_stale_helper_failure_returns_500(client, runtime_stub, monkeypatch):
    """Helper exception is caught, logged, and surfaces as HTTP 500."""
    monkeypatch.setenv("DATABASE_URL", "postgresql://test")
    with patch(
        "src.commands.maintenance.expire_stale_commands",
        side_effect=RuntimeError("connection refused"),
    ):
        resp = client.post("/api/commands/expire-stale")
    assert resp.status_code == 500
    assert "connection refused" in resp.json()["detail"]
    runtime_stub.logger.error.assert_called_once()


def test_expire_stale_requires_auth(runtime_stub, monkeypatch):
    """Route must use verify_auth — auth-denying dependency rejects unauthed callers."""
    monkeypatch.setenv("DATABASE_URL", "")
    app = FastAPI()
    app.include_router(create_router(runtime_stub, _denying_auth))
    client = TestClient(app)
    resp = client.post("/api/commands/expire-stale")
    assert resp.status_code == 401


def test_outcome_counts_uses_coalesce_in_training_query():
    """Tier 1.F: outcome_counts query must COALESCE the three outcome columns.

    Pre-fix used `outcome` only (0/1844 NULL post-migration). The fix:
    COALESCE(trade_outcome, outcome_type, outcome) — preferring the most-
    populated column, falling back through to legacy.
    """
    import inspect

    from src.api.cloud_routes import training

    source = inspect.getsource(training)
    assert "COALESCE(trade_outcome, outcome_type, outcome)" in source, (
        "Tier 1.F regression: outcome_counts query must use "
        "COALESCE(trade_outcome, outcome_type, outcome). "
        "See #54 / cloud_routes/training.py outcome_rows query."
    )
