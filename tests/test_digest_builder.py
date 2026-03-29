"""Tests for email digest builder — all 4 digest types."""

import sqlite3

import pytest

from src.email.digest_builder import (
    build_eod_digest,
    build_evening_digest,
    build_midday_digest,
    build_premarket_digest,
)
from src.journal.store import initialize_database


@pytest.fixture
def db_path(tmp_path):
    """Create a temporary DB with all tables."""
    path = str(tmp_path / "test_digest.sqlite3")
    initialize_database(path)
    return path


@pytest.fixture
def populated_db(db_path):
    """DB with some trades and data."""
    with sqlite3.connect(db_path) as conn:
        # Open paper trade
        conn.execute(
            "INSERT INTO shadow_trades (trade_id, ticker, status, source, entry_price, "
            "planned_shares, direction, created_at, updated_at) VALUES "
            "(?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("t1", "AAPL", "open", "paper", 180.0, 10, "long",
             "2026-03-27T10:00:00", "2026-03-27T10:00:00"),
        )
        # Closed trade today
        conn.execute(
            "INSERT INTO shadow_trades (trade_id, ticker, status, source, entry_price, "
            "planned_shares, direction, pnl_dollars, pnl_pct, exit_reason, "
            "actual_exit_time, created_at, updated_at) VALUES "
            "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("t2", "MSFT", "closed", "paper", 400.0, 5, "long",
             50.0, 2.5, "target_hit", "2026-03-27T15:00:00",
             "2026-03-27T09:30:00", "2026-03-27T15:00:00"),
        )
        # Training examples (table may not exist from initialize_database, create it)
        conn.execute(
            "CREATE TABLE IF NOT EXISTS training_examples ("
            "example_id TEXT PRIMARY KEY, ticker TEXT, quality_score_auto REAL, "
            "created_at TEXT, updated_at TEXT)"
        )
        conn.execute(
            "INSERT INTO training_examples (example_id, ticker, created_at, updated_at) "
            "VALUES (?, ?, ?, ?)",
            ("ex1", "AAPL", "2026-03-27T10:00:00", "2026-03-27T10:00:00"),
        )
    return db_path


class TestPremarketDigest:
    def test_returns_subject_and_body(self, db_path):
        subject, body = build_premarket_digest(db_path=db_path)
        assert len(subject) > 0
        assert "Pre-Market" in subject
        assert len(body) > 0

    def test_body_contains_sections(self, db_path):
        _, body = build_premarket_digest(db_path=db_path)
        assert "PORTFOLIO STATUS" in body
        assert "TODAY'S PLAN" in body

    def test_with_populated_data(self, populated_db):
        subject, body = build_premarket_digest(db_path=populated_db)
        assert "1 paper" in subject
        assert "Paper positions: 1" in body


class TestMiddayDigest:
    def test_returns_subject_and_body(self, db_path):
        subject, body = build_midday_digest(db_path=db_path)
        assert len(subject) > 0
        assert "Midday" in subject
        assert len(body) > 0

    def test_body_contains_sections(self, db_path):
        _, body = build_midday_digest(db_path=db_path)
        assert "MORNING ACTIVITY" in body


class TestEodDigest:
    def test_returns_subject_and_body(self, db_path):
        subject, body = build_eod_digest(db_path=db_path)
        assert len(subject) > 0
        assert "EOD" in subject
        assert len(body) > 0

    def test_body_contains_sections(self, db_path):
        _, body = build_eod_digest(db_path=db_path)
        assert "CUMULATIVE" in body
        assert "OPEN POSITIONS" in body

    def test_with_populated_data(self, populated_db):
        subject, body = build_eod_digest(db_path=populated_db)
        assert "Total P&L:" in body


class TestEveningDigest:
    def test_returns_subject_and_body(self, db_path):
        subject, body = build_evening_digest(db_path=db_path)
        assert len(subject) > 0
        assert "Evening" in subject
        assert len(body) > 0

    def test_body_contains_sections(self, db_path):
        _, body = build_evening_digest(db_path=db_path)
        assert "DATA ASSET" in body
        assert "FLYWHEEL" in body
        assert "MODEL QUALITY" in body

    def test_with_populated_data(self, populated_db):
        subject, body = build_evening_digest(db_path=populated_db)
        assert "1/2,800" in body


class TestAllDigestsHandleEmptyDB:
    """All 4 digests should work with zero data — no crash."""

    @pytest.mark.parametrize(
        "builder",
        [build_premarket_digest, build_midday_digest, build_eod_digest, build_evening_digest],
        ids=["premarket", "midday", "eod", "evening"],
    )
    def test_empty_db_no_crash(self, db_path, builder):
        subject, body = builder(db_path=db_path)
        assert len(subject) > 0
        assert len(body) > 0
