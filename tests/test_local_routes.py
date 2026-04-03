"""Tests for local API route parity with cloud."""

import json
import sqlite3
import os
import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient


@pytest.fixture
def local_db(tmp_path):
    """Create a temporary SQLite database with schema."""
    db_path = str(tmp_path / "test.sqlite3")
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE activity_log ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "event_type TEXT NOT NULL, "
        "detail TEXT, "
        "level TEXT, "
        "created_at TEXT NOT NULL)"
    )
    conn.execute(
        "INSERT INTO activity_log (event_type, detail, created_at) "
        "VALUES (?, ?, ?)",
        ("scan_complete", '{"event": "scan done"}', "2026-04-02T14:30:00"),
    )
    conn.execute(
        "INSERT INTO activity_log (event_type, detail, created_at) "
        "VALUES (?, ?, ?)",
        ("trade_opened", '{"event": "opened AAPL"}', "2026-04-02T14:31:00"),
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
        import src.api.app as app_mod
        importlib.reload(app_mod)
        yield TestClient(app_mod.app)


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
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE build_score_history ("
        "score_id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "score_date TEXT, build_score REAL, "
        "gate_velocity REAL, system_health REAL, "
        "data_asset_value REAL, model_quality REAL, "
        "research_velocity REAL, reliability REAL, "
        "decay_applied INTEGER DEFAULT 0, "
        "created_at TEXT NOT NULL)"
    )
    conn.execute(
        "INSERT INTO build_score_history "
        "(score_date, build_score, gate_velocity, system_health, "
        "data_asset_value, model_quality, research_velocity, reliability, "
        "decay_applied, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("2026-04-02", 72.4, 82.0, 91.0, 58.0, 74.0, 68.0, 85.0, 0,
         "2026-04-02T16:45:00"),
    )
    conn.execute(
        "CREATE TABLE shadow_trades ("
        "trade_id TEXT PRIMARY KEY, ticker TEXT, status TEXT, "
        "pnl_dollars REAL, pnl_pct REAL, "
        "actual_exit_time TEXT, created_at TEXT, "
        "entry_price REAL, planned_shares INTEGER, source TEXT)"
    )
    conn.execute(
        "INSERT INTO shadow_trades VALUES "
        "('t1','AAPL','closed',100.0,1.0,'2026-04-01','2026-03-30',150.0,10,'shadow')"
    )
    conn.execute(
        "CREATE TABLE training_examples ("
        "id INTEGER PRIMARY KEY, ticker TEXT, source TEXT, outcome TEXT, "
        "quality_score REAL, quality_score_auto REAL, "
        "curriculum_stage TEXT, regime_label TEXT, created_at TEXT)"
    )
    conn.execute(
        "CREATE TABLE model_versions ("
        "id INTEGER PRIMARY KEY, version_name TEXT, status TEXT, created_at TEXT)"
    )
    conn.execute(
        "CREATE TABLE scan_metrics ("
        "id INTEGER PRIMARY KEY, llm_success INTEGER, llm_total INTEGER, "
        "created_at TEXT)"
    )
    conn.execute(
        "CREATE TABLE canary_evaluations ("
        "id INTEGER PRIMARY KEY, verdict TEXT, perplexity REAL, "
        "distinct_2 REAL, created_at TEXT)"
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
        yield TestClient(app_mod.app)


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
            client = TestClient(app_mod.app)
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
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE council_sessions ("
        "session_id TEXT PRIMARY KEY, ticker TEXT, "
        "result_json TEXT, created_at TEXT NOT NULL)"
    )
    conn.execute(
        "CREATE TABLE council_votes ("
        "vote_id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "session_id TEXT, agent_name TEXT, round INTEGER, "
        "vote TEXT, reasoning TEXT, "
        "key_data_points TEXT, risk_flags TEXT, "
        "created_at TEXT)"
    )
    conn.execute(
        "INSERT INTO council_sessions VALUES (?, ?, ?, ?)",
        ("sess-1", "AAPL", '{"summary": "bullish"}', "2026-04-02T14:00:00"),
    )
    conn.execute(
        "INSERT INTO council_votes (session_id, agent_name, round, vote, reasoning, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("sess-1", "fundamentals", 1, "BUY", "Strong earnings", "2026-04-02T14:00:01"),
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
        yield TestClient(app_mod.app)


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
            client = TestClient(app_mod.app)
            resp = client.get("/api/council/latest")
            assert resp.status_code == 200
            assert resp.json() == {"session": None}

    def test_council_history(self, council_client):
        resp = council_client.get("/api/council/history?days=30")
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
