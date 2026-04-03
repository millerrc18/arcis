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
