"""Council response parsing and normalization.

Called by: protocol.py, tests
Calls: json, council/constants.py
"""

import json
import logging

from src.council.constants import PARAMETER_DEFAULTS

logger = logging.getLogger(__name__)


def default_response(agent_name: str, reason: str = "") -> dict:
    """Return a safe default when an agent fails."""
    return {
        "agent": agent_name,
        "direction": "neutral",
        "confidence": 0.1,
        "parameters": PARAMETER_DEFAULTS.copy(),
        "sector_tilts": {"prefer": [], "avoid": []},
        "key_reasoning": f"Agent unavailable: {reason}" if reason else "Agent unavailable",
        "key_risk": "Unable to assess",
        "falsifiable_prediction": None,
        "position": "neutral",
        "confidence_int": 1,
        "recommendation": f"Agent unavailable: {reason}",
        "key_data_points": [],
        "risk_flags": [reason] if reason else [],
        "vote": "hold_steady",
        "_parse_failed": True,
    }


def parse_agent_response(raw: str | None, agent_name: str) -> dict:
    """Parse structured JSON from an agent response."""
    if raw is None:
        logger.warning("[COUNCIL] Empty response from %s", agent_name)
        return default_response(agent_name, "API call returned None")

    text = raw.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        lines = [line for line in lines if not line.strip().startswith("```")]
        text = "\n".join(lines).strip()

    data = None
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}") + 1
        if start != -1 and end > start:
            try:
                data = json.loads(text[start:end])
            except json.JSONDecodeError:
                data = None

    if data is None:
        logger.warning("[COUNCIL] JSON parse failed for %s. Raw: %s", agent_name, raw[:300])
        return default_response(agent_name, "Could not parse JSON from response")

    data["agent"] = agent_name
    valid_directions = {"bullish", "neutral", "bearish"}
    if data.get("direction") not in valid_directions:
        position_map = {"offensive": "bullish", "defensive": "bearish", "neutral": "neutral"}
        data["direction"] = position_map.get(data.get("position", "neutral"), "neutral")

    confidence = data.get("confidence", 0.5)
    if isinstance(confidence, int) and confidence > 1:
        confidence = confidence / 10.0
    data["confidence"] = max(0.0, min(1.0, float(confidence)))

    params = data.get("parameters", {})
    params.setdefault("position_sizing_multiplier", PARAMETER_DEFAULTS["position_sizing_multiplier"])
    params.setdefault("cash_reserve_target_pct", PARAMETER_DEFAULTS["cash_reserve_target_pct"])
    params.setdefault("scan_aggressiveness", PARAMETER_DEFAULTS["scan_aggressiveness"])
    data["parameters"] = params

    data.setdefault("sector_tilts", {"prefer": [], "avoid": []})
    data.setdefault("key_reasoning", "")
    data.setdefault("key_risk", "")
    data.setdefault("falsifiable_prediction", None)

    data["position"] = {"bullish": "offensive", "neutral": "neutral", "bearish": "defensive"}.get(
        data["direction"], "neutral"
    )
    data["confidence_int"] = max(1, min(10, int(data["confidence"] * 10)))
    data["recommendation"] = data.get("key_reasoning", "")
    data["key_data_points"] = []
    data["risk_flags"] = [data["key_risk"]] if data.get("key_risk") else []
    data["vote"] = {
        "bullish": "increase_exposure",
        "neutral": "hold_steady",
        "bearish": "reduce_exposure",
    }.get(data["direction"], "hold_steady")

    return data
