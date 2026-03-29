"""Halcyon System Health Score (HSHS) computation.

Five dimensions scored 0-100, combined via weighted geometric mean.
Phase-dependent weights shift priorities as the system matures.
"""

import math
from typing import Dict

PHASE_WEIGHTS = {
    "early": {  # months 1-6
        "data_asset": 0.35,
        "model_quality": 0.25,
        "flywheel_velocity": 0.20,
        "performance": 0.10,
        "defensibility": 0.10,
    },
    "growth": {  # months 7-18
        "data_asset": 0.20,
        "model_quality": 0.20,
        "flywheel_velocity": 0.20,
        "performance": 0.20,
        "defensibility": 0.20,
    },
    "mature": {  # months 18+
        "defensibility": 0.25,
        "performance": 0.30,
        "model_quality": 0.20,
        "data_asset": 0.15,
        "flywheel_velocity": 0.10,
    },
}

DIMENSION_KEYS = [
    "performance",
    "model_quality",
    "data_asset",
    "flywheel_velocity",
    "defensibility",
]


def _get_phase(months_active: int) -> str:
    if months_active <= 6:
        return "early"
    elif months_active <= 18:
        return "growth"
    return "mature"


def _weighted_geometric_mean(values: Dict[str, float], weights: Dict[str, float]) -> float:
    """Compute the weighted geometric mean: prod(v_i ^ w_i).

    If any dimension is zero the overall score is zero (geometric mean property).
    All dimensions must be non-negative.
    """
    if not values or not weights:
        return 0.0

    log_sum = 0.0
    weight_sum = 0.0

    for key, weight in weights.items():
        val = values.get(key, 0.0)
        if val <= 0:
            return 0.0
        log_sum += weight * math.log(val)
        weight_sum += weight

    if weight_sum == 0:
        return 0.0

    return math.exp(log_sum / weight_sum * weight_sum)


def compute_hshs_score(dimensions: Dict[str, float], months_active: int = 3) -> dict:
    """Compute the Halcyon System Health Score.

    Args:
        dimensions: Dict with keys performance, model_quality, data_asset,
                    flywheel_velocity, defensibility -- each scored 0-100.
        months_active: Determines the weight phase (1-6, 7-18, 18+).

    Returns:
        Dict with keys: overall, dimensions, weights, phase.
    """
    phase = _get_phase(months_active)
    weights = PHASE_WEIGHTS[phase]

    # Clamp dimensions to 0-100, default missing to 0
    clamped = {}
    for key in DIMENSION_KEYS:
        val = dimensions.get(key, 0.0)
        clamped[key] = max(0.0, min(100.0, float(val)))

    overall = _weighted_geometric_mean(clamped, weights)

    return {
        "overall": round(overall, 2),
        "dimensions": clamped,
        "weights": weights,
        "phase": phase,
    }
