"""Tests for the manual intervention drift detector (C4 / #45).

Covers: DriftFinding returned on divergence, threshold boundary at 29/31 min,
state-file persistence + 24h dedup, broker outage guard, platform_events row insert.
"""
import json
import sqlite3
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

from src.monitoring.manual_intervention_drift import (
    BrokerPosition,
    DBPosition,
    DriftFinding,
    detect_drift,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_conn() -> sqlite3.Connection:
    """Return an in-memory SQLite connection with platform_events table."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE platform_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type TEXT NOT NULL,
            severity TEXT NOT NULL,
            payload_json TEXT,
            source TEXT NOT NULL,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.commit()
    return conn


def _make_state_path(tmp_path: Path) -> Path:
    return tmp_path / "drift_state.json"


# ---------------------------------------------------------------------------
# Test 1 — basic divergence produces 1 DriftFinding
# ---------------------------------------------------------------------------

def test_drift_detector_with_mocked_broker_db(tmp_path):
    broker = {"AAPL": BrokerPosition(ticker="AAPL", status="closed")}
    db = {"AAPL": DBPosition(ticker="AAPL", status="active")}

    # Pre-seed state so first_seen_iso is old enough (31 min ago)
    state_path = _make_state_path(tmp_path)
    first_seen = (datetime.now(timezone.utc) - timedelta(minutes=31)).isoformat()
    state_path.write_text(
        json.dumps({"AAPL": {"first_seen_iso": first_seen, "last_alerted_iso": None,
                              "expected_state": "closed", "actual_state": "active"}})
    )

    conn = _make_conn()
    findings = detect_drift(
        broker_positions=broker,
        db_positions=db,
        threshold_minutes=30,
        state_path=state_path,
        conn=conn,
    )
    assert len(findings) == 1
    f = findings[0]
    assert f.ticker == "AAPL"
    assert f.expected_state == "closed"
    assert f.actual_state == "active"


# ---------------------------------------------------------------------------
# Test 2 — threshold boundary: 29 min → no finding
# ---------------------------------------------------------------------------

def test_drift_detector_threshold_boundary_no_alert_at_29_min(tmp_path):
    broker = {"TSLA": BrokerPosition(ticker="TSLA", status="closed")}
    db = {"TSLA": DBPosition(ticker="TSLA", status="active")}

    state_path = _make_state_path(tmp_path)
    first_seen = (datetime.now(timezone.utc) - timedelta(minutes=29)).isoformat()
    state_path.write_text(
        json.dumps({"TSLA": {"first_seen_iso": first_seen, "last_alerted_iso": None,
                              "expected_state": "closed", "actual_state": "active"}})
    )

    conn = _make_conn()
    findings = detect_drift(
        broker_positions=broker,
        db_positions=db,
        threshold_minutes=30,
        state_path=state_path,
        conn=conn,
    )
    assert findings == []


# ---------------------------------------------------------------------------
# Test 3 — threshold boundary: 31 min → finding emitted
# ---------------------------------------------------------------------------

def test_drift_detector_threshold_boundary_alert_at_31_min(tmp_path):
    broker = {"TSLA": BrokerPosition(ticker="TSLA", status="closed")}
    db = {"TSLA": DBPosition(ticker="TSLA", status="active")}

    state_path = _make_state_path(tmp_path)
    first_seen = (datetime.now(timezone.utc) - timedelta(minutes=31)).isoformat()
    state_path.write_text(
        json.dumps({"TSLA": {"first_seen_iso": first_seen, "last_alerted_iso": None,
                              "expected_state": "closed", "actual_state": "active"}})
    )

    conn = _make_conn()
    findings = detect_drift(
        broker_positions=broker,
        db_positions=db,
        threshold_minutes=30,
        state_path=state_path,
        conn=conn,
    )
    assert len(findings) == 1
    assert findings[0].ticker == "TSLA"


# ---------------------------------------------------------------------------
# Test 4 — state persistence + 24h dedup
# ---------------------------------------------------------------------------

def test_drift_detector_state_persistence_across_calls(tmp_path):
    broker = {"MSFT": BrokerPosition(ticker="MSFT", status="closed")}
    db = {"MSFT": DBPosition(ticker="MSFT", status="active")}

    state_path = _make_state_path(tmp_path)
    conn = _make_conn()

    # Call 1 — first detection, no prior state; first_seen now; no finding yet
    findings1 = detect_drift(
        broker_positions=broker,
        db_positions=db,
        threshold_minutes=30,
        state_path=state_path,
        conn=conn,
    )
    assert findings1 == []
    # State file should have been written
    assert state_path.exists()
    state = json.loads(state_path.read_text())
    assert "MSFT" in state

    # Call 2 — advance first_seen to 31 min ago
    state["MSFT"]["first_seen_iso"] = (
        datetime.now(timezone.utc) - timedelta(minutes=31)
    ).isoformat()
    state_path.write_text(json.dumps(state))

    findings2 = detect_drift(
        broker_positions=broker,
        db_positions=db,
        threshold_minutes=30,
        state_path=state_path,
        conn=conn,
    )
    assert len(findings2) == 1

    # Call 3 — same divergence within 24h; should deduplicate (last_alerted within 24h)
    state3 = json.loads(state_path.read_text())
    assert state3["MSFT"]["last_alerted_iso"] is not None

    findings3 = detect_drift(
        broker_positions=broker,
        db_positions=db,
        threshold_minutes=30,
        state_path=state_path,
        conn=conn,
    )
    assert findings3 == []


# ---------------------------------------------------------------------------
# Test 5 — broker outage (None) → no finding
# ---------------------------------------------------------------------------

def test_drift_detector_no_alert_on_broker_outage(tmp_path):
    db = {"GOOG": DBPosition(ticker="GOOG", status="active")}
    state_path = _make_state_path(tmp_path)
    conn = _make_conn()

    findings = detect_drift(
        broker_positions=None,
        db_positions=db,
        threshold_minutes=30,
        state_path=state_path,
        conn=conn,
    )
    assert findings == []


# ---------------------------------------------------------------------------
# Test 6 — platform_events row inserted when finding emitted
# ---------------------------------------------------------------------------

def test_drift_detector_writes_platform_events_row(tmp_path):
    broker = {"NVDA": BrokerPosition(ticker="NVDA", status="closed")}
    db = {"NVDA": DBPosition(ticker="NVDA", status="active")}

    state_path = _make_state_path(tmp_path)
    first_seen = (datetime.now(timezone.utc) - timedelta(minutes=35)).isoformat()
    state_path.write_text(
        json.dumps({"NVDA": {"first_seen_iso": first_seen, "last_alerted_iso": None,
                              "expected_state": "closed", "actual_state": "active"}})
    )

    conn = _make_conn()
    findings = detect_drift(
        broker_positions=broker,
        db_positions=db,
        threshold_minutes=30,
        state_path=state_path,
        conn=conn,
    )
    assert len(findings) == 1

    rows = conn.execute("SELECT * FROM platform_events").fetchall()
    assert len(rows) == 1
    row = rows[0]
    assert row["event_type"] == "drift_detected"
    assert row["severity"] == "high"
    assert row["source"] == "drift_detector"
    payload = json.loads(row["payload_json"])
    assert payload["ticker"] == "NVDA"
    assert "expected_state" in payload
    assert "actual_state" in payload
