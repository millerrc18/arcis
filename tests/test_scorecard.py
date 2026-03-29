"""Tests for scorecard generation."""

import sqlite3
import tempfile
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from src.journal.store import initialize_database, insert_shadow_trade, close_shadow_trade
from src.evaluation.scorecard import generate_weekly_scorecard, generate_bootcamp_scorecard


@pytest.fixture
def tmp_db():
    """Create a temporary database for testing."""
    fd, path = tempfile.mkstemp(suffix=".sqlite3")
    os.close(fd)
    initialize_database(path)
    yield path
    try:
        os.unlink(path)
    except PermissionError:
        pass


def _insert_test_trades(db_path, count=5):
    """Insert synthetic trades for testing."""
    et = ZoneInfo("America/New_York")
    now = datetime.now(et)

    for i in range(count):
        entry_time = now - timedelta(days=count - i)
        trade = {
            "trade_id": f"test-trade-{i}",
            "recommendation_id": None,
            "ticker": f"TST{i}",
            "direction": "long",
            "status": "open",
            "entry_price": 100.0 + i,
            "stop_price": 95.0 + i,
            "target_1": 110.0 + i,
            "target_2": 120.0 + i,
            "planned_shares": 10,
            "planned_allocation": 1000.0,
            "actual_entry_price": 100.0 + i,
            "actual_entry_time": entry_time.isoformat(),
            "max_favorable_excursion": 5.0,
            "max_adverse_excursion": -2.0,
            "duration_days": i + 1,
            "earnings_adjacent": 0,
            "created_at": entry_time.isoformat(),
            "updated_at": entry_time.isoformat(),
        }
        insert_shadow_trade(trade, db_path)

        # Close some trades
        if i % 2 == 0:
            pnl = 10.0 if i % 4 == 0 else -5.0
            pnl_pct = 10.0 if i % 4 == 0 else -5.0
            close_shadow_trade(
                f"test-trade-{i}",
                exit_price=100.0 + i + (10 if i % 4 == 0 else -5),
                exit_time=now.isoformat(),
                exit_reason="target_1_hit" if i % 4 == 0 else "stop_hit",
                pnl_dollars=pnl,
                pnl_pct=pnl_pct,
                db_path=db_path,
            )


def test_weekly_scorecard_with_data(tmp_db):
    _insert_test_trades(tmp_db)
    scorecard = generate_weekly_scorecard(weeks_back=1, db_path=tmp_db)

    assert "WEEKLY SCORECARD" in scorecard
    assert "ACTIVITY:" in scorecard
    assert "SHADOW PERFORMANCE:" in scorecard
    assert "BY EXIT REASON:" in scorecard
    assert "EARNINGS-ADJACENT:" in scorecard
    assert "HOLD PERIOD:" in scorecard
    assert "EXCURSION ANALYSIS:" in scorecard
    assert "QUALITY:" in scorecard


def test_weekly_scorecard_empty(tmp_db):
    scorecard = generate_weekly_scorecard(weeks_back=1, db_path=tmp_db)
    assert "WEEKLY SCORECARD" in scorecard
    # Should not crash with zero data
    assert "Win rate:" in scorecard


def test_bootcamp_scorecard_with_data(tmp_db):
    _insert_test_trades(tmp_db, count=10)
    scorecard = generate_bootcamp_scorecard(days=30, db_path=tmp_db)

    assert "BOOTCAMP SCORECARD" in scorecard
    assert "OVERALL PERFORMANCE:" in scorecard
    assert "RECOMMENDATIONS:" in scorecard


def test_bootcamp_scorecard_empty(tmp_db):
    scorecard = generate_bootcamp_scorecard(days=30, db_path=tmp_db)
    assert "BOOTCAMP SCORECARD" in scorecard


def test_all_scorecard_sections(tmp_db):
    _insert_test_trades(tmp_db)
    scorecard = generate_weekly_scorecard(weeks_back=1, db_path=tmp_db)

    required = [
        "ACTIVITY:",
        "SHADOW PERFORMANCE:",
        "BY EXIT REASON:",
        "EARNINGS-ADJACENT:",
        "HOLD PERIOD:",
        "EXCURSION ANALYSIS:",
        "QUALITY:",
    ]
    for section in required:
        assert section in scorecard, f"Missing section: {section}"
