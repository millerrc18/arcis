"""Tests for A/B model shadow evaluation."""

import sqlite3
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

ET = ZoneInfo("America/New_York")


@pytest.fixture
def db_with_evaluations(tmp_path):
    """Create a test DB with model evaluation records."""
    db_path = str(tmp_path / "test.sqlite3")
    from src.training.versioning import init_training_tables
    init_training_tables(db_path)
    return db_path


def _insert_evaluation(db_path, new_model, winner, score_delta=0.5):
    """Helper to insert an evaluation record."""
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """INSERT INTO model_evaluations
               (evaluation_id, created_at, ticker, input_text,
                current_model, current_score, new_model, new_score, winner, score_delta)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (str(uuid.uuid4()), datetime.now(ET).isoformat(), "AAPL", "test input",
             "halcyon-v1", 3.5, new_model, 4.0 if winner == "new" else 3.0,
             winner, score_delta),
        )
        conn.commit()


class TestPromotionLogic:
    def test_promote_when_win_rate_above_60(self, db_with_evaluations):
        from src.training.ab_evaluation import check_promotion_ready

        # Insert 25 evaluations, 18 wins (72%)
        for i in range(18):
            _insert_evaluation(db_with_evaluations, "halcyon-v2", "new", 0.5)
        for i in range(7):
            _insert_evaluation(db_with_evaluations, "halcyon-v2", "current", -0.3)

        result = check_promotion_ready("halcyon-v2", min_evaluations=20, db_path=db_with_evaluations)
        assert result["ready"] is True
        assert result["recommendation"] == "promote"
        assert result["win_rate"] >= 0.60

    def test_reject_when_win_rate_below_60(self, db_with_evaluations):
        from src.training.ab_evaluation import check_promotion_ready

        # Insert 25 evaluations, 10 wins (40%)
        for i in range(10):
            _insert_evaluation(db_with_evaluations, "halcyon-v2", "new", 0.3)
        for i in range(15):
            _insert_evaluation(db_with_evaluations, "halcyon-v2", "current", -0.3)

        result = check_promotion_ready("halcyon-v2", min_evaluations=20, db_path=db_with_evaluations)
        assert result["ready"] is False
        assert result["recommendation"] == "reject"

    def test_needs_more_data_below_threshold(self, db_with_evaluations):
        from src.training.ab_evaluation import check_promotion_ready

        # Only 5 evaluations
        for i in range(5):
            _insert_evaluation(db_with_evaluations, "halcyon-v2", "new", 0.5)

        result = check_promotion_ready("halcyon-v2", min_evaluations=20, db_path=db_with_evaluations)
        assert result["ready"] is False
        assert result["recommendation"] == "needs_more_data"
        assert result["needed"] == 15

    def test_evaluations_stored_correctly(self, db_with_evaluations):
        _insert_evaluation(db_with_evaluations, "halcyon-v2", "new", 0.5)

        with sqlite3.connect(db_with_evaluations) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM model_evaluations").fetchone()

        assert row is not None
        assert row["new_model"] == "halcyon-v2"
        assert row["winner"] == "new"
        assert row["score_delta"] == 0.5
