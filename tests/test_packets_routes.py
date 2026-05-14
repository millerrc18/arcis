"""Tests for /packets endpoint field completeness (P9 fix).

Verifies that every row returned by GET /packets contains the five
price-target fields that Packets.jsx renders:
  entry_zone, stop_level, target_1, target_2, confidence_score

Root-cause investigation (commit message documents this in full):
- store.get_recommendations_in_period() uses SELECT * so all columns
  are always returned.  The server-side code is correct.
- The issue is data-side: rows written before the LLM enrichment pass
  had NULL for these columns.  The keys are present; values may be null.
- These tests assert the KEYS always exist regardless of value so that
  the frontend can render "—" rather than crash on missing attributes.

Tests use a per-test hermetic SQLite fixture (NOT prod DB).  Store
functions are patched to read from the fixture DB so ARCIS_PG_CUTOVER_ENABLED
and the production DB path are never consulted.
"""

import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


# ── Hermetic SQLite fixture ──────────────────────────────────────────────────

@pytest.fixture
def sqlite_db(tmp_path):
    """Create a hermetic SQLite DB with the recommendations table populated."""
    db_file = str(tmp_path / "test_packets.sqlite3")
    from tests.conftest import init_test_db
    init_test_db(db_file, tables=["recommendations"])
    return db_file


def _insert_recommendation(db_path, **kwargs):
    """Insert a minimal recommendations row; returns the recommendation_id."""
    et = timezone(timedelta(hours=-5))
    now = datetime.now(et).isoformat()
    rec_id = str(uuid.uuid4())
    row = {
        "recommendation_id": rec_id,
        "created_at": now,
        "updated_at": now,
        "ticker": "AAPL",
        "company_name": "Apple Inc.",
        "mode": "short_swing",
        "setup_type": "pullback",
        "priority_score": 80.0,
        "confidence_score": None,
        "packet_type": "action_packet",
        "recommendation": "BUY",
        "entry_zone": None,
        "stop_level": None,
        "target_1": None,
        "target_2": None,
    }
    row.update(kwargs)
    row["recommendation_id"] = rec_id  # keep rec_id stable

    cols = ", ".join(row.keys())
    placeholders = ", ".join("?" for _ in row)
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            f"INSERT INTO recommendations ({cols}) VALUES ({placeholders})",
            list(row.values()),
        )
        conn.commit()
    finally:
        conn.close()
    return rec_id


def _read_recommendations(db_path):
    """Read all recommendations from the fixture DB as list[dict]."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT * FROM recommendations ORDER BY created_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def _read_recommendation_by_id(db_path, rec_id):
    """Read one recommendation by ID from the fixture DB."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT * FROM recommendations WHERE recommendation_id = ?",
            (rec_id,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


@pytest.fixture
def packets_client():
    from src.api.routes.packets import router as packets_router
    app = FastAPI()
    app.include_router(packets_router, prefix="/api")
    return TestClient(app)


# ── Test 1: every row contains the five required keys (values may be null) ──

def test_list_packets_response_keys_present(packets_client, sqlite_db):
    """GET /packets must include entry_zone/stop_level/target_1/target_2/confidence_score
    on every row even when the underlying data is NULL."""
    _insert_recommendation(sqlite_db)
    fixture_rows = _read_recommendations(sqlite_db)

    with patch("src.api.routes.packets.get_recommendations_in_period",
               return_value=fixture_rows):
        r = packets_client.get("/api/packets?days=7")

    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list)
    assert len(data) == 1

    row = data[0]
    for field in ("entry_zone", "stop_level", "target_1", "target_2", "confidence_score"):
        assert field in row, f"Field '{field}' missing from /packets response row"


# ── Test 2: known non-null field values are surfaced correctly ──

def test_list_packets_field_values_surfaced(packets_client, sqlite_db):
    """When a recommendation has price-target data, all five fields must
    render with the stored values (not get silently dropped or nulled)."""
    _insert_recommendation(
        sqlite_db,
        entry_zone="185.00-187.50",
        stop_level="182.00",
        target_1="195.00",
        target_2="205.00",
        confidence_score=7.5,
    )
    fixture_rows = _read_recommendations(sqlite_db)

    with patch("src.api.routes.packets.get_recommendations_in_period",
               return_value=fixture_rows):
        r = packets_client.get("/api/packets?days=7")

    assert r.status_code == 200
    data = r.json()
    assert len(data) == 1

    row = data[0]
    assert row["entry_zone"] == "185.00-187.50"
    assert row["stop_level"] == "182.00"
    assert row["target_1"] == "195.00"
    assert row["target_2"] == "205.00"
    assert row["confidence_score"] == pytest.approx(7.5)


# ── Test 3: single packet detail endpoint returns the five fields ──

def test_get_packet_by_id_fields_present(packets_client, sqlite_db):
    """GET /packets/{id} must include the five target fields."""
    rec_id = _insert_recommendation(
        sqlite_db,
        entry_zone="190.00",
        stop_level="185.00",
        target_1="200.00",
        target_2="210.00",
        confidence_score=8.0,
    )
    fixture_row = _read_recommendation_by_id(sqlite_db, rec_id)

    with patch("src.api.routes.packets.get_recommendation_by_id",
               return_value=fixture_row):
        r = packets_client.get(f"/api/packets/{rec_id}")

    assert r.status_code == 200
    row = r.json()
    assert row.get("recommendation_id") == rec_id

    for field in ("entry_zone", "stop_level", "target_1", "target_2", "confidence_score"):
        assert field in row, f"Field '{field}' missing from /packets/{{id}} response"

    assert row["entry_zone"] == "190.00"
    assert row["confidence_score"] == pytest.approx(8.0)
