"""Council protocol constants and thresholds.

Called by: protocol.py, engine.py, value_tracker.py
Calls: none
"""

DOMAIN_WEIGHTS = {
    "daily": {
        "tactical_operator": 1.2,
        "strategic_architect": 0.8,
        "red_team": 1.0,
        "innovation_engine": 0.6,
        "macro_navigator": 0.9,
    },
    "weekly": {
        "tactical_operator": 0.8,
        "strategic_architect": 1.3,
        "red_team": 1.0,
        "innovation_engine": 1.0,
        "macro_navigator": 1.2,
    },
    "monthly": {
        "tactical_operator": 0.6,
        "strategic_architect": 1.5,
        "red_team": 1.0,
        "innovation_engine": 1.2,
        "macro_navigator": 1.3,
    },
    "strategic": {
        "tactical_operator": 0.7,
        "strategic_architect": 1.4,
        "red_team": 1.0,
        "innovation_engine": 1.1,
        "macro_navigator": 1.0,
    },
}

DECISION_THRESHOLDS = {
    "strong_bullish": 0.5,
    "lean_bullish": 0.2,
    "neutral_low": -0.2,
    "lean_bearish": -0.5,
}

RATE_LIMITS = {
    "max_daily_change_pct": 0.25,
    "max_weekly_change_pct": 0.50,
    "min_confidence_to_apply": 0.40,
    "emergency_reset_streak": 3,
}

PARAMETER_BOUNDS = {
    "position_sizing_multiplier": (0.25, 1.5),
    "cash_reserve_target_pct": (10, 50),
}

PARAMETER_DEFAULTS = {
    "position_sizing_multiplier": 1.0,
    "cash_reserve_target_pct": 15,
    "scan_aggressiveness": "normal",
}

DIRECTION_MAP = {"bullish": 1.0, "neutral": 0.0, "bearish": -1.0}
