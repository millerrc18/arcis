"""Tests for the fine-tuning trainer logic."""

import os
import sqlite3
import tempfile
import uuid
from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from src.training.trainer import should_train, check_model_performance
from src.training.versioning import init_training_tables, register_model_version

ET = ZoneInfo("America/New_York")


def _tmp_db():
    fd, path = tempfile.mkstemp(suffix=".sqlite3")
    os.close(fd)
    return path


def _insert_examples(db_path: str, count: int, created_at: str | None = None):
    """Insert N training examples."""
    with sqlite3.connect(db_path) as conn:
        for _ in range(count):
            ts = created_at or datetime.now(ET).isoformat()
            conn.execute(
                """INSERT INTO training_examples
                   (example_id, created_at, source, instruction, input_text, output_text)
                   VALUES (?, ?, 'synthetic_claude', 'sys', 'in', 'out')""",
                (str(uuid.uuid4()), ts),
            )
        conn.commit()


_ENABLED_CONFIG = {
    "training": {
        "enabled": True,
        "auto_train_threshold": 50,
        "auto_train_time_days": 7,
        "auto_train_min_examples": 20,
        "auto_rollback_expectancy_drop": 0.20,
        "auto_rollback_winrate_drop": 0.10,
    }
}

_DISABLED_CONFIG = {"training": {"enabled": False}}


def _mock_enabled():
    return _ENABLED_CONFIG


def _mock_disabled():
    return _DISABLED_CONFIG


# Isolate the threshold trigger from the temporal-holdout viability gate
# (should_train added a get_training_split_viability check inside the
# threshold branch). Viability is covered by tests/test_trainer_holdout_alert.py;
# here we assert only that meeting the example threshold triggers training.
# Without this, the 55 same-day seed examples yield an empty holdout -> non-viable.
@patch("src.training.trainer.get_training_split_viability",
       return_value=(True, "viable (test)", {}))
@patch("src.training.trainer.load_config", _mock_enabled)
def test_should_train_true_when_threshold_met(mock_viability):
    db = _tmp_db()
    init_training_tables(db)
    _insert_examples(db, 55)

    trigger, reason = should_train(db)
    assert trigger is True
    assert "55" in reason


@patch("src.training.trainer.load_config", _mock_enabled)
def test_should_train_false_when_below_threshold():
    db = _tmp_db()
    init_training_tables(db)
    _insert_examples(db, 10)

    trigger, reason = should_train(db)
    assert trigger is False


@patch("src.training.trainer.load_config", _mock_disabled)
def test_should_train_false_when_disabled():
    db = _tmp_db()
    init_training_tables(db)
    _insert_examples(db, 100)

    trigger, reason = should_train(db)
    assert trigger is False
    assert "disabled" in reason.lower()


@patch("src.training.trainer.load_config", _mock_enabled)
def test_check_model_performance_waiting_insufficient_trades():
    db = _tmp_db()
    init_training_tables(db)
    result = check_model_performance(db)
    assert result["action"] == "waiting"
