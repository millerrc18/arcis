"""Tests for the Render cloud API (read-only FastAPI)."""

import os
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


# ── Fixtures ─────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def set_env(monkeypatch):
    """Set DATABASE_URL for all tests."""
    monkeypatch.setenv("DATABASE_URL", "postgresql://test:test@localhost/halcyon")
    monkeypatch.delenv("API_SECRET", raising=False)


@pytest.fixture
def client():
    """Create a test client for the cloud API."""
    # Re-import to pick up env vars and ensure API_SECRET is cleared
    import importlib
    import src.api.cloud_app as cloud_mod
    importlib.reload(cloud_mod)
    return TestClient(cloud_mod.app)


@pytest.fixture
def authed_client(monkeypatch):
    """Create a test client with API_SECRET set."""
    monkeypatch.setenv("API_SECRET", "test-secret-token")
    # Must re-import to pick up the new env var
    import importlib
    import src.api.cloud_app as cloud_mod
    importlib.reload(cloud_mod)
    return TestClient(cloud_mod.app)


# ── Mock helpers ─────────────────────────────────────────────────────

def _mock_query(return_value):
    """Return a patch for _query that returns the given value."""
    return patch("src.api.cloud_app._query", return_value=return_value)


def _mock_query_one(return_value):
    """Return a patch for _query_one that returns the given value."""
    return patch("src.api.cloud_app._query_one", return_value=return_value)


# ── Status endpoint ──────────────────────────────────────────────────

class TestStatusEndpoint:
    """Tests for /api/status."""

    @patch("src.api.cloud_app._query_one")
    @patch("src.api.cloud_app._query")
    def test_status_returns_structure(self, mock_query, mock_query_one, client):
        mock_query.return_value = [{"count": 3}]
        # _query_one: latest_model, latest_audit, training_examples count
        mock_query_one.side_effect = [
            {"version_name": "v1.0", "created_at": "2025-01-01", "status": "active"},
            {"overall_assessment": "green", "created_at": "2025-01-01"},
            {"c": 978},
        ]

        resp = client.get("/api/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["environment"] == "cloud"
        assert "open_positions" in data
        assert "timestamp" in data
        assert data["llm_available"] is False
        assert data["model_version"] == "v1.0"
        assert data["training_examples"] == 978

    @patch("src.api.cloud_app._query_one")
    @patch("src.api.cloud_app._query")
    def test_status_handles_db_error(self, mock_query, mock_query_one, client):
        mock_query.side_effect = Exception("connection error")

        resp = client.get("/api/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "error" in data


# ── Shadow trade endpoints ───────────────────────────────────────────

class TestShadowEndpoints:
    """Tests for shadow trading endpoints."""

    @patch("src.api.cloud_app._query_one")
    @patch("src.api.cloud_app._query")
    def test_shadow_open_returns_trades(self, mock_query, mock_one, client):
        mock_query.return_value = [
            {"trade_id": "t1", "ticker": "AAPL", "status": "open"},
        ]
        mock_one.return_value = {"total": 500}
        resp = client.get("/api/shadow/open")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 1
        assert data["open_count"] == 1
        assert data["trades"][0]["ticker"] == "AAPL"
        assert data["account_equity"] == 100500

    @patch("src.api.cloud_app._query")
    def test_shadow_closed_accepts_days_param(self, mock_query, client):
        mock_query.return_value = []
        resp = client.get("/api/shadow/closed?days=7")
        assert resp.status_code == 200
        data = resp.json()
        assert data["days"] == 7

    @patch("src.api.cloud_app._query")
    def test_shadow_metrics_computes_stats(self, mock_query, client):
        mock_query.return_value = [
            {"pnl_dollars": 100.0, "pnl_pct": 5.0},
            {"pnl_dollars": -50.0, "pnl_pct": -2.5},
            {"pnl_dollars": 75.0, "pnl_pct": 3.0},
        ]
        resp = client.get("/api/shadow/metrics")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_trades"] == 3
        assert data["wins"] == 2
        assert data["losses"] == 1
        assert data["total_pnl"] == 125.0


# ── Packets endpoint ─────────────────────────────────────────────────

class TestPacketsEndpoint:
    """Tests for /api/packets."""

    @patch("src.api.cloud_app._query")
    def test_packets_returns_list(self, mock_query, client):
        mock_query.return_value = [
            {"recommendation_id": "r1", "ticker": "AAPL", "created_at": "2025-01-01"},
        ]
        resp = client.get("/api/packets")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1


# ── Training endpoints ───────────────────────────────────────────────

class TestTrainingEndpoints:
    """Tests for training endpoints."""

    @patch("src.api.cloud_app._query")
    @patch("src.api.cloud_app._query_one")
    def test_training_status(self, mock_one, mock_query, client):
        # _query_one is called: active_model, total_examples, win_examples, loss_examples, synthetic_examples
        mock_one.side_effect = [
            {"version_name": "v1.0", "status": "active"},  # active_model
            {"c": 978},    # total_examples
            {"c": 200},    # win_examples
            {"c": 100},    # loss_examples
            {"c": 5},      # synthetic_examples
        ]
        mock_query.return_value = [{"count": 5}]

        resp = client.get("/api/training/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "active_model" in data
        assert data["model_name"] == "v1.0"
        assert data["dataset_total"] == 978
        assert data["total_versions"] == 5

    @patch("src.api.cloud_app._query")
    def test_training_versions(self, mock_query, client):
        mock_query.return_value = [
            {"version_id": "v1", "version_name": "v1.0"},
            {"version_id": "v2", "version_name": "v2.0"},
        ]
        resp = client.get("/api/training/versions")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["versions"]) == 2


# ── Metrics endpoint ─────────────────────────────────────────────────

class TestMetricsEndpoint:
    """Tests for /api/metrics/history."""

    @patch("src.api.cloud_app._query")
    def test_metrics_history(self, mock_query, client):
        mock_query.return_value = [
            {"snapshot_id": "s1", "metrics_json": '{"win_rate": 0.6}', "created_at": "2025-01-01"},
        ]
        resp = client.get("/api/metrics/history")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        # JSON field should be parsed
        assert data[0]["metrics_json"] == {"win_rate": 0.6}


# ── Analytics stub endpoints ────────────────────────────────────────

class TestAnalyticsStubEndpoints:
    """Tests for new analytics stub endpoints."""

    def test_build_score_stub_shape(self, client):
        resp = client.get("/api/build-score")
        assert resp.status_code == 200
        data = resp.json()
        assert data["build_score"] == 0
        assert data["delta_7d"] == 0
        assert data["components"]["gate_velocity"] == 0
        assert data["phase_progress"]["trades_required"] == 50
        assert data["history_7d"] == []

    def test_traffic_light_current_stub_shape(self, client):
        resp = client.get("/api/traffic-light/current")
        assert resp.status_code == 200
        data = resp.json()
        assert data == {"regime": "UNKNOWN", "score": 0, "vix": 0}


# ── Schedule metrics endpoint ────────────────────────────────────────

class TestScheduleMetricsEndpoint:
    """Tests for /api/schedule-metrics."""

    @patch("src.api.cloud_app._query")
    def test_schedule_metrics(self, mock_query, client):
        mock_query.return_value = [
            {"metric_date": "2025-01-01", "metric_name": "gpu_util", "metric_value": 85.0},
        ]
        resp = client.get("/api/schedule-metrics")
        assert resp.status_code == 200
        assert len(resp.json()) == 1


# ── Earnings endpoint ────────────────────────────────────────────────

class TestEarningsEndpoint:
    """Tests for /api/earnings."""

    @patch("src.api.cloud_app._query")
    def test_earnings(self, mock_query, client):
        mock_query.return_value = [
            {"ticker": "AAPL", "earnings_date": "2025-01-25", "earnings_time": "AMC"},
        ]
        resp = client.get("/api/earnings")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 1
        assert data["earnings"][0]["ticker"] == "AAPL"


# ── Audit endpoint ───────────────────────────────────────────────────

class TestAuditEndpoint:
    """Tests for /api/audit/latest."""

    @patch("src.api.cloud_app._query_one")
    def test_audit_latest(self, mock_one, client):
        mock_one.return_value = {
            "audit_id": "a1",
            "overall_assessment": "healthy",
            "flags": '["flag1"]',
            "metrics_to_watch": '{"win_rate": 0.55}',
        }
        resp = client.get("/api/audit/latest")
        assert resp.status_code == 200
        data = resp.json()
        assert data["overall_assessment"] == "healthy"
        assert data["flags"] == ["flag1"]

    @patch("src.api.cloud_app._query_one")
    def test_audit_latest_empty(self, mock_one, client):
        mock_one.return_value = None
        resp = client.get("/api/audit/latest")
        assert resp.status_code == 200
        assert resp.json()["audit"] is None


# ── Docs endpoint ────────────────────────────────────────────────────

class TestDocsEndpoint:
    """Tests for /api/docs."""

    @patch("src.api.cloud_app._query")
    def test_docs_returns_array(self, mock_query, client):
        mock_query.return_value = [
            {"id": "abc123", "filename": "docs/architecture.md", "title": "Architecture", "category": "Core", "size_kb": 10, "updated_at": "2026-03-27"},
        ]
        resp = client.get("/api/docs")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) > 0
        assert "id" in data[0]
        assert "title" in data[0]

    @patch("src.api.cloud_app._query_one")
    def test_docs_single_doc(self, mock_one, client):
        mock_one.return_value = {"id": "abc123", "title": "Architecture", "category": "Core", "content": "# Architecture\n\nTest doc content"}
        resp = client.get("/api/docs/abc123")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == "abc123"
        assert "content" in data


# ── Council endpoints ────────────────────────────────────────────────

class TestCouncilEndpoints:
    """Tests for council endpoints."""

    @patch("src.api.cloud_app._query")
    @patch("src.api.cloud_app._query_one")
    def test_council_latest_with_votes(self, mock_one, mock_query, client):
        mock_one.return_value = {
            "session_id": "s1",
            "session_type": "weekly",
            "consensus": "bullish",
        }
        mock_query.return_value = [
            {"vote_id": "v1", "agent_name": "technician", "key_data_points": None, "risk_flags": None},
        ]
        resp = client.get("/api/council/latest")
        assert resp.status_code == 200
        data = resp.json()
        assert data["session_id"] == "s1"
        assert len(data["votes"]) == 1

    @patch("src.api.cloud_app._query_one")
    def test_council_latest_empty(self, mock_one, client):
        mock_one.return_value = None
        resp = client.get("/api/council/latest")
        assert resp.status_code == 200
        assert resp.json()["session"] is None

    @patch("src.api.cloud_app._query")
    def test_council_history(self, mock_query, client):
        mock_query.return_value = [
            {"session_id": "s1", "created_at": "2025-01-01"},
        ]
        resp = client.get("/api/council/history")
        assert resp.status_code == 200
        assert len(resp.json()) == 1


# ── Auth tests ───────────────────────────────────────────────────────

class TestAuth:
    """Tests for bearer token authentication."""

    def test_no_auth_required_when_no_secret(self, client):
        """When API_SECRET is not set, all endpoints are accessible."""
        with patch("src.api.cloud_app._query", return_value=[{"count": 0}]), \
             patch("src.api.cloud_app._query_one", return_value=None):
            resp = client.get("/api/status")
            assert resp.status_code == 200

    def test_auth_required_when_secret_set(self, monkeypatch):
        """When API_SECRET is set, requests without token get 401."""
        monkeypatch.setenv("API_SECRET", "my-secret")
        import importlib
        import src.api.cloud_app as cloud_mod
        importlib.reload(cloud_mod)

        test_client = TestClient(cloud_mod.app)
        resp = test_client.get("/api/status")
        assert resp.status_code == 401

    def test_auth_succeeds_with_correct_token(self, monkeypatch):
        """Correct bearer token grants access."""
        monkeypatch.setenv("API_SECRET", "my-secret")
        import importlib
        import src.api.cloud_app as cloud_mod
        importlib.reload(cloud_mod)

        test_client = TestClient(cloud_mod.app)
        with patch.object(cloud_mod, "_query", return_value=[{"count": 0}]), \
             patch.object(cloud_mod, "_query_one", return_value=None):
            resp = test_client.get(
                "/api/status",
                headers={"Authorization": "Bearer my-secret"},
            )
            assert resp.status_code == 200

    def test_auth_fails_with_wrong_token(self, monkeypatch):
        """Wrong bearer token gets 401."""
        monkeypatch.setenv("API_SECRET", "my-secret")
        import importlib
        import src.api.cloud_app as cloud_mod
        importlib.reload(cloud_mod)

        test_client = TestClient(cloud_mod.app)
        resp = test_client.get(
            "/api/status",
            headers={"Authorization": "Bearer wrong-token"},
        )
        assert resp.status_code == 401


# ── POST stub tests ──────────────────────────────────────────────────

CLOUD_POST_STUBS = [
    "/api/actions/scan",
    "/api/actions/cto-report",
    "/api/actions/collect-data",
    "/api/actions/collect-training",
    "/api/actions/train-pipeline",
    "/api/actions/score",
    "/api/actions/council",
    "/api/halt-trading",
    "/api/resume-trading",
    "/api/training/train",
    "/api/training/bootstrap",
    "/api/training/rollback",
    "/api/shadow/close/AAPL",
]

ALLOWED_CLOUD_PUT_ENDPOINTS = ["/api/notes/{note_id}"]
ALLOWED_CLOUD_DELETE_ENDPOINTS = ["/api/notes/{note_id}"]

class TestPostStubs:
    """Verify POST action stubs return cloud_mode error."""

    def test_post_stubs_return_cloud_mode(self, client):
        """All POST stubs should return cloud_mode error."""
        for path in CLOUD_POST_STUBS:
            resp = client.post(path)
            assert resp.status_code == 200, f"{path}: {resp.status_code}"
            data = resp.json()
            assert data.get("error") == "cloud_mode", f"{path}: {data}"

    def test_no_put_endpoints(self, client):
        """Cloud API should only expose the expected Notes PUT endpoint."""
        routes = client.app.routes
        put_routes = []
        for route in routes:
            if hasattr(route, "methods") and "PUT" in route.methods:
                put_routes.append(route.path)
        assert sorted(put_routes) == ALLOWED_CLOUD_PUT_ENDPOINTS, f"Unexpected PUT endpoints: {put_routes}"

    def test_no_delete_endpoints(self, client):
        """Cloud API should only expose the expected Notes DELETE endpoint."""
        routes = client.app.routes
        delete_routes = []
        for route in routes:
            if hasattr(route, "methods") and "DELETE" in route.methods:
                delete_routes.append(route.path)
        assert sorted(delete_routes) == ALLOWED_CLOUD_DELETE_ENDPOINTS, f"Unexpected DELETE endpoints: {delete_routes}"


# ── New endpoint tests ───────────────────────────────────────────────

class TestNewEndpoints:
    """Tests for all new cloud API endpoints."""

    def test_config_returns_sections(self, client):
        resp = client.get("/api/config")
        assert resp.status_code == 200
        data = resp.json()
        assert "risk" in data
        assert "shadow_trading" in data
        assert "llm" in data
        assert data["environment"] == "cloud"

    def test_halt_status(self, client):
        resp = client.get("/api/halt-status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["halted"] is False

    def test_costs_no_db(self, client):
        resp = client.get("/api/costs")
        assert resp.status_code == 200
        data = resp.json()
        assert "total_cost" in data
        assert data["total_cost"] == 0

    @patch("src.api.cloud_app._query_one")
    def test_health_score(self, mock_one, client):
        mock_one.return_value = {"count": 10}
        resp = client.get("/api/health/score")
        assert resp.status_code == 200
        data = resp.json()
        assert "score" in data

    @patch("src.api.cloud_app._query")
    def test_shadow_account(self, mock_query, client):
        mock_query.return_value = []
        resp = client.get("/api/shadow/account")
        assert resp.status_code == 200

    @patch("src.api.cloud_app._ensure_user_notes_table")
    @patch("src.api.cloud_app._query")
    def test_notes_list(self, mock_query, mock_ensure, client):
        mock_query.return_value = [
            {
                "note_id": "n1",
                "title": "Watchlist",
                "content": "Check event risk",
                "tags": '["ops","risk"]',
                "pinned": 1,
                "created_at": "2026-03-29T09:00:00-04:00",
                "updated_at": "2026-03-29T09:05:00-04:00",
            }
        ]
        resp = client.get("/api/notes")
        assert resp.status_code == 200
        data = resp.json()
        assert data["notes"][0]["note_id"] == "n1"
        assert data["notes"][0]["tags"] == ["ops", "risk"]
        assert data["notes"][0]["pinned"] is True

    @patch("src.api.cloud_app._ensure_user_notes_table")
    @patch("src.api.cloud_app.get_pg")
    def test_create_note_with_tags(self, mock_get_pg, mock_ensure, client):
        mock_cursor = MagicMock()
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_get_pg.return_value.__enter__.return_value = mock_conn

        resp = client.post(
            "/api/notes",
            json={
                "title": "Morning prep",
                "content": "Review brackets",
                "tags": "ops, risk,  journal ",
                "pinned": True,
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["title"] == "Morning prep"
        assert data["tags"] == ["ops", "risk", "journal"]
        assert data["pinned"] is True
        insert_sql = mock_cursor.execute.call_args.args[0]
        insert_params = mock_cursor.execute.call_args.args[1]
        assert "INSERT INTO user_notes" in insert_sql
        assert insert_params[3] == '["ops", "risk", "journal"]'

    @patch("src.api.cloud_app._ensure_user_notes_table")
    @patch("src.api.cloud_app._query_one")
    @patch("src.api.cloud_app.get_pg")
    def test_update_note(self, mock_get_pg, mock_query_one, mock_ensure, client):
        mock_cursor = MagicMock()
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_get_pg.return_value.__enter__.return_value = mock_conn
        mock_query_one.return_value = {
            "note_id": "n1",
            "title": "Updated",
            "content": "Re-check CPI",
            "tags": '["macro"]',
            "pinned": 0,
            "created_at": "2026-03-29T09:00:00-04:00",
            "updated_at": "2026-03-29T09:10:00-04:00",
        }

        resp = client.put(
            "/api/notes/n1",
            json={"title": "Updated", "content": "Re-check CPI", "tags": ["macro"]},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["note_id"] == "n1"
        assert data["tags"] == ["macro"]
        update_sql = mock_cursor.execute.call_args.args[0]
        assert update_sql.startswith("UPDATE user_notes SET")

    @patch("src.api.cloud_app._ensure_user_notes_table")
    @patch("src.api.cloud_app.get_pg")
    def test_delete_note(self, mock_get_pg, mock_ensure, client):
        mock_cursor = MagicMock()
        mock_cursor.rowcount = 1
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_get_pg.return_value.__enter__.return_value = mock_conn

        resp = client.delete("/api/notes/n1")
        assert resp.status_code == 204
        delete_sql = mock_cursor.execute.call_args.args[0]
        assert delete_sql == "DELETE FROM user_notes WHERE note_id = %s"

    @patch("src.api.cloud_app._query_one")
    @patch("src.api.cloud_app._query")
    def test_cto_report(self, mock_query, mock_one, client):
        mock_query.return_value = []
        mock_one.return_value = {"c": 0}
        resp = client.get("/api/cto-report")
        assert resp.status_code == 200
        data = resp.json()
        assert "trade_summary" in data

    def test_scan_latest_no_db(self, client):
        resp = client.get("/api/scan/latest")
        assert resp.status_code == 200

    def test_review_pending_no_db(self, client):
        resp = client.get("/api/review/pending")
        assert resp.status_code == 200

    def test_review_scorecard(self, client):
        resp = client.get("/api/review/scorecard")
        assert resp.status_code == 200
        assert resp.json()["weeks"] == 4

    def test_review_postmortems(self, client):
        resp = client.get("/api/review/postmortems")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_audit_history_no_db(self, client):
        resp = client.get("/api/audit/history")
        assert resp.status_code == 200

    def test_training_report_no_db(self, client):
        resp = client.get("/api/training/report")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_examples"] == 0

    def test_metric_history_no_db(self, client):
        resp = client.get("/api/metric-history")
        assert resp.status_code in (200, 503)  # 503 when no Postgres available


# ── Untested endpoint coverage ──────────────────────────────────────


class TestActivityFeed:
    """Tests for /api/activity/feed."""

    @patch("src.api.cloud_app._query")
    def test_activity_feed_returns_list(self, mock_query, client):
        mock_query.return_value = [
            {"id": 1, "event_type": "trade_open", "detail": "LIN", "created_at": "2026-03-27"},
        ]
        r = client.get("/api/activity/feed?limit=10")
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)
        assert len(data) == 1

    @patch("src.api.cloud_app._query")
    def test_activity_feed_empty(self, mock_query, client):
        mock_query.return_value = []
        r = client.get("/api/activity/feed")
        assert r.status_code == 200
        assert r.json() == []

    @patch("src.api.cloud_app._query")
    def test_activity_feed_with_event_type_filter(self, mock_query, client):
        mock_query.return_value = []
        r = client.get("/api/activity/feed?event_type=trade_open")
        assert r.status_code == 200
        assert isinstance(r.json(), list)


class TestLiveTrades:
    """Tests for /api/live/trades and /api/live/summary."""

    @patch("src.api.cloud_app._query")
    def test_live_trades_returns_open_and_closed(self, mock_query, client):
        mock_query.side_effect = [
            [{"ticker": "AAPL", "status": "open", "source": "live"}],
            [],
        ]
        r = client.get("/api/live/trades")
        assert r.status_code == 200
        data = r.json()
        assert "open" in data
        assert "closed" in data

    @patch("src.api.cloud_app._query_one")
    @patch("src.api.cloud_app._query")
    def test_live_summary_returns_metrics(self, mock_query, mock_one, client):
        mock_query.return_value = []
        mock_one.return_value = {"c": 0}
        r = client.get("/api/live/summary")
        assert r.status_code == 200
        data = r.json()
        assert "starting_capital" in data
        assert "current_equity" in data

    @patch("src.api.cloud_app._query_one")
    @patch("src.api.cloud_app._query")
    def test_live_summary_with_closed_trades(self, mock_query, mock_one, client):
        mock_query.return_value = [{"pnl_dollars": 5.0, "pnl_pct": 2.0}]
        mock_one.return_value = {"c": 1}
        r = client.get("/api/live/summary")
        data = r.json()
        assert data["total_pnl"] == 5.0
        assert data["open_positions"] == 1


class TestCouncilSessionDetail:
    """Tests for /api/council/session/{id}."""

    @patch("src.api.cloud_app._query")
    @patch("src.api.cloud_app._query_one")
    def test_council_session_detail_returns_votes(self, mock_one, mock_query, client):
        mock_one.return_value = {"session_id": "abc", "session_type": "daily", "agent_count": 5}
        mock_query.return_value = [
            {"agent_name": "Bull", "position": "BULLISH", "confidence": 0.8},
        ]
        r = client.get("/api/council/session/abc")
        assert r.status_code == 200
        data = r.json()
        assert "session" in data
        assert "votes" in data

    @patch("src.api.cloud_app._query_one")
    def test_council_session_not_found(self, mock_one, client):
        mock_one.return_value = None
        r = client.get("/api/council/session/nonexistent")
        assert r.status_code == 404


class TestHealthScore:
    """Tests for /api/health/score."""

    @patch("src.api.cloud_app._query_one")
    @patch("src.api.cloud_app._query")
    def test_health_score_returns_all_dimensions(self, mock_query, mock_one, client):
        mock_query.side_effect = [
            [{"pnl_dollars": 100, "pnl_pct": 4.0}, {"pnl_dollars": -50, "pnl_pct": -2.0}],
            [{"source": "backfill", "cnt": 700}, {"source": "blinded_win", "cnt": 200}],
        ]
        mock_one.side_effect = [
            {"c": 18}, {"count": 969}, None, None,
            {"llm_success": 17, "llm_total": 20},
            {"cnt": 3}, {"cnt": 50},
        ]
        r = client.get("/api/health/score")
        assert r.status_code == 200
        data = r.json()
        score = data.get("score", data)
        assert "overall" in score
        assert "dimensions" in score
        dims = score["dimensions"]
        for key in ["performance", "model_quality", "data_asset", "flywheel_velocity", "defensibility"]:
            assert key in dims
            assert isinstance(dims[key], (int, float)), f"{key} is not numeric"

    @patch("src.api.cloud_app._query_one")
    @patch("src.api.cloud_app._query")
    def test_health_score_handles_empty_db(self, mock_query, mock_one, client):
        mock_query.side_effect = [[], []]
        mock_one.side_effect = [{"c": 0}, {"count": 0}, None, None, None, {"cnt": 0}, {"cnt": 0}]
        r = client.get("/api/health/score")
        assert r.status_code == 200


class TestSettings:
    """Tests for /api/settings."""

    def test_settings_returns_safe_config(self, client):
        r = client.get("/api/settings")
        assert r.status_code == 200
        data = r.json()
        flat = str(data).lower()
        assert "api_key" not in flat
        assert "password" not in flat
        assert "secret" not in flat

    def test_settings_post_returns_cloud_mode(self, client):
        r = client.post("/api/settings")
        assert r.status_code == 200
        assert r.json()["error"] == "cloud_mode"


class TestMarketOverview:
    """Tests for /api/market/overview."""

    @patch("src.api.cloud_app._query")
    @patch("src.api.cloud_app._query_one")
    def test_market_overview(self, mock_one, mock_query, client):
        mock_one.return_value = {"vix_close": 18.5}
        mock_query.return_value = [{"series_id": "DFF", "value": 4.5}]
        r = client.get("/api/market/overview")
        assert r.status_code == 200
        data = r.json()
        assert "vix" in data
        assert "macro" in data


class TestDataAssetGrowth:
    """Tests for /api/data-asset/growth."""

    @patch("src.api.cloud_app._query")
    def test_data_asset_growth(self, mock_query, client):
        mock_query.return_value = [{"date": "2026-03-27", "count": 5}]
        r = client.get("/api/data-asset/growth")
        assert r.status_code == 200
        data = r.json()
        assert "daily_counts" in data


class TestJournal:
    """Tests for /api/journal."""

    @patch("src.api.cloud_app._query")
    def test_journal(self, mock_query, client):
        mock_query.return_value = []
        r = client.get("/api/journal")
        assert r.status_code == 200
        data = r.json()
        assert "trades" in data
        assert "count" in data


class TestSignalZoo:
    """Tests for /api/signal-zoo."""

    @patch("src.api.cloud_app._query")
    def test_signal_zoo(self, mock_query, client):
        mock_query.return_value = []
        r = client.get("/api/signal-zoo")
        assert r.status_code == 200
        data = r.json()
        assert "signals" in data


class TestMacroDashboard:
    """Tests for /api/macro/dashboard."""

    @patch("src.api.cloud_app._query")
    def test_macro_dashboard(self, mock_query, client):
        mock_query.return_value = []
        r = client.get("/api/macro/dashboard")
        assert r.status_code == 200
        data = r.json()
        assert "series" in data


class TestResearchEndpoints:
    """Tests for /api/research/*."""

    @patch("src.api.cloud_app._query")
    def test_research_papers(self, mock_query, client):
        mock_query.return_value = []
        r = client.get("/api/research/papers")
        assert r.status_code == 200
        data = r.json()
        assert "papers" in data

    @patch("src.api.cloud_app._query_one")
    def test_research_digest(self, mock_one, client):
        mock_one.return_value = None
        r = client.get("/api/research/digest")
        assert r.status_code == 200

    @patch("src.api.cloud_app._query_one")
    def test_research_digest_with_data(self, mock_one, client):
        mock_one.return_value = {"id": "d1", "summary": "Weekly digest", "created_at": "2026-03-27"}
        r = client.get("/api/research/digest")
        assert r.status_code == 200
        data = r.json()
        assert data["summary"] == "Weekly digest"


class TestTrainingQuality:
    """Tests for /api/training/quality."""

    @patch("src.api.cloud_app._query")
    @patch("src.api.cloud_app._query_one")
    def test_training_quality(self, mock_one, mock_query, client):
        mock_one.return_value = {"c": 500}
        mock_query.side_effect = [
            [{"source": "blinded_win", "count": 200}],
            [{"curriculum_stage": "stage1", "count": 200}],
            [{"outcome": "win", "count": 200}],
        ]
        r = client.get("/api/training/quality")
        assert r.status_code == 200
        data = r.json()
        assert "total" in data
        assert "by_source" in data


class TestScanMetrics:
    """Tests for /api/scan/metrics."""

    @patch("src.api.cloud_app._query_one")
    def test_scan_metrics(self, mock_one, client):
        mock_one.return_value = {"llm_success": 5, "llm_total": 6}
        r = client.get("/api/scan/metrics")
        assert r.status_code == 200


class TestProjectionsLive:
    """Tests for /api/projections/live."""

    @patch("src.api.cloud_app._query")
    def test_projections_live_no_data(self, mock_query, client):
        mock_query.return_value = []
        r = client.get("/api/projections/live")
        assert r.status_code == 200
        data = r.json()
        assert data["trades"] == 0

    @patch("src.api.cloud_app._query")
    def test_projections_live_with_data(self, mock_query, client):
        mock_query.return_value = [
            {"pnl_dollars": 100, "pnl_pct": 4.0},
            {"pnl_dollars": -50, "pnl_pct": -2.0},
        ]
        r = client.get("/api/projections/live")
        assert r.status_code == 200
        data = r.json()
        assert data["trades"] == 2
        assert "winRate" in data
        assert "sharpe" in data


class TestHealthz:
    """Tests for /healthz."""

    def test_healthz(self, client):
        r = client.get("/healthz")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"


class TestDiagnostics:
    """Tests for /api/diagnostics."""

    @patch("src.api.cloud_app._query_one")
    def test_diagnostics_healthy(self, mock_one, client):
        mock_one.return_value = {"c": 10}
        r = client.get("/api/diagnostics")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "healthy"
        assert data["failed_count"] == 0

    @patch("src.api.cloud_app._query_one")
    def test_diagnostics_degraded(self, mock_one, client):
        mock_one.side_effect = Exception("relation does not exist")
        r = client.get("/api/diagnostics")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "degraded"
        assert data["failed_count"] > 0


class TestReconcileEndpoint:
    """Tests for /api/live/reconcile."""

    def test_reconcile_returns_cloud_mode(self, client):
        r = client.post("/api/live/reconcile")
        assert r.status_code == 200
        assert r.json()["error"] == "cloud_mode"


class TestFrontendContracts:
    """Verify API responses match the exact field paths each frontend page reads."""

    @patch("src.api.cloud_app._query_one")
    @patch("src.api.cloud_app._query")
    def test_cto_report_shape(self, mock_query, mock_one, client):
        """Dashboard.jsx reads: headline_kpis.sharpe_ratio, trade_summary.trades_closed, etc."""
        mock_one.side_effect = [{"c": 5}, None, None]
        mock_query.side_effect = [
            [{"ticker": "AAPL", "pnl_dollars": 100, "pnl_pct": 4.0, "exit_reason": "target"}],
        ]
        r = client.get("/api/cto-report?days=30")
        assert r.status_code == 200
        data = r.json()
        assert "headline_kpis" in data
        assert "trade_summary" in data
        ts = data["trade_summary"]
        assert "trades_closed" in ts
        assert "total_pnl" in ts
        assert "expectancy_dollars" in ts

    @patch("src.api.cloud_app._query_one")
    @patch("src.api.cloud_app._query")
    def test_health_score_shape(self, mock_query, mock_one, client):
        """Health.jsx reads: score.overall, score.dimensions.{5 keys}, score.dimension_metrics, score.weights, score.phase."""
        mock_query.side_effect = [
            [{"pnl_dollars": 100, "pnl_pct": 4.0}, {"pnl_dollars": -50, "pnl_pct": -2.0}],
            [{"source": "backfill", "cnt": 700}],
        ]
        mock_one.side_effect = [
            {"c": 10}, {"count": 500}, None, None,
            {"llm_success": 17, "llm_total": 20},
            {"cnt": 3}, {"cnt": 50},
        ]
        r = client.get("/api/health/score")
        data = r.json()
        score = data.get("score", data)
        assert "overall" in score
        assert "dimensions" in score
        assert "dimension_metrics" in score
        assert "weights" in score
        assert "phase" in score
        dm = score.get("dimension_metrics", {})
        for key in ["performance", "model_quality", "data_asset", "flywheel_velocity", "defensibility"]:
            assert key in dm, f"dimension_metrics missing {key}"

    @patch("src.api.cloud_app._query")
    def test_live_trades_shape(self, mock_query, client):
        """LiveLedger.jsx reads: {open: [...], closed: [...]}."""
        mock_query.side_effect = [[], []]
        r = client.get("/api/live/trades")
        data = r.json()
        assert "open" in data
        assert "closed" in data
        assert isinstance(data["open"], list)
        assert isinstance(data["closed"], list)

    @patch("src.api.cloud_app._query")
    @patch("src.api.cloud_app._query_one")
    def test_council_session_shape(self, mock_one, mock_query, client):
        """Council.jsx reads: {session: {...}, votes: [...]}."""
        mock_one.return_value = {"session_id": "s1", "session_type": "daily", "consensus": "BULLISH"}
        mock_query.return_value = [{"agent_name": "Risk Officer", "position": "BULLISH", "confidence": 8}]
        r = client.get("/api/council/session/s1")
        data = r.json()
        assert "session" in data
        assert "votes" in data
        assert isinstance(data["votes"], list)

    @patch("src.api.cloud_app._query")
    def test_shadow_account_shape(self, mock_query, client):
        """ShadowLedger.jsx reads: equity, starting_capital, closed_pnl, open_positions."""
        mock_query.side_effect = [
            [{"entry_price": 100, "planned_shares": 10, "pnl_dollars": 0}],
            [{"pnl_dollars": 50, "pnl_pct": 2.0}],
        ]
        r = client.get("/api/shadow/account")
        data = r.json()
        assert "equity" in data
        assert "starting_capital" in data
        assert "closed_pnl" in data
        assert "open_positions" in data

    @patch("src.api.cloud_app._query_one")
    @patch("src.api.cloud_app._query")
    def test_live_summary_shape(self, mock_query, mock_one, client):
        """LiveLedger.jsx reads: starting_capital, current_equity, total_pnl, open_positions, win_rate."""
        mock_query.return_value = [{"pnl_dollars": 5.0, "pnl_pct": 2.0}]
        mock_one.return_value = {"c": 1}
        r = client.get("/api/live/summary")
        data = r.json()
        for key in ["starting_capital", "current_equity", "total_pnl", "open_positions", "win_rate"]:
            assert key in data, f"live/summary missing {key}"


class TestDataCollectionStats:
    """Tests for /api/data-collection-stats schema compatibility."""

    @patch("src.api.cloud_app._query_one")
    def test_data_collection_stats_shape(self, mock_one, client):
        def _query_one_side_effect(sql, params=()):
            if "FROM options_chains" in sql:
                raise Exception("relation does not exist")
            if "FROM options_metrics" in sql:
                return {"total_records": 5, "latest_collection": "2026-03-30", "coverage_count": 2}
            return {"total_records": 0, "latest_collection": None, "coverage_count": 0}

        mock_one.side_effect = _query_one_side_effect

        r = client.get("/api/data-collection-stats")
        assert r.status_code == 200
        data = r.json()
        assert "earnings_calendar" in data
        assert "analyst_estimates" in data

        for table_stats in data.values():
            assert set(table_stats.keys()) == {"total_records", "latest_collection", "coverage_count"}

        assert data["options_metrics"]["total_records"] == 5
        assert data["options_metrics"]["latest_collection"] == "2026-03-30"
        assert data["options_chains"] == {
            "total_records": 0,
            "latest_collection": None,
            "coverage_count": 0,
        }
