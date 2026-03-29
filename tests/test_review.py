"""Tests for review flow journal queries."""

import sqlite3
import tempfile
import os
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from src.journal.store import (
    initialize_database,
    get_recommendations_pending_review,
    get_recommendation_by_id,
    get_recommendations_by_ticker,
    update_recommendation_review,
    update_recommendation,
)


@pytest.fixture
def tmp_db():
    fd, path = tempfile.mkstemp(suffix=".sqlite3")
    os.close(fd)
    initialize_database(path)
    yield path
    try:
        os.unlink(path)
    except PermissionError:
        pass


def _insert_recommendation(db_path, rec_id="test-rec-1", ticker="AAPL",
                           ryan_executed=None, user_grade=None):
    """Insert a test recommendation directly."""
    et = ZoneInfo("America/New_York")
    now = datetime.now(et).isoformat()

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO recommendations (recommendation_id, created_at, ticker, "
            "company_name, ryan_executed, user_grade) VALUES (?, ?, ?, ?, ?, ?)",
            (rec_id, now, ticker, f"{ticker} Corp", ryan_executed, user_grade),
        )
        conn.commit()


def test_get_pending_review_empty(tmp_db):
    result = get_recommendations_pending_review(tmp_db)
    assert result == []


def test_get_pending_review_with_data(tmp_db):
    _insert_recommendation(tmp_db, "rec-1", "AAPL", ryan_executed=1, user_grade=None)
    _insert_recommendation(tmp_db, "rec-2", "MSFT", ryan_executed=1, user_grade="A")
    _insert_recommendation(tmp_db, "rec-3", "GOOG", ryan_executed=None, user_grade=None)

    pending = get_recommendations_pending_review(tmp_db)
    assert len(pending) == 1
    assert pending[0]["recommendation_id"] == "rec-1"


def test_get_recommendation_by_id(tmp_db):
    _insert_recommendation(tmp_db, "rec-1", "AAPL")

    rec = get_recommendation_by_id("rec-1", tmp_db)
    assert rec is not None
    assert rec["ticker"] == "AAPL"

    rec2 = get_recommendation_by_id("nonexistent", tmp_db)
    assert rec2 is None


def test_get_recommendations_by_ticker(tmp_db):
    _insert_recommendation(tmp_db, "rec-1", "AAPL")
    _insert_recommendation(tmp_db, "rec-2", "AAPL")
    _insert_recommendation(tmp_db, "rec-3", "MSFT")

    recs = get_recommendations_by_ticker("AAPL", limit=10, db_path=tmp_db)
    assert len(recs) == 2


def test_update_recommendation_review(tmp_db):
    _insert_recommendation(tmp_db, "rec-1", "AAPL", ryan_executed=1)

    update_recommendation_review("rec-1", {
        "user_grade": "B",
        "ryan_notes": "Good setup",
        "repeatable_setup": 1,
    }, tmp_db)

    rec = get_recommendation_by_id("rec-1", tmp_db)
    assert rec["user_grade"] == "B"
    assert rec["ryan_notes"] == "Good setup"
    assert rec["repeatable_setup"] == 1


def test_mark_executed(tmp_db):
    _insert_recommendation(tmp_db, "rec-1", "AAPL")

    update_recommendation("rec-1", {"ryan_executed": 1}, tmp_db)

    rec = get_recommendation_by_id("rec-1", tmp_db)
    assert rec["ryan_executed"] == 1
