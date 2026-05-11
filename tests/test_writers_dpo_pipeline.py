"""Phase 3-revised T3 — dpo_pipeline writer cross-engine verification.

Called by: pytest (Sprint 5 §J5/§J6 Phase 3-revised T3)
Calls: src.training.dpo_pipeline
Owns tables: preference_pairs (test verifies writes round-trip on SQLite)
Config keys: none (uses fixture-injected db_path)
Tests: SQLite preference_pairs insert behavior via engine_aware_upsert

Note: preference_pairs has sync_to_postgres=False — the PG path is not
exercised in production. The SQLite round-trip test verifies the INSERT
site was converted to engine_aware_upsert and commits correctly.
"""

import sqlite3
import uuid
from unittest.mock import patch, MagicMock

import pytest

from tests.conftest import init_test_db


def _make_preference_row():
    return {
        "pair_id": str(uuid.uuid4()),
        "created_at": "2026-05-11T10:00:00-04:00",
        "ticker": "MSFT",
        "input_text": "MSFT analysis input",
        "chosen_output": "better output text",
        "rejected_output": "worse output text",
        "chosen_source": "ollama_generated",
        "rejected_source": "ollama_generated",
        "quality_delta": 2.0,
        "notes": "Best: 4.0, Worst: 2.0",
    }


def test_dpo_pipeline_uses_engine_aware_upsert(tmp_path):
    """Verify generate_preference_pairs writes via engine_aware_upsert (not raw INSERT).

    Inspects the import of dpo_pipeline to confirm engine_aware_upsert is
    imported from src.utils.db — this is the static contract that T3 establishes.
    """
    import src.training.dpo_pipeline as mod

    assert hasattr(mod, "engine_aware_upsert"), (
        "engine_aware_upsert must be imported in src/training/dpo_pipeline.py "
        "(the INSERT site was not converted to engine_aware_upsert)"
    )


def test_dpo_pipeline_writes_round_trip_sqlite(tmp_path):
    """SQLite path: write a preference_pairs row + read back.

    Patches all external dependencies (LLM calls) so only the DB write path
    is exercised. Verifies the row appears with correct column values.
    """
    db_path = str(tmp_path / "test.db")
    init_test_db(db_path, tables=["preference_pairs", "training_examples"])

    row = _make_preference_row()

    # Write a real training_examples row so the SELECT query finds something
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO training_examples "
        "(example_id, created_at, source, ticker, input_text, output_text, instruction, quality_score_auto) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            str(uuid.uuid4()),
            "2026-05-11T09:00:00-04:00",
            "outcome_win",
            row["ticker"],
            row["input_text"],
            "some output",
            "You are a senior equity research analyst.",
            4.0,
        ),
    )
    conn.commit()
    conn.close()

    with (
        patch("src.training.dpo_pipeline.init_training_tables"),
        patch("src.llm.client.generate") as mock_gen,
        patch("src.training.quality_filter.score_training_example") as mock_score,
    ):
        mock_gen.side_effect = [
            row["chosen_output"],
            row["rejected_output"],
            None,
            None,
        ]
        mock_score.side_effect = [
            {"overall": 4.0},
            {"overall": 2.0},
        ]

        from src.training.dpo_pipeline import generate_preference_pairs
        count = generate_preference_pairs(n_pairs=1, db_path=db_path)

    assert count == 1, f"Expected 1 preference pair generated, got {count}"

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute("SELECT * FROM preference_pairs").fetchall()
    finally:
        conn.close()

    assert len(rows) == 1, f"Expected 1 row in preference_pairs, got {len(rows)}"
    written = rows[0]
    assert written["ticker"] == row["ticker"]
    assert written["input_text"] == row["input_text"]
    assert written["chosen_source"] == "ollama_generated"
    assert written["rejected_source"] == "ollama_generated"
    assert written["quality_delta"] >= 1.0


def test_dpo_pipeline_import_no_raw_insert(tmp_path):
    """Verify no raw INSERT INTO preference_pairs in dpo_pipeline.py source."""
    import ast
    import pathlib

    src_path = pathlib.Path("src/training/dpo_pipeline.py")
    source = src_path.read_text(encoding="utf-8")
    tree = ast.parse(source)

    raw_insert_found = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if (
                "INSERT INTO preference_pairs" in node.value
                and "engine_aware_upsert" not in node.value
            ):
                raw_insert_found = True
                break

    assert not raw_insert_found, (
        "src/training/dpo_pipeline.py still contains a raw 'INSERT INTO preference_pairs' "
        "string literal — the INSERT site must be converted to engine_aware_upsert"
    )
