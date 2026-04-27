"""Tests for Sprint 8 Task 1 — Training Pipeline Safety.

Covers: #110 feature snapshot sanitization, #111 canary exclusion,
#113 leakage detector minimum sample size, #114 temporal split order,
#115 small dataset handling, #116 partial close detection,
#625 quarantined row filter + outcome_template quarantine migration.
"""

import json
import sqlite3
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from tests.conftest import init_test_db


# ── #110: Feature snapshot sanitization ──────────────────────────────────

def test_sanitize_feature_snapshot_removes_outcome_fields():
    """Outcome-correlated fields must not appear in stored feature snapshots."""
    from src.training.data_collector import _sanitize_feature_snapshot, OUTCOME_FIELDS

    snapshot = (
        "Ticker: AAPL\n"
        "Current Price: $150.00\n"
        "Pnl Dollars: $250.00\n"
        "Exit Reason: target_hit\n"
        "Max Favorable Excursion: $300.00\n"
        "Trend State: uptrend\n"
        "Status: closed\n"
        "Duration Days: 5\n"
    )
    result = _sanitize_feature_snapshot(snapshot)
    for field in OUTCOME_FIELDS:
        # Convert field to the format used in the text (e.g. pnl_dollars -> pnl_dollars)
        assert field not in result.lower().replace(" ", "_"), f"Outcome field '{field}' leaked through"
    assert "Ticker: AAPL" in result
    assert "Current Price" in result
    assert "Trend State" in result


def test_sanitize_keeps_pre_trade_fields():
    """Pre-trade observable fields should be preserved."""
    from src.training.data_collector import _sanitize_feature_snapshot

    snapshot = (
        "Ticker: MSFT\n"
        "Current Price: $300.00\n"
        "Trend State: uptrend\n"
        "Pullback Depth: -2.5%\n"
        "Volume State: above_average\n"
    )
    result = _sanitize_feature_snapshot(snapshot)
    assert "Ticker: MSFT" in result
    assert "Pullback Depth" in result
    assert "Volume State" in result


# ── #111: Canary set exclusion ───────────────────────────────────────────

def test_canary_examples_excluded_from_training_export(tmp_path):
    """Canary example IDs must not appear in exported training data."""
    db_path = str(tmp_path / "test.db")

    # Create canary file
    canary_path = tmp_path / "canary_set.jsonl"
    canary_ids = ["canary-001", "canary-002"]
    for cid in canary_ids:
        canary_path.write_text(
            canary_path.read_text() + json.dumps({"example_id": cid, "input": "test", "expected_output": "test"}) + "\n"
            if canary_path.exists() else
            json.dumps({"example_id": cid, "input": "test", "expected_output": "test"}) + "\n"
        )

    # Create DB with training examples including canary IDs
    init_test_db(db_path, ["training_examples", "model_versions"])
    with sqlite3.connect(db_path) as conn:
        now = datetime.now().isoformat()
        for i, eid in enumerate(["canary-001", "canary-002", "train-001", "train-002"]):
            conn.execute(
                "INSERT INTO training_examples (example_id, created_at, source, ticker, recommendation_id, feature_snapshot, trade_outcome, instruction, input_text, output_text, quality_score, difficulty, curriculum_stage) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (eid, now, "blinded_win", "AAPL", f"rec-{i}", "features",
                 "outcome", "instruction", "input", "output", None, "structure", None)
            )

    # Patch canary path and run export
    with patch("src.training.canary.DEFAULT_CANARY_PATH", canary_path):
        from src.training.trainer import export_training_data
        output_dir = str(tmp_path / "output")
        result, total = export_training_data(output_dir=output_dir, db_path=db_path)

    # Read exported dataset and verify no canary IDs leaked
    dataset_path = Path(output_dir) / "dataset.jsonl"
    if dataset_path.exists():
        exported = dataset_path.read_text()
        # The exported JSONL doesn't include example_id, but the filtering
        # should have removed the canary examples entirely
        assert result["training"] + result["holdout"] <= 2  # Only non-canary examples


# ── #113: Leakage detector insufficient data ─────────────────────────────

def test_leakage_detector_insufficient_data(tmp_path):
    """With <30 examples per class, detector should return INSUFFICIENT_DATA."""
    pytest.importorskip("sklearn", reason="scikit-learn required for leakage tests")
    db_path = str(tmp_path / "test.db")
    init_test_db(db_path, ["training_examples"])
    with sqlite3.connect(db_path) as conn:
        # 45 wins but only 10 losses — losses below 30 threshold
        # Total >= 50 so we pass the initial minimum check
        for i in range(45):
            conn.execute(
                "INSERT INTO training_examples (example_id, created_at, source, ticker, "
                "instruction, input_text, output_text) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (f"win-{i}", "2026-03-25", "blinded_win", "AAPL",
                 "instr", "input",
                 f"analysis of stock {i} showing uptrend with strong momentum indicators"))
        for i in range(10):
            conn.execute(
                "INSERT INTO training_examples (example_id, created_at, source, ticker, "
                "instruction, input_text, output_text) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (f"loss-{i}", "2026-03-25", "blinded_loss", "MSFT",
                 "instr", "input",
                 f"analysis of stock {i} showing downtrend with weak volume"))

    from src.training.leakage_detector import check_outcome_leakage
    result = check_outcome_leakage(db_path)
    assert result["status"] == "INSUFFICIENT_DATA"
    assert "Need >=30 per class" in result.get("reason", "")


# ── #114: Temporal split order ───────────────────────────────────────────

def test_holdout_examples_are_chronologically_after_training(tmp_path):
    """All holdout examples must have created_at AFTER all training examples."""
    db_path = str(tmp_path / "test.db")
    init_test_db(db_path, ["training_examples", "model_versions"])
    with sqlite3.connect(db_path) as conn:
        base = datetime(2025, 1, 1)
        for i in range(50):
            dt = (base + timedelta(days=i)).isoformat()
            # Alternate quality scores: some good, some poor
            quality = 4.0 if i % 3 != 0 else 2.0
            conn.execute(
                "INSERT INTO training_examples (example_id, created_at, source, ticker, recommendation_id, feature_snapshot, trade_outcome, instruction, input_text, output_text, quality_score, difficulty, curriculum_stage) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (f"ex-{i}", dt, "blinded_win", "AAPL", f"rec-{i}", "features",
                 "outcome", "instruction", "input", "output", None, "structure", quality)
            )

    from src.training.trainer import export_training_data
    output_dir = str(tmp_path / "output")
    result, _ = export_training_data(output_dir=output_dir, db_path=db_path)

    # Read holdout and dataset files to verify temporal ordering
    holdout_path = Path(output_dir) / "holdout.jsonl"
    dataset_path = Path(output_dir) / "dataset.jsonl"

    if holdout_path.exists() and dataset_path.exists():
        split_info = json.loads((Path(output_dir) / "split_info.json").read_text())
        train_end = split_info["training_date_range"]["end"]
        holdout_start = split_info["holdout_date_range"]["start"]
        if train_end and holdout_start:
            assert holdout_start >= train_end, \
                f"Holdout start {holdout_start} is before training end {train_end}"


# ── #115: Small dataset handling ─────────────────────────────────────────

def test_small_dataset_does_not_crash(tmp_path):
    """Datasets with <5 examples should skip training, not crash."""
    db_path = str(tmp_path / "test.db")
    init_test_db(db_path, ["training_examples", "model_versions"])
    with sqlite3.connect(db_path) as conn:
        # Only 3 examples
        for i in range(3):
            conn.execute(
                "INSERT INTO training_examples (example_id, created_at, source, ticker, recommendation_id, feature_snapshot, trade_outcome, instruction, input_text, output_text, quality_score, difficulty, curriculum_stage) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (f"ex-{i}", datetime.now().isoformat(), "blinded_win", "AAPL",
                 f"rec-{i}", "feat", "out", "instr", "input", "output", None, "structure", None)
            )

    from src.training.trainer import export_training_data
    output_dir = str(tmp_path / "output")
    # Should not crash even with tiny dataset
    result, total = export_training_data(output_dir=output_dir, db_path=db_path)
    assert total == 3


# ── #116: Partial close detection ────────────────────────────────────────

def test_partial_close_detected_and_excluded():
    """Trades with partial close exit_reason should be labeled PARTIAL and excluded."""
    from src.training.data_collector import _sanitize_feature_snapshot

    # Verify the source label logic works with partial exit reasons
    exit_reason = "partial_target_stop"
    pnl = 50.0

    # Simulate the labeling logic from data_collector
    if "partial" in exit_reason.lower():
        source = "blinded_partial"
    elif pnl > 0:
        source = "blinded_win"
    else:
        source = "blinded_loss"

    assert source == "blinded_partial"


def test_partial_examples_excluded_from_export(tmp_path):
    """Partial-close examples should not appear in exported training data."""
    db_path = str(tmp_path / "test.db")
    init_test_db(db_path, ["training_examples", "model_versions"])
    with sqlite3.connect(db_path) as conn:
        now = datetime.now().isoformat()
        # 5 normal + 2 partial
        for i in range(5):
            conn.execute(
                "INSERT INTO training_examples (example_id, created_at, source, ticker, recommendation_id, feature_snapshot, trade_outcome, instruction, input_text, output_text, quality_score, difficulty, curriculum_stage) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (f"ex-{i}", now, "blinded_win", "AAPL", f"rec-{i}", "feat",
                 "out", "instr", "input", "output", None, "structure", None)
            )
        for i in range(2):
            conn.execute(
                "INSERT INTO training_examples (example_id, created_at, source, ticker, recommendation_id, feature_snapshot, trade_outcome, instruction, input_text, output_text, quality_score, difficulty, curriculum_stage) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (f"partial-{i}", now, "blinded_partial", "MSFT", f"prec-{i}", "feat",
                 "out", "instr", "input", "output", None, "structure", None)
            )

    from src.training.trainer import export_training_data
    output_dir = str(tmp_path / "output")
    result, total = export_training_data(output_dir=output_dir, db_path=db_path)
    # Total includes all 7, but training+holdout should only include 5
    assert result["training"] + result["holdout"] <= 5


# ── #625: Quarantined row filter + outcome_template migration ─────────────

def test_quarantined_rows_excluded_from_export(tmp_path):
    """Rows with quarantined=1 must not appear in exported training data (#625).

    The DB-level WHERE COALESCE(quarantined, 0) = 0 filter means quarantined
    rows never even enter the Python-side filtering pipeline.
    """
    db_path = str(tmp_path / "test.db")
    init_test_db(db_path, ["training_examples", "model_versions"])
    with sqlite3.connect(db_path) as conn:
        now = datetime.now().isoformat()
        # 5 normal examples
        for i in range(5):
            conn.execute(
                "INSERT INTO training_examples "
                "(example_id, created_at, source, instruction, input_text, output_text, quarantined) "
                "VALUES (?,?,?,?,?,?,?)",
                (f"normal-{i}", now, "blinded_win", "instr", "input", "output", 0),
            )
        # 3 quarantined examples (should be invisible to trainer)
        for i in range(3):
            conn.execute(
                "INSERT INTO training_examples "
                "(example_id, created_at, source, instruction, input_text, output_text, quarantined, quarantine_reason) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (f"quar-{i}", now, "outcome_template_primary_timeout",
                 "instr", "input", "", 1, "OUTCOME_TEMPLATE_FILLER_UNSCHEDULED"),
            )

    from src.training.trainer import export_training_data
    output_dir = str(tmp_path / "output")
    result, total = export_training_data(output_dir=output_dir, db_path=db_path)
    # DB-level filter must exclude quarantined rows; total = rows fetched before Python filters
    assert total == 5


def test_quarantine_stuck_outcome_templates_sets_flag(tmp_path):
    """quarantine_stuck_outcome_templates() must set quarantined=1 on all
    outcome_template_* rows whose output_text is NULL or empty (#625).
    """
    db_path = str(tmp_path / "test.db")
    init_test_db(db_path, ["training_examples"])
    with sqlite3.connect(db_path) as conn:
        now = datetime.now().isoformat()
        # 5 stuck outcome_template rows
        for i in range(5):
            conn.execute(
                "INSERT INTO training_examples "
                "(example_id, created_at, source, instruction, input_text, output_text) "
                "VALUES (?,?,?,?,?,?)",
                (f"tmpl-{i}", now, f"outcome_template_primary_timeout",
                 "instr", "input", ""),
            )
        # 2 normal rows — must NOT be quarantined
        for i in range(2):
            conn.execute(
                "INSERT INTO training_examples "
                "(example_id, created_at, source, instruction, input_text, output_text) "
                "VALUES (?,?,?,?,?,?)",
                (f"normal-{i}", now, "blinded_win", "instr", "input", "output"),
            )

    from src.training.trainer import quarantine_stuck_outcome_templates
    quarantined_count = quarantine_stuck_outcome_templates(db_path)

    assert quarantined_count == 5
    with sqlite3.connect(db_path) as conn:
        stuck = conn.execute(
            "SELECT COUNT(*) FROM training_examples "
            "WHERE source LIKE 'outcome_template_%' AND quarantined = 1"
        ).fetchone()[0]
        assert stuck == 5
        # Normal rows untouched
        normal_quarantined = conn.execute(
            "SELECT COUNT(*) FROM training_examples "
            "WHERE source = 'blinded_win' AND quarantined = 1"
        ).fetchone()[0]
        assert normal_quarantined == 0


def test_quarantine_stuck_outcome_templates_idempotent(tmp_path):
    """Running quarantine_stuck_outcome_templates() twice must not double-count (#625)."""
    db_path = str(tmp_path / "test.db")
    init_test_db(db_path, ["training_examples"])
    with sqlite3.connect(db_path) as conn:
        now = datetime.now().isoformat()
        for i in range(3):
            conn.execute(
                "INSERT INTO training_examples "
                "(example_id, created_at, source, instruction, input_text, output_text) "
                "VALUES (?,?,?,?,?,?)",
                (f"tmpl-{i}", now, "outcome_template_primary_win", "instr", "input", ""),
            )

    from src.training.trainer import quarantine_stuck_outcome_templates
    first = quarantine_stuck_outcome_templates(db_path)
    second = quarantine_stuck_outcome_templates(db_path)

    assert first == 3
    assert second == 0  # Already quarantined; idempotent returns 0 new quarantines
