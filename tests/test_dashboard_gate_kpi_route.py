"""Tests for the GET /api/kpis/gate-proposals endpoint.

Tests the T7 route that surfaces methodology-gate-proposal counts
(1d/7d/30d x {promote, reject, defer, unknown}) for the dashboard.

Implementation choice: Option A — new sub-route /kpis/gate-proposals.
Rationale: cleaner separation of concerns, does not change existing /kpis
contract, easier to evolve independently.

Called by: pytest (CI)
Calls: src.api.cloud_routes.kpis (route), src.analytics.kpis_compute (compute)
Owns tables: none
Config keys: none
Tests: Sprint 2 T7
"""
from __future__ import annotations

import json
import os
import sqlite3
import tempfile
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient


# ── Helpers ──────────────────────────────────────────────────────────────────

_CANONICAL_ZERO = {
    "1d":  {"promote": 0, "reject": 0, "defer": 0, "unknown": 0},
    "7d":  {"promote": 0, "reject": 0, "defer": 0, "unknown": 0},
    "30d": {"promote": 0, "reject": 0, "defer": 0, "unknown": 0},
}

_API_SECRET = "test-gate-kpi-secret"


def _make_app(api_secret: str = _API_SECRET):
    """Reload cloud_app with given API_SECRET and return the FastAPI app.

    Follows the same reload pattern as tests/test_cloud_auth.py so that
    verify_auth dependency_overrides are wired correctly.
    """
    import importlib
    import src.api.app as cloud_mod
    with patch.dict(os.environ, {"API_SECRET": api_secret, "DATABASE_URL": ""}):
        importlib.reload(cloud_mod)
        return cloud_mod.app


def _auth_headers():
    return {"Authorization": f"Bearer {_API_SECRET}"}


def _seed_db(db_path: str, rows: list[dict]) -> None:
    """Create the strategy_promotion_events table and insert rows."""
    conn = sqlite3.connect(db_path)
    conn.execute(
        """CREATE TABLE IF NOT EXISTS strategy_promotion_events (
            id INTEGER PRIMARY KEY,
            triggered_by TEXT,
            timestamp TEXT,
            gate_result_json TEXT
        )"""
    )
    for row in rows:
        conn.execute(
            "INSERT INTO strategy_promotion_events (triggered_by, timestamp, gate_result_json) "
            "VALUES (?, ?, ?)",
            (row["triggered_by"], row["timestamp"], row.get("gate_result_json")),
        )
    conn.commit()
    conn.close()


def _gate_proposal_row(decision: str, timestamp: str) -> dict:
    """Build a gate_proposal row with given decision and timestamp."""
    return {
        "triggered_by": "gate_proposal",
        "timestamp": timestamp,
        "gate_result_json": json.dumps({"methodology_gate": {"decision": decision}}),
    }


def _operator_confirm_row(timestamp: str) -> dict:
    """Build an operator_confirm row (should NOT appear in gate-proposal counts)."""
    return {
        "triggered_by": "operator_confirm",
        "timestamp": timestamp,
        "gate_result_json": json.dumps({"methodology_gate": {"decision": "promote"}}),
    }


# Recent timestamps well within all three windows.
_TS_RECENT = "2026-05-06T10:00:00+00:00"


# ── Test 1: empty table → 200 + canonical zero shape ─────────────────────────

class TestRouteReturns200WhenTableEmpty:
    def test_route_returns_200_when_table_empty(self):
        with tempfile.NamedTemporaryFile(suffix=".sqlite3", delete=False) as f:
            db_path = f.name
        try:
            _seed_db(db_path, [])
            app = _make_app()
            client = TestClient(app)
            with patch(
                "src.analytics.kpis_compute.get_gate_proposal_counts",
                return_value=_CANONICAL_ZERO,
            ):
                resp = client.get(
                    "/api/kpis/gate-proposals",
                    headers=_auth_headers(),
                )
            assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
            data = resp.json()
            for window in ("1d", "7d", "30d"):
                assert window in data, f"Missing window key '{window}' in response"
                for decision in ("promote", "reject", "defer", "unknown"):
                    assert decision in data[window], (
                        f"Missing decision key '{decision}' under window '{window}'"
                    )
                    assert data[window][decision] == 0, (
                        f"Expected 0 for {window}.{decision}, got {data[window][decision]}"
                    )
        finally:
            os.unlink(db_path)


# ── Test 2: seeded rows → response matches direct compute output ──────────────

class TestRouteResponseMatchesKpisComputeOutput:
    def test_route_response_matches_kpis_compute_output(self):
        expected = {
            "1d":  {"promote": 1, "reject": 1, "defer": 1, "unknown": 0},
            "7d":  {"promote": 1, "reject": 1, "defer": 1, "unknown": 0},
            "30d": {"promote": 1, "reject": 1, "defer": 1, "unknown": 0},
        }
        app = _make_app()
        client = TestClient(app)
        with patch(
            "src.analytics.kpis_compute.get_gate_proposal_counts",
            return_value=expected,
        ):
            resp = client.get(
                "/api/kpis/gate-proposals",
                headers=_auth_headers(),
            )
        assert resp.status_code == 200
        data = resp.json()
        for window in ("1d", "7d", "30d"):
            assert data[window] == expected[window], (
                f"Window {window}: response {data[window]} != expected {expected[window]}"
            )


# ── Test 3: operator_confirm rows excluded ────────────────────────────────────

class TestRouteExcludesOperatorConfirmRows:
    def test_route_excludes_operator_confirm_rows(self):
        with tempfile.NamedTemporaryFile(suffix=".sqlite3", delete=False) as f:
            db_path = f.name
        try:
            rows = [
                _gate_proposal_row("promote", _TS_RECENT),
                _gate_proposal_row("promote", _TS_RECENT),
                _operator_confirm_row(_TS_RECENT),  # must NOT be counted
                _operator_confirm_row(_TS_RECENT),  # must NOT be counted
            ]
            _seed_db(db_path, rows)

            from src.analytics.kpis_compute import get_gate_proposal_counts
            counts = get_gate_proposal_counts(db_path)

            # Direct compute: 2 gate_proposals, 0 operator_confirm
            assert counts["1d"]["promote"] == 2, (
                f"Expected 2 promote in 1d, got {counts['1d']['promote']}"
            )
            assert counts["1d"]["reject"] == 0
            assert counts["1d"]["defer"] == 0
            assert counts["1d"]["unknown"] == 0

            # Route should return the same as direct compute
            app = _make_app()
            client = TestClient(app)
            with patch(
                "src.analytics.kpis_compute.get_gate_proposal_counts",
                return_value=counts,
            ):
                resp = client.get(
                    "/api/kpis/gate-proposals",
                    headers=_auth_headers(),
                )
            assert resp.status_code == 200
            data = resp.json()
            assert data["1d"]["promote"] == 2
            assert data["1d"]["reject"] == 0
        finally:
            os.unlink(db_path)


# ── Test 4: no auth header → 401 ─────────────────────────────────────────────

class TestRouteRequiresAuth:
    def test_route_requires_auth(self):
        app = _make_app()
        client = TestClient(app)
        resp = client.get("/api/kpis/gate-proposals")
        assert resp.status_code == 401, (
            f"Expected 401 without Authorization header, got {resp.status_code}"
        )

    def test_route_rejects_wrong_token(self):
        app = _make_app()
        client = TestClient(app)
        resp = client.get(
            "/api/kpis/gate-proposals",
            headers={"Authorization": "Bearer wrong-token-xyz"},
        )
        assert resp.status_code == 401, (
            f"Expected 401 with wrong token, got {resp.status_code}"
        )


# ── Test 5: missing table → graceful response ─────────────────────────────────

class TestRouteHandlesMissingTableGracefully:
    """Fresh SQLite without strategy_promotion_events table.

    Contract: route returns 200 with the canonical zero shape.
    Rationale: the underlying get_gate_proposal_counts raises OperationalError
    when the table is missing. The route catches this and returns zeros so the
    dashboard does not show an error card during fresh deployments before the
    table has been created.
    """

    def test_route_handles_missing_table_gracefully(self):
        with tempfile.NamedTemporaryFile(suffix=".sqlite3", delete=False) as f:
            db_path = f.name
        try:
            # Do NOT call _seed_db — table should not exist
            app = _make_app()
            client = TestClient(app)
            # Patch get_gate_proposal_counts to simulate missing-table path:
            # raise OperationalError (what sqlite3 raises on unknown table)
            import sqlite3 as _sqlite3
            with patch(
                "src.analytics.kpis_compute.get_gate_proposal_counts",
                side_effect=_sqlite3.OperationalError("no such table: strategy_promotion_events"),
            ):
                resp = client.get(
                    "/api/kpis/gate-proposals",
                    headers=_auth_headers(),
                )
            # Route must handle this gracefully — 200 with zero counts
            assert resp.status_code == 200, (
                f"Expected 200 on missing table, got {resp.status_code}: {resp.text}"
            )
            data = resp.json()
            for window in ("1d", "7d", "30d"):
                for decision in ("promote", "reject", "defer", "unknown"):
                    assert data[window][decision] == 0, (
                        f"Expected 0 for {window}.{decision} on missing table, "
                        f"got {data[window][decision]}"
                    )
        finally:
            os.unlink(db_path)
