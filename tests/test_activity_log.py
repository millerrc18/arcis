"""Tests for the persistent activity logging system."""

import json
import os
import sqlite3
import tempfile
from unittest import mock

import pytest

# Patch DB_PATH before importing the module
_temp_db = tempfile.NamedTemporaryFile(suffix=".sqlite3", delete=False)
_temp_db_path = _temp_db.name
_temp_db.close()


@pytest.fixture(autouse=True)
def _patch_db(monkeypatch):
    """Use a temp database for every test and reset table state."""
    import src.logging.activity as mod

    monkeypatch.setattr(mod, "DB_PATH", _temp_db_path)
    monkeypatch.setattr(mod, "_table_created", False)

    # Clear the table between tests
    with sqlite3.connect(_temp_db_path) as conn:
        conn.execute("DROP TABLE IF EXISTS activity_log")

    yield

    # Reset module-level flag
    mod._table_created = False


@pytest.fixture(autouse=True, scope="session")
def _cleanup_temp_db():
    """Remove temp database after all tests."""
    yield
    try:
        os.unlink(_temp_db_path)
    except OSError:
        pass


def test_log_activity_creates_table():
    """log_activity should auto-create the activity_log table."""
    from src.logging.activity import log_activity

    log_activity("system", "test event")

    with sqlite3.connect(_temp_db_path) as conn:
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='activity_log'"
        ).fetchall()
    assert len(tables) == 1


def test_entries_stored_and_retrieved():
    """Logged entries should be retrievable via get_recent_activity."""
    from src.logging.activity import get_recent_activity, log_activity

    log_activity("scan", "Scan complete", detail={"count": 20})
    log_activity("trade", "Trade opened", detail={"ticker": "AAPL"})

    entries = get_recent_activity(limit=10)
    assert len(entries) == 2

    # Most recent first
    assert entries[0]["category"] == "trade"
    assert entries[0]["event"] == "Trade opened"
    assert entries[1]["category"] == "scan"
    assert entries[1]["event"] == "Scan complete"


def test_category_filtering():
    """get_recent_activity should filter by category when specified."""
    from src.logging.activity import get_recent_activity, log_activity

    log_activity("scan", "Scan A")
    log_activity("trade", "Trade A")
    log_activity("scan", "Scan B")
    log_activity("system", "System event")

    scan_entries = get_recent_activity(limit=10, category="scan")
    assert len(scan_entries) == 2
    assert all(e["category"] == "scan" for e in scan_entries)

    trade_entries = get_recent_activity(limit=10, category="trade")
    assert len(trade_entries) == 1
    assert trade_entries[0]["event"] == "Trade A"


def test_detail_json_serialization():
    """Detail dicts should round-trip through JSON serialization."""
    from src.logging.activity import get_recent_activity, log_activity

    detail = {"ticker": "MSFT", "price": 425.50, "tags": ["momentum", "breakout"]}
    log_activity("trade", "Trade signal", detail=detail)

    entries = get_recent_activity(limit=1)
    assert len(entries) == 1
    assert entries[0]["detail"] == detail
    assert entries[0]["detail"]["price"] == 425.50
    assert "breakout" in entries[0]["detail"]["tags"]


def test_detail_none_stored_as_null():
    """When detail is None, it should be stored as NULL."""
    from src.logging.activity import get_recent_activity, log_activity

    log_activity("system", "No detail event")

    entries = get_recent_activity(limit=1)
    assert entries[0]["detail"] is None


def test_get_recent_activity_limit():
    """get_recent_activity should respect the limit parameter."""
    from src.logging.activity import get_recent_activity, log_activity

    for i in range(20):
        log_activity("system", f"Event {i}")

    entries = get_recent_activity(limit=5)
    assert len(entries) == 5

    # Should be the 5 most recent (highest event numbers)
    assert entries[0]["event"] == "Event 19"
    assert entries[4]["event"] == "Event 15"


def test_source_field_default():
    """Source should default to 'system'."""
    from src.logging.activity import get_recent_activity, log_activity

    log_activity("scan", "Default source event")
    entries = get_recent_activity(limit=1)
    assert entries[0]["source"] == "system"


def test_source_field_custom():
    """Custom source should be stored correctly."""
    from src.logging.activity import get_recent_activity, log_activity

    log_activity("scan", "Custom source", source="telegram")
    entries = get_recent_activity(limit=1)
    assert entries[0]["source"] == "telegram"


def test_timestamp_is_populated():
    """Each entry should have a non-empty timestamp."""
    from src.logging.activity import get_recent_activity, log_activity

    log_activity("system", "Timestamp test")
    entries = get_recent_activity(limit=1)
    assert entries[0]["timestamp"]
    # Should be an ISO format timestamp
    assert "T" in entries[0]["timestamp"]
