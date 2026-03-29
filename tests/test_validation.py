"""Tests for training dataset validation."""

import pytest
import sqlite3
import tempfile
import os
from datetime import datetime


@pytest.fixture
def test_db():
    fd, path = tempfile.mkstemp(suffix=".sqlite3")
    os.close(fd)
    from src.training.versioning import init_training_tables
    init_training_tables(path)
    yield path
    try:
        os.unlink(path)
    except PermissionError:
        pass


def _insert_example(db_path, ticker, source="historical_backfill",
                    output_text="WHY NOW: Test.\nDEEPER ANALYSIS: Test analysis.",
                    input_text="Score: 80/100\nSector: Technology"):
    import uuid
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO training_examples "
            "(example_id, created_at, source, ticker, instruction, input_text, output_text) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (str(uuid.uuid4()), datetime.now().isoformat(), source, ticker,
             "Write analysis.", input_text, output_text),
        )
        conn.commit()


def test_validate_empty_dataset(test_db):
    from src.training.validation import validate_training_dataset
    result = validate_training_dataset(test_db)
    assert result["total_examples"] == 0
    assert result["overall_health"] == "empty"


def test_validate_format_compliance(test_db):
    from src.training.validation import validate_training_dataset

    # Good format
    _insert_example(test_db, "AAPL",
                    output_text="WHY NOW: Strong momentum.\nDEEPER ANALYSIS: The trend is clear.")
    # Bad format (missing sections)
    _insert_example(test_db, "MSFT",
                    output_text="This stock looks good. Buy it.")

    result = validate_training_dataset(test_db)
    assert result["format_compliance"] == 0.5  # 1 of 2 pass


def test_validate_win_loss_balance(test_db):
    from src.training.validation import validate_training_dataset

    # Add wins
    for i in range(6):
        _insert_example(test_db, f"WIN{i}",
                        input_text="target_1_hit clean_win Score: 80/100")
    # Add losses
    for i in range(4):
        _insert_example(test_db, f"LOSS{i}",
                        input_text="stop_hit clean_loss Score: 60/100")

    result = validate_training_dataset(test_db)
    assert result["wins"] == 6
    assert result["losses"] == 4
    assert 0.55 < result["win_pct"] < 0.65


def test_validate_diversity_score(test_db):
    from src.training.validation import validate_training_dataset

    # All same ticker = low diversity
    for _ in range(10):
        _insert_example(test_db, "AAPL")

    result = validate_training_dataset(test_db)
    assert result["tickers_represented"] == 1
    assert result["diversity_score"] == 0  # Shannon entropy of 1 element


def test_validate_duplicate_detection(test_db):
    from src.training.validation import validate_training_dataset

    same_output = "WHY NOW: Exact same text.\nDEEPER ANALYSIS: Identical content."
    _insert_example(test_db, "AAPL", output_text=same_output)
    _insert_example(test_db, "MSFT", output_text=same_output)

    result = validate_training_dataset(test_db)
    assert result["exact_duplicates"] == 1


def test_validate_output_length_stats(test_db):
    from src.training.validation import validate_training_dataset

    _insert_example(test_db, "AAPL", output_text="WHY NOW: Short.\nDEEPER ANALYSIS: Also short.")
    _insert_example(test_db, "MSFT",
                    output_text="WHY NOW: " + "word " * 100 + "\nDEEPER ANALYSIS: " + "text " * 100)

    result = validate_training_dataset(test_db)
    assert result["output_length"]["min_words"] < result["output_length"]["max_words"]
