"""Tests for local API route parity with cloud."""

import json
import sqlite3
import os
import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient
from tests.conftest import init_test_db


def _noop_auth():
    """No-op auth override for TestClient fixtures."""
    return None


def _make_client(app_mod):
    """Create a TestClient with verify_auth bypassed."""
    app_mod.app.dependency_overrides[app_mod.verify_auth] = _noop_auth
    return TestClient(app_mod.app)


@pytest.fixture
def local_db(tmp_path):
    """Create a temporary SQLite database with schema."""
    db_path = str(tmp_path / "test.sqlite3")
    init_test_db(db_path, ["activity_log"])
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO activity_log (id, event_type, detail, created_at) "
        "VALUES (?, ?, ?, ?)",
        (1, "scan_complete", '{"event": "scan done"}', "2026-04-02T14:30:00"),
    )
    conn.execute(
        "INSERT INTO activity_log (id, event_type, detail, created_at) "
        "VALUES (?, ?, ?, ?)",
        (2, "trade_opened", '{"event": "opened AAPL"}', "2026-04-02T14:31:00"),
    )
    conn.commit()
    conn.close()
    return db_path


@pytest.fixture
def client(local_db):
    """Create a TestClient for the local API with mocked DB_PATH."""
    with patch("src.api.routes.system.DB_PATH", local_db), \
         patch("src.config.DB_PATH", local_db):
        import importlib
        import src.api.routes.system as sys_mod
        importlib.reload(sys_mod)
        import src.api.routes.system_status as sys_status_mod
        importlib.reload(sys_status_mod)
        import src.api.app as app_mod
        importlib.reload(app_mod)
        yield _make_client(app_mod)


class TestActivityFeed:
    def test_activity_feed_returns_list(self, client):
        resp = client.get("/api/activity/feed?limit=10")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) == 2

    def test_activity_feed_with_event_type_filter(self, client):
        resp = client.get("/api/activity/feed?limit=10&event_type=scan_complete")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["event_type"] == "scan_complete"

    def test_activity_feed_respects_limit(self, client):
        resp = client.get("/api/activity/feed?limit=1")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1


@pytest.fixture
def health_db(tmp_path):
    """Create a DB with tables needed by health routes."""
    db_path = str(tmp_path / "health.sqlite3")
    init_test_db(db_path, [
        "build_score_history", "shadow_trades", "training_examples",
        "model_versions", "scan_metrics", "canary_evaluations",
    ])
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO build_score_history "
        "(score_id, score_date, build_score, gate_velocity, system_health, "
        "data_asset_value, model_quality, research_velocity, reliability, "
        "decay_applied, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("bs-1", "2026-04-02", 72.4, 82.0, 91.0, 58.0, 74.0, 68.0, 85.0, 0,
         "2026-04-02T16:45:00"),
    )
    conn.execute(
        "INSERT INTO shadow_trades "
        "(trade_id, ticker, status, pnl_dollars, pnl_pct, "
        "actual_exit_time, created_at, updated_at, entry_price, planned_shares, source) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("t1", "AAPL", "closed", 100.0, 1.0, "2026-04-01", "2026-03-30",
         "2026-03-30", 150.0, 10, "shadow"),
    )
    conn.commit()
    conn.close()
    return db_path


@pytest.fixture
def health_client(health_db):
    """TestClient with health-related tables."""
    with patch("src.api.routes.health.DB_PATH", health_db), \
         patch("src.api.routes.system.DB_PATH", health_db), \
         patch("src.config.DB_PATH", health_db), \
         patch("src.evaluation.hshs_live.DEFAULT_DB_PATH", health_db), \
         patch("src.evaluation.build_score.DEFAULT_DB", health_db):
        import importlib
        import src.api.routes.health as health_mod
        importlib.reload(health_mod)
        import src.api.routes.system as sys_mod
        importlib.reload(sys_mod)
        import src.api.app as app_mod
        importlib.reload(app_mod)
        yield _make_client(app_mod)


class TestBuildScore:
    def test_build_score_returns_structure(self, health_client):
        resp = health_client.get("/api/build-score")
        assert resp.status_code == 200
        data = resp.json()
        assert "build_score" in data
        assert "components" in data
        assert "phase_progress" in data
        assert data["build_score"] == 72.4

    def test_build_score_empty_table(self, health_db):
        """When build_score_history is empty, compute live instead."""
        conn = sqlite3.connect(health_db)
        conn.execute("DELETE FROM build_score_history")
        conn.commit()
        conn.close()
        with patch("src.api.routes.health.DB_PATH", health_db), \
             patch("src.evaluation.build_score.DEFAULT_DB", health_db), \
             patch("src.config.DB_PATH", health_db):
            import importlib
            import src.api.routes.health as health_mod
            importlib.reload(health_mod)
            import src.api.app as app_mod
            importlib.reload(app_mod)
            client = _make_client(app_mod)
            resp = client.get("/api/build-score")
            assert resp.status_code == 200
            data = resp.json()
            assert "build_score" in data
            assert "components" in data


class TestHealthHSHS:
    def test_hshs_returns_structure(self, health_client):
        resp = health_client.get("/api/health/hshs")
        assert resp.status_code == 200
        data = resp.json()
        assert "hshs" in data
        assert "dimensions" in data
        assert "weights" in data
        assert "phase" in data


class TestHealthScore:
    def test_health_score_returns_structure(self, health_client):
        resp = health_client.get("/api/health/score")
        assert resp.status_code == 200
        data = resp.json()
        assert "score" in data
        assert "overall" in data["score"]
        assert "dimensions" in data["score"]


@pytest.fixture
def council_db(tmp_path):
    """Create a DB with council tables."""
    db_path = str(tmp_path / "council.sqlite3")
    init_test_db(db_path, ["council_sessions", "council_votes"])
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO council_sessions (session_id, result_json, created_at) "
        "VALUES (?, ?, ?)",
        ("sess-1", '{"summary": "bullish"}', "2026-04-02T14:00:00"),
    )
    conn.execute(
        "INSERT INTO council_votes (vote_id, session_id, agent_name, round, vote, direction) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("vote-1", "sess-1", "fundamentals", 1, "BUY", "bullish"),
    )
    conn.commit()
    conn.close()
    return db_path


@pytest.fixture
def council_client(council_db):
    with patch("src.api.routes.council.DB_PATH", council_db), \
         patch("src.config.DB_PATH", council_db):
        import importlib
        import src.api.routes.council as council_mod
        importlib.reload(council_mod)
        import src.api.app as app_mod
        importlib.reload(app_mod)
        yield _make_client(app_mod)


class TestCouncil:
    def test_council_latest_returns_session(self, council_client):
        resp = council_client.get("/api/council/latest")
        assert resp.status_code == 200
        data = resp.json()
        assert data["session_id"] == "sess-1"
        assert "votes" in data

    def test_council_latest_empty(self, council_db):
        conn = sqlite3.connect(council_db)
        conn.execute("DELETE FROM council_sessions")
        conn.commit()
        conn.close()
        with patch("src.api.routes.council.DB_PATH", council_db), \
             patch("src.config.DB_PATH", council_db):
            import importlib
            import src.api.routes.council as council_mod
            importlib.reload(council_mod)
            import src.api.app as app_mod
            importlib.reload(app_mod)
            client = _make_client(app_mod)
            resp = client.get("/api/council/latest")
            assert resp.status_code == 200
            assert resp.json() == {"session": None}

    def test_council_history(self, council_client):
        resp = council_client.get("/api/council/history?days=90")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) >= 1

    def test_council_session_detail(self, council_client):
        resp = council_client.get("/api/council/session/sess-1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["session"]["session_id"] == "sess-1"
        assert len(data["votes"]) == 1

    def test_council_session_not_found(self, council_client):
        resp = council_client.get("/api/council/session/nonexistent")
        assert resp.status_code == 404


@pytest.fixture
def notes_db(tmp_path):
    """Create a DB with user_notes table."""
    db_path = str(tmp_path / "notes.sqlite3")
    init_test_db(db_path, ["user_notes"])
    return db_path


@pytest.fixture
def notes_client(notes_db):
    with patch("src.api.routes.notes.DB_PATH", notes_db), \
         patch("src.config.DB_PATH", notes_db):
        import importlib
        import src.api.routes.notes as notes_mod
        importlib.reload(notes_mod)
        import src.api.app as app_mod
        importlib.reload(app_mod)
        yield _make_client(app_mod)


class TestNotes:
    def test_list_notes_empty(self, notes_client):
        resp = notes_client.get("/api/notes")
        assert resp.status_code == 200
        assert resp.json() == {"notes": []}

    def test_create_note(self, notes_client):
        resp = notes_client.post("/api/notes", json={
            "title": "Test Note",
            "content": "Hello world",
            "tags": ["test"],
            "pinned": False,
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["title"] == "Test Note"
        assert data["note_id"]
        assert data["tags"] == ["test"]

    def test_create_then_list(self, notes_client):
        notes_client.post("/api/notes", json={"title": "Note 1"})
        notes_client.post("/api/notes", json={"title": "Note 2"})
        resp = notes_client.get("/api/notes")
        assert len(resp.json()["notes"]) == 2

    def test_update_note(self, notes_client):
        create_resp = notes_client.post("/api/notes", json={"title": "Original"})
        note_id = create_resp.json()["note_id"]
        resp = notes_client.put(f"/api/notes/{note_id}", json={"title": "Updated"})
        assert resp.status_code == 200
        assert resp.json()["title"] == "Updated"

    def test_delete_note(self, notes_client):
        create_resp = notes_client.post("/api/notes", json={"title": "To Delete"})
        note_id = create_resp.json()["note_id"]
        resp = notes_client.delete(f"/api/notes/{note_id}")
        assert resp.status_code == 204
        list_resp = notes_client.get("/api/notes")
        assert len(list_resp.json()["notes"]) == 0

    def test_delete_nonexistent(self, notes_client):
        resp = notes_client.delete("/api/notes/nonexistent")
        assert resp.status_code == 404


@pytest.fixture
def live_db(tmp_path):
    """Create a DB with shadow_trades including live-source trades."""
    db_path = str(tmp_path / "live.sqlite3")
    init_test_db(db_path, ["shadow_trades"])
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO shadow_trades "
        "(trade_id, ticker, status, pnl_dollars, pnl_pct, "
        "actual_exit_time, created_at, updated_at, entry_price, planned_shares, source) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("t1", "AAPL", "open", None, None, None, "2026-04-01", "2026-04-01", 150.0, 10, "live"),
    )
    conn.execute(
        "INSERT INTO shadow_trades "
        "(trade_id, ticker, status, pnl_dollars, pnl_pct, "
        "actual_exit_time, created_at, updated_at, entry_price, planned_shares, source) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("t2", "MSFT", "closed", 50.0, 0.5, "2026-04-02", "2026-03-28", "2026-03-28", 300.0, 5, "live"),
    )
    conn.execute(
        "INSERT INTO shadow_trades "
        "(trade_id, ticker, status, pnl_dollars, pnl_pct, "
        "actual_exit_time, created_at, updated_at, entry_price, planned_shares, source) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("t3", "NVDA", "open", None, None, None, "2026-04-01", "2026-04-01", 800.0, 2, "shadow"),
    )
    conn.commit()
    conn.close()
    return db_path


@pytest.fixture
def live_client(live_db):
    with patch("src.api.routes.live.DB_PATH", live_db), \
         patch("src.config.DB_PATH", live_db):
        import importlib
        import src.api.routes.live as live_mod
        importlib.reload(live_mod)
        import src.api.app as app_mod
        importlib.reload(app_mod)
        yield _make_client(app_mod)


class TestLiveLedger:
    def test_live_trades_filters_by_source(self, live_client):
        resp = live_client.get("/api/live/trades")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["open"]) == 1
        assert data["open"][0]["ticker"] == "AAPL"
        assert len(data["closed"]) == 1
        assert data["closed"][0]["ticker"] == "MSFT"

    def test_live_summary(self, live_client):
        resp = live_client.get("/api/live/summary")
        assert resp.status_code == 200
        data = resp.json()
        assert data["open_positions"] == 1
        assert data["closed_trades"] == 1
        assert data["total_pnl"] == 50.0


@pytest.fixture
def logs_db(tmp_path):
    """Create a DB with log_entries and command tables."""
    db_path = str(tmp_path / "logs.sqlite3")
    init_test_db(db_path, ["log_entries", "pending_commands", "command_results"])
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO log_entries (log_id, log_level, source, message, created_at) "
        "VALUES ('log-1', 'INFO', 'scanner', 'Scan started', '2026-04-02T14:00:00')"
    )
    conn.execute(
        "INSERT INTO log_entries (log_id, log_level, source, message, created_at) "
        "VALUES ('log-2', 'ERROR', 'llm', 'Timeout', '2026-04-02T14:01:00')"
    )
    conn.commit()
    conn.close()
    return db_path


@pytest.fixture
def logs_client(logs_db):
    with patch("src.api.routes.logs.DB_PATH", logs_db), \
         patch("src.config.DB_PATH", logs_db):
        import importlib
        import src.api.routes.logs as logs_mod
        importlib.reload(logs_mod)
        import src.api.app as app_mod
        importlib.reload(app_mod)
        yield _make_client(app_mod)


class TestLogs:
    def test_recent_logs(self, logs_client):
        resp = logs_client.get("/api/logs/recent?level=INFO&limit=50")
        assert resp.status_code == 200
        data = resp.json()
        assert "logs" in data
        assert data["count"] == 2

    def test_recent_logs_level_filter(self, logs_client):
        resp = logs_client.get("/api/logs/recent?level=ERROR&limit=50")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 1
        assert data["logs"][0]["log_level"] == "ERROR"


class TestCommands:
    def test_submit_command(self, logs_client):
        resp = logs_client.post("/api/commands/submit", json={
            "command_name": "scan",
            "command_type": "action",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "command_id" in data
        assert data["status"] == "pending"

    def test_command_status(self, logs_client):
        create_resp = logs_client.post("/api/commands/submit", json={
            "command_name": "scan",
        })
        cmd_id = create_resp.json()["command_id"]
        resp = logs_client.get(f"/api/commands/{cmd_id}/status")
        assert resp.status_code == 200
        assert resp.json()["command"]["command_id"] == cmd_id

    def test_recent_commands(self, logs_client):
        logs_client.post("/api/commands/submit", json={"command_name": "scan"})
        resp = logs_client.get("/api/commands/recent?limit=10")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] >= 1


@pytest.fixture
def settings_db(tmp_path):
    """Create a DB with config_overrides, scan_metrics, model_versions."""
    db_path = str(tmp_path / "settings.sqlite3")
    init_test_db(db_path, ["config_overrides", "scan_metrics", "model_versions"])
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO scan_metrics (id, llm_success, llm_total, created_at) "
        "VALUES (1, 90, 100, '2026-04-02T14:00:00')"
    )
    conn.commit()
    conn.close()
    return db_path


@pytest.fixture
def settings_client(settings_db):
    with patch("src.api.routes.system.DB_PATH", settings_db), \
         patch("src.config.DB_PATH", settings_db):
        import importlib
        import src.api.routes.system as sys_mod
        importlib.reload(sys_mod)
        import src.api.routes.system_status as sys_status_mod
        importlib.reload(sys_status_mod)
        import src.api.app as app_mod
        importlib.reload(app_mod)
        yield _make_client(app_mod)


class TestSettings:
    def test_get_settings(self, settings_client):
        resp = settings_client.get("/api/settings")
        assert resp.status_code == 200
        data = resp.json()
        assert "overrides" in data
        assert isinstance(data["overrides"], dict)

    def test_post_settings(self, settings_client):
        resp = settings_client.post("/api/settings", json={
            "key": "risk.max_open_positions",
            "value": 25,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "saved"


class TestScanMetrics:
    def test_scan_metrics(self, settings_client):
        resp = settings_client.get("/api/scan/metrics?limit=10")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) == 1


class TestTrainingHistory:
    def test_training_history(self, settings_client):
        resp = settings_client.get("/api/training/history")
        assert resp.status_code == 200
        data = resp.json()
        assert "versions" in data
