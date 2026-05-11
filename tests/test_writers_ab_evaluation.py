"""Phase 3-revised T3 — ab_evaluation writer cross-engine verification.

Called by: pytest (Sprint 5 §J5/§J6 Phase 3-revised T3)
Calls: src.training.ab_evaluation
Owns tables: model_evaluations (test verifies writes round-trip on SQLite)
Config keys: none (uses fixture-injected db_path)
Tests: SQLite model_evaluations insert behavior via engine_aware_upsert

Note: model_evaluations has sync_to_postgres=False — the PG path is not
exercised in production. The SQLite round-trip test verifies the INSERT
site was converted to engine_aware_upsert and commits correctly.
"""

import sqlite3
import uuid
from unittest.mock import patch, MagicMock

import pytest

from tests.conftest import init_test_db


def _make_evaluation_row():
    return {
        "evaluation_id": str(uuid.uuid4()),
        "created_at": "2026-05-11T10:00:00-04:00",
        "recommendation_id": "rec-001",
        "ticker": "AAPL",
        "input_text": "AAPL analysis input",
        "current_model": "halcyon-v1",
        "current_output": "current analysis text",
        "current_score": 3.0,
        "new_model": "halcyon-v2",
        "new_output": "new analysis text",
        "new_score": 4.0,
        "winner": "new",
        "score_delta": 1.0,
    }


def test_ab_evaluation_uses_engine_aware_upsert(tmp_path):
    """Verify run_shadow_evaluation writes via engine_aware_upsert (not raw INSERT).

    Inspects the import of ab_evaluation to confirm engine_aware_upsert is
    imported from src.utils.db — this is the static contract that T3 establishes.
    """
    import importlib
    import src.training.ab_evaluation as mod

    assert hasattr(mod, "engine_aware_upsert"), (
        "engine_aware_upsert must be imported in src/training/ab_evaluation.py "
        "(the INSERT site was not converted to engine_aware_upsert)"
    )


def test_ab_evaluation_writes_round_trip_sqlite(tmp_path):
    """SQLite path: write a model_evaluations row + read back.

    Patches all external dependencies (LLM calls) so only the DB write path
    is exercised. Verifies the row appears with correct column values.
    """
    db_path = str(tmp_path / "test.db")
    init_test_db(db_path, tables=["model_evaluations"])

    eval_row = _make_evaluation_row()

    with (
        patch("src.training.ab_evaluation.init_training_tables"),
        patch("src.llm.client.generate", return_value="current output text"),
        patch("src.training.ab_evaluation._score_output") as mock_score,
        patch("src.training.ab_evaluation.load_config") as mock_cfg,
    ):
        import requests as _req
        with patch.object(_req, "post") as mock_post:
            mock_resp = MagicMock()
            mock_resp.ok = True
            mock_resp.json.return_value = {"response": "new output text"}
            mock_post.return_value = mock_resp
            mock_score.side_effect = [eval_row["current_score"], eval_row["new_score"]]
            mock_cfg.return_value = {"llm": {"model": "halcyon-v1", "base_url": "http://localhost:11434"}}

            from src.training.ab_evaluation import run_shadow_evaluation
            run_shadow_evaluation(
                new_model=eval_row["new_model"],
                current_model=eval_row["current_model"],
                input_text=eval_row["input_text"],
                ticker=eval_row["ticker"],
                recommendation_id=eval_row["recommendation_id"],
                db_path=db_path,
            )

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute("SELECT * FROM model_evaluations").fetchall()
    finally:
        conn.close()

    assert len(rows) == 1, f"Expected 1 row in model_evaluations, got {len(rows)}"
    row = rows[0]
    assert row["current_model"] == eval_row["current_model"]
    assert row["new_model"] == eval_row["new_model"]
    assert row["ticker"] == eval_row["ticker"]
    assert row["winner"] in ("new", "current", "tie")


def test_ab_evaluation_import_no_raw_insert(tmp_path):
    """Verify no raw INSERT INTO model_evaluations in ab_evaluation.py source."""
    import ast
    import pathlib

    src_path = pathlib.Path(
        "src/training/ab_evaluation.py"
    )
    source = src_path.read_text(encoding="utf-8")
    tree = ast.parse(source)

    raw_insert_found = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if (
                "INSERT INTO model_evaluations" in node.value
                and "engine_aware_upsert" not in node.value
            ):
                raw_insert_found = True
                break

    assert not raw_insert_found, (
        "src/training/ab_evaluation.py still contains a raw 'INSERT INTO model_evaluations' "
        "string literal — the INSERT site must be converted to engine_aware_upsert"
    )
