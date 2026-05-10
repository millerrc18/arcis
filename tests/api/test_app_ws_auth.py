"""Tests for /ws/live token-query-parameter auth (Issue 2 of PR #1047 review).

Pre-cutover the WebSocket bound to 127.0.0.1 only and ran without auth.
Post-cutover (Cloudflare Tunnel exposes `wss://halcyonlab.app/ws/live` to the
internet) the WS endpoint requires the same `API_SECRET` bearer token the
HTTP routes use, but passed via query parameter because browser WebSocket
APIs don't expose a way to set custom request headers.

These tests verify:
 - missing token → close 1008
 - wrong token → close 1008
 - correct plaintext token → connect succeeds
 - correct SHA-256 hashed token → connect succeeds (matches AuthGate)
 - API_SECRET unset in env → close 1008 (fail closed)
"""
from __future__ import annotations

import hashlib
import os
from unittest import mock

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect


@pytest.fixture
def app_with_secret(monkeypatch):
    """Reload src.api.app with API_SECRET set; return the TestClient + secret values."""
    secret = "test-ws-secret-32-bytes-of-entropy-here"
    monkeypatch.setenv("API_SECRET", secret)
    # Force reload so the module re-reads API_SECRET + recomputes _API_SECRET_HASH.
    import importlib
    import src.api.app
    importlib.reload(src.api.app)
    client = TestClient(src.api.app.app)
    hashed = hashlib.sha256(secret.encode()).hexdigest()
    return client, secret, hashed


def test_ws_live_rejects_missing_token(app_with_secret):
    """No token query-parameter → 1008 close before message exchange."""
    client, _, _ = app_with_secret
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect("/ws/live"):
            pass
    assert exc.value.code == 1008


def test_ws_live_rejects_wrong_token(app_with_secret):
    """Wrong token value → 1008 close."""
    client, _, _ = app_with_secret
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect("/ws/live?token=wrong-token"):
            pass
    assert exc.value.code == 1008


def test_ws_live_accepts_plaintext_token(app_with_secret):
    """Correct plaintext token → connects cleanly (no immediate close)."""
    client, secret, _ = app_with_secret
    with client.websocket_connect(f"/ws/live?token={secret}") as ws:
        # Connection accepted; no message exchange required for this assertion.
        # The fact that the context manager entered without raising
        # WebSocketDisconnect proves auth succeeded.
        assert ws is not None


def test_ws_live_accepts_hashed_token(app_with_secret):
    """Correct SHA-256 hashed token (frontend AuthGate format) → connects cleanly."""
    client, _, hashed = app_with_secret
    with client.websocket_connect(f"/ws/live?token={hashed}") as ws:
        assert ws is not None


def test_ws_live_fail_closed_when_api_secret_unset(monkeypatch):
    """If API_SECRET env var is empty/missing, refuse all WS connections (fail closed)."""
    monkeypatch.delenv("API_SECRET", raising=False)
    monkeypatch.setenv("API_SECRET", "")
    import importlib
    import src.api.app
    importlib.reload(src.api.app)
    client = TestClient(src.api.app.app)
    # Even with the "right" empty token, fail closed.
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect("/ws/live?token="):
            pass
    assert exc.value.code == 1008
