"""Live HSHS computation from database state.

Called by: api.cloud_routes.analytics, council.agent_data, council.context, evaluation.cto_report
Calls: evaluation.hshs
Owns tables: none
Config keys: none
Tests: tests/test_hshs_live.py

Queries the actual database to compute each HSHS dimension score (0-100),
then delegates to compute_hshs_score() for the weighted geometric mean.

HSHS: Halcyon System Health Score
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Five dimensions, each 0-100, combined via weighted geometric mean:

  1. performance      — win rate, profit factor, max drawdown, trade count
  2. model_quality    — template fallback rate, quality scores, volume
  3. data_asset       — training data count, freshness, source diversity
  4. flywheel_velocity — model version count, data growth rate
  5. defensibility    — proprietary data volume, system complexity, time

Phase-dependent weighting (from hshs.py PHASE_WEIGHTS):
  - Early (months 1-6):  data_asset 35%, model_quality 25% — build the moat
  - Growth (months 7-18): even 20% each — balanced investment
  - Mature (18+):         performance 30%, defensibility 25% — prove returns

The geometric mean means a zero in ANY dimension collapses the overall
score to zero.  This is intentional: a system with great performance
but zero data asset is not healthy — it is one model failure away from
having nothing to retrain on.

float() casts throughout (#181): database values can arrive as Decimal,
None, or string types depending on SQLite driver behavior and NULL
coalescing.  Every DB value is explicitly cast to float() to prevent
TypeError in arithmetic.  This was a hard-won lesson from production
database corruption events.
"""

import logging
import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo

from src.config import DB_PATH
from src.utils.db import connect_db
from src.evaluation.hshs import DIMENSION_KEYS, compute_hshs_score

logger = logging.getLogger(__name__)

ET = ZoneInfo("America/New_York")
# System start date determines the phase (early/growth/mature) which
# controls dimension weights.  Changing this date shifts all phase
# transitions, so it should only be set once at project inception.
SYSTEM_START = datetime(2026, 3, 25, tzinfo=ET)

DEFAULT_DB_PATH = DB_PATH


# ---------------------------------------------------------------------------
# Dimension scorers -- each returns 0-100
# ---------------------------------------------------------------------------


def _score_performance(conn: sqlite3.Connection) -> float:
    """Score based on win rate, profit factor, max drawdown, trade count.

    Four sub-components, each worth 0-25 points (sum to 0-100):
      - Win rate:       50% WR = 25 pts (target is modest for swing trading)
      - Profit factor:  2.0 PF = 25 pts (gross wins / gross losses)
      - Max drawdown:   <10% DD = 25 pts (penalizes tail risk)
      - Trade count:    10 trades = 25 pts (minimum sample for significance)

    Returns 5.0 when no trades exist — a minimal "system exists" baseline
    so the geometric mean doesn't collapse during bootstrapping.

    All DB values are explicitly cast to float() (#181) to prevent
    TypeError from Decimal/None values.
    """
    try:
        cur = conn.execute(
            "SELECT COUNT(*) as total FROM shadow_trades WHERE status = 'closed'"
            " AND COALESCE(quarantined, 0) = 0"
        )
        total = int(cur.fetchone()[0] or 0)

        if total == 0:
            return 5.0  # Minimal baseline -- system exists but no trades yet

        cur = conn.execute(
            "SELECT COUNT(*) FROM shadow_trades "
            "WHERE status = 'closed' AND pnl_dollars > 0"
            " AND COALESCE(quarantined, 0) = 0"
        )
        winners = int(cur.fetchone()[0] or 0)
        win_rate = winners / total if total else 0

        # Profit factor: gross profit / gross loss.
        # Floor gross_loss at 0.01 to avoid division by zero when all
        # trades are winners (which would give infinite PF).
        cur = conn.execute(
            "SELECT COALESCE(SUM(pnl_dollars), 0) FROM shadow_trades "
            "WHERE status = 'closed' AND pnl_dollars > 0"
            " AND COALESCE(quarantined, 0) = 0"
        )
        gross_profit = float(cur.fetchone()[0] or 0)

        cur = conn.execute(
            "SELECT COALESCE(ABS(SUM(pnl_dollars)), 0) FROM shadow_trades "
            "WHERE status = 'closed' AND pnl_dollars < 0"
            " AND COALESCE(quarantined, 0) = 0"
        )
        gross_loss = float(cur.fetchone()[0] or 0.01)
        if gross_loss == 0:
            gross_loss = 0.01
        profit_factor = gross_profit / gross_loss

        # Max drawdown proxy: worst single trade loss.
        # This is a proxy because true portfolio drawdown requires a
        # cumulative equity curve, which is computed elsewhere (CTO report).
        # Using the single worst trade is conservative — it overstates
        # drawdown in a diversified portfolio.
        cur = conn.execute(
            "SELECT COALESCE(MIN(pnl_pct), 0) FROM shadow_trades "
            "WHERE status = 'closed' AND COALESCE(quarantined, 0) = 0"
        )
        raw = cur.fetchone()[0]
        # float() cast (#181/#195): raw can be None, empty string, Decimal,
        # or a TEXT-typed number from SQLite.  Without float(), abs(raw)
        # raises "bad operand type for abs(): 'str'".
        try:
            max_dd = abs(float(raw)) if raw is not None and raw != "" else 0.0
        except (TypeError, ValueError):
            max_dd = 0.0

        # Scoring components (each 0-25, summed to 0-100).
        # float() casts (#181) prevent TypeError from mixed DB types.
        wr_score = min(25.0, float(win_rate) * 50)  # 50% WR = 25 pts
        pf_score = min(25.0, float(profit_factor) * 12.5)  # 2.0 PF = 25 pts
        dd_score = max(0.0, 25.0 - float(max_dd) * 2.5)  # <10% DD = 25 pts
        count_score = min(25.0, float(total) * 2.5)  # 10 trades = 25 pts

        return min(100.0, wr_score + pf_score + dd_score + count_score)

    except Exception as e:
        logger.warning("[HSHS] performance sub-score error: %s", e)
        return 5.0


def _score_model_quality(conn: sqlite3.Connection) -> float:
    """Score based on template fallback rate, quality scores, training volume.

    Three sub-components:
      - Fallback rate (35 pts): lower is better — 0% fallback = full score
      - Quality score (35 pts): average quality_score from rubric grading
      - Volume (30 pts): raw example count, 100 examples = full score

    The fallback rate is the most important signal: a model that produces
    valid structured output consistently is far more useful than one that
    occasionally produces brilliant output but frequently fails to parse.
    """
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
        avg_quality = float(row[0]) if row and row[0] is not None else 0.5

        # Scoring components
        fallback_score = min(35.0, (1 - float(fallback_rate)) * 35)  # 0% fallback = 35
        quality_score = min(35.0, float(avg_quality) * 35)  # 1.0 quality = 35
        volume_score = min(30.0, float(total_examples) * 0.3)  # 100 examples = 30

        return min(100.0, fallback_score + quality_score + volume_score)

    except Exception as e:
        logger.warning("[HSHS] model_quality sub-score error: %s", e)
        return 5.0


def _score_data_asset(conn: sqlite3.Connection) -> float:
    """Score based on training data count, freshness, source diversity.

    The data asset is the system's primary moat — it is the one thing
    that cannot be replicated by a competitor just running the same code.
    Three sub-components:
      - Volume (40 pts):    100 examples = full score
      - Freshness (30 pts): recent-to-total ratio (stale data loses value)
      - Diversity (30 pts): distinct sources (live, backfill, manual, etc.)
    """
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
    """Score based on *completed* train-deploy-observe cycles.

    A flywheel needs motion. The first deployed model is the starting push —
    not a cycle — so ``cycles = version_count - 1``. Data growth and recent
    volume are scaled by a "spin factor" that's zero until the first cycle
    completes; without a second model version, the flywheel hasn't turned and
    training-data activity alone doesn't count as velocity (HSHS issue #69).

      - Cycle score (50 pts): 25 pts per completed cycle, capped at 50.
      - Growth score (25 pts): week-over-week growth rate * 12.5 * spin.
      - Recent score (25 pts): recent_week examples * 2.5 * spin.
    """
    try:
        cur = conn.execute(
            "SELECT COUNT(*) FROM model_versions WHERE status IN ('active', 'retired', 'evaluation')"
        )
        version_count = cur.fetchone()[0] or 0
        cycles = max(0, version_count - 1)

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

        if prior_week > 0:
            growth_rate = recent_week / prior_week
        elif recent_week > 0:
            growth_rate = 2.0
        else:
            growth_rate = 0.0

        spin_factor = min(1.0, cycles)

        cycle_score = min(50.0, cycles * 25.0)
        growth_score = min(25.0, growth_rate * 12.5) * spin_factor
        recent_score = min(25.0, recent_week * 2.5) * spin_factor

        return min(100.0, cycle_score + growth_score + recent_score)

    except Exception as e:
        logger.warning("[HSHS] flywheel_velocity sub-score error: %s", e)
        return 5.0


def _score_defensibility(conn: sqlite3.Connection) -> float:
    """Score based on proprietary data volume, system complexity, time invested.

    Defensibility answers "how hard would it be for someone else to
    replicate this system?"  Three axes:
      - Data volume (35 pts):    proprietary training examples
      - Complexity (35 pts):     tables with data (proxy for system breadth)
      - Time invested (30 pts):  months since SYSTEM_START

    Time is an inherent moat: even with identical code, a competitor
    would need months of operation to accumulate equivalent data.
    """
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

    Each dimension scorer is called independently and wrapped in a
    try/except so that a failure in one dimension (e.g. missing table)
    doesn't block the others — it just scores 0.0 for that dimension.
    This resilience is important because HSHS is called from multiple
    contexts (dashboard, council, CTO report) and must never crash.

    Returns:
        Dict with keys: hshs, dimensions, weights, phase, months_active, computed_at.
    """
    now = datetime.now(ET)
    months_active = max(1, int((now - SYSTEM_START).days / 30) + 1)

    dimensions: dict[str, float] = {}

    conn = connect_db(db_path)
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
