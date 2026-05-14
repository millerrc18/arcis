"""Training pipeline service.

Called by: api.routes.training, cli.commands
Calls: training.bootstrap, training.report, training.trainer, training.versioning
Owns tables: none
Config keys: none
Tests: tests/test_services.py

Capability registration (Sprint 1B):
- training_corpus (State) — example counts by outcome_type and by source
"""
import logging
from datetime import date

from src.platform.capability_registry import register_state
from src.utils.db import connect_db

logger = logging.getLogger(__name__)


def _training_corpus_counts() -> dict:
    """Return counts of training_examples grouped by outcome_type and source."""
    import sqlite3

    from src.config import DB_PATH

    conn = connect_db(DB_PATH)
    try:
        outcome_rows = conn.execute(
            "SELECT UPPER(COALESCE(outcome_type, 'UNKNOWN')) AS outcome, COUNT(*) AS n "
            "FROM training_examples GROUP BY UPPER(COALESCE(outcome_type, 'UNKNOWN'))",
        ).fetchall()
        source_rows = conn.execute(
            "SELECT COALESCE(source, 'unknown') AS source, COUNT(*) AS n "
            "FROM training_examples GROUP BY COALESCE(source, 'unknown')",
        ).fetchall()
        total_row = conn.execute(
            "SELECT COUNT(*) FROM training_examples",
        ).fetchone()
    except sqlite3.OperationalError as exc:
        return {"error": f"training_examples unavailable: {exc}"}
    finally:
        conn.close()
    return {
        "value": {
            "total": int((total_row or (0,))[0]),
            "by_outcome": {row[0]: int(row[1]) for row in outcome_rows},
            "by_source": {row[0]: int(row[1]) for row in source_rows},
        },
    }


@register_state(
    name="training_corpus",
    description=(
        "Total training examples by outcome (WIN/LOSS/UNKNOWN) and by "
        "source (shadow, backfill, synthetic). Drives when to retrain."
    ),
    category="training",
    version="1.0",
    maintainer="ai_session",
    introduced_in="v0.18.0",
    last_reviewed_date=date(2026, 4, 18),
    refresh_hint="real-time",
)
def training_corpus() -> dict:
    return _training_corpus_counts()


def get_training_status() -> dict:
    """Get current training pipeline status."""
    import sqlite3

    from src.config import DB_PATH
    from src.training.versioning import (
        get_active_model_version, get_training_example_counts,
        get_new_examples_since, get_active_model_name,
    )
    from src.training.trainer import should_train, check_model_performance

    active = get_active_model_version()
    counts = get_training_example_counts()
    trigger, trigger_reason = should_train()
    perf_check = check_model_performance()

    new_since = 0
    if active:
        new_since = get_new_examples_since(active["created_at"])
    else:
        new_since = counts["total"]

    if perf_check["action"] == "waiting":
        rollback_status = f"Watching (need {perf_check.get('trades_needed', '?')} more trades)"
    elif perf_check["action"] == "none":
        rollback_status = f"Passing -- {perf_check.get('status', 'ok')}"
    elif perf_check["action"] == "rolled_back":
        rollback_status = f"Triggered -- {perf_check.get('reason', '')}"
    else:
        rollback_status = "Unknown"

    # DB-2 Task 16: outcome + source distributions. The Training page
    # previously rendered "Outcome data pending migration" because these
    # fields weren't in the response. Compute from training_examples so
    # the dashboard has real counts.
    outcome_counts: dict[str, int] = {}
    source_counts: dict[str, int] = {}
    try:
        with connect_db(DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            for row in conn.execute(
                "SELECT UPPER(COALESCE(outcome_type, 'UNKNOWN')) AS o, COUNT(*) AS n "
                "FROM training_examples GROUP BY UPPER(COALESCE(outcome_type, 'UNKNOWN'))"
            ).fetchall():
                outcome_counts[row["o"]] = row["n"]
            for row in conn.execute(
                "SELECT COALESCE(source, 'unknown') AS s, COUNT(*) AS n "
                "FROM training_examples GROUP BY COALESCE(source, 'unknown')"
            ).fetchall():
                source_counts[row["s"]] = row["n"]
    except Exception as exc:
        logger.debug("outcome/source distribution query failed: %s", exc)

    return {
        "active_version": dict(active) if active else None,
        "model_name": get_active_model_name(),
        "dataset_total": counts["total"],
        "dataset_synthetic": counts.get("synthetic_claude", 0),
        "dataset_wins": counts.get("outcome_win", 0),
        "dataset_losses": counts.get("outcome_loss", 0),
        "outcome_counts": outcome_counts,
        "source_counts": source_counts,
        "new_since_last_train": new_since,
        "train_queued": trigger,
        "train_reason": trigger_reason,
        "rollback_status": rollback_status,
    }


def get_training_history() -> dict:
    """Get all model versions with performance data."""
    from src.training.versioning import get_model_history, get_performance_by_version

    history = get_model_history()
    perf_data = get_performance_by_version()
    perf_map = {p["version_name"]: p for p in perf_data}

    versions = []
    for v in history:
        name = v["version_name"]
        p = perf_map.get(name, {})
        versions.append({
            "version_id": v["version_id"],
            "version_name": name,
            "created_at": v["created_at"],
            "training_examples_count": v.get("training_examples_count"),
            "synthetic_examples_count": v.get("synthetic_examples_count"),
            "outcome_examples_count": v.get("outcome_examples_count"),
            "status": v["status"],
            "trade_count": p.get("trade_count", 0),
            "win_rate": p.get("win_rate"),
            "expectancy": p.get("expectancy"),
        })

    # Add base model row
    base_perf = perf_map.get("base", {})
    versions.append({
        "version_id": "base",
        "version_name": "base",
        "created_at": "",
        "training_examples_count": None,
        "synthetic_examples_count": None,
        "outcome_examples_count": None,
        "status": "--",
        "trade_count": base_perf.get("trade_count", 0),
        "win_rate": base_perf.get("win_rate"),
        "expectancy": base_perf.get("expectancy"),
    })

    return {"versions": versions}


def get_training_report() -> str:
    """Generate the full training progress report."""
    from src.training.report import generate_training_report
    return generate_training_report()


def run_bootstrap(count: int = 500) -> dict:
    """Generate synthetic training data."""
    from src.training.bootstrap import estimate_bootstrap_cost, generate_synthetic_training_data
    created = generate_synthetic_training_data(count)
    cost = estimate_bootstrap_cost(created)
    return {"count_created": created, "estimated_cost": cost}


def run_fine_tune_service() -> dict | None:
    """Trigger fine-tuning."""
    from src.training.trainer import run_fine_tune
    return run_fine_tune()


def rollback_model_service() -> dict | None:
    """Rollback to previous model version."""
    from src.training.versioning import rollback_model
    return rollback_model()
