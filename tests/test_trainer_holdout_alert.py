"""#617 — trainer must WARN when holdout=0 due to corpus stall.

Pre-#617, export_training_data wrote an empty holdout.jsonl and returned
{"training": N, "holdout": 0} silently when the most recent example was
older than the 5-day temporal-gap window. Across 4/21, 4/22, 4/23 the
nightly trainer reported "Exported 1393 training + 0 holdout" with zero
visible signal that model evaluation was blocked.

Post-fix, that condition emits:
  - logger.error with corpus-stall details
  - Telegram alert (if enabled) so operators can react before the next train cycle
"""
import logging
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest


def _make_corpus(tmp_path, dates):
    """Seed training_examples with rows on the given dates (YYYY-MM-DD strings)."""
    import sqlite3
    db_path = tmp_path / "training.sqlite3"
    from tests.conftest import init_test_db
    init_test_db(str(db_path), ["training_examples"])
    with sqlite3.connect(db_path) as conn:
        for i, d in enumerate(dates):
            conn.execute(
                "INSERT INTO training_examples "
                "(example_id, source, instruction, input_text, output_text, "
                "created_at) VALUES (?, 'blinded_win', 'i', 'in', 'out', ?)",
                (f"ex-{i}", f"{d}T10:00:00"),
            )
        conn.commit()
    return str(db_path)


def test_holdout_empty_emits_error_when_train_nonempty(tmp_path, caplog):
    """All examples are from a single old date — split window pushes holdout past end."""
    from src.training.trainer import export_training_data

    # 30 examples all from 4/12 — stale corpus
    db_path = _make_corpus(tmp_path, ["2026-04-12"] * 30)
    output_dir = tmp_path / "out"
    output_dir.mkdir()

    with caplog.at_level(logging.ERROR):
        result, total = export_training_data(
            output_dir=str(output_dir), db_path=db_path,
        )

    assert result["holdout"] == 0
    assert result["training"] > 0
    err_lines = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert any("HOLDOUT EMPTY" in r.getMessage() for r in err_lines), (
        f"Expected HOLDOUT EMPTY error log; got:\n"
        + "\n".join(r.getMessage() for r in caplog.records)
    )


def test_holdout_empty_sends_telegram_alert(tmp_path):
    """When holdout=0 + train>0 + telegram enabled, alert is sent."""
    from src.training.trainer import export_training_data

    db_path = _make_corpus(tmp_path, ["2026-04-12"] * 30)
    output_dir = tmp_path / "out"
    output_dir.mkdir()

    with patch("src.notifications.telegram.is_telegram_enabled", return_value=True), \
         patch("src.notifications.telegram.notify_trainer_holdout_empty") as mock_notify:
        export_training_data(output_dir=str(output_dir), db_path=db_path)

    mock_notify.assert_called_once()
    # Should pass at least the most-recent-date and train-count
    kwargs = mock_notify.call_args.kwargs
    assert "most_recent_date" in kwargs or len(mock_notify.call_args.args) >= 1


def test_holdout_populated_does_not_alert(tmp_path):
    """Healthy corpus (recent examples) — no alert fires."""
    from src.training.trainer import export_training_data

    today = datetime.now().date()
    dates = [str(today - timedelta(days=i)) for i in range(30)]
    db_path = _make_corpus(tmp_path, dates)
    output_dir = tmp_path / "out"
    output_dir.mkdir()

    with patch("src.notifications.telegram.is_telegram_enabled", return_value=True), \
         patch("src.notifications.telegram.notify_trainer_holdout_empty") as mock_notify:
        result, total = export_training_data(output_dir=str(output_dir), db_path=db_path)

    # Healthy corpus should not alert; holdout may or may not be non-empty
    # depending on the temporal-gap window. The alert specifically fires
    # only when holdout=0 + train>0. Check accordingly.
    if result["training"] > 0 and result["holdout"] == 0:
        # Edge case: even today's corpus could result in empty holdout.
        # If so the alert SHOULD fire.
        mock_notify.assert_called_once()
    else:
        mock_notify.assert_not_called()


def test_run_fine_tune_skips_before_subprocess_when_holdout_empty():
    """Training handoff must not launch GPU work without a holdout set."""
    from src.training import trainer

    with patch.object(
        trainer,
        "export_training_data",
        return_value=({"training": 42, "holdout": 0}, 42),
    ), patch.object(trainer.subprocess, "run") as mock_run:
        result = trainer.run_fine_tune(db_path=":memory:")

    assert result is None
    mock_run.assert_not_called()


def test_training_subprocess_env_forces_utf8():
    """Windows subprocesses must emit/capture UTF-8 so logs cannot crash decode."""
    from src.training.trainer import _training_subprocess_env

    env = _training_subprocess_env()
    assert env["PYTHONUTF8"] == "1"
    assert env["PYTHONIOENCODING"] == "utf-8"


def test_should_train_blocks_gpu_handoff_when_split_not_viable():
    """The scheduler gate should skip before run_fine_tune when holdout is empty."""
    from src.training import trainer

    with patch.object(trainer, "load_config", return_value={
        "training": {
            "enabled": True,
            "auto_train_threshold": 50,
            "auto_train_time_days": 7,
            "auto_train_min_examples": 20,
        }
    }), patch.object(trainer, "init_training_tables"), \
         patch.object(trainer, "get_active_model_version", return_value=None), \
         patch.object(trainer, "get_training_example_counts", return_value={"total": 60}), \
         patch.object(
             trainer,
             "get_training_split_viability",
             return_value=(False, "HOLDOUT EMPTY: 60 training / 0 holdout", {"training": 60, "holdout": 0}),
         ):
        should, reason = trainer.should_train(db_path=":memory:")

    assert should is False
    assert "HOLDOUT EMPTY" in reason


def test_run_fine_tune_activation_requires_all_gates_in_source():
    """Model activation must stay after holdout, canary, and promotion gate checks."""
    source = Path("src/training/trainer.py").read_text(encoding="utf-8")
    assert 'status="evaluation"' in source
    assert 'gate_result.get("decision") != "promote"' in source
    assert "_activate_model_version(version_id, db_path)" in source
    assert source.index('gate_result.get("decision") != "promote"') < source.index(
        "_activate_model_version(version_id, db_path)"
    )
    assert source.index("_activate_model_version(version_id, db_path)") < source.index(
        "update_config_model(version_name)"
    )
