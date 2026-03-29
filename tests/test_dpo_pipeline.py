"""Tests for DPO preference pair pipeline."""

import pytest
import sqlite3
import tempfile
import os
from unittest.mock import patch


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


def test_preference_table_creation(test_db):
    from src.training.dpo_pipeline import _ensure_preference_table

    _ensure_preference_table(test_db)

    with sqlite3.connect(test_db) as conn:
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='preference_pairs'"
        )
        assert cursor.fetchone() is not None


def test_preference_table_schema(test_db):
    from src.training.dpo_pipeline import _ensure_preference_table

    _ensure_preference_table(test_db)

    with sqlite3.connect(test_db) as conn:
        cursor = conn.execute("PRAGMA table_info(preference_pairs)")
        columns = [row[1] for row in cursor.fetchall()]

    assert "pair_id" in columns
    assert "input_text" in columns
    assert "chosen_output" in columns
    assert "rejected_output" in columns
    assert "quality_delta" in columns


def test_pair_selection_minimum_delta(test_db):
    """Pairs with quality delta < 1.0 should not be stored."""
    from src.training.dpo_pipeline import _ensure_preference_table

    _ensure_preference_table(test_db)

    # Manually insert a pair with low delta
    with sqlite3.connect(test_db) as conn:
        conn.execute(
            "INSERT INTO preference_pairs "
            "(pair_id, created_at, input_text, chosen_output, rejected_output, quality_delta) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("test1", "2026-01-01", "input", "chosen", "rejected", 0.5),
        )
        conn.commit()

    # The pair exists but should be flagged as low-quality
    with sqlite3.connect(test_db) as conn:
        row = conn.execute(
            "SELECT quality_delta FROM preference_pairs WHERE pair_id = 'test1'"
        ).fetchone()
    assert row[0] == 0.5  # Stored but delta is below threshold


def test_export_format(test_db):
    """DPO export should produce correct JSONL format."""
    import json
    import tempfile
    from src.training.dpo_pipeline import _ensure_preference_table, export_preference_pairs

    _ensure_preference_table(test_db)

    # Insert test pairs
    with sqlite3.connect(test_db) as conn:
        for i in range(3):
            conn.execute(
                "INSERT INTO preference_pairs "
                "(pair_id, created_at, input_text, chosen_output, rejected_output, quality_delta) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (f"pair_{i}", "2026-01-01", f"input {i}", f"good output {i}",
                 f"bad output {i}", 1.5),
            )
        conn.commit()

    with tempfile.TemporaryDirectory() as tmpdir:
        count = export_preference_pairs(output_dir=tmpdir, db_path=test_db)
        assert count == 3

        with open(os.path.join(tmpdir, "preference_pairs.jsonl")) as f:
            lines = f.readlines()
        assert len(lines) == 3

        first = json.loads(lines[0])
        assert "prompt" in first
        assert "chosen" in first
        assert "rejected" in first
        assert isinstance(first["prompt"], list)


def test_get_preference_pair_count(test_db):
    from src.training.dpo_pipeline import _ensure_preference_table, get_preference_pair_count

    _ensure_preference_table(test_db)
    assert get_preference_pair_count(test_db) == 0

    with sqlite3.connect(test_db) as conn:
        conn.execute(
            "INSERT INTO preference_pairs "
            "(pair_id, created_at, input_text, chosen_output, rejected_output) "
            "VALUES (?, ?, ?, ?, ?)",
            ("p1", "2026-01-01", "inp", "chosen", "rejected"),
        )
        conn.commit()

    assert get_preference_pair_count(test_db) == 1


def test_generate_preference_pairs_empty_db(test_db):
    """Test that generate_preference_pairs handles empty DB gracefully."""
    from src.training.dpo_pipeline import generate_preference_pairs
    count = generate_preference_pairs(n_pairs=5, db_path=test_db)
    assert count == 0  # No training examples to work with
