"""Tests for Telegram action reminder notifications."""

import sqlite3
from datetime import datetime, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

from src.notifications.telegram import check_action_reminders, notify_action_required

ET = ZoneInfo("America/New_York")


@pytest.fixture
def db_path(tmp_path):
    """Create a temp DB with required tables."""
    path = str(tmp_path / "test.sqlite3")
    with sqlite3.connect(path) as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS shadow_trades (
                trade_id TEXT PRIMARY KEY,
                ticker TEXT, status TEXT, source TEXT,
                pnl_dollars REAL, pnl_pct REAL,
                created_at TEXT, actual_exit_time TEXT
            );
            CREATE TABLE IF NOT EXISTS activity_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT, detail TEXT, metadata TEXT, created_at TEXT
            );
            CREATE TABLE IF NOT EXISTS training_examples (
                example_id TEXT PRIMARY KEY,
                quality_score_auto REAL, quality_score REAL,
                created_at TEXT, source TEXT
            );
            CREATE TABLE IF NOT EXISTS model_versions (
                version_id TEXT PRIMARY KEY,
                version_name TEXT, status TEXT, created_at TEXT,
                training_examples_count INTEGER,
                synthetic_examples_count INTEGER,
                outcome_examples_count INTEGER,
                model_file_path TEXT
            );
        """)
    return path


@patch("src.notifications.telegram.send_telegram", return_value=True)
def test_no_reminders_when_empty_db(mock_send, db_path):
    """Empty DB should produce no action reminders."""
    sent = check_action_reminders(db_path)
    assert sent == []
    mock_send.assert_not_called()


@patch("src.notifications.telegram.send_telegram", return_value=True)
def test_gate_milestone_50_trades(mock_send, db_path):
    """Should notify when 50 closed trades reached."""
    with sqlite3.connect(db_path) as conn:
        for i in range(52):
            conn.execute(
                "INSERT INTO shadow_trades (trade_id, ticker, status, source, created_at) "
                "VALUES (?, ?, 'closed', 'paper', ?)",
                (f"t{i}", f"TICK{i}", datetime.now(ET).isoformat()),
            )
    sent = check_action_reminders(db_path)
    assert "gate_50" in sent
    assert mock_send.called
    call_text = mock_send.call_args[0][0]
    assert "50 closed trades" in call_text
    assert "evaluate-gate" in call_text


@patch("src.notifications.telegram.send_telegram", return_value=True)
def test_gate_milestone_not_duplicated(mock_send, db_path):
    """Should not re-notify for same milestone."""
    with sqlite3.connect(db_path) as conn:
        for i in range(52):
            conn.execute(
                "INSERT INTO shadow_trades (trade_id, ticker, status, source, created_at) "
                "VALUES (?, ?, 'closed', 'paper', ?)",
                (f"t{i}", f"TICK{i}", datetime.now(ET).isoformat()),
            )
    # First call should notify
    sent1 = check_action_reminders(db_path)
    assert "gate_50" in sent1
    # Second call should NOT notify (already logged)
    sent2 = check_action_reminders(db_path)
    assert "gate_50" not in sent2


@patch("src.notifications.telegram.send_telegram", return_value=True)
def test_unscored_training_data_reminder(mock_send, db_path):
    """Should remind when >100 unscored training examples."""
    with sqlite3.connect(db_path) as conn:
        for i in range(150):
            conn.execute(
                "INSERT INTO training_examples (example_id, quality_score_auto, created_at, source) "
                "VALUES (?, NULL, ?, 'backfill')",
                (f"ex{i}", datetime.now(ET).isoformat()),
            )
    sent = check_action_reminders(db_path)
    assert "score_training" in sent
    call_text = mock_send.call_args[0][0]
    assert "150 unscored" in call_text or "score-training-data" in call_text


@patch("src.notifications.telegram.send_telegram", return_value=True)
def test_no_scoring_reminder_when_few_unscored(mock_send, db_path):
    """Should NOT remind when <100 unscored examples."""
    with sqlite3.connect(db_path) as conn:
        for i in range(50):
            conn.execute(
                "INSERT INTO training_examples (example_id, quality_score_auto, created_at, source) "
                "VALUES (?, NULL, ?, 'backfill')",
                (f"ex{i}", datetime.now(ET).isoformat()),
            )
    sent = check_action_reminders(db_path)
    assert "score_training" not in sent


@patch("src.notifications.telegram.send_telegram", return_value=True)
def test_notify_action_required_sends_message(mock_send):
    """notify_action_required should send a formatted Telegram message."""
    result = notify_action_required("Test action", "Do the thing", urgency="high")
    assert result is True
    call_text = mock_send.call_args[0][0]
    assert "ACTION REQUIRED" in call_text
    assert "Test action" in call_text
    assert "⚠️" in call_text  # high urgency icon


@patch("src.notifications.telegram.send_telegram", return_value=True)
def test_retrain_overdue_check(mock_send, db_path):
    """Should remind if model retrain is overdue (>14 days)."""
    with sqlite3.connect(db_path) as conn:
        old_date = (datetime.now(ET) - timedelta(days=20)).isoformat()
        conn.execute(
            "INSERT INTO model_versions (version_id, version_name, status, created_at, "
            "training_examples_count, synthetic_examples_count, outcome_examples_count, model_file_path) "
            "VALUES (?, ?, 'active', ?, 969, 0, 0, 'test.gguf')",
            ("v1", "halcyon-v1.0.0", old_date),
        )

    now = datetime.now(ET)
    # Only triggers on Sundays at 10+ AM
    if now.weekday() == 6 and now.hour >= 10:
        sent = check_action_reminders(db_path)
        assert "retrain_overdue" in sent
    else:
        # On non-Sundays, retrain check doesn't fire
        sent = check_action_reminders(db_path)
        assert "retrain_overdue" not in sent
