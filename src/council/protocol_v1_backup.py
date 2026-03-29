"""Modified Delphi protocol for the AI Council.

Implements a three-round deliberation process:
  Round 1: Independent assessment (each agent gets its data + shared context).
  Round 2: Cross-examination (each agent sees all Round 1 outputs).
  Round 3: Final vote with confidence weighting.
"""

import json
import logging
from typing import Any

from src.council.agents import (
    AGENT_DATA_FUNCTIONS,
    AGENT_NAMES,
    AGENT_PROMPTS,
    gather_devils_advocate_data,
)

logger = logging.getLogger(__name__)


def _call_claude(
    system_prompt: str,
    user_prompt: str,
    temperature: float = 0.8,
) -> str | None:
    """Call the Claude API via the shared training client.

    Uses purpose="council" for cost tracking and model routing.
    """
    from src.training.claude_client import generate_training_example

    return generate_training_example(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        purpose="council",
    )


def _parse_agent_response(raw: str | None, agent_name: str) -> dict:
    """Parse a raw agent response string into a structured dict.

    Attempts JSON extraction; falls back to a default cautious response
    if the LLM output cannot be parsed.
    """
    if raw is None:
        return _default_response(agent_name, reason="API call returned None")

    # Strip markdown code fences if present
    text = raw.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        text = "\n".join(lines)

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # Try to find JSON object in the text
        start = text.find("{")
        end = text.rfind("}") + 1
        if start != -1 and end > start:
            try:
                data = json.loads(text[start:end])
            except json.JSONDecodeError:
                return _default_response(
                    agent_name, reason="Could not parse JSON from response"
                )
        else:
            return _default_response(
                agent_name, reason="No JSON object found in response"
            )

    # Validate and normalize required fields -- always enforce the caller's
    # agent_name so the downstream storage logic can rely on it.
    data["agent"] = agent_name
    data.setdefault("position", "neutral")
    data.setdefault("confidence", 5)
    data.setdefault("recommendation", "")
    data.setdefault("key_data_points", [])
    data.setdefault("risk_flags", [])
    data.setdefault("vote", "hold_steady")

    # Clamp confidence to 1-10
    data["confidence"] = max(1, min(10, int(data["confidence"])))

    # Validate vote value
    valid_votes = {
        "reduce_exposure",
        "hold_steady",
        "increase_exposure",
        "selective_buying",
    }
    if data["vote"] not in valid_votes:
        data["vote"] = "hold_steady"

    # Validate position value
    valid_positions = {"defensive", "neutral", "offensive"}
    if data["position"] not in valid_positions:
        data["position"] = "neutral"

    return data


def _default_response(agent_name: str, reason: str = "") -> dict:
    """Return a cautious default response when parsing fails."""
    return {
        "agent": agent_name,
        "position": "neutral",
        "confidence": 3,
        "recommendation": f"Unable to produce full analysis. {reason}",
        "key_data_points": [],
        "risk_flags": [reason] if reason else [],
        "vote": "hold_steady",
    }


def build_shared_context(db_path: str) -> str:
    """Build a shared context summary that all agents receive."""
    from src.council.agents import _query_db

    parts = []

    try:
        recent_recs = _query_db(
            """SELECT COUNT(*) as count, AVG(priority_score) as avg_score
               FROM recommendations
               WHERE created_at >= datetime('now', '-1 day')""",
            db_path=db_path,
        )
        if recent_recs:
            r = recent_recs[0]
            parts.append(
                f"Today's scan: {r.get('count', 0)} candidates, "
                f"avg score {r.get('avg_score', 0):.1f}"
            )
    except Exception as e:
        logger.warning("[COUNCIL] Failed to query recent recommendations: %s", e)

    try:
        open_count = _query_db(
            "SELECT COUNT(*) as n FROM shadow_trades WHERE status = 'open'",
            db_path=db_path,
        )
        if open_count:
            parts.append(f"Open shadow trades: {open_count[0]['n']}")
    except Exception as e:
        logger.warning("[COUNCIL] Failed to query open shadow trades: %s", e)

    try:
        from src.evaluation.hshs_live import compute_hshs
        hshs = compute_hshs()
        parts.append(f"System Health (HSHS): {hshs.get('hshs', 0):.1f}/100 "
                     f"(P={hshs['dimensions'].get('performance', 0):.0f} "
                     f"M={hshs['dimensions'].get('model_quality', 0):.0f} "
                     f"D={hshs['dimensions'].get('data_asset', 0):.0f} "
                     f"F={hshs['dimensions'].get('flywheel_velocity', 0):.0f} "
                     f"C={hshs['dimensions'].get('defensibility', 0):.0f})")
    except Exception as e:
        logger.warning("[COUNCIL] HSHS query failed: %s", e)

    try:
        vix = _query_db(
            "SELECT vix_close FROM vix_daily ORDER BY date DESC LIMIT 1",
            db_path=db_path,
        )
        if vix:
            parts.append(f"Latest VIX: {vix[0]['vix_close']}")
    except Exception as e:
        logger.warning("[COUNCIL] Failed to query VIX data: %s", e)

    return "\n".join(parts) if parts else "No shared context data available."


# ---------------------------------------------------------------------------
# Protocol rounds
# ---------------------------------------------------------------------------


def run_round_1(
    shared_context: str,
    db_path: str,
    temperature: float = 0.8,
) -> list[dict]:
    """Round 1: Independent assessment.

    Each agent receives its private data payload plus the shared context,
    then produces an independent assessment.
    """
    assessments: list[dict] = []

    for agent_name in AGENT_NAMES:
        if agent_name == "devils_advocate":
            continue  # Devil's advocate runs after Round 1

        system_prompt = AGENT_PROMPTS[agent_name]
        data_fn = AGENT_DATA_FUNCTIONS[agent_name]
        payload = data_fn(db_path=db_path)

        user_prompt = (
            f"SHARED CONTEXT:\n{shared_context}\n\n"
            f"YOUR PRIVATE DATA:\n{json.dumps(payload, indent=2, default=str)}\n\n"
            "Provide your independent assessment as a JSON object."
        )

        raw = _call_claude(system_prompt, user_prompt, temperature=temperature)
        assessment = _parse_agent_response(raw, agent_name)
        assessments.append(assessment)
        logger.info(
            "Round 1 - %s: position=%s, confidence=%d, vote=%s",
            agent_name,
            assessment["position"],
            assessment["confidence"],
            assessment["vote"],
        )

    # Now run the devil's advocate with Round 1 results
    da_system = AGENT_PROMPTS["devils_advocate"]
    da_payload = gather_devils_advocate_data(assessments, db_path=db_path)
    da_user = (
        f"ROUND 1 ASSESSMENTS FROM OTHER AGENTS:\n"
        f"{json.dumps(assessments, indent=2, default=str)}\n\n"
        f"HISTORICAL CONTEXT:\n"
        f"{json.dumps(da_payload.get('past_sessions', []), indent=2, default=str)}\n\n"
        "Argue against the emerging consensus. Provide your assessment as a JSON object."
    )
    raw = _call_claude(da_system, da_user, temperature=temperature)
    da_assessment = _parse_agent_response(raw, "devils_advocate")
    assessments.append(da_assessment)
    logger.info(
        "Round 1 - devils_advocate: position=%s, confidence=%d, vote=%s",
        da_assessment["position"],
        da_assessment["confidence"],
        da_assessment["vote"],
    )

    return assessments


def run_round_2(
    round1_assessments: list[dict],
    temperature: float = 0.85,
) -> list[dict]:
    """Round 2: Cross-examination.

    Each agent sees all Round 1 outputs and is asked to maintain, strengthen,
    or revise their position.
    """
    assessments: list[dict] = []

    round1_summary = json.dumps(round1_assessments, indent=2, default=str)

    for agent_name in AGENT_NAMES:
        system_prompt = AGENT_PROMPTS[agent_name]

        # Find this agent's Round 1 position
        own_r1 = next(
            (a for a in round1_assessments if a["agent"] == agent_name),
            None,
        )
        own_summary = (
            json.dumps(own_r1, indent=2, default=str) if own_r1 else "N/A"
        )

        user_prompt = (
            f"ALL ROUND 1 ASSESSMENTS:\n{round1_summary}\n\n"
            f"YOUR ROUND 1 POSITION:\n{own_summary}\n\n"
            "Having seen all perspectives, you may MAINTAIN, STRENGTHEN, or REVISE "
            "your position. Explain any changes. Respond with a JSON object."
        )

        raw = _call_claude(system_prompt, user_prompt, temperature=temperature)
        assessment = _parse_agent_response(raw, agent_name)
        assessments.append(assessment)
        logger.info(
            "Round 2 - %s: position=%s, confidence=%d, vote=%s",
            agent_name,
            assessment["position"],
            assessment["confidence"],
            assessment["vote"],
        )

    return assessments


def run_round_3(
    round2_assessments: list[dict],
    temperature: float = 0.9,
) -> list[dict]:
    """Round 3: Final vote with confidence weighting.

    Each agent casts a final vote after seeing the Round 2 cross-examination.
    """
    assessments: list[dict] = []

    round2_summary = json.dumps(round2_assessments, indent=2, default=str)

    for agent_name in AGENT_NAMES:
        system_prompt = AGENT_PROMPTS[agent_name]

        user_prompt = (
            f"ROUND 2 CROSS-EXAMINATION RESULTS:\n{round2_summary}\n\n"
            "This is the FINAL ROUND. Cast your definitive vote with your final "
            "confidence level. Your confidence weighting will affect the consensus. "
            "Be precise. Respond with a JSON object."
        )

        raw = _call_claude(system_prompt, user_prompt, temperature=temperature)
        assessment = _parse_agent_response(raw, agent_name)
        assessments.append(assessment)
        logger.info(
            "Round 3 - %s: position=%s, confidence=%d, vote=%s",
            agent_name,
            assessment["position"],
            assessment["confidence"],
            assessment["vote"],
        )

    return assessments


def tally_votes(final_assessments: list[dict]) -> dict:
    """Tally Round 3 votes with confidence weighting.

    Returns the consensus result. If no vote achieves a >66% supermajority
    of weighted confidence, the result is marked as contested.
    """
    vote_weights: dict[str, float] = {}
    total_weight = 0.0

    for assessment in final_assessments:
        vote = assessment.get("vote", "hold_steady")
        confidence = assessment.get("confidence", 1)
        weight = float(confidence)
        vote_weights[vote] = vote_weights.get(vote, 0.0) + weight
        total_weight += weight

    if total_weight == 0:
        return {
            "consensus": "hold_steady",
            "confidence_weighted_score": 0.0,
            "is_contested": True,
            "vote_breakdown": {},
            "reason": "No votes cast",
        }

    # Find the leading vote
    leading_vote = max(vote_weights, key=vote_weights.get)  # type: ignore[arg-type]
    leading_pct = vote_weights[leading_vote] / total_weight

    is_contested = leading_pct < 0.66

    # Build breakdown as percentages
    vote_breakdown = {
        vote: round(w / total_weight * 100, 1) for vote, w in vote_weights.items()
    }

    return {
        "consensus": leading_vote if not is_contested else "contested",
        "leading_vote": leading_vote,
        "confidence_weighted_score": round(leading_pct * 100, 1),
        "is_contested": is_contested,
        "vote_breakdown": vote_breakdown,
        "reason": (
            "contested -- human review required"
            if is_contested
            else f"{leading_vote} with {leading_pct:.0%} weighted confidence"
        ),
    }
