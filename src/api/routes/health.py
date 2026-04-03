"""Health and Build Score API routes (local mode).

Called by: api.app
Calls: evaluation.build_score, evaluation.hshs_live
Owns tables: none
Config keys: none
Tests: tests/test_local_routes.py
"""

import json
import logging
import sqlite3

from fastapi import APIRouter

from src.config import DB_PATH

router = APIRouter(tags=["health"])
logger = logging.getLogger(__name__)


@router.get("/build-score")
def build_score():
    """Return Build Score matching cloud response shape.

    Reads from build_score_history if available, otherwise computes live.
    """
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        try:
            latest = conn.execute(
                "SELECT build_score, gate_velocity, system_health, "
                "data_asset_value, model_quality, research_velocity, "
                "reliability, decay_applied, created_at "
                "FROM build_score_history ORDER BY created_at DESC LIMIT 1"
            ).fetchone()

            if not latest:
                # No persisted scores -- compute live
                from src.evaluation.build_score import compute_build_score
                return compute_build_score(DB_PATH)

            row = dict(latest)
            components = {
                "gate_velocity": row.get("gate_velocity", 0) or 0,
                "system_health": row.get("system_health", 0) or 0,
                "data_asset_value": row.get("data_asset_value", 0) or 0,
                "model_quality": row.get("model_quality", 0) or 0,
                "research_velocity": row.get("research_velocity", 0) or 0,
                "reliability": row.get("reliability", 0) or 0,
            }

            history_rows = conn.execute(
                "SELECT build_score FROM build_score_history "
                "ORDER BY created_at DESC LIMIT 7"
            ).fetchall()
            history_7d = [r["build_score"] for r in reversed(history_rows)] if history_rows else []

            delta_7d = None
            if len(history_7d) >= 2:
                delta_7d = round(history_7d[-1] - history_7d[0], 1)

            closed_row = conn.execute(
                "SELECT COUNT(*) as c FROM shadow_trades WHERE status = 'closed'"
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
        finally:
            conn.close()
    except Exception as exc:
        logger.error("[API] build-score failed: %s", exc, exc_info=True)
        return {"build_score": 0, "components": {}, "error": str(exc)}


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

        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        try:
            closed_row = conn.execute(
                "SELECT COUNT(*) as c FROM shadow_trades WHERE status = 'closed'"
            ).fetchone()
            example_row = conn.execute(
                "SELECT COUNT(*) as c FROM training_examples"
            ).fetchone()
            model = conn.execute(
                "SELECT version_name, status FROM model_versions "
                "ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
            canary = conn.execute(
                "SELECT verdict, perplexity, distinct_2 FROM canary_evaluations "
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
