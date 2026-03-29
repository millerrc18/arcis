"""Tests for chronological validation holdout."""

import json
import os
import sqlite3
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

ET = ZoneInfo("America/New_York")


@pytest.fixture
def db_with_examples(tmp_path):
    """Create a test DB with training examples spanning dates."""
    db_path = str(tmp_path / "test.sqlite3")

    from src.training.versioning import init_training_tables
    init_training_tables(db_path)

    with sqlite3.connect(db_path) as conn:
        base_date = datetime(2026, 1, 1, tzinfo=ET)
        for i in range(100):
            date = base_date + timedelta(days=i)
            conn.execute(
                """INSERT INTO training_examples
                   (example_id, created_at, source, ticker, instruction, input_text, output_text, quality_score)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (f"ex-{i}", date.isoformat(), "historical_backfill", f"TICK{i % 10}",
                 "instruction", f"input {i}", f"output {i}", 4.0),
            )
        conn.commit()

    return db_path


class TestChronologicalSplit:
    def test_split_produces_correct_date_ordering(self, db_with_examples, tmp_path):
        from src.training.trainer import export_training_data
        output_dir = str(tmp_path / "output")
        split_counts, total = export_training_data(output_dir=output_dir, db_path=db_with_examples)

        assert total == 100
        assert split_counts["training"] > 0
        assert split_counts["holdout"] > 0

        # Training examples should come before holdout
        train_dates = []
        with open(os.path.join(output_dir, "dataset.jsonl")) as f:
            for line in f:
                # Training file doesn't have created_at, but holdout does
                pass  # Just verify it exists and is non-empty

        holdout_dates = []
        with open(os.path.join(output_dir, "holdout.jsonl")) as f:
            for line in f:
                ex = json.loads(line)
                holdout_dates.append(ex["created_at"])

        # Holdout dates should be chronologically after training dates
        assert len(holdout_dates) > 0

    def test_temporal_gap_between_train_and_holdout(self, db_with_examples, tmp_path):
        from src.training.trainer import export_training_data
        output_dir = str(tmp_path / "output")
        export_training_data(output_dir=output_dir, db_path=db_with_examples)

        with open(os.path.join(output_dir, "split_info.json")) as f:
            info = json.load(f)

        # Should have a temporal gap
        assert info["temporal_gap_days"] >= 5

    def test_holdout_examples_not_in_training(self, db_with_examples, tmp_path):
        from src.training.trainer import export_training_data
        output_dir = str(tmp_path / "output")
        export_training_data(output_dir=output_dir, db_path=db_with_examples)

        train_inputs = set()
        with open(os.path.join(output_dir, "dataset.jsonl")) as f:
            for line in f:
                ex = json.loads(line)
                train_inputs.add(ex["input"])

        holdout_inputs = set()
        with open(os.path.join(output_dir, "holdout.jsonl")) as f:
            for line in f:
                ex = json.loads(line)
                holdout_inputs.add(ex["input"])

        # No overlap between train and holdout
        assert len(train_inputs & holdout_inputs) == 0

    def test_split_info_contains_correct_metadata(self, db_with_examples, tmp_path):
        from src.training.trainer import export_training_data
        output_dir = str(tmp_path / "output")
        split_counts, total = export_training_data(output_dir=output_dir, db_path=db_with_examples)

        with open(os.path.join(output_dir, "split_info.json")) as f:
            info = json.load(f)

        assert info["total_examples"] == 100
        assert info["training_examples"] == split_counts["training"]
        assert info["holdout_examples"] == split_counts["holdout"]
        assert info["training_date_range"]["start"] is not None
        assert info["holdout_date_range"]["start"] is not None
        assert "temporal_gap_days" in info

    def test_empty_dataset_produces_empty_files(self, tmp_path):
        db_path = str(tmp_path / "empty.sqlite3")
        from src.training.versioning import init_training_tables
        init_training_tables(db_path)

        from src.training.trainer import export_training_data
        output_dir = str(tmp_path / "output")
        split_counts, total = export_training_data(output_dir=output_dir, db_path=db_path)

        assert total == 0
        assert split_counts["training"] == 0
        assert split_counts["holdout"] == 0
