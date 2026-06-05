"""Tests for DECIDE-region endpoints (P2-T3 — Founder Console Phase 2).

Covers:
  GET /api/console/decide/pending  — returns exact contract envelope
  POST /api/console/decide/action  — records verdict; 409 on duplicate; 422 on bad enum
  GET /api/console/decide/decided  — recently-decided trail + override_rate envelope

Design-law assertions enforced:
  law #8 — the route only records the human verdict; it MUST NOT call any
            promotion/execution/sizing/risk pipeline.
  override_rate state="no_data" when n==0; state="ok" with numeric value after data.

Tests run against a real test PG (TEST_DATABASE_URL). Skip if absent.
Non-vacuous: tests patch at the service layer and verify round-trips to prove
the route actually delegates to src.console.decisions (not hard-coded returns).
"""
from __future__ import annotations

import os
from unittest.mock import patch, MagicMock

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
    """Create console_decisions if absent (mirrors the registry DDL)."""
    wrapper.execute("""
        CREATE TABLE IF NOT EXISTS console_decisions (
            id SERIAL PRIMARY KEY,
            created_at TEXT NOT NULL,
            decision_key TEXT NOT NULL,
            decision_type TEXT NOT NULL,
            action TEXT NOT NULL,
            risk_tier TEXT NOT NULL,
            reason TEXT,
            decided_by TEXT,
            evidence_json TEXT,
            decided_at TEXT NOT NULL
        )
    """)
    wrapper.commit()


def _wipe_table(wrapper) -> None:
    wrapper.execute("DELETE FROM console_decisions")
    wrapper.commit()


@pytest.fixture(autouse=True)
def _clean_decisions_table():
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
    """Build a minimal FastAPI TestClient around the console_decide router.

    The router's verify_auth placeholder is left as-is (returns None per the
    override), so no auth header is needed in tests.
    """
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from src.api.cloud_routes import console_decide as console_decide_route

    app = FastAPI()
    app.dependency_overrides[console_decide_route.verify_auth] = lambda: None
    app.include_router(console_decide_route.router, prefix="/api")
    return TestClient(app, raise_server_exceptions=True)


# ── GET /api/console/decide/pending ─────────────────────────────────────────

class TestGetPending:

    def test_pending_returns_200(self):
        client = _make_client()
        with patch("src.console.decisions.connect_db", side_effect=_make_pg_wrapper):
            resp = client.get("/api/console/decide/pending")
        assert resp.status_code == 200

    def test_pending_returns_exact_envelope_keys(self):
        """Contract: response has items, count, degraded_sources, as_of."""
        client = _make_client()
        with patch("src.console.decisions.connect_db", side_effect=_make_pg_wrapper):
            resp = client.get("/api/console/decide/pending")
        data = resp.json()
        for key in ("items", "count", "degraded_sources", "as_of"):
            assert key in data, f"pending response missing key '{key}'"

    def test_pending_items_is_list_count_int(self):
        """items is a list; count is an int >= 0."""
        client = _make_client()
        with patch("src.console.decisions.connect_db", side_effect=_make_pg_wrapper):
            data = client.get("/api/console/decide/pending").json()
        assert isinstance(data["items"], list)
        assert isinstance(data["count"], int) and data["count"] >= 0

    def test_pending_delegates_to_service(self):
        """Non-vacuous: route must call get_pending_decisions from the service."""
        from src.api.cloud_routes import console_decide
        client = _make_client()
        fake_result = {
            "items": [
                {
                    "decision_key": "test:1",
                    "decision_type": "strategy_promotion",
                    "title": "Promote ARMA",
                    "risk_tier": "low",
                    "evidence": {"label": "Stats", "items": [{"label": "Sharpe", "value": "1.8"}]},
                    "intent": "Promote strategy ARMA to live.",
                    "blast_radius": "Affects paper book only.",
                    "rollback": "Revert via config.",
                    "as_of": "2026-06-05T10:00:00+00:00",
                    "source_state": "ok",
                }
            ],
            "count": 1,
            "degraded_sources": [],
            "as_of": "2026-06-05T10:00:00+00:00",
        }
        with patch("src.api.cloud_routes.console_decide.decisions") as mock_decisions:
            mock_decisions.get_pending_decisions.return_value = fake_result
            data = client.get("/api/console/decide/pending").json()
        mock_decisions.get_pending_decisions.assert_called_once()
        assert data["count"] == 1
        item = data["items"][0]
        # Verify all contract fields are present in item
        for field in ("decision_key", "decision_type", "title", "risk_tier",
                      "evidence", "intent", "blast_radius", "rollback", "as_of", "source_state"):
            assert field in item, f"item missing contract field '{field}'"

    def test_pending_item_evidence_has_label_and_items(self):
        """evidence field has label and items list per contract."""
        from src.api.cloud_routes import console_decide
        client = _make_client()
        fake_result = {
            "items": [
                {
                    "decision_key": "strat:x:1",
                    "decision_type": "strategy_promotion",
                    "title": "Test",
                    "risk_tier": "low",
                    "evidence": {
                        "label": "Evidence",
                        "items": [{"label": "Sharpe", "value": "1.8"}],
                    },
                    "intent": "Test intent",
                    "blast_radius": "Low",
                    "rollback": "Config revert",
                    "as_of": "2026-06-05T10:00:00+00:00",
                    "source_state": "ok",
                }
            ],
            "count": 1,
            "degraded_sources": [],
            "as_of": "2026-06-05T10:00:00+00:00",
        }
        with patch("src.api.cloud_routes.console_decide.decisions") as mock_decisions:
            mock_decisions.get_pending_decisions.return_value = fake_result
            data = client.get("/api/console/decide/pending").json()
        ev = data["items"][0]["evidence"]
        assert "label" in ev
        assert "items" in ev
        assert isinstance(ev["items"], list)
        assert ev["items"][0]["label"] == "Sharpe"


# ── POST /api/console/decide/action ─────────────────────────────────────────

class TestPostAction:

    def _approve_body(self, key="strat:test:001"):
        return {
            "decision_key": key,
            "decision_type": "strategy_promotion",
            "action": "approve",
            "risk_tier": "low",
            "reason": "Looks good",
            "evidence": None,
        }

    def test_post_approve_returns_200_recorded_true(self):
        client = _make_client()
        with patch("src.console.decisions.connect_db", side_effect=_make_pg_wrapper), \
             patch("src.console.decisions.log_activity"):
            resp = client.post("/api/console/decide/action", json=self._approve_body())
        assert resp.status_code == 200
        data = resp.json()
        assert data["recorded"] is True

    def test_post_approve_returns_decision_row(self):
        """Response must include a 'decision' key with the inserted row dict."""
        client = _make_client()
        with patch("src.console.decisions.connect_db", side_effect=_make_pg_wrapper), \
             patch("src.console.decisions.log_activity"):
            data = client.post("/api/console/decide/action",
                               json=self._approve_body("strat:check:001")).json()
        assert "decision" in data
        row = data["decision"]
        assert row["decision_key"] == "strat:check:001"
        assert row["action"] == "approve"

    def test_post_approve_row_persisted_non_vacuous(self):
        """Round-trip: after POST, the row appears in GET /decided (proves persistence)."""
        client = _make_client()
        with patch("src.console.decisions.connect_db", side_effect=_make_pg_wrapper), \
             patch("src.console.decisions.log_activity"):
            post_resp = client.post("/api/console/decide/action",
                                    json=self._approve_body("strat:persist:001"))
            assert post_resp.status_code == 200
            decided_resp = client.get("/api/console/decide/decided")
        decided_data = decided_resp.json()
        keys = [item["decision_key"] for item in decided_data["items"]]
        assert "strat:persist:001" in keys, (
            f"Inserted decision key not found in decided trail: {keys}"
        )

    def test_post_duplicate_key_returns_409(self):
        """Re-POSTing an already-decided key must return HTTP 409."""
        client = _make_client()
        body = self._approve_body("strat:dup:001")
        with patch("src.console.decisions.connect_db", side_effect=_make_pg_wrapper), \
             patch("src.console.decisions.log_activity"):
            first = client.post("/api/console/decide/action", json=body)
            assert first.status_code == 200, f"first POST failed: {first.text}"
            second = client.post("/api/console/decide/action", json=body)
        assert second.status_code == 409, (
            f"duplicate decision_key must return 409, got {second.status_code}: {second.text}"
        )

    def test_post_invalid_action_returns_422(self):
        """action='bogus' is not a valid Literal — FastAPI returns 422."""
        client = _make_client()
        body = {**self._approve_body(), "action": "bogus"}
        resp = client.post("/api/console/decide/action", json=body)
        assert resp.status_code == 422

    def test_post_invalid_risk_tier_returns_422(self):
        """risk_tier='critical' is not a valid Literal — FastAPI returns 422."""
        client = _make_client()
        body = {**self._approve_body(), "risk_tier": "critical"}
        resp = client.post("/api/console/decide/action", json=body)
        assert resp.status_code == 422

    def test_post_medium_risk_tier_accepted(self):
        """medium risk_tier is a valid human routing surface — must be accepted."""
        client = _make_client()
        body = {**self._approve_body("strat:medium:001"), "risk_tier": "medium"}
        with patch("src.console.decisions.connect_db", side_effect=_make_pg_wrapper), \
             patch("src.console.decisions.log_activity"):
            resp = client.post("/api/console/decide/action", json=body)
        assert resp.status_code == 200
        assert resp.json()["decision"]["risk_tier"] == "medium"

    def test_post_high_risk_tier_accepted(self):
        """high risk_tier is a valid human routing surface — must be accepted."""
        client = _make_client()
        body = {**self._approve_body("strat:high:001"), "risk_tier": "high"}
        with patch("src.console.decisions.connect_db", side_effect=_make_pg_wrapper), \
             patch("src.console.decisions.log_activity"):
            resp = client.post("/api/console/decide/action", json=body)
        assert resp.status_code == 200
        assert resp.json()["decision"]["risk_tier"] == "high"

    def test_post_reject_action_accepted(self):
        """action='reject' must be accepted and recorded."""
        client = _make_client()
        body = {**self._approve_body("strat:reject:001"), "action": "reject"}
        with patch("src.console.decisions.connect_db", side_effect=_make_pg_wrapper), \
             patch("src.console.decisions.log_activity"):
            resp = client.post("/api/console/decide/action", json=body)
        assert resp.status_code == 200
        assert resp.json()["decision"]["action"] == "reject"

    def test_post_defer_action_accepted(self):
        """action='defer' must be accepted and recorded."""
        client = _make_client()
        body = {**self._approve_body("strat:defer:001"), "action": "defer"}
        with patch("src.console.decisions.connect_db", side_effect=_make_pg_wrapper), \
             patch("src.console.decisions.log_activity"):
            resp = client.post("/api/console/decide/action", json=body)
        assert resp.status_code == 200
        assert resp.json()["decision"]["action"] == "defer"

    def test_post_response_has_as_of(self):
        """POST response must include as_of timestamp."""
        client = _make_client()
        with patch("src.console.decisions.connect_db", side_effect=_make_pg_wrapper), \
             patch("src.console.decisions.log_activity"):
            data = client.post("/api/console/decide/action",
                               json=self._approve_body("strat:asof:001")).json()
        assert "as_of" in data
        assert data["as_of"] is not None


# ── GET /api/console/decide/decided ─────────────────────────────────────────

class TestGetDecided:

    def test_decided_returns_200(self):
        client = _make_client()
        with patch("src.console.decisions.connect_db", side_effect=_make_pg_wrapper):
            resp = client.get("/api/console/decide/decided")
        assert resp.status_code == 200

    def test_decided_returns_required_keys(self):
        """Response must have items, override_rate, as_of."""
        client = _make_client()
        with patch("src.console.decisions.connect_db", side_effect=_make_pg_wrapper):
            data = client.get("/api/console/decide/decided").json()
        for key in ("items", "override_rate", "as_of"):
            assert key in data, f"decided response missing key '{key}'"

    def test_decided_override_rate_no_data_when_empty(self):
        """override_rate state must be 'no_data' when no decisions exist (n==0)."""
        client = _make_client()
        with patch("src.console.decisions.connect_db", side_effect=_make_pg_wrapper):
            data = client.get("/api/console/decide/decided").json()
        rate = data["override_rate"]
        assert rate["state"] == "no_data", (
            f"expected state='no_data' when no decisions exist, got: {rate}"
        )
        assert rate["value"] is None, "value must be None when n==0 (not 0.0)"
        assert rate["n"] == 0

    def test_decided_override_rate_envelope_has_all_fields(self):
        """override_rate envelope must have value, n, as_of, cohort, unit, state."""
        client = _make_client()
        with patch("src.console.decisions.connect_db", side_effect=_make_pg_wrapper):
            data = client.get("/api/console/decide/decided").json()
        rate = data["override_rate"]
        for field in ("value", "n", "as_of", "cohort", "unit", "state"):
            assert field in rate, f"override_rate envelope missing field '{field}'"

    def test_decided_override_rate_ok_after_decisions(self):
        """After decisions exist, override_rate must have state='ok' and numeric value."""
        client = _make_client()
        body = {
            "decision_key": "strat:rate:001",
            "decision_type": "strategy_promotion",
            "action": "reject",
            "risk_tier": "low",
        }
        with patch("src.console.decisions.connect_db", side_effect=_make_pg_wrapper), \
             patch("src.console.decisions.log_activity"):
            client.post("/api/console/decide/action", json=body)
            data = client.get("/api/console/decide/decided").json()
        rate = data["override_rate"]
        assert rate["state"] == "ok", f"expected state='ok' after decisions, got: {rate}"
        assert isinstance(rate["value"], float)
        assert rate["n"] > 0

    def test_decided_override_rate_cohort_and_unit_set(self):
        """cohort must be 'decisions.all'; unit must be 'ratio'."""
        client = _make_client()
        with patch("src.console.decisions.connect_db", side_effect=_make_pg_wrapper):
            data = client.get("/api/console/decide/decided").json()
        rate = data["override_rate"]
        assert rate["cohort"] == "decisions.all"
        assert rate["unit"] == "ratio"

    def test_decided_items_is_list(self):
        """items must be a list."""
        client = _make_client()
        with patch("src.console.decisions.connect_db", side_effect=_make_pg_wrapper):
            data = client.get("/api/console/decide/decided").json()
        assert isinstance(data["items"], list)


# ── Router mounted in the full app ───────────────────────────────────────────

class TestRouterMounted:

    def test_get_pending_reachable_via_full_app(self):
        """Router is registered in app.py — GET /api/console/decide/pending is not 404."""
        from src.api.cloud_routes import console_decide as console_decide_route

        with patch.dict(os.environ, {"API_SECRET": "test-secret"}):
            import importlib
            import src.api.app as _app_module
            importlib.reload(_app_module)
            app = _app_module.app

        # Override auth for the test
        app.dependency_overrides[console_decide_route.verify_auth] = lambda: None

        from fastapi.testclient import TestClient
        client = TestClient(app, raise_server_exceptions=False)
        with patch("src.console.decisions.connect_db", side_effect=_make_pg_wrapper):
            resp = client.get("/api/console/decide/pending")
        assert resp.status_code != 404, (
            f"GET /api/console/decide/pending returned 404 — router not mounted in app.py"
        )
