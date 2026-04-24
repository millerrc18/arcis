"""Tests for src/utils/activity_logger.py."""

import json
import os
import sqlite3

import pytest

from src.utils.activity_logger import (
    log_activity,
    SCAN_COMPLETE,
    TRADE_OPENED,
    SYSTEM_EVENT,
)
from tests.conftest import init_test_db


# #613 — log_activity now refuses to write under pytest unless opted in.
# These tests are the legitimate consumer that asserts writes happen, so
# they must opt in via the env var. Auto-applied to every test in this file.
@pytest.fixture(autouse=True)
def _opt_in_activity_writes(monkeypatch):
    monkeypatch.setenv("ARCIS_LOG_ACTIVITY_IN_PYTEST", "1")


def _create_activity_log_table(db_path: str) -> None:
    """Create the activity_log table expected by log_activity."""
    init_test_db(db_path, ["activity_log"])


class TestLogActivity:
    def test_basic_insert(self, tmp_path):
        db_path = str(tmp_path / "test.sqlite3")
        _create_activity_log_table(db_path)

        log_activity(SCAN_COMPLETE, "Scanned 50 tickers", db_path=db_path)

        with sqlite3.connect(db_path) as conn:
            rows = conn.execute("SELECT event_type, detail FROM activity_log").fetchall()

        assert len(rows) == 1
        assert rows[0][0] == "scan_complete"
        assert "Scanned 50 tickers" in rows[0][1]

    def test_metadata_stored_in_detail(self, tmp_path):
        db_path = str(tmp_path / "test.sqlite3")
        _create_activity_log_table(db_path)

        meta = {"tickers": 50, "packets": 3}
        log_activity(SCAN_COMPLETE, "Scan done", metadata=meta, db_path=db_path)

        with sqlite3.connect(db_path) as conn:
            rows = conn.execute("SELECT detail FROM activity_log").fetchall()

        assert len(rows) == 1
        detail = rows[0][0]
        # When metadata is provided, detail is "text | {json}"
        assert "Scan done" in detail
        assert '"tickers": 50' in detail or '"tickers":50' in detail

    def test_no_metadata_stores_plain_detail(self, tmp_path):
        db_path = str(tmp_path / "test.sqlite3")
        _create_activity_log_table(db_path)

        log_activity(TRADE_OPENED, "Opened AAPL", db_path=db_path)

        with sqlite3.connect(db_path) as conn:
            rows = conn.execute("SELECT detail FROM activity_log").fetchall()

        assert rows[0][0] == "Opened AAPL"  # No " | " separator

    def test_created_at_populated(self, tmp_path):
        db_path = str(tmp_path / "test.sqlite3")
        _create_activity_log_table(db_path)

        log_activity(SYSTEM_EVENT, "Boot", db_path=db_path)

        with sqlite3.connect(db_path) as conn:
            rows = conn.execute("SELECT created_at FROM activity_log").fetchall()

        assert len(rows) == 1
        assert rows[0][0]  # Non-empty ISO timestamp string

    def test_multiple_inserts(self, tmp_path):
        db_path = str(tmp_path / "test.sqlite3")
        _create_activity_log_table(db_path)

        log_activity(SCAN_COMPLETE, "Event 1", db_path=db_path)
        log_activity(TRADE_OPENED, "Event 2", db_path=db_path)
        log_activity(SYSTEM_EVENT, "Event 3", db_path=db_path)

        with sqlite3.connect(db_path) as conn:
            count = conn.execute("SELECT COUNT(*) FROM activity_log").fetchone()[0]

        assert count == 3

    def test_missing_table_does_not_raise(self, tmp_path):
        """If the table doesn't exist, log_activity should fail silently."""
        db_path = str(tmp_path / "no_table.sqlite3")
        # Do NOT create the table
        # Should not raise, just logs a debug message
        result = log_activity(SCAN_COMPLETE, "Will fail silently", db_path=db_path)
        assert result is None

    def test_invalid_db_path_does_not_raise(self):
        """Totally bogus path should not crash."""
        log_activity(SCAN_COMPLETE, "Bogus", db_path="/nonexistent/dir/db.sqlite3")
