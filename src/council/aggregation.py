"""Council vote aggregation and backward-compat tallies.

Called by: protocol.py, engine.py, tests
Calls: council/constants.py
"""

from src.council.constants import (
    DECISION_THRESHOLDS,
    DIRECTION_MAP,
    DOMAIN_WEIGHTS,
    PARAMETER_DEFAULTS,
)


def aggregate_votes(
    assessments: list[dict],
    session_type: str = "daily",
) -> dict:
    """Aggregate council assessments into a consensus direction and parameters."""
    weights = DOMAIN_WEIGHTS.get(session_type, DOMAIN_WEIGHTS["daily"])
    numerator = 0.0
    denominator = 0.0
    vote_dist = {"bullish": 0, "neutral": 0, "bearish": 0}
    confidences = []
    param_num = {"position_sizing_multiplier": 0.0, "cash_reserve_target_pct": 0.0}
    param_den = 0.0
    scan_votes = {"conservative": 0.0, "normal": 0.0, "aggressive": 0.0}

    for assessment in assessments:
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
    total_agents = len(assessments)
    consensus_reached = max_votes >= 3
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
