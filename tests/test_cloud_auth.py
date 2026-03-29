"""Tests for cloud_app.py authentication middleware."""

import os
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def app_with_secret():
    """Create app instance with API_SECRET set."""
    with patch.dict(os.environ, {"API_SECRET": "test-secret-123", "DATABASE_URL": ""}):
        # Re-import to pick up the env var
        import importlib
        import src.api.cloud_app as cloud_mod

        importlib.reload(cloud_mod)
        yield cloud_mod.app


@pytest.fixture
def app_without_secret():
    """Create app instance with API_SECRET empty."""
    with patch.dict(os.environ, {"API_SECRET": "", "DATABASE_URL": ""}):
        import importlib
        import src.api.cloud_app as cloud_mod

        importlib.reload(cloud_mod)
        yield cloud_mod.app


class TestBearerTokenValidation:
    """Test that bearer token auth works correctly."""

    def test_valid_token_returns_200(self, app_with_secret):
        client = TestClient(app_with_secret)
        res = client.get(
            "/api/status",
            headers={"Authorization": "Bearer test-secret-123"},
        )
        # May be 200 or 503 (no DB), but NOT 401
        assert res.status_code != 401

    def test_invalid_token_returns_401(self, app_with_secret):
        client = TestClient(app_with_secret)
        res = client.get(
            "/api/status",
            headers={"Authorization": "Bearer wrong-token"},
        )
        assert res.status_code == 401

    def test_missing_token_returns_401(self, app_with_secret):
        client = TestClient(app_with_secret)
        res = client.get("/api/status")
        assert res.status_code == 401


class TestPassthroughWhenNoSecret:
    """Test that auth is disabled when API_SECRET is empty."""

    def test_no_token_passes_through(self, app_without_secret):
        client = TestClient(app_without_secret)
        res = client.get("/api/status")
        # Should NOT be 401 -- auth is disabled
        assert res.status_code != 401

    def test_any_token_passes_through(self, app_without_secret):
        client = TestClient(app_without_secret)
        res = client.get(
            "/api/status",
            headers={"Authorization": "Bearer anything"},
        )
        assert res.status_code != 401
