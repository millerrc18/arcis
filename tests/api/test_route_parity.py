"""Tests for C2/C3/C4/C5: local route parity — routes that existed only in
cloud_routes must also be reachable via the local FastAPI app.

C2: /ib-shadow/summary, /ib-shadow/log, /ib-shadow/health
C3: /strategy-detail/{type}
C4: /system/index  (GET) and /system/index/{name}/mark-reviewed (POST)
C5: /projections/live
"""
from __future__ import annotations

import sqlite3
import tempfile
import os
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from src.api.app import app


@pytest.fixture(scope="module")
def client():
    return TestClient(app, raise_server_exceptions=False)


# ── C2: IB Shadow routes ─────────────────────────────────────────────────────

def test_ib_shadow_summary_exists(client):
    """GET /api/ib-shadow/summary must return 200, not 404."""
    resp = client.get("/api/ib-shadow/summary")
    assert resp.status_code == 200, f"/api/ib-shadow/summary returned {resp.status_code}"


def test_ib_shadow_summary_shape(client):
    """GET /api/ib-shadow/summary must return a dict (not array, not 404 body)."""
    resp = client.get("/api/ib-shadow/summary")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, dict)
    assert "total_shadows" in data


def test_ib_shadow_log_exists(client):
    """GET /api/ib-shadow/log must return 200, not 404."""
    resp = client.get("/api/ib-shadow/log")
    assert resp.status_code == 200, f"/api/ib-shadow/log returned {resp.status_code}"


def test_ib_shadow_log_shape(client):
    """GET /api/ib-shadow/log must return a dict with entries key."""
    resp = client.get("/api/ib-shadow/log")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, dict)
    assert "entries" in data
    assert isinstance(data["entries"], list)


def test_ib_shadow_health_exists(client):
    """GET /api/ib-shadow/health must return 200, not 404."""
    resp = client.get("/api/ib-shadow/health")
    assert resp.status_code == 200, f"/api/ib-shadow/health returned {resp.status_code}"


def test_ib_shadow_health_shape(client):
    """GET /api/ib-shadow/health must return a dict with shadow_mode_enabled key."""
    resp = client.get("/api/ib-shadow/health")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, dict)
    assert "shadow_mode_enabled" in data


# ── C3: Strategy detail route ─────────────────────────────────────────────────

def test_strategy_detail_pullback_exists(client):
    """GET /api/strategy-detail/pullback must return 200, not 404."""
    resp = client.get("/api/strategy-detail/pullback")
    assert resp.status_code == 200, f"/api/strategy-detail/pullback returned {resp.status_code}"


def test_strategy_detail_shape(client):
    """GET /api/strategy-detail/{type} must return dict with trades key."""
    resp = client.get("/api/strategy-detail/pullback")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, dict)
    assert "trades" in data
    assert isinstance(data["trades"], list)


def test_strategy_detail_mean_reversion_exists(client):
    """GET /api/strategy-detail/mean_reversion must return 200, not 404."""
    resp = client.get("/api/strategy-detail/mean_reversion")
    assert resp.status_code == 200, f"/api/strategy-detail/mean_reversion returned {resp.status_code}"


# ── C4: System index route ────────────────────────────────────────────────────

def test_system_index_exists(client):
    """GET /api/system/index must return 200, not 404."""
    resp = client.get("/api/system/index")
    assert resp.status_code == 200, f"/api/system/index returned {resp.status_code}"


def test_system_index_shape(client):
    """GET /api/system/index must return a dict with expected top-level keys."""
    resp = client.get("/api/system/index")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, dict)
    assert "actions" in data
    assert "states" in data
    assert "systems" in data
    assert "decisions" in data
    assert "counts" in data


# ── C5: Projections live route ────────────────────────────────────────────────

def test_projections_live_exists(client):
    """GET /api/projections/live must return 200, not 404."""
    resp = client.get("/api/projections/live")
    assert resp.status_code == 200, f"/api/projections/live returned {resp.status_code}"


def test_projections_live_shape(client):
    """GET /api/projections/live must return a dict with trades key."""
    resp = client.get("/api/projections/live")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, dict)
    assert "trades" in data
