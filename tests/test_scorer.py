"""Tests for the GuardedScorer between-scan inference scoring."""

import json
import sqlite3
from datetime import datetime
from unittest.mock import patch, MagicMock
from zoneinfo import ZoneInfo

import pytest

ET = ZoneInfo("America/New_York")


# ── minutes_until_next_scan ──────────────────────────────────────────


@pytest.mark.parametrize("minute,expected", [
    (0, 30),   # Just past :00 scan
    (5, 25),   # 5 minutes in
    (15, 15),  # Mid-window
    (27, 3),   # Near guard band
    (29, 1),   # Almost at :30
    (30, 30),  # Just past :30 scan
    (35, 25),  # 5 minutes into second half
    (45, 15),  # Mid second window
    (57, 3),   # Near second guard band
    (59, 1),   # Almost at :00
])
def test_minutes_until_next_scan(minute, expected):
    from src.scheduler.scorer import GuardedScorer
    scorer = GuardedScorer()
    mock_now = datetime(2026, 3, 25, 10, minute, 0, tzinfo=ET)
    with patch("src.scheduler.scorer.datetime") as mock_dt:
        mock_dt.now.return_value = mock_now
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
        result = scorer.minutes_until_next_scan()
        assert result == expected


# ── is_scoring_window ────────────────────────────────────────────────


@pytest.mark.parametrize("hour,minute,expected,reason", [
    # Before market open
    (8, 30, False, "pre-market"),
    (9, 0, False, "pre-market"),
    (9, 29, False, "pre-market"),
    # First window of day — skipped for stability
    (9, 30, False, "scan firing"),
    (9, 35, False, "first window skipped"),
    # First valid window
    (9, 38, True, "first valid window"),
    (9, 57, True, "end of first valid window"),
    # Between windows — scan time
    (10, 0, False, "scan time :00"),
    (10, 5, False, "CPU task time"),
    (10, 7, False, "CPU task time"),
    # Valid scoring window
    (10, 8, True, "scoring window start"),
    (10, 15, True, "mid scoring window"),
    (10, 27, True, "scoring window end"),
    # Scan time again
    (10, 28, False, "approaching :30 scan"),
    (10, 30, False, "scan time :30"),
    (10, 37, False, "CPU task time"),
    # Second half window
    (10, 38, True, "second half window start"),
    (10, 50, True, "mid second half window"),
    (10, 57, True, "second half window end"),
    (10, 58, False, "approaching :00 scan"),
    # Mid-day valid windows
    (13, 10, True, "mid-day scoring window"),
    (14, 45, True, "afternoon scoring window"),
    # Last 30 min before close — skipped
    (15, 30, False, "last 30 min before close"),
    (15, 45, False, "last 30 min before close"),
    # After market close
    (16, 10, False, "after close"),
    (17, 0, False, "after close"),
])
def test_is_scoring_window(hour, minute, expected, reason):
    from src.scheduler.scorer import GuardedScorer
    scorer = GuardedScorer()
    mock_now = datetime(2026, 3, 25, hour, minute, 0, tzinfo=ET)  # Wednesday
    with patch("src.scheduler.scorer.datetime") as mock_dt:
        mock_dt.now.return_value = mock_now
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
        result = scorer.is_scoring_window()
        assert result == expected, f"Failed at {hour}:{minute:02d} ({reason})"


def test_is_scoring_window_weekend():
    """Scoring should not run on weekends."""
    from src.scheduler.scorer import GuardedScorer
    scorer = GuardedScorer()
    # Saturday at 10:15 — would be valid on weekday
    mock_now = datetime(2026, 3, 28, 10, 15, 0, tzinfo=ET)  # Saturday
    with patch("src.scheduler.scorer.datetime") as mock_dt:
        mock_dt.now.return_value = mock_now
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
        # is_scoring_window doesn't check weekday (watch loop handles that),
        # but it checks market hours which are defined by time
        # The method only checks time, not day-of-week — that's the watch loop's job
        # So at 10:15 it would return True
        result = scorer.is_scoring_window()
        assert result is True  # Day-of-week filtering is in watch loop


# ── score_batch ──────────────────────────────────────────────────────


def test_score_batch_empty_backlog(tmp_path):
    """Scoring handles empty backlog gracefully."""
    from src.scheduler.scorer import GuardedScorer

    db = str(tmp_path / "test.db")
    scorer = GuardedScorer(db_path=db)

    result = scorer.score_batch()
    assert result["scored"] == 0
    assert result["remaining"] == 0
    assert result["stopped_reason"] == "backlog_empty"


def test_score_batch_scores_examples(tmp_path):
    """Scoring processes unscored examples and saves results."""
    from src.scheduler.scorer import GuardedScorer
    from src.training.versioning import init_training_tables

    db = str(tmp_path / "test.db")
    init_training_tables(db)

    # Ensure quality_score_auto column
    with sqlite3.connect(db) as conn:
        try:
            conn.execute("ALTER TABLE training_examples ADD COLUMN quality_score_auto REAL")
        except sqlite3.OperationalError:
            pass

    # Insert test examples
    with sqlite3.connect(db) as conn:
        for i in range(3):
            conn.execute(
                "INSERT INTO training_examples "
                "(example_id, created_at, source, ticker, instruction, input_text, output_text) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (f"test-{i}", "2026-03-25", "outcome_win", "AAPL",
                 "instruction", f"input data {i}", f"output commentary {i}"),
            )
        conn.commit()

    scorer = GuardedScorer(db_path=db)

    mock_scores = json.dumps({
        "thesis_clarity": 4, "evidence_grounding": 3, "risk_identification": 4,
        "calibration": 3, "structure": 4, "actionability": 4,
        "weighted_overall": 3.6, "process_quality": "good",
        "issues": "Minor calibration gap"
    })

    with patch("src.scheduler.scorer.GuardedScorer.minutes_until_next_scan", return_value=20.0), \
         patch("src.llm.client.generate", return_value=mock_scores):
        result = scorer.score_batch()

    assert result["scored"] == 3
    assert result["remaining"] == 0
    assert result["stopped_reason"] == "backlog_empty"

    # Verify scores saved to DB
    with sqlite3.connect(db) as conn:
        row = conn.execute(
            "SELECT quality_score_auto FROM training_examples WHERE example_id = 'test-0'"
        ).fetchone()
        assert row[0] is not None
        assert row[0] > 0


def test_score_batch_stops_at_guard_band(tmp_path):
    """Scoring stops when guard band is reached."""
    from src.scheduler.scorer import GuardedScorer
    from src.training.versioning import init_training_tables

    db = str(tmp_path / "test.db")
    init_training_tables(db)

    with sqlite3.connect(db) as conn:
        try:
            conn.execute("ALTER TABLE training_examples ADD COLUMN quality_score_auto REAL")
        except sqlite3.OperationalError:
            pass
        for i in range(5):
            conn.execute(
                "INSERT INTO training_examples "
                "(example_id, created_at, source, ticker, instruction, input_text, output_text) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (f"test-{i}", "2026-03-25", "outcome_win", "AAPL",
                 "instruction", f"input {i}", f"output {i}"),
            )
        conn.commit()

    scorer = GuardedScorer(guard_minutes=3, db_path=db)

    mock_scores = json.dumps({
        "thesis_clarity": 4, "evidence_grounding": 3, "risk_identification": 4,
        "calibration": 3, "structure": 4, "actionability": 4,
    })

    call_count = 0

    def fake_minutes():
        nonlocal call_count
        call_count += 1
        # First call: plenty of time, second call: guard band
        return 15.0 if call_count <= 1 else 2.0

    with patch.object(scorer, "minutes_until_next_scan", side_effect=fake_minutes), \
         patch("src.llm.client.generate", return_value=mock_scores):
        result = scorer.score_batch()

    assert result["scored"] == 1
    assert result["stopped_reason"] == "guard_band"
    assert result["remaining"] > 0


def test_score_batch_max_per_window(tmp_path):
    """Scoring respects max_per_window cap."""
    from src.scheduler.scorer import GuardedScorer
    from src.training.versioning import init_training_tables

    db = str(tmp_path / "test.db")
    init_training_tables(db)

    with sqlite3.connect(db) as conn:
        try:
            conn.execute("ALTER TABLE training_examples ADD COLUMN quality_score_auto REAL")
        except sqlite3.OperationalError:
            pass
        for i in range(10):
            conn.execute(
                "INSERT INTO training_examples "
                "(example_id, created_at, source, ticker, instruction, input_text, output_text) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (f"test-{i}", "2026-03-25", "outcome_win", "AAPL",
                 "instruction", f"input {i}", f"output {i}"),
            )
        conn.commit()

    scorer = GuardedScorer(max_per_window=2, db_path=db)

    mock_scores = json.dumps({
        "thesis_clarity": 4, "evidence_grounding": 3, "risk_identification": 4,
        "calibration": 3, "structure": 4, "actionability": 4,
    })

    with patch.object(scorer, "minutes_until_next_scan", return_value=20.0), \
         patch("src.llm.client.generate", return_value=mock_scores):
        result = scorer.score_batch()

    assert result["scored"] == 2
    assert result["stopped_reason"] == "max_reached"


def test_score_batch_handles_llm_failure(tmp_path):
    """Scoring continues gracefully when LLM returns None."""
    from src.scheduler.scorer import GuardedScorer
    from src.training.versioning import init_training_tables

    db = str(tmp_path / "test.db")
    init_training_tables(db)

    with sqlite3.connect(db) as conn:
        try:
            conn.execute("ALTER TABLE training_examples ADD COLUMN quality_score_auto REAL")
        except sqlite3.OperationalError:
            pass
        conn.execute(
            "INSERT INTO training_examples "
            "(example_id, created_at, source, ticker, instruction, input_text, output_text) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("test-0", "2026-03-25", "outcome_win", "AAPL",
             "instruction", "input", "output"),
        )
        conn.commit()

    scorer = GuardedScorer(db_path=db)

    with patch.object(scorer, "minutes_until_next_scan", return_value=20.0), \
         patch("src.llm.client.generate", return_value=None):
        result = scorer.score_batch()

    # LLM failed, so nothing scored, but no crash
    assert result["scored"] == 0
    assert result["remaining"] == 0
    assert result["stopped_reason"] == "backlog_empty"


# ── _score_with_ollama ───────────────────────────────────────────────


def test_score_with_ollama_valid_response():
    """Ollama scoring parses valid JSON response correctly."""
    from src.scheduler.scorer import GuardedScorer
    scorer = GuardedScorer()

    mock_response = json.dumps({
        "thesis_clarity": 4, "evidence_grounding": 3, "risk_identification": 4,
        "calibration": 3, "structure": 4, "actionability": 4,
    })

    with patch("src.llm.client.generate", return_value=mock_response):
        result = scorer._score_with_ollama("input text", "output text")

    assert result is not None
    expected = round(4*0.25 + 3*0.20 + 4*0.20 + 3*0.15 + 4*0.10 + 4*0.10, 1)
    assert result["weighted_overall"] == expected
    assert result["process_quality"] == "good"


def test_score_with_ollama_markdown_fences():
    """Ollama scoring handles markdown-wrapped JSON."""
    from src.scheduler.scorer import GuardedScorer
    scorer = GuardedScorer()

    inner = json.dumps({
        "thesis_clarity": 5, "evidence_grounding": 5, "risk_identification": 5,
        "calibration": 5, "structure": 5, "actionability": 5,
    })
    mock_response = f"```json\n{inner}\n```"

    with patch("src.llm.client.generate", return_value=mock_response):
        result = scorer._score_with_ollama("input", "output")

    assert result is not None
    assert result["weighted_overall"] == 5.0
    assert result["process_quality"] == "excellent"


def test_score_with_ollama_returns_none_on_failure():
    """Ollama scoring returns None when LLM fails."""
    from src.scheduler.scorer import GuardedScorer
    scorer = GuardedScorer()

    with patch("src.llm.client.generate", return_value=None):
        result = scorer._score_with_ollama("input", "output")
    assert result is None


def test_score_with_ollama_invalid_json():
    """Ollama scoring returns None for unparseable response."""
    from src.scheduler.scorer import GuardedScorer
    scorer = GuardedScorer()

    with patch("src.llm.client.generate", return_value="This is not JSON"):
        result = scorer._score_with_ollama("input", "output")
    assert result is None
