"""Model versioning and performance tracking for the training pipeline.

Called by: api.routes.system, cli.commands, evaluation.auditor, evaluation.cto_report, llm.client, llm.grammar_client, notifications.telegram, scheduler.premarket, scheduler.scorer, scheduler.vram_manager, scheduler.watch, services.scan_service, services.system_service, services.training_service, training.ab_evaluation, training.backfill, training.bootstrap, training.claude_client, training.curriculum, training.data_collector, training.dpo_pipeline, training.quality_filter, training.report, training.trainer, training.validation
Calls: journal.store
Owns tables: api_costs, audit_reports, metric_snapshots, model_evaluations, model_versions, training_examples
Config keys: none
Tests: tests/test_ab_evaluation.py, tests/test_auditor.py, tests/test_dpo_pipeline.py, tests/test_holdout.py, tests/test_leakage_detector.py, tests/test_premarket.py, tests/test_scorer.py, tests/test_trainer.py, tests/test_training_data.py, tests/test_validation.py, tests/test_versioning.py
"""

import logging
import sqlite3
import uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")

TRAINING_SCHEMA = """
CREATE TABLE IF NOT EXISTS model_versions (
    version_id TEXT PRIMARY KEY,
    version_name TEXT NOT NULL,
    created_at TEXT NOT NULL,
    training_examples_count INTEGER,
    synthetic_examples_count INTEGER,
    outcome_examples_count INTEGER,
    model_file_path TEXT,
    status TEXT NOT NULL DEFAULT 'active',
    notes TEXT
);

CREATE TABLE IF NOT EXISTS training_examples (
    example_id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    source TEXT NOT NULL,
    ticker TEXT,
    recommendation_id TEXT,
    feature_snapshot TEXT,
    trade_outcome TEXT,
    instruction TEXT NOT NULL,
    input_text TEXT NOT NULL,
    output_text TEXT NOT NULL,
    quality_score REAL
);

-- Training table indexes
CREATE INDEX IF NOT EXISTS idx_training_examples_source ON training_examples(source);
CREATE INDEX IF NOT EXISTS idx_training_examples_ticker ON training_examples(ticker);
CREATE INDEX IF NOT EXISTS idx_training_examples_created_at ON training_examples(created_at);
CREATE INDEX IF NOT EXISTS idx_training_examples_recommendation_id ON training_examples(recommendation_id);
CREATE INDEX IF NOT EXISTS idx_model_versions_status ON model_versions(status);
"""


def init_training_tables(db_path: str = "ai_research_desk.sqlite3") -> None:
    """Create training tables if they don't exist."""
    with sqlite3.connect(db_path) as conn:
        conn.executescript(TRAINING_SCHEMA)
        conn.commit()

        # Migration: add holdout_score to model_versions
        try:
            conn.execute("ALTER TABLE model_versions ADD COLUMN holdout_score REAL")
            conn.commit()
        except sqlite3.OperationalError:
            pass

        # Migration: add holdout_details (JSON blob) to model_versions
        try:
            conn.execute("ALTER TABLE model_versions ADD COLUMN holdout_details TEXT")
            conn.commit()
        except sqlite3.OperationalError:
            pass

        # Migration: add curriculum columns to training_examples
        for col, col_type in [("difficulty", "TEXT"), ("curriculum_stage", "TEXT"),
                               ("quality_score_auto", "REAL")]:
            try:
                conn.execute(f"ALTER TABLE training_examples ADD COLUMN {col} {col_type}")
                conn.commit()
            except sqlite3.OperationalError:
                pass

        # Model evaluations table for A/B testing
        conn.execute("""
            CREATE TABLE IF NOT EXISTS model_evaluations (
                evaluation_id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                recommendation_id TEXT,
                ticker TEXT,
                input_text TEXT NOT NULL,
                current_model TEXT NOT NULL,
                current_output TEXT,
                current_score REAL,
                new_model TEXT NOT NULL,
                new_output TEXT,
                new_score REAL,
                winner TEXT,
                score_delta REAL
            )
        """)
        conn.commit()

        # Audit reports table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS audit_reports (
                audit_id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                audit_date TEXT NOT NULL,
                overall_assessment TEXT NOT NULL,
                summary TEXT,
                flags TEXT,
                metrics_to_watch TEXT,
                model_health TEXT,
                full_report TEXT
            )
        """)
        conn.commit()

        # Metric snapshots for historical trending
        conn.execute("""
            CREATE TABLE IF NOT EXISTS metric_snapshots (
                snapshot_id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                snapshot_date TEXT NOT NULL,
                metrics_json TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_metric_snapshots_date
            ON metric_snapshots(snapshot_date)
        """)
        conn.commit()

        # API cost tracking table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS api_costs (
                cost_id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                model TEXT NOT NULL,
                purpose TEXT NOT NULL,
                input_tokens INTEGER NOT NULL,
                output_tokens INTEGER NOT NULL,
                cost_dollars REAL NOT NULL
            )
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_api_costs_created_at ON api_costs(created_at)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_api_costs_purpose ON api_costs(purpose)"
        )
        conn.commit()


def save_metric_snapshot(metrics: dict, db_path: str = "ai_research_desk.sqlite3") -> None:
    """Save a metric snapshot for historical trending.

    Called automatically by the CTO report generator. Stores one snapshot
    per day (skips if today's snapshot already exists).
    """
    import json
    from datetime import datetime
    init_training_tables(db_path)
    today = datetime.now(ET).strftime("%Y-%m-%d")

    with sqlite3.connect(db_path) as conn:
        existing = conn.execute(
            "SELECT 1 FROM metric_snapshots WHERE snapshot_date = ?", (today,)
        ).fetchone()
        if existing:
            return  # Already have today's snapshot

        snapshot_id = str(uuid.uuid4())
        conn.execute(
            "INSERT INTO metric_snapshots (snapshot_id, created_at, snapshot_date, metrics_json) "
            "VALUES (?, ?, ?, ?)",
            (snapshot_id, datetime.now(ET).isoformat(), today, json.dumps(metrics)),
        )
        conn.commit()


def get_metric_history(days: int = 90, db_path: str = "ai_research_desk.sqlite3") -> list[dict]:
    """Retrieve historical metric snapshots for trending.

    Returns a list of {date, metrics} dicts, sorted chronologically.
    """
    import json
    init_training_tables(db_path)
    cutoff = (datetime.now(ZoneInfo("America/New_York")) - timedelta(days=days)).strftime("%Y-%m-%d")
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT snapshot_date, metrics_json FROM metric_snapshots "
            "WHERE snapshot_date >= ? "
            "ORDER BY snapshot_date ASC",
            (cutoff,),
        ).fetchall()

    result = []
    for row in rows:
        try:
            metrics = json.loads(row["metrics_json"])
            result.append({"date": row["snapshot_date"], **metrics})
        except (json.JSONDecodeError, TypeError):
            continue
    return result

def get_active_model_version(db_path: str = "ai_research_desk.sqlite3") -> dict | None:
    """Return the currently active model version, or None if using base."""
    init_training_tables(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM model_versions WHERE status = 'active' ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
    return dict(row) if row else None


def register_model_version(
    version_name: str,
    examples_count: int,
    synthetic_count: int,
    outcome_count: int,
    model_file_path: str,
    db_path: str = "ai_research_desk.sqlite3",
    holdout_score: float | None = None,
    holdout_details: str | None = None,
    status: str = "active",
) -> str:
    """Retire current active version and register new one. Returns version_id."""
    init_training_tables(db_path)
    version_id = str(uuid.uuid4())
    created_at = datetime.now(ET).isoformat()

    with sqlite3.connect(db_path) as conn:
        if status == "active":
            # Retire current active version
            conn.execute(
                "UPDATE model_versions SET status = 'retired' WHERE status = 'active'"
            )
        # Insert new version
        conn.execute(
            """INSERT INTO model_versions
               (version_id, version_name, created_at, training_examples_count,
                synthetic_examples_count, outcome_examples_count,
                model_file_path, status, holdout_score, holdout_details)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (version_id, version_name, created_at, examples_count,
             synthetic_count, outcome_count, model_file_path, status,
             holdout_score, holdout_details),
        )
        conn.commit()
    return version_id


def get_evaluation_model(db_path: str = "ai_research_desk.sqlite3") -> dict | None:
    """Return a model in 'evaluation' status, or None."""
    init_training_tables(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM model_versions WHERE status = 'evaluation' ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
    return dict(row) if row else None


def promote_evaluation_model(db_path: str = "ai_research_desk.sqlite3") -> dict | None:
    """Promote the evaluation model to active status."""
    init_training_tables(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        eval_model = conn.execute(
            "SELECT * FROM model_versions WHERE status = 'evaluation' ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
        if not eval_model:
            return None
        conn.execute("UPDATE model_versions SET status = 'retired' WHERE status = 'active'")
        conn.execute("UPDATE model_versions SET status = 'active' WHERE version_id = ?",
                     (eval_model["version_id"],))
        conn.commit()
    return dict(eval_model)


def reject_evaluation_model(db_path: str = "ai_research_desk.sqlite3") -> dict | None:
    """Reject the evaluation model (set to rejected status)."""
    init_training_tables(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        eval_model = conn.execute(
            "SELECT * FROM model_versions WHERE status = 'evaluation' ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
        if not eval_model:
            return None
        conn.execute("UPDATE model_versions SET status = 'rejected' WHERE version_id = ?",
                     (eval_model["version_id"],))
        conn.commit()
    return dict(eval_model)


def rollback_model(db_path: str = "ai_research_desk.sqlite3") -> dict | None:
    """Roll back active model to previous retired version. Returns restored version or None."""
    init_training_tables(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row

        # Set active to rolled_back
        conn.execute(
            "UPDATE model_versions SET status = 'rolled_back' WHERE status = 'active'"
        )

        # Find most recent retired version
        row = conn.execute(
            "SELECT * FROM model_versions WHERE status = 'retired' ORDER BY created_at DESC LIMIT 1"
        ).fetchone()

        if row:
            conn.execute(
                "UPDATE model_versions SET status = 'active' WHERE version_id = ?",
                (row["version_id"],),
            )
            conn.commit()
            return dict(row)

        conn.commit()
    return None


def get_model_history(db_path: str = "ai_research_desk.sqlite3") -> list[dict]:
    """Return all model versions ordered by created_at descending."""
    init_training_tables(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM model_versions ORDER BY created_at DESC"
        ).fetchall()
    return [dict(row) for row in rows]


def get_next_semver(db_path: str = "ai_research_desk.sqlite3") -> str:
    """Compute the next semver version name from model history.

    Convention: halcyon-v{major}.{minor}.{patch}
      major: new base model or new strategy LoRA
      minor: retrain cycle with new data (auto-incremented)
      patch: hyperparameter tweak, same data

    Returns e.g. 'halcyon-v1.1.0' if current active is 'halcyon-v1.0.0'.
    Returns 'halcyon-v1.0.0' if no versions exist.
    """
    import re
    active = get_active_model_version(db_path)
    if not active:
        return "halcyon-v1.0.0"
    name = active.get("version_name", "")
    match = re.match(r"halcyon-v(\d+)\.(\d+)\.(\d+)", name)
    if match:
        major, minor, patch = int(match.group(1)), int(match.group(2)), int(match.group(3))
        return f"halcyon-v{major}.{minor + 1}.0"
    # Fallback: old-style halcyon-v{N}
    match = re.match(r"halcyon-v(\d+)$", name)
    if match:
        return f"halcyon-v1.{int(match.group(1))}.0"
    return "halcyon-v1.0.0"


def update_config_model(version_name: str, config_path: str = "config/settings.local.yaml") -> bool:
    """Update the llm.model field in settings.local.yaml to the new version.

    Also keeps 'halcyonlatest' as a fallback by ensuring Ollama has both tags.
    """
    from pathlib import Path
    import re

    path = Path(config_path)
    if not path.exists():
        logger.warning("[VERSION] Config file not found: %s", config_path)
        return False

    content = path.read_text()
    # Match:  model: halcyon-v1.0.0  or  model: halcyonlatest  or  model: "halcyon-v1.0.0"
    updated = re.sub(
        r'(model:\s*)["\']?halcyon[^"\'\s]*["\']?',
        rf'\g<1>{version_name}',
        content,
    )
    if updated == content:
        # No match found — append to llm section
        logger.info("[VERSION] No model field found in config, skipping update")
        return False

    path.write_text(updated)
    logger.info("[VERSION] Updated config %s → model: %s", config_path, version_name)
    return True


def get_active_model_name(db_path: str = "ai_research_desk.sqlite3") -> str:
    """Return active model version name, or 'base' if none exists."""
    version = get_active_model_version(db_path)
    return version["version_name"] if version else "base"


def get_performance_by_version(db_path: str = "ai_research_desk.sqlite3") -> list[dict]:
    """Query closed shadow trades grouped by model_version on their recommendation."""
    from src.journal.store import initialize_database
    initialize_database(db_path)
    init_training_tables(db_path)

    # Ensure model_version column exists
    _migrate_model_version_column(db_path)

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("""
            SELECT
                COALESCE(r.model_version, 'base') as version_name,
                COUNT(*) as trade_count,
                SUM(CASE WHEN st.pnl_dollars > 0 THEN 1 ELSE 0 END) as wins,
                SUM(CASE WHEN st.pnl_dollars <= 0 THEN 1 ELSE 0 END) as losses,
                AVG(CASE WHEN st.pnl_dollars > 0 THEN st.pnl_dollars END) as avg_gain,
                AVG(CASE WHEN st.pnl_dollars <= 0 THEN st.pnl_dollars END) as avg_loss,
                AVG(st.pnl_dollars) as expectancy,
                SUM(st.pnl_dollars) as total_pnl
            FROM shadow_trades st
            JOIN recommendations r ON st.recommendation_id = r.recommendation_id
            WHERE st.status = 'closed'
            GROUP BY COALESCE(r.model_version, 'base')
            ORDER BY MIN(r.created_at) DESC
        """).fetchall()

    results = []
    for row in rows:
        d = dict(row)
        d["win_rate"] = (d["wins"] / d["trade_count"] * 100) if d["trade_count"] > 0 else 0
        results.append(d)
    return results


def get_training_example_counts(db_path: str = "ai_research_desk.sqlite3") -> dict:
    """Return counts of training examples by source."""
    init_training_tables(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT source, COUNT(*) as count FROM training_examples GROUP BY source"
        ).fetchall()

    counts = {"total": 0, "historical_backfill": 0, "synthetic_claude": 0, "outcome_win": 0, "outcome_loss": 0}
    for row in rows:
        counts[row["source"]] = row["count"]
        counts["total"] += row["count"]
    return counts


def get_new_examples_since(since_date: str, db_path: str = "ai_research_desk.sqlite3") -> int:
    """Count training examples created after the given date."""
    init_training_tables(db_path)
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT COUNT(*) FROM training_examples WHERE created_at > ?",
            (since_date,),
        ).fetchone()
    return row[0] if row else 0


def _migrate_model_version_column(db_path: str = "ai_research_desk.sqlite3") -> None:
    """Add model_version column to recommendations table if it doesn't exist."""
    try:
        with sqlite3.connect(db_path) as conn:
            conn.execute("ALTER TABLE recommendations ADD COLUMN model_version TEXT")
            conn.commit()
    except sqlite3.OperationalError:
        pass  # Column already exists


# ---------------------------------------------------------------------------
# API cost tracking
# ---------------------------------------------------------------------------

# Pricing per million tokens
API_PRICING = {
    "claude-haiku-4-5-20251001": {"input": 1.0, "output": 5.0},
    "claude-haiku-4-5-20251022": {"input": 1.0, "output": 5.0},
}
_DEFAULT_PRICING = {"input": 1.0, "output": 5.0}


def log_api_cost(
    model: str,
    purpose: str,
    input_tokens: int,
    output_tokens: int,
    db_path: str = "ai_research_desk.sqlite3",
) -> None:
    """Log an API call's token usage and cost. Never raises."""
    try:
        init_training_tables(db_path)
        rates = API_PRICING.get(model, _DEFAULT_PRICING)
        cost = (input_tokens * rates["input"] + output_tokens * rates["output"]) / 1_000_000

        cost_id = str(uuid.uuid4())
        created_at = datetime.now(ET).isoformat()

        with sqlite3.connect(db_path) as conn:
            conn.execute(
                """INSERT INTO api_costs
                   (cost_id, created_at, model, purpose, input_tokens, output_tokens, cost_dollars)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (cost_id, created_at, model, purpose, input_tokens, output_tokens, cost),
            )
            conn.commit()
    except Exception as e:
        logger.debug("Failed to log API cost: %s", e)


def get_cost_summary(days: int = 30, db_path: str = "ai_research_desk.sqlite3") -> dict:
    """Return cost summary: total, by purpose, by day."""
    init_training_tables(db_path)
    now = datetime.now(ET)
    cutoff = (now - timedelta(days=days)).isoformat()
    today_str = now.strftime("%Y-%m-%d")
    week_ago = (now - timedelta(days=7)).isoformat()

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row

        # Total (all time)
        row = conn.execute("SELECT COALESCE(SUM(cost_dollars), 0) as total FROM api_costs").fetchone()
        total_all_time = row["total"]

        # Total in window
        row = conn.execute(
            "SELECT COALESCE(SUM(cost_dollars), 0) as total, "
            "COALESCE(SUM(input_tokens), 0) as inp, "
            "COALESCE(SUM(output_tokens), 0) as outp, "
            "COUNT(*) as calls "
            "FROM api_costs WHERE created_at >= ?",
            (cutoff,),
        ).fetchone()
        total_period = row["total"]
        total_input_tokens = row["inp"]
        total_output_tokens = row["outp"]
        total_calls = row["calls"]

        # Today
        row = conn.execute(
            "SELECT COALESCE(SUM(cost_dollars), 0) as total FROM api_costs WHERE created_at >= ?",
            (today_str,),
        ).fetchone()
        total_today = row["total"]

        # This week
        row = conn.execute(
            "SELECT COALESCE(SUM(cost_dollars), 0) as total FROM api_costs WHERE created_at >= ?",
            (week_ago,),
        ).fetchone()
        total_week = row["total"]

        # By purpose
        rows = conn.execute(
            "SELECT purpose, SUM(cost_dollars) as cost, SUM(input_tokens) as inp, "
            "SUM(output_tokens) as outp, COUNT(*) as calls "
            "FROM api_costs WHERE created_at >= ? GROUP BY purpose ORDER BY cost DESC",
            (cutoff,),
        ).fetchall()
        by_purpose = {
            r["purpose"]: {
                "cost": round(r["cost"], 4),
                "input_tokens": r["inp"],
                "output_tokens": r["outp"],
                "calls": r["calls"],
            }
            for r in rows
        }

        # Daily totals
        daily_rows = conn.execute(
            "SELECT DATE(created_at) as day, SUM(cost_dollars) as cost, COUNT(*) as calls "
            "FROM api_costs WHERE created_at >= ? GROUP BY DATE(created_at) ORDER BY day",
            (cutoff,),
        ).fetchall()
        daily = [{"date": r["day"], "cost": round(r["cost"], 4), "calls": r["calls"]} for r in daily_rows]

    return {
        "total_all_time": round(total_all_time, 4),
        "total_period": round(total_period, 4),
        "total_today": round(total_today, 4),
        "total_week": round(total_week, 4),
        "total_input_tokens": total_input_tokens,
        "total_output_tokens": total_output_tokens,
        "total_calls": total_calls,
        "days": days,
        "by_purpose": by_purpose,
        "daily": daily,
    }
