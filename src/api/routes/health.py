"""Health and Build Score API routes (local mode).

Called by: api.app
Calls: evaluation.build_score, evaluation.hshs_live
Owns tables: none
Config keys: none
Tests: tests/test_local_routes.py

Endpoints:
    GET /build-score     - Build Score (persisted first, fallback to live compute)
    GET /health/startup  - Latest startup validation result
    GET /health/sync     - Render sync thread liveness check
    GET /health/hshs     - Halcyon System Health Score (live compute)
    GET /health/score    - Detailed health score with model/canary info

Build Score and HSHS are different metrics: Build Score measures project
progress toward production readiness (gates, data asset size, research
velocity); HSHS measures live system health (performance, model quality,
data defensibility). Both are displayed on separate dashboard cards.
"""

import json
import logging
import sqlite3

from fastapi import APIRouter

from src.config import DB_PATH
from src.utils.db import connect_db
from src.shadow_trading.exit_reason import outcome_stats_filter_sql

router = APIRouter(tags=["health"])
logger = logging.getLogger(__name__)

_COMPONENT_KEYS = [
    "gate_velocity", "system_health", "data_asset_value",
    "model_quality", "research_velocity", "reliability",
]


def _read_persisted_score(conn):
    """Read latest build score and 7-day history from DB. Returns None if empty.

    We persist build scores rather than computing on every request because the
    computation is expensive (queries many tables) and the score only changes
    once per day when the overnight pipeline runs.
    """
    latest = conn.execute(
        "SELECT build_score, gate_velocity, system_health, "
        "data_asset_value, model_quality, research_velocity, "
        "reliability, decay_applied, created_at "
        "FROM build_score_history ORDER BY created_at DESC LIMIT 1"
    ).fetchone()
    if not latest:
        return None

    row = dict(latest)
    components = {k: row.get(k, 0) or 0 for k in _COMPONENT_KEYS}

    history_rows = conn.execute(
        "SELECT build_score FROM build_score_history "
        "ORDER BY created_at DESC LIMIT 7"
    ).fetchall()
    history_7d = [r["build_score"] for r in reversed(history_rows)] if history_rows else []

    delta_7d = round(history_7d[-1] - history_7d[0], 1) if len(history_7d) >= 2 else None

    closed_row = conn.execute(
        "SELECT COUNT(*) as c FROM shadow_trades WHERE status = 'closed'"
        f" AND COALESCE(quarantined, 0) = 0 {outcome_stats_filter_sql()}"
    ).fetchone()
    closed_count = closed_row["c"] if closed_row else 0

    return {
        "build_score": row.get("build_score", 0) or 0,
        "delta_7d": delta_7d,
        "components": components,
        "data_asset_detail": {},
        "phase_progress": {
            "current_phase": 1,
            "trades_required": 50,
            "trades_closed": closed_count,
            "pct_complete": round(min(100, (closed_count / 50) * 100), 1),
        },
        "decay_today": bool(row.get("decay_applied")),
        "history_7d": history_7d,
        "computed_at": row.get("created_at", ""),
    }


@router.get("/build-score")
def build_score():
    """Return Build Score matching cloud response shape."""
    try:
        conn = connect_db(DB_PATH)
        conn.row_factory = sqlite3.Row
        try:
            result = _read_persisted_score(conn)
            if result:
                return result
            from src.evaluation.build_score import compute_build_score
            return compute_build_score(DB_PATH)
        finally:
            conn.close()
    except Exception as exc:
        logger.error("[API] build-score failed: %s", exc, exc_info=True)
        return {"build_score": 0, "components": {}, "error": str(exc)}


@router.get("/health/startup")
def health_startup():
    """Return the latest startup validation result for dashboard display."""
    import json as _json
    try:
        conn = connect_db(DB_PATH)
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute(
                "SELECT results_json, overall_status, created_at "
                "FROM validation_results "
                "WHERE results_json LIKE '%\"trigger\": \"startup\"%' "
                "ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
            if not row:
                return {"overall_status": None, "message": "No startup validation recorded"}

            result = _json.loads(row["results_json"])

            # Get previous status for transition display
            prev = conn.execute(
                "SELECT overall_status FROM validation_results "
                "WHERE results_json LIKE '%\"trigger\": \"startup\"%' "
                "ORDER BY created_at DESC LIMIT 1 OFFSET 1"
            ).fetchone()
            result["previous_status"] = prev["overall_status"] if prev else None
            return result
        finally:
            conn.close()
    except Exception as exc:
        logger.error("[API] health/startup failed: %s", exc)
        return {"overall_status": None, "error": str(exc)}


@router.get("/health/sync")
def health_sync():
    """Return sync thread health status — disabled post one-DB cutover.

    Post SP5 §J5/§J6 Phase 3-revised: render_sync.py was deleted (one-DB
    cutover makes PG the production database; no sync thread needed).
    Static "disabled" payload preserves the dashboard's expected response
    shape so the health card renders without errors.
    """
    return {"alive": False, "last_success_seconds_ago": None,
            "consecutive_errors": 0, "stale": False,
            "note": "render sync removed in one-DB cutover (SP5 Phase 3-revised)"}


@router.get("/health/hshs")
def health_hshs():
    """Compute live HSHS from local SQLite."""
    try:
        from src.evaluation.hshs_live import compute_hshs
        return compute_hshs(DB_PATH)
    except Exception as exc:
        logger.error("[API] HSHS computation failed: %s", exc)
        return {"hshs": 0, "dimensions": {}, "error": str(exc)}


@router.get("/health/score")
def health_score():
    """Compute detailed health score from local SQLite.

    Response shape matches cloud /api/health/score.
    """
    try:
        from src.evaluation.hshs_live import compute_hshs
        hshs_result = compute_hshs(DB_PATH)

        conn = connect_db(DB_PATH)
        conn.row_factory = sqlite3.Row
        try:
            closed_row = conn.execute(
                "SELECT COUNT(*) as c FROM shadow_trades WHERE status = 'closed'"
                f" AND COALESCE(quarantined, 0) = 0 {outcome_stats_filter_sql()}"
            ).fetchone()
            example_row = conn.execute(
                "SELECT COUNT(*) as c FROM training_examples"
            ).fetchone()
            model = conn.execute(
                "SELECT version_name, status FROM model_versions "
                "ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
            canary = conn.execute(
                "SELECT degradation_detected, avg_score, distinct_2 FROM canary_evaluations "
                "ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
        finally:
            conn.close()

        return {
            "score": {
                "overall": hshs_result.get("hshs", 0),
                "dimensions": hshs_result.get("dimensions", {}),
                "dimension_metrics": {},
                "weights": hshs_result.get("weights", {}),
                "phase": hshs_result.get("phase", "early"),
            },
            "closed_trades": closed_row["c"] if closed_row else 0,
            "training_examples": example_row["c"] if example_row else 0,
            "model": dict(model) if model else None,
            "canary": dict(canary) if canary else None,
            "history": [],
        }
    except Exception as exc:
        logger.error("[API] health_score failed: %s", exc, exc_info=True)
        return {
            "score": {"overall": 0, "dimensions": {}, "weights": {}, "phase": "early"},
            "history": [],
            "error": str(exc),
        }
