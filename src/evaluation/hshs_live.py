"""Live HSHS computation from database state.

Called by: api.cloud_routes.analytics, council.agent_data, council.context, evaluation.cto_report
Calls: evaluation.hshs
Owns tables: none
Config keys: none
Tests: tests/test_hshs_live.py

Queries the actual database to compute each HSHS dimension score (0-100),
then delegates to compute_hshs_score() for the weighted geometric mean.
"""

import logging
import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo

from src.evaluation.hshs import DIMENSION_KEYS, compute_hshs_score

logger = logging.getLogger(__name__)

ET = ZoneInfo("America/New_York")
SYSTEM_START = datetime(2026, 3, 25, tzinfo=ET)

DEFAULT_DB_PATH = "ai_research_desk.sqlite3"


# ---------------------------------------------------------------------------
# Dimension scorers -- each returns 0-100
# ---------------------------------------------------------------------------


def _score_performance(conn: sqlite3.Connection) -> float:
    """Score based on win rate, profit factor, max drawdown, trade count."""
    try:
        cur = conn.execute(
            "SELECT COUNT(*) as total FROM shadow_trades WHERE status = 'closed'"
        )
        total = cur.fetchone()[0] or 0

        if total == 0:
            return 5.0  # Minimal baseline -- system exists but no trades yet

        cur = conn.execute(
            "SELECT COUNT(*) FROM shadow_trades "
            "WHERE status = 'closed' AND pnl_dollars > 0"
        )
        winners = cur.fetchone()[0] or 0
        win_rate = winners / total if total else 0

        # Profit factor: gross profit / gross loss
        cur = conn.execute(
            "SELECT COALESCE(SUM(pnl_dollars), 0) FROM shadow_trades "
            "WHERE status = 'closed' AND pnl_dollars > 0"
        )
        gross_profit = cur.fetchone()[0] or 0

        cur = conn.execute(
            "SELECT COALESCE(ABS(SUM(pnl_dollars)), 0) FROM shadow_trades "
            "WHERE status = 'closed' AND pnl_dollars < 0"
        )
        gross_loss = cur.fetchone()[0] or 0.01  # avoid division by zero
        profit_factor = gross_profit / gross_loss

        # Max drawdown from pnl_pct (worst single trade loss as proxy)
        cur = conn.execute(
            "SELECT COALESCE(MIN(pnl_pct), 0) FROM shadow_trades "
            "WHERE status = 'closed'"
        )
        max_dd = abs(cur.fetchone()[0] or 0)

        # Scoring components (each 0-25, summed to 0-100)
        wr_score = min(25.0, win_rate * 50)  # 50% WR = 25 pts
        pf_score = min(25.0, profit_factor * 12.5)  # 2.0 PF = 25 pts
        dd_score = max(0.0, 25.0 - max_dd * 2.5)  # <10% DD = 25 pts
        count_score = min(25.0, total * 2.5)  # 10 trades = 25 pts

        return min(100.0, wr_score + pf_score + dd_score + count_score)

    except Exception as e:
        logger.warning("[HSHS] performance sub-score error: %s", e)
        return 5.0


def _score_model_quality(conn: sqlite3.Connection) -> float:
    """Score based on template fallback rate, quality scores, training volume."""
    try:
        cur = conn.execute("SELECT COUNT(*) FROM training_examples")
        total_examples = cur.fetchone()[0] or 0

        if total_examples == 0:
            return 5.0

        # Template fallback rate (lower is better)
        cur = conn.execute(
            "SELECT COUNT(*) FROM training_examples "
            "WHERE source = 'template' OR source = 'fallback'"
        )
        fallback_count = cur.fetchone()[0] or 0
        fallback_rate = fallback_count / total_examples if total_examples else 1.0

        # Quality scores (if available)
        cur = conn.execute(
            "SELECT AVG(quality_score) FROM training_examples "
            "WHERE quality_score IS NOT NULL"
        )
        row = cur.fetchone()
        avg_quality = row[0] if row and row[0] is not None else 0.5

        # Scoring components
        fallback_score = min(35.0, (1 - fallback_rate) * 35)  # 0% fallback = 35
        quality_score = min(35.0, avg_quality * 35)  # 1.0 quality = 35
        volume_score = min(30.0, total_examples * 0.3)  # 100 examples = 30

        return min(100.0, fallback_score + quality_score + volume_score)

    except Exception as e:
        logger.warning("[HSHS] model_quality sub-score error: %s", e)
        return 5.0


def _score_data_asset(conn: sqlite3.Connection) -> float:
    """Score based on training data count, freshness, source diversity."""
    try:
        cur = conn.execute("SELECT COUNT(*) FROM training_examples")
        total = cur.fetchone()[0] or 0

        if total == 0:
            return 5.0

        # Data volume score
        volume_score = min(40.0, total * 0.4)  # 100 examples = 40 pts

        # Freshness: examples created in last 7 days
        cur = conn.execute(
            "SELECT COUNT(*) FROM training_examples "
            "WHERE created_at >= datetime('now', '-7 days')"
        )
        recent = cur.fetchone()[0] or 0
        freshness_score = min(30.0, (recent / max(total, 1)) * 60)  # 50% recent = 30

        # Source diversity
        cur = conn.execute(
            "SELECT COUNT(DISTINCT source) FROM training_examples "
            "WHERE source IS NOT NULL"
        )
        distinct_sources = cur.fetchone()[0] or 1
        diversity_score = min(30.0, distinct_sources * 10)  # 3 sources = 30

        return min(100.0, volume_score + freshness_score + diversity_score)

    except Exception as e:
        logger.warning("[HSHS] data_asset sub-score error: %s", e)
        return 5.0


def _score_flywheel_velocity(conn: sqlite3.Connection) -> float:
    """Score based on model version count, training data growth rate."""
    try:
        # Model version count
        cur = conn.execute("SELECT COUNT(*) FROM model_versions")
        version_count = cur.fetchone()[0] or 0

        # Training data growth: examples in last 7 days vs prior 7 days
        cur = conn.execute(
            "SELECT COUNT(*) FROM training_examples "
            "WHERE created_at >= datetime('now', '-7 days')"
        )
        recent_week = cur.fetchone()[0] or 0

        cur = conn.execute(
            "SELECT COUNT(*) FROM training_examples "
            "WHERE created_at >= datetime('now', '-14 days') "
            "AND created_at < datetime('now', '-7 days')"
        )
        prior_week = cur.fetchone()[0] or 0

        # Growth rate
        if prior_week > 0:
            growth_rate = recent_week / prior_week
        elif recent_week > 0:
            growth_rate = 2.0  # new data from nothing is strong signal
        else:
            growth_rate = 0.0

        # Scoring
        version_score = min(40.0, version_count * 20)  # 2 versions = 40
        growth_score = min(30.0, growth_rate * 15)  # 2x growth = 30
        recent_score = min(30.0, recent_week * 3)  # 10 recent = 30

        return min(100.0, version_score + growth_score + recent_score)

    except Exception as e:
        logger.warning("[HSHS] flywheel_velocity sub-score error: %s", e)
        return 5.0


def _score_defensibility(conn: sqlite3.Connection) -> float:
    """Score based on proprietary data volume, system complexity, time invested."""
    try:
        # Proprietary data volume (training examples)
        cur = conn.execute("SELECT COUNT(*) FROM training_examples")
        data_count = cur.fetchone()[0] or 0

        # System complexity proxy: number of tables with data
        tables_with_data = 0
        for table in [
            "shadow_trades",
            "training_examples",
            "model_versions",
            "scan_metrics",
            "macro_snapshots",
            "council_sessions",
        ]:
            try:
                cur = conn.execute(f"SELECT COUNT(*) FROM {table}")
                if (cur.fetchone()[0] or 0) > 0:
                    tables_with_data += 1
            except Exception:
                pass

        # Time invested: months since system start
        now = datetime.now(ET)
        months_active = max(0.1, (now - SYSTEM_START).days / 30.0)

        # Scoring
        data_score = min(35.0, data_count * 0.35)  # 100 examples = 35
        complexity_score = min(35.0, tables_with_data * (35 / 6))  # 6 tables = 35
        time_score = min(30.0, months_active * 10)  # 3 months = 30

        return min(100.0, data_score + complexity_score + time_score)

    except Exception as e:
        logger.warning("[HSHS] defensibility sub-score error: %s", e)
        return 5.0


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

SCORERS = {
    "performance": _score_performance,
    "model_quality": _score_model_quality,
    "data_asset": _score_data_asset,
    "flywheel_velocity": _score_flywheel_velocity,
    "defensibility": _score_defensibility,
}


def compute_hshs(db_path: str = DEFAULT_DB_PATH) -> dict:
    """Compute the live Arcis System Health Score from database state.

    Returns:
        Dict with keys: hshs, dimensions, weights, phase, months_active, computed_at.
    """
    now = datetime.now(ET)
    months_active = max(1, int((now - SYSTEM_START).days / 30) + 1)

    dimensions: dict[str, float] = {}

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        for key in DIMENSION_KEYS:
            scorer = SCORERS.get(key)
            if scorer is None:
                dimensions[key] = 0.0
                continue
            try:
                dimensions[key] = round(scorer(conn), 2)
            except Exception as e:
                logger.warning("[HSHS] scorer %s failed: %s", key, e)
                dimensions[key] = 0.0
    finally:
        conn.close()

    result = compute_hshs_score(dimensions, months_active=months_active)

    return {
        "hshs": result["overall"],
        "dimensions": result["dimensions"],
        "weights": result["weights"],
        "phase": result["phase"],
        "months_active": months_active,
        "computed_at": now.isoformat(),
    }
