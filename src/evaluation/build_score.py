"""Build Score -- single composite KPI (0-100) for Arcis.

Six components combined via geometric mean with daily idle-day decay.
See docs/research/Build_Score_Specification__Composite_KPI.md for the
full specification.

Components (6 dimensions):
    gate_velocity     -- weekly closed trade rate vs 1.92/week target
    system_health     -- HSHS composite score (passthrough)
    data_asset_value  -- quality (40%) + diversity (35%) + freshness (25%)
    model_quality     -- 7-day rolling LLM success rate
    research_velocity -- HSHS flywheel_velocity proxy
    reliability       -- scan success rate (60%) + uptime proxy (40%)

Why geometric mean?
~~~~~~~~~~~~~~~~~~~
Unlike arithmetic mean, geometric mean *punishes* any single dimension
being near zero.  A system that scores 95 on five dimensions but 2 on
reliability is NOT an 80/100 system — it is fragile.  The geometric mean
naturally produces a low composite when any leg is weak, which forces
balanced improvement across all dimensions rather than gaming one metric.

Each component is floored at 1.0 (not 0.0) before the geometric mean so
that a truly-zero dimension doesn't collapse the entire score to zero,
but it still penalizes heavily (log(1) = 0 drags the product down).

Why idle-day decay?
~~~~~~~~~~~~~~~~~~~
A 1-point/day penalty for days with zero activity (no trades, no
training examples, no scans) ensures the score reflects *ongoing*
operational health, not a one-time high-water mark.  If the system
stops running, the score gradually degrades to signal staleness.

Called by: api.cloud_routes.analytics, evaluation.hshs_live
Calls: evaluation.hshs
Owns tables: build_score_history
Config keys: none
Tests: tests/test_cloud_analytics.py
"""

import logging
import math
import sqlite3
import uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from src.config import DB_PATH

logger = logging.getLogger(__name__)

ET = ZoneInfo("America/New_York")

# Gate target: 50 trades in 26 weeks = ~1.92 trades/week.
# This is the Phase 1 (paper trading) graduation gate — the system must
# demonstrate it can sustain a minimum trade cadence before moving to
# live capital.  The target is deliberately modest to prioritize quality
# over volume.
GATE_TARGET_WEEKLY = 1.92
GATE_TOTAL_TARGET = 50

# Data asset scoring weights — quality dominates because the training
# data is the system's moat.  High-quality examples (rubric score >= 3.5)
# are worth more than a large volume of low-quality examples.
DATA_QUALITY_WEIGHT = 0.40
DATA_DIVERSITY_WEIGHT = 0.35
DATA_FRESHNESS_WEIGHT = 0.25

# Reliability weights — scan success rate matters more than raw uptime
# because a system that is "up" but producing failed scans is worse
# than one that was briefly down but produced clean scans.
RELIABILITY_SCAN_WEIGHT = 0.60
RELIABILITY_UPTIME_WEIGHT = 0.40
EXPECTED_WEEKLY_SCANS = 65  # 13/day x 5 weekdays

# 1-point daily penalty for idle days (no trades, no examples, no scans).
# Keeps the score from "coasting" on past performance when the system
# stops running.  Calibrated to be noticeable over a week but not so
# aggressive that a single weekend tanks the score.
DECAY_POINTS = 1

DEFAULT_DB = DB_PATH

def _score_gate_velocity(conn: sqlite3.Connection) -> float:
    """Weekly closed-trade count vs target rate.

    Caps at 100 to avoid over-rewarding high-volume trading at the
    expense of quality.  The 50x multiplier means hitting 1.92 trades/week
    (the target) scores 50/100 — you need to exceed the target to score
    higher, which rewards consistency above the minimum.
    """
    try:
        cutoff = (datetime.now(ET) - timedelta(days=7)).isoformat()
        cur = conn.execute(
            "SELECT COUNT(*) FROM shadow_trades "
            "WHERE status = 'closed' AND actual_exit_time >= ?"
            " AND COALESCE(quarantined, 0) = 0",
            (cutoff,),
        )
        weekly_closed = cur.fetchone()[0] or 0
        return min(100.0, (weekly_closed / GATE_TARGET_WEEKLY) * 50)
    except Exception as e:
        logger.warning("[BuildScore] gate_velocity error: %s", e)
        return 0.0

def _score_system_health(conn: sqlite3.Connection) -> float:
    """Direct passthrough from HSHS composite score.

    Delegates to the HSHS engine to avoid duplicating health logic.
    This makes system_health a "meta-dimension" that rolls up the 5
    HSHS dimensions into the Build Score's 6-component framework.
    """
    try:
        from src.evaluation.hshs_live import compute_hshs

        result = compute_hshs()
        return float(result.get("hshs", 0))
    except Exception as e:
        logger.warning("[BuildScore] system_health error: %s", e)
        return 0.0

def _query_diversity(conn: sqlite3.Connection) -> float:
    """Compute diversity sub-score from regime, outcome balance, ticker breadth.

    Diversity matters for training data because a model trained only on
    bull-market winners will fail in drawdowns.  Three axes:
      - Regime coverage: all 4 regime labels represented?
      - Outcome balance: at least 15% losses (avoids survivorship bias)
      - Ticker breadth: 100 distinct tickers = full score
    """
    cur = conn.execute(
        "SELECT COUNT(DISTINCT regime) FROM training_examples WHERE regime IS NOT NULL"
    )
    regime_score = min(100.0, ((cur.fetchone()[0] or 0) / 4.0) * 100.0)
    cur = conn.execute("SELECT COUNT(*) FROM training_examples")
    total = cur.fetchone()[0] or 0
    cur = conn.execute("SELECT COUNT(*) FROM training_examples WHERE outcome_type = 'loss'")
    loss_pct = (cur.fetchone()[0] or 0) / max(total, 1)
    balance = min(100.0, (loss_pct / 0.15) * 50 + 50) if total > 0 else 50.0
    cur = conn.execute(
        "SELECT COUNT(DISTINCT ticker) FROM training_examples WHERE ticker IS NOT NULL"
    )
    breadth = min(100.0, ((cur.fetchone()[0] or 0) / 100.0) * 100.0)
    return (regime_score + balance + breadth) / 3.0

def _score_data_asset_value(conn: sqlite3.Connection) -> float:
    """Quality (40%) + Diversity (35%) + Freshness (25%)."""
    try:
        cur = conn.execute(
            "SELECT AVG(quality_score) FROM training_examples "
            "WHERE quality_score IS NOT NULL AND created_at >= datetime('now', '-30 days')"
        )
        row = cur.fetchone()
        avg_q = row[0] if row and row[0] is not None else None
        quality = min(100.0, (avg_q / 30.0) * 100.0) if avg_q is not None else 20.0

        diversity = _query_diversity(conn)

        cur = conn.execute("SELECT COUNT(*) FROM training_examples")
        total = cur.fetchone()[0] or 1
        cur = conn.execute(
            "SELECT COUNT(*) FROM training_examples WHERE created_at >= datetime('now', '-90 days')"
        )
        freshness = min(100.0, ((cur.fetchone()[0] or 0) / total) * 100.0)

        return round(
            quality * DATA_QUALITY_WEIGHT + diversity * DATA_DIVERSITY_WEIGHT + freshness * DATA_FRESHNESS_WEIGHT, 2
        )
    except Exception as e:
        logger.warning("[BuildScore] data_asset_value error: %s", e)
        return 0.0

def _score_model_quality(conn: sqlite3.Connection) -> float:
    """7-day rolling fallback rate from scan_metrics.

    Measures how often the LLM produces a usable analysis vs falling
    back to a template.  A high fallback rate means the model is failing
    to generate valid JSON or meaningful reasoning, which degrades
    signal quality even if the system keeps running.  Returns 50.0
    when no scan data exists (neutral assumption during bootstrapping).
    """
    try:
        cutoff = (datetime.now(ET) - timedelta(days=7)).isoformat()
        cur = conn.execute(
            "SELECT SUM(llm_success), SUM(llm_total) FROM scan_metrics "
            "WHERE created_at >= ?",
            (cutoff,),
        )
        row = cur.fetchone()
        if row and row[1] and row[1] > 0:
            fallback_rate = 1 - (row[0] or 0) / row[1]
            return round((1 - fallback_rate) * 100, 2)
        return 50.0  # no scan data yet
    except Exception as e:
        logger.warning("[BuildScore] model_quality error: %s", e)
        return 0.0

def _score_research_velocity(conn: sqlite3.Connection) -> float:
    """Proxy via HSHS flywheel_velocity dimension.

    Rather than computing a separate research metric, this delegates to
    HSHS's flywheel_velocity which already tracks model version count
    and training data growth rate — the best available proxies for
    research momentum.
    """
    try:
        from src.evaluation.hshs_live import compute_hshs

        result = compute_hshs()
        dims = result.get("dimensions", {})
        return float(dims.get("flywheel_velocity", 0))
    except Exception as e:
        logger.warning("[BuildScore] research_velocity error: %s", e)
        return 0.0

def _score_reliability(conn: sqlite3.Connection) -> float:
    """Scan success rate (60%) + uptime proxy (40%)."""
    try:
        cutoff = (datetime.now(ET) - timedelta(days=7)).isoformat()
        cur = conn.execute(
            "SELECT COUNT(*) FROM scan_metrics WHERE created_at >= ?",
            (cutoff,),
        )
        total_scans = cur.fetchone()[0] or 0
        scan_rate = min(100.0, (total_scans / EXPECTED_WEEKLY_SCANS) * 100)

        # Uptime proxy: scheduler heartbeat (if recent scan exists, system was up)
        uptime = 100.0 if total_scans > 0 else 0.0

        return round(
            scan_rate * RELIABILITY_SCAN_WEIGHT
            + uptime * RELIABILITY_UPTIME_WEIGHT,
            2,
        )
    except Exception as e:
        logger.warning("[BuildScore] reliability error: %s", e)
        return 0.0

def _geometric_mean(values: list[float]) -> float:
    """Geometric mean of component scores (equal weight).

    Floors each component at 1.0 to avoid zero-collapse while still
    penalising very low dimensions heavily.  The floor is 1.0 (not 0.0)
    because log(0) is undefined and would crash, but log(1) = 0 still
    drags the geometric mean down significantly — a dimension scoring
    1.0 out of 100 effectively halves the composite.

    Equal weighting is intentional: the Build Score is meant to be a
    balanced health indicator, not a weighted priority like HSHS.  If
    any single dimension is weak, the whole score should reflect that.
    """
    if not values:
        return 0.0
    floored = [max(1.0, v) for v in values]
    log_sum = sum(math.log(v) for v in floored)
    return round(math.exp(log_sum / len(floored)), 2)

def _check_idle_day(conn: sqlite3.Connection) -> bool:
    """Return True if today qualifies as an idle day.

    Idle = zero closed trades AND zero new training examples AND zero scans.
    All three must be zero because the system can legitimately have no
    trades on a given day (e.g. no setups passed the score threshold)
    while still collecting data and running scans — that is not "idle".
    """
    today = datetime.now(ET).strftime("%Y-%m-%d")
    try:
        cur = conn.execute(
            "SELECT COUNT(*) FROM shadow_trades "
            "WHERE status = 'closed' AND actual_exit_time >= ?"
            " AND COALESCE(quarantined, 0) = 0",
            (today,),
        )
        closed_today = cur.fetchone()[0] or 0

        cur = conn.execute(
            "SELECT COUNT(*) FROM training_examples WHERE created_at >= ?",
            (today,),
        )
        examples_today = cur.fetchone()[0] or 0

        cur = conn.execute(
            "SELECT COUNT(*) FROM scan_metrics WHERE created_at >= ?",
            (today,),
        )
        scans_today = cur.fetchone()[0] or 0

        return closed_today == 0 and examples_today == 0 and scans_today == 0
    except Exception:
        return False

def _compute_phase_progress(conn: sqlite3.Connection) -> dict:
    """Compute 50-trade gate progress."""
    try:
        cur = conn.execute("SELECT COUNT(*) FROM shadow_trades WHERE status = 'closed' AND COALESCE(quarantined, 0) = 0")
        closed = cur.fetchone()[0] or 0
        pct = min(100.0, (closed / GATE_TOTAL_TARGET) * 100)
        remaining = max(0, GATE_TOTAL_TARGET - closed)
        return {
            "current_phase": 1, "trades_closed": closed,
            "trades_required": GATE_TOTAL_TARGET, "pct_complete": round(pct, 1),
            "estimated_weeks_remaining": round(remaining / GATE_TARGET_WEEKLY, 1) if remaining else 0,
        }
    except Exception:
        return {"current_phase": 1, "trades_closed": 0, "trades_required": GATE_TOTAL_TARGET,
                "pct_complete": 0, "estimated_weeks_remaining": 26}

def _get_history_7d(conn: sqlite3.Connection) -> list[float]:
    """Return last 7 daily build scores from history table."""
    try:
        cur = conn.execute(
            "SELECT build_score FROM build_score_history "
            "ORDER BY score_date DESC LIMIT 7"
        )
        rows = [r[0] for r in cur.fetchall()]
        return list(reversed(rows))
    except Exception:
        return []

def _get_delta_7d(conn: sqlite3.Connection, current: float) -> float | None:
    """Compute 7-day score delta."""
    try:
        cutoff = (datetime.now(ET) - timedelta(days=7)).strftime("%Y-%m-%d")
        cur = conn.execute(
            "SELECT build_score FROM build_score_history "
            "WHERE score_date <= ? ORDER BY score_date DESC LIMIT 1",
            (cutoff,),
        )
        row = cur.fetchone()
        if row:
            return round(current - row[0], 1)
        return None
    except Exception:
        return None

COMPONENT_KEYS = [
    "gate_velocity",
    "system_health",
    "data_asset_value",
    "model_quality",
    "research_velocity",
    "reliability",
]

SCORERS = {
    "gate_velocity": _score_gate_velocity,
    "system_health": _score_system_health,
    "data_asset_value": _score_data_asset_value,
    "model_quality": _score_model_quality,
    "research_velocity": _score_research_velocity,
    "reliability": _score_reliability,
}

def compute_build_score(db_path: str = DEFAULT_DB) -> dict:
    """Compute the Build Score and return the full API response shape.

    Returns dict matching GET /api/build-score spec.
    """
    conn = sqlite3.connect(db_path, timeout=10)  # #258: busy timeout
    conn.row_factory = sqlite3.Row
    try:
        components: dict[str, float] = {}
        for key in COMPONENT_KEYS:
            scorer = SCORERS[key]
            try:
                components[key] = round(scorer(conn), 2)
            except Exception as e:
                logger.warning("[BuildScore] %s failed: %s", key, e)
                components[key] = 0.0

        raw_score = _geometric_mean(list(components.values()))

        # Apply idle-day decay
        decay = _check_idle_day(conn)
        final_score = max(0.0, raw_score - DECAY_POINTS) if decay else raw_score

        # Data asset detail breakdown
        data_detail = _build_data_detail(conn)

        # Phase progress
        phase = _compute_phase_progress(conn)

        # History
        history_7d = _get_history_7d(conn)
        delta_7d = _get_delta_7d(conn, final_score)

        return {
            "build_score": round(final_score, 1),
            "delta_7d": delta_7d,
            "components": components,
            "data_asset_detail": data_detail,
            "phase_progress": phase,
            "decay_today": decay,
            "history_7d": history_7d,
            "computed_at": datetime.now(ET).isoformat(),
        }
    finally:
        conn.close()

def _build_data_detail(conn: sqlite3.Connection) -> dict:
    """Break down data_asset_value into quality/diversity/freshness."""
    try:
        cur = conn.execute(
            "SELECT AVG(quality_score) FROM training_examples "
            "WHERE quality_score IS NOT NULL "
            "AND created_at >= datetime('now', '-30 days')"
        )
        row = cur.fetchone()
        avg_q = row[0] if row and row[0] is not None else None
        quality = min(100.0, (avg_q / 30.0) * 100.0) if avg_q else 20.0

        cur = conn.execute("SELECT COUNT(*) FROM training_examples")
        total = cur.fetchone()[0] or 1
        cur = conn.execute(
            "SELECT COUNT(DISTINCT regime) FROM training_examples "
            "WHERE regime IS NOT NULL"
        )
        regimes = cur.fetchone()[0] or 0
        cur = conn.execute(
            "SELECT COUNT(DISTINCT ticker) FROM training_examples WHERE ticker IS NOT NULL"
        )
        tickers = cur.fetchone()[0] or 0
        diversity = round(
            (min(100, (regimes / 4) * 100) + min(100, (tickers / 100) * 100)) / 2, 1
        )

        cur = conn.execute(
            "SELECT COUNT(*) FROM training_examples "
            "WHERE created_at >= datetime('now', '-90 days')"
        )
        recent = cur.fetchone()[0] or 0
        freshness = round(min(100, (recent / max(total, 1)) * 100), 1)

        return {
            "quality": round(quality, 1),
            "diversity": diversity,
            "freshness": freshness,
        }
    except Exception:
        return {"quality": 0, "diversity": 0, "freshness": 0}

def persist_build_score(db_path: str = DEFAULT_DB) -> dict:
    """Compute build score and save to build_score_history table.

    Called daily at 4:30 PM ET by the scheduler (after market close).
    Uses INSERT OR REPLACE keyed on score_date so re-runs on the same
    day overwrite rather than duplicate.  The history table powers the
    7-day trend chart and delta_7d computation on the dashboard.
    """
    result = compute_build_score(db_path)

    conn = sqlite3.connect(db_path, timeout=10)  # #258: busy timeout
    try:
        conn.execute(
            "INSERT OR REPLACE INTO build_score_history "
            "(score_id, score_date, build_score, gate_velocity, system_health, "
            "data_asset_value, model_quality, research_velocity, reliability, "
            "decay_applied, components_json, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                str(uuid.uuid4()),
                datetime.now(ET).strftime("%Y-%m-%d"),
                result["build_score"],
                result["components"]["gate_velocity"],
                result["components"]["system_health"],
                result["components"]["data_asset_value"],
                result["components"]["model_quality"],
                result["components"]["research_velocity"],
                result["components"]["reliability"],
                1 if result["decay_today"] else 0,
                str(result["components"]),
                datetime.now(ET).isoformat(),
            ),
        )
        conn.commit()
    except Exception as e:
        logger.error("[BuildScore] persist failed: %s", e)
    finally:
        conn.close()

    return result
