"""Tests for GET/POST /api/console/pause (T5 — Founder Console Phase-1).

Covers:
- GET returns the canonical status envelope (all 6 keys present).
- POST action='pause' engages the pause; subsequent GET reflects it (real round-trip).
- POST action='resume' clears the pause; subsequent GET reflects it.
- Malformed / missing 'action' returns 4xx (422 or 400).
- Non-vacuous: tests exercise the real engine (set_pause / clear_pause /
  read_pause_state) behind a mocked connect_db, so a broken route body
  would fail the test.

Skip if TEST_DATABASE_URL is absent — the real PG round-trip requires it.
"""
from __future__ import annotations

import os
from unittest.mock import patch

import pytest

TEST_PG_URL = os.environ.get("TEST_DATABASE_URL", "")

pytestmark = pytest.mark.skipif(
    not TEST_PG_URL.startswith("postgres"),
    reason="integration(authoritative-coverage:pg-tests)",
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_pg_wrapper():
    """Return a fresh PostgresConnectionWrapper against the test PG."""
    import psycopg2
    import psycopg2.extras
    from src.utils.db import PostgresConnectionWrapper

    raw = psycopg2.connect(TEST_PG_URL, cursor_factory=psycopg2.extras.RealDictCursor)
    raw.autocommit = False
    return PostgresConnectionWrapper(raw)


def _provision_table(wrapper) -> None:
    """Create console_pause_state if absent."""
    wrapper.execute("""
        CREATE TABLE IF NOT EXISTS console_pause_state (
            id INTEGER PRIMARY KEY,
            is_paused INTEGER NOT NULL DEFAULT 0,
            paused_at TEXT,
            paused_by TEXT,
            reason TEXT,
            resumed_at TEXT,
            updated_at TEXT NOT NULL
        )
    """)
    wrapper.commit()


def _wipe_table(wrapper) -> None:
    wrapper.execute("DELETE FROM console_pause_state")
    wrapper.commit()


@pytest.fixture(autouse=True)
def _clean_pause_table():
    """Provision + wipe before each test; wipe after."""
    w = _make_pg_wrapper()
    _provision_table(w)
    _wipe_table(w)
    w.close()

    yield

    w2 = _make_pg_wrapper()
    _wipe_table(w2)
    w2.close()


def _make_client():
    """Build a minimal FastAPI TestClient around the console_pause router.

    The router's verify_auth placeholder is left as-is (returns None), so no
    auth header is needed in tests — identical to how notifications tests work.
    """
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from src.api.cloud_routes.console_pause import router

    app = FastAPI()
    app.include_router(router, prefix="/api")
    return TestClient(app, raise_server_exceptions=True)


# ── GET /api/console/pause ───────────────────────────────────────────────────

class TestGetPauseStatus:

    def test_get_returns_200(self):
        client = _make_client()
        with patch("src.console.pause.connect_db", side_effect=_make_pg_wrapper):
            resp = client.get("/api/console/pause")
        assert resp.status_code == 200

    def test_get_returns_all_required_keys(self):
        client = _make_client()
        with patch("src.console.pause.connect_db", side_effect=_make_pg_wrapper):
            resp = client.get("/api/console/pause")
        data = resp.json()
        required = {"is_paused", "paused_at", "paused_by", "reason", "resumed_at", "updated_at"}
        assert required <= set(data.keys()), f"missing keys: {required - set(data.keys())}"

    def test_get_default_state_not_paused(self):
        """Fresh table → is_paused is False, all timestamps are None."""
        client = _make_client()
        with patch("src.console.pause.connect_db", side_effect=_make_pg_wrapper):
            resp = client.get("/api/console/pause")
        data = resp.json()
        assert data["is_paused"] is False
        assert data["paused_at"] is None
        assert data["paused_by"] is None
        assert data["reason"] is None


# ── POST /api/console/pause — pause action ───────────────────────────────────

class TestPostPauseAction:

    def test_post_pause_returns_200_with_state(self):
        client = _make_client()
        with patch("src.console.pause.connect_db", side_effect=_make_pg_wrapper), \
                patch("src.console.pause.log_activity"):
            resp = client.post("/api/console/pause", json={"action": "pause", "reason": "test"})
        assert resp.status_code == 200
        data = resp.json()
        assert "is_paused" in data

    def test_post_pause_reflects_paused_state(self):
        """POST pause → GET must reflect is_paused=True (real engine round-trip)."""
        client = _make_client()
        with patch("src.console.pause.connect_db", side_effect=_make_pg_wrapper), \
                patch("src.console.pause.log_activity"):
            resp = client.post(
                "/api/console/pause",
                json={"action": "pause", "reason": "operator break"},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["is_paused"] is True, f"expected is_paused=True, got {data}"
        assert data["reason"] == "operator break"

    def test_get_after_post_pause_reflects_paused(self):
        """POST pause then GET: GET must also return is_paused=True."""
        client = _make_client()
        with patch("src.console.pause.connect_db", side_effect=_make_pg_wrapper), \
                patch("src.console.pause.log_activity"):
            client.post("/api/console/pause", json={"action": "pause", "reason": "test-get"})
            resp = client.get("/api/console/pause")
        data = resp.json()
        assert data["is_paused"] is True, f"GET after POST pause must show paused, got {data}"

    def test_post_pause_without_reason_defaults(self):
        """reason is optional — omitting it should not cause a 4xx."""
        client = _make_client()
        with patch("src.console.pause.connect_db", side_effect=_make_pg_wrapper), \
                patch("src.console.pause.log_activity"):
            resp = client.post("/api/console/pause", json={"action": "pause"})
        assert resp.status_code == 200


# ── POST /api/console/pause — resume action ──────────────────────────────────

class TestPostResumeAction:

    def test_post_resume_clears_pause(self):
        """POST pause then POST resume: final state is is_paused=False."""
        client = _make_client()
        with patch("src.console.pause.connect_db", side_effect=_make_pg_wrapper), \
                patch("src.console.pause.log_activity"):
            client.post("/api/console/pause", json={"action": "pause", "reason": "r"})
            resp = client.post("/api/console/pause", json={"action": "resume"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["is_paused"] is False, f"resume must clear pause, got {data}"

    def test_get_after_resume_reflects_not_paused(self):
        """GET after POST resume must also return is_paused=False."""
        client = _make_client()
        with patch("src.console.pause.connect_db", side_effect=_make_pg_wrapper), \
                patch("src.console.pause.log_activity"):
            client.post("/api/console/pause", json={"action": "pause", "reason": "r"})
            client.post("/api/console/pause", json={"action": "resume"})
            resp = client.get("/api/console/pause")
        data = resp.json()
        assert data["is_paused"] is False
        assert data["resumed_at"] is not None

    def test_post_resume_returns_resumed_at(self):
        """After resume the state envelope must have resumed_at set."""
        client = _make_client()
        with patch("src.console.pause.connect_db", side_effect=_make_pg_wrapper), \
                patch("src.console.pause.log_activity"):
            client.post("/api/console/pause", json={"action": "pause", "reason": "r"})
            resp = client.post("/api/console/pause", json={"action": "resume"})
        data = resp.json()
        assert data["resumed_at"] is not None


# ── POST /api/console/pause — malformed input ────────────────────────────────

class TestMalformedAction:

    def test_missing_action_returns_4xx(self):
        """Body with no 'action' field must return a 4xx response."""
        client = _make_client()
        resp = client.post("/api/console/pause", json={"reason": "no action"})
        assert resp.status_code in (400, 422), f"expected 4xx, got {resp.status_code}"

    def test_invalid_action_value_returns_4xx(self):
        """action='unknown' must return a 4xx response."""
        client = _make_client()
        resp = client.post("/api/console/pause", json={"action": "unknown"})
        assert resp.status_code in (400, 422), f"expected 4xx, got {resp.status_code}"

    def test_empty_body_returns_4xx(self):
        """Empty body must return a 4xx response."""
        client = _make_client()
        resp = client.post("/api/console/pause", json={})
        assert resp.status_code in (400, 422), f"expected 4xx, got {resp.status_code}"

    def test_non_vacuous_bad_route_would_fail(self):
        """Confirm the route actually processes valid input (non-vacuous check).

        If the route body were broken (e.g. always returned {is_paused: False}),
        the TestPostPauseAction.test_post_pause_reflects_paused_state test would
        fail because the state read via the real engine would still be paused.
        This test just asserts a sanity-check on the route path existing.
        """
        client = _make_client()
        with patch("src.console.pause.connect_db", side_effect=_make_pg_wrapper), \
                patch("src.console.pause.log_activity"):
            resp = client.post("/api/console/pause", json={"action": "pause", "reason": "x"})
        assert resp.status_code == 200
        assert resp.json()["is_paused"] is True
