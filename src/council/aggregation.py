"""Council vote aggregation and backward-compat tallies.

Called by: council/protocol.py
Calls: council/constants.py
Owns tables: none
Config keys: none
Tests: tests/test_council_aggregation.py
"""

import logging
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from src.config import DB_PATH
from src.council.constants import (
    DECISION_THRESHOLDS,
    DIRECTION_MAP,
    DOMAIN_WEIGHTS,
    DYNAMIC_WEIGHT_ENABLED,
    INITIAL_AGENT_ALPHA,
    INITIAL_AGENT_BETA,
    MIN_AGENT_WEIGHT,
    MIN_VOTES_FOR_DYNAMIC,
    PARAMETER_DEFAULTS,
    VALUE_TRACKER_WINDOW_WEEKS,
)

logger = logging.getLogger(__name__)

ET = ZoneInfo("America/New_York")


def compute_dynamic_weights(db_path: str = DB_PATH,
                             session_type: str = "daily") -> dict[str, float] | None:
    """Compute Bayesian agent weights from vote accuracy history.

    WHY: Static weights can't adapt. Yue (2025, ICAID) showed dynamic weighting
    improves Sharpe by 38.5%. Beta distribution provides uncertainty-aware estimates
    that naturally revert to equal weights when data is sparse.

    Returns None if insufficient data (falls back to static DOMAIN_WEIGHTS).
    """
    if not DYNAMIC_WEIGHT_ENABLED:
        return None

    static_weights = DOMAIN_WEIGHTS.get(session_type, DOMAIN_WEIGHTS["daily"])
    agents = list(static_weights.keys())
    cutoff = (datetime.now(ET) - timedelta(weeks=VALUE_TRACKER_WINDOW_WEEKS)).isoformat()

    try:
        with closing(sqlite3.connect(db_path)) as conn:
            conn.row_factory = sqlite3.Row
            # #386 follow-up: Aggregate net PnL per day FIRST, then join to
            # council votes. This prevents many-to-many inflation where a
            # single bullish vote matched to 5 same-day trades counted as 5
            # data points instead of 1. One vote = one accuracy signal.
            rows = conn.execute(
                """
                SELECT cv.agent_name,
                       cv.direction,
                       daily_pnl.net_pnl
                FROM council_votes cv
                JOIN council_sessions cs ON cv.session_id = cs.session_id
                JOIN (
                    SELECT date(created_at) AS trade_date,
                           SUM(CAST(pnl_dollars AS REAL)) AS net_pnl
                    FROM shadow_trades
                    WHERE status = 'closed'
                      AND pnl_dollars IS NOT NULL
                      AND COALESCE(quarantined, 0) = 0
                    GROUP BY date(created_at)
                ) daily_pnl ON date(cs.created_at) = daily_pnl.trade_date
                WHERE cs.created_at >= ?
                  AND cs.session_type = ?
                  AND cv.direction IN ('bullish', 'bearish')
                """,
                (cutoff, session_type),
            ).fetchall()
    except Exception as exc:
        logger.warning("[COUNCIL] Dynamic weights DB query failed: %s", exc)
        return None

    # Tally correct/incorrect per agent
    records: dict[str, dict] = {a: {"correct": 0, "incorrect": 0} for a in agents}
    for row in rows:
        agent = row["agent_name"]
        if agent not in records:
            continue
        direction = row["direction"]
        net_pnl = float(row["net_pnl"] or 0)
        # Bullish + net positive day = correct; Bearish + net negative = correct
        if (direction == "bullish" and net_pnl > 0) or (direction == "bearish" and net_pnl < 0):
            records[agent]["correct"] += 1
        else:
            records[agent]["incorrect"] += 1

    # Check minimum vote threshold — ANY agent below threshold → fall back to static
    for agent in agents:
        total = records[agent]["correct"] + records[agent]["incorrect"]
        if total < MIN_VOTES_FOR_DYNAMIC:
            logger.info("[COUNCIL] Agent %s has %d votes (< %d) — using static weights",
                        agent, total, MIN_VOTES_FOR_DYNAMIC)
            return None

    # Compute Beta posterior expected accuracy per agent
    raw_weights = {}
    for agent in agents:
        alpha = INITIAL_AGENT_ALPHA + records[agent]["correct"]
        beta = INITIAL_AGENT_BETA + records[agent]["incorrect"]
        expected_accuracy = alpha / (alpha + beta)
        raw_weights[agent] = expected_accuracy

    # Apply floor
    for agent in raw_weights:
        raw_weights[agent] = max(raw_weights[agent], MIN_AGENT_WEIGHT)

    # Normalize to sum to 1.0
    total = sum(raw_weights.values())
    weights = {a: round(w / total, 4) for a, w in raw_weights.items()}

    logger.info("[COUNCIL] Dynamic weights: %s", weights)
    return weights


def aggregate_votes(
    assessments: list[dict],
    session_type: str = "daily",
    db_path: str = DB_PATH,
) -> dict:
    """Aggregate council assessments into a consensus direction and parameters."""
    # #118 — Filter out votes where parsing failed (no valid direction/assessment)
    valid_assessments = [
        a for a in assessments
        if not a.get("_parse_failed") and a.get("direction")
    ]
    filtered_count = len(assessments) - len(valid_assessments)
    if filtered_count:
        logger.warning("[COUNCIL] Filtered %d unparseable votes from tally", filtered_count)
    if not valid_assessments:
        valid_assessments = assessments  # Fallback to all if everything failed

    # Try dynamic weights first, fall back to static
    dynamic = compute_dynamic_weights(db_path, session_type)
    weights = dynamic if dynamic else DOMAIN_WEIGHTS.get(session_type, DOMAIN_WEIGHTS["daily"])
    numerator = 0.0
    denominator = 0.0
    vote_dist = {"bullish": 0, "neutral": 0, "bearish": 0}
    confidences = []
    param_num = {"position_sizing_multiplier": 0.0, "cash_reserve_target_pct": 0.0}
    param_den = 0.0
    scan_votes = {"conservative": 0.0, "normal": 0.0, "aggressive": 0.0}

    for assessment in valid_assessments:
        agent = assessment.get("agent", "unknown")
        direction = assessment.get("direction", "neutral")
        confidence = assessment.get("confidence", 0.5)
        domain_weight = weights.get(agent, 1.0)
        weight = confidence * domain_weight

        numerator += DIRECTION_MAP.get(direction, 0.0) * weight
        denominator += weight
        vote_dist[direction] = vote_dist.get(direction, 0) + 1
        confidences.append(confidence)

        params = assessment.get("parameters", {})
        for param_name in param_num:
            param_num[param_name] += float(
                params.get(param_name, PARAMETER_DEFAULTS.get(param_name, 1.0))
            ) * weight
        param_den += weight

        scan_choice = params.get("scan_aggressiveness", "normal")
        if scan_choice in scan_votes:
            scan_votes[scan_choice] += weight

    score = numerator / denominator if denominator > 0 else 0.0
    confidence_avg = sum(confidences) / len(confidences) if confidences else 0.0
    max_votes = max(vote_dist.values()) if vote_dist else 0
    total_agents = len(valid_assessments)
    # #119 — Dynamic majority threshold instead of hardcoded 3
    consensus_threshold = total_agents // 2 + 1
    consensus_reached = max_votes >= consensus_threshold
    consensus_type = f"{max_votes}-{total_agents - max_votes}" if total_agents > 0 else "0-0"

    if score > DECISION_THRESHOLDS["lean_bullish"]:
        direction = "bullish"
    elif score < DECISION_THRESHOLDS["neutral_low"]:
        direction = "bearish"
    else:
        direction = "neutral"

    parameter_recommendations = {}
    if param_den > 0:
        for param_name in param_num:
            parameter_recommendations[param_name] = round(param_num[param_name] / param_den, 3)
    parameter_recommendations["scan_aggressiveness"] = (
        max(scan_votes, key=scan_votes.get) if scan_votes else "normal"
    )

    return {
        "aggregated_score": round(score, 4),
        "direction": direction,
        "confidence_avg": round(confidence_avg, 3),
        "vote_distribution": vote_dist,
        "consensus_reached": consensus_reached,
        "consensus_type": consensus_type,
        "round2_needed": not consensus_reached,
        "parameter_recommendations": parameter_recommendations,
    }


def tally_votes(final_assessments: list[dict]) -> dict:
    """Backward-compatible tally for older council consumers."""
    result = aggregate_votes(final_assessments, "daily")
    return {
        "consensus": result["direction"] if result["consensus_reached"] else "contested",
        "leading_vote": {
            "bullish": "increase_exposure",
            "neutral": "hold_steady",
            "bearish": "reduce_exposure",
        }.get(result["direction"], "hold_steady"),
        "confidence_weighted_score": round(abs(result["aggregated_score"]) * 100, 1),
        "is_contested": not result["consensus_reached"],
        "vote_breakdown": result["vote_distribution"],
        "reason": (
            f"{result['consensus_type']} consensus"
            if result["consensus_reached"]
            else "contested"
        ),
        "_v2": result,
    }
