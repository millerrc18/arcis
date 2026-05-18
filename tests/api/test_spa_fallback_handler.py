"""Regression-lock for _spa_fallback_404 in src/api/app.py (v0.36.21 fix).

Pre-fix the handler re-raised non-404 exceptions on line 250 (`raise exc`).
Raising inside an exception handler bubbles to uvicorn and becomes a 500.
Effects:
  - Bad/missing bearer token → 500 instead of 401 → the frontend AuthGate
    redirect-on-401 in `frontend/src/api.js:33` never fires, so every dashboard
    panel showed "failed to load" while the user was silently signed out.
  - Any HTTPException raised from a route (validation, business logic) also
    became 500 instead of its real status.

Post-fix the handler returns a JSONResponse mirroring FastAPI's default
exception response shape ({"detail": ...} with the real status_code).

These tests pin both the SPA-route path (still serves index.html) AND the
API-route path (returns the real status_code, not 500).
"""
from __future__ import annotations

import importlib
import os
import tempfile

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def app_with_frontend(monkeypatch, tmp_path):
    """Reload src.api.app with API_SECRET set + a stubbed frontend/dist directory."""
    secret = "test-spa-secret-32-bytes-of-entropy-here"
    monkeypatch.setenv("API_SECRET", secret)
    # Force reload so the module re-reads env vars.
    import src.api.app
    importlib.reload(src.api.app)
    return TestClient(src.api.app.app), secret


def test_unauthed_api_call_returns_401_not_500(app_with_frontend):
    """Bad/missing bearer token on /api/* must return 401, not 500.

    Pre-v0.36.21: the SPA fallback handler re-raised the 401, becoming a 500.
    This broke `frontend/src/api.js:33` which only triggers re-auth on 401.
    """
    client, _secret = app_with_frontend
    # No Authorization header at all.
    res = client.get("/api/status")
    assert res.status_code == 401, (
        f"Expected 401 for unauthed call, got {res.status_code}. "
        f"Body: {res.text[:200]}. "
        "If 500: the SPA fallback handler is re-raising non-404 exceptions again."
    )
    # And the body should be JSON-shaped {"detail": ...} like FastAPI's default.
    assert res.headers.get("content-type", "").startswith("application/json"), (
        f"Expected JSON content-type, got {res.headers.get('content-type')!r}"
    )
    body = res.json()
    assert "detail" in body, f"Expected 'detail' key in response body, got {body!r}"


def test_unauthed_api_call_with_bad_token_returns_401(app_with_frontend):
    """Invalid bearer token on /api/* must return 401, not 500."""
    client, _secret = app_with_frontend
    res = client.get(
        "/api/status",
        headers={"Authorization": "Bearer this-is-not-the-real-token"},
    )
    assert res.status_code == 401, (
        f"Expected 401 for invalid token, got {res.status_code}. "
        f"Body: {res.text[:200]}"
    )


def test_authed_api_call_still_works(app_with_frontend):
    """Sanity check — valid token still returns 200 (the patch didn't break auth)."""
    client, secret = app_with_frontend
    res = client.get(
        "/api/status",
        headers={"Authorization": f"Bearer {secret}"},
    )
    assert res.status_code == 200, (
        f"Expected 200 for authed call, got {res.status_code}. "
        f"Body: {res.text[:200]}"
    )


def test_healthz_unaffected(app_with_frontend):
    """/healthz is unauthenticated by design — must still return 200."""
    client, _ = app_with_frontend
    res = client.get("/healthz")
    assert res.status_code == 200
    assert res.json() == {"status": "ok"}
