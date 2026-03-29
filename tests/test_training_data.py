"""Tests for training data export and bootstrap cost estimation."""

import json
import os
import sqlite3
import tempfile
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

from src.training.bootstrap import estimate_bootstrap_cost
from src.training.trainer import export_training_data
from src.training.versioning import init_training_tables

ET = ZoneInfo("America/New_York")


def _tmp_db():
    fd, path = tempfile.mkstemp(suffix=".sqlite3")
    os.close(fd)
    return path


def _insert_example(db_path: str, instruction: str = "sys", input_text: str = "in",
                    output_text: str = "out", source: str = "synthetic_claude"):
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """INSERT INTO training_examples
               (example_id, created_at, source, instruction, input_text, output_text)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (str(uuid.uuid4()), datetime.now(ET).isoformat(), source,
             instruction, input_text, output_text),
        )
        conn.commit()


def test_training_tables_created():
    db = _tmp_db()
    init_training_tables(db)
    with sqlite3.connect(db) as conn:
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        table_names = {t[0] for t in tables}
        assert "model_versions" in table_names
        assert "training_examples" in table_names


def test_export_training_data_writes_valid_jsonl():
    db = _tmp_db()
    init_training_tables(db)
    _insert_example(db, "system prompt", "input data", "output text")
    _insert_example(db, "system prompt 2", "input data 2", "output text 2")

    tmpdir = tempfile.mkdtemp()
    split_counts, count = export_training_data(tmpdir, db_path=db)

    assert count == 2
    # With only 2 examples, all go to training (holdout needs more data)
    file_path = os.path.join(tmpdir, "dataset.jsonl")
    assert os.path.exists(file_path)

    with open(file_path) as f:
        lines = f.readlines()
        assert len(lines) >= 1  # At least some in training
        for line in lines:
            obj = json.loads(line)
            assert "instruction" in obj
            assert "input" in obj
            assert "output" in obj


def test_estimate_bootstrap_cost():
    # 100 examples: 100 * (500 * 1.0/1M + 800 * 5.0/1M) = 100 * 0.0045 = $0.45
    cost = estimate_bootstrap_cost(100)
    assert abs(cost - 0.45) < 0.01

    cost_500 = estimate_bootstrap_cost(500)
    assert abs(cost_500 - 2.25) < 0.01

    assert estimate_bootstrap_cost(0) == 0.0
