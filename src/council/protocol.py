"""Council protocol — vote-first Modified Delphi.

Round 1: All 5 agents assess independently (always runs).
Aggregate: Confidence-weighted voting with domain weights.
Round 2: Only if <3/5 consensus. Agents see others' views. (conditional)

Research: AI_Council_Redesign_v2__Architecture_and_Implementation.md
NeurIPS 2025: majority voting > multi-agent debate for factual tasks.

ISSUE FIXES APPLIED:
- #1: Uses generate_training_example() from claude_client (not raw anthropic)
- #3: tally_votes() replaced with aggregate_votes() using new direction schema
- #4: Weekly cumulative rate limiter implemented
- #5: Value attribution limited to position_sizing_multiplier
- #8: JSON fallback parsing with find("{") / rfind("}")
- #9: Red Team prompt corrected for independent Round 1 assessment
- #10: Debug logging wraps existing client with timing capture
"""

import json
import logging
import sqlite3
import time
import uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

ET = ZoneInfo("America/New_York")

# ── Domain weights by session type ────────────────────────────────
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

# ── Decision thresholds (hardcoded per architecture decision #2) ──
# To modify: edit this dict. DO NOT move to settings.yaml.
# Rationale: these are empirical thresholds derived from research that
# should not be tweaked casually. If changing is needed, edit here —
# all thresholds are co-located in this single constant.
DECISION_THRESHOLDS = {
    "strong_bullish": 0.5,
    "lean_bullish": 0.2,
    "neutral_low": -0.2,
    "lean_bearish": -0.5,
}

# ── Rate limiters for parameter auto-application ──────────────────
RATE_LIMITS = {
    "max_daily_change_pct": 0.25,
    "max_weekly_change_pct": 0.50,
    "min_confidence_to_apply": 0.40,
    "emergency_reset_streak": 3,
}

# ── Parameter bounds (hard limits — council CANNOT exceed) ────────
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


# ── API call wrapper ──────────────────────────────────────────────
# FIX #1: Uses existing claude_client for API key, model routing, cost tracking
# FIX #10: Wraps with timing for debug log

def _call_claude(system_prompt: str, user_prompt: str) -> tuple[str | None, dict]:
    """Call Claude via the shared training client with timing.

    Uses generate_training_example() which handles:
    - API key from config
    - Model selection via purpose="council"
    - Cost logging to api_costs table

    Returns:
        (response_text, debug_info) where debug_info has latency_ms and raw text.
    """
    debug = {"latency_ms": 0, "raw": None}

    start = time.monotonic()
    try:
        from src.training.claude_client import generate_training_example
        raw = generate_training_example(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            purpose="council",
        )
        elapsed = (time.monotonic() - start) * 1000
        debug["latency_ms"] = int(elapsed)
        debug["raw"] = raw
        return raw, debug
    except Exception as e:
        elapsed = (time.monotonic() - start) * 1000
        debug["latency_ms"] = int(elapsed)
        debug["raw"] = str(e)
        logger.error("[COUNCIL] Claude API call failed: %s", e)
        return None, debug


def _normalize_claude_result(result: object) -> tuple[str | None, dict]:
    """Accept the standard tuple or simplified mocked Claude return values."""
    if isinstance(result, tuple) and len(result) == 2 and isinstance(result[1], dict):
        return result[0], result[1]
    if result is None:
        return None, {"latency_ms": 0, "raw": None}
    return str(result), {"latency_ms": 0, "raw": result}


# ── Response parsing ──────────────────────────────────────────────
# FIX #8: Keeps the existing fallback parsing (find "{" / rfind "}")

def _parse_agent_response(raw: str | None, agent_name: str) -> dict:
    """Parse structured JSON from agent response.

    Handles: clean JSON, markdown-fenced JSON, JSON embedded in prose.
    Returns default response on any parse failure (logged, never silent).
    """
    if raw is None:
        logger.warning("[COUNCIL] Empty response from %s", agent_name)
        return _default_response(agent_name, "API call returned None")

    # Strip markdown code fences
    text = raw.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        text = "\n".join(lines).strip()

    # Try direct JSON parse
    data = None
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # Fallback: find JSON object in text (existing pattern from old protocol.py)
        start = text.find("{")
        end = text.rfind("}") + 1
        if start != -1 and end > start:
            try:
                data = json.loads(text[start:end])
            except json.JSONDecodeError:
                pass

    if data is None:
        logger.warning("[COUNCIL] JSON parse failed for %s. Raw: %s", agent_name, raw[:300])
        return _default_response(agent_name, "Could not parse JSON from response")

    # Validate and normalize
    data["agent"] = agent_name

    # Direction (new schema)
    valid_directions = {"bullish", "neutral", "bearish"}
    if data.get("direction") not in valid_directions:
        # Try to map old "position" field if present
        position_map = {"offensive": "bullish", "defensive": "bearish", "neutral": "neutral"}
        old_pos = data.get("position", "neutral")
        data["direction"] = position_map.get(old_pos, "neutral")

    # Confidence: new schema uses 0.0-1.0 float
    conf = data.get("confidence", 0.5)
    if isinstance(conf, int) and conf > 1:
        # Old schema used 1-10 integer — convert
        conf = conf / 10.0
    data["confidence"] = max(0.0, min(1.0, float(conf)))

    # Parameters with defaults
    params = data.get("parameters", {})
    params.setdefault("position_sizing_multiplier", PARAMETER_DEFAULTS["position_sizing_multiplier"])
    params.setdefault("cash_reserve_target_pct", PARAMETER_DEFAULTS["cash_reserve_target_pct"])
    params.setdefault("scan_aggressiveness", PARAMETER_DEFAULTS["scan_aggressiveness"])
    data["parameters"] = params

    # Other fields with defaults
    data.setdefault("sector_tilts", {"prefer": [], "avoid": []})
    data.setdefault("key_reasoning", "")
    data.setdefault("key_risk", "")
    data.setdefault("falsifiable_prediction", None)

    # Backward compat: populate old-schema fields for _store_votes()
    # FIX #2: Map new fields to old column names
    data["position"] = {"bullish": "offensive", "neutral": "neutral", "bearish": "defensive"}.get(
        data["direction"], "neutral"
    )
    data["confidence_int"] = max(1, min(10, int(data["confidence"] * 10)))
    data["recommendation"] = data.get("key_reasoning", "")
    data["key_data_points"] = []
    data["risk_flags"] = [data["key_risk"]] if data.get("key_risk") else []
    data["vote"] = {"bullish": "increase_exposure", "neutral": "hold_steady", "bearish": "reduce_exposure"}.get(
        data["direction"], "hold_steady"
    )

    return data


def _default_response(agent_name: str, reason: str = "") -> dict:
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
        "_parse_failed": True,
        # Backward compat fields
        "position": "neutral",
        "confidence_int": 1,
        "recommendation": f"Agent unavailable: {reason}",
        "key_data_points": [],
        "risk_flags": [reason] if reason else [],
        "vote": "hold_steady",
    }


# ── Shared context ────────────────────────────────────────────────

def build_shared_context(db_path: str = "ai_research_desk.sqlite3") -> str:
    """Build shared market context for all agents."""
    from src.council.agents import _query_db

    parts = [f"Session date: {datetime.now(ET).strftime('%Y-%m-%d %H:%M ET')}"]

    try:
        recs = _query_db(
            "SELECT COUNT(*) as count, AVG(priority_score) as avg_score "
            "FROM recommendations WHERE created_at >= datetime('now', '-1 day')",
            db_path=db_path,
        )
        if recs:
            r = recs[0]
            parts.append(f"Today's scan: {r.get('count', 0)} candidates, avg score {r.get('avg_score', 0):.1f}")
    except Exception as e:
        logger.warning("[COUNCIL] Failed to query recommendations: %s", e)

    try:
        oc = _query_db("SELECT COUNT(*) as n FROM shadow_trades WHERE status = 'open'", db_path=db_path)
        if oc:
            parts.append(f"Open positions: {oc[0]['n']}")
    except Exception as e:
        logger.warning("[COUNCIL] Failed to query open trades: %s", e)

    try:
        from src.evaluation.hshs_live import compute_hshs
        hshs = compute_hshs(db_path)
        dims = hshs.get("dimensions", {})
        parts.append(
            f"System Health (HSHS): {hshs.get('hshs', 0):.1f}/100 "
            f"(P={dims.get('performance', 0):.0f} M={dims.get('model_quality', 0):.0f} "
            f"D={dims.get('data_asset', 0):.0f} F={dims.get('flywheel_velocity', 0):.0f} "
            f"C={dims.get('defensibility', 0):.0f})"
        )
    except Exception:
        pass

    # Traffic Light
    try:
        import sqlite3 as _sql
        with _sql.connect(db_path) as _conn:
            tl = _conn.execute("SELECT current_regime, last_total_score FROM traffic_light_state WHERE id = 1").fetchone()
            if tl:
                parts.append(f"Traffic Light: {tl[0]} (score {tl[1]}/6)")
    except Exception:
        pass

    # VIX
    try:
        vix = _query_db(
            "SELECT vix FROM vix_term_structure ORDER BY collected_date DESC LIMIT 1",
            db_path=db_path,
        )
        if vix:
            parts.append(f"VIX: {vix[0]['vix']:.1f}")
    except Exception:
        pass

    return "\n".join(parts) if parts else "No shared context available."


# ── Protocol rounds ───────────────────────────────────────────────

def run_round_1(
    shared_context: str,
    session_id: str | None = None,
    db_path: str = "ai_research_desk.sqlite3",
    custom_question: str | None = None,
) -> list[dict]:
    """Round 1: All 5 agents assess independently. Always runs.

    Args:
        shared_context: Market context shared across agents.
        session_id: For debug log storage. Optional.
        db_path: Database path.
        custom_question: For strategic sessions — overrides default prompt.

    Returns:
        List of 5 parsed agent assessments.
    """
    from src.council.agents import AGENT_PROMPTS, AGENT_DATA_FUNCTIONS

    assessments = []

    for agent_name, system_prompt in AGENT_PROMPTS.items():
        # Gather agent-specific data (returns formatted string)
        data_fn = AGENT_DATA_FUNCTIONS.get(agent_name)
        agent_data = data_fn(db_path) if data_fn else "No specialist data available."

        # Build user prompt
        if custom_question:
            user_prompt = (
                f"STRATEGIC QUESTION FROM FOUNDER:\n{custom_question}\n\n"
                f"SHARED MARKET CONTEXT:\n{shared_context}\n\n"
                f"YOUR SPECIALIST DATA:\n{agent_data}\n\n"
                "Analyze this question through your specific analytical framework.\n"
                "Direction: bullish = proceed/yes, neutral = wait/unclear, bearish = don't/no.\n"
                "Produce your assessment as a JSON object. No preamble, no markdown fences."
            )
        else:
            user_prompt = (
                f"SHARED MARKET CONTEXT:\n{shared_context}\n\n"
                f"YOUR SPECIALIST DATA:\n{agent_data}\n\n"
                "Produce your assessment as a JSON object. No preamble, no markdown fences."
            )

        # Call API with timing
        raw, debug = _normalize_claude_result(_call_claude(system_prompt, user_prompt))
        assessment = _parse_agent_response(raw, agent_name)
        assessments.append(assessment)

        logger.info(
            "Round 1 — %s: direction=%s confidence=%.2f",
            agent_name, assessment["direction"], assessment["confidence"],
        )

        # Store debug log if session_id provided
        if session_id:
            _store_debug_log(
                session_id, agent_name, 1, system_prompt, user_prompt,
                debug, assessment, db_path,
            )

    return assessments


def run_round_2(
    round1_assessments: list[dict],
    shared_context: str = "",
    session_id: str | None = None,
    db_path: str = "ai_research_desk.sqlite3",
) -> tuple[list[dict], list[str]]:
    """Round 2: Agents see others' views. Conditional — only when <3/5 consensus.

    Returns:
        (updated_assessments, sycophancy_flags)
    """
    from src.council.agents import AGENT_PROMPTS

    # Summarize Round 1 for all agents
    r1_lines = ["ROUND 1 RESULTS (other agents' assessments):"]
    for a in round1_assessments:
        r1_lines.append(
            f"  {a.get('agent', '?')}: {a.get('direction', '?')} "
            f"(confidence {a.get('confidence', 0):.2f}) — "
            f"{a.get('key_reasoning', '')[:120]}"
        )
    r1_summary = "\n".join(r1_lines)

    original_directions = {a["agent"]: a.get("direction", "neutral") for a in round1_assessments}

    updated = []
    sycophancy_flags = []

    for a in round1_assessments:
        agent_name = a["agent"]
        system_prompt = AGENT_PROMPTS.get(agent_name, "")

        user_prompt = (
            f"SHARED CONTEXT:\n{shared_context}\n\n"
            f"{r1_summary}\n\n"
            f"You previously assessed: {a.get('direction', 'neutral')} "
            f"with confidence {a.get('confidence', 0):.2f}.\n"
            f"Your reasoning: {a.get('key_reasoning', '')}\n\n"
            "After seeing others' views, you may update your assessment or maintain it.\n"
            "If you change direction, explain why. Respond with a JSON object."
        )

        raw, debug = _normalize_claude_result(_call_claude(system_prompt, user_prompt))
        parsed = _parse_agent_response(raw, agent_name)
        updated.append(parsed)

        # Sycophancy detection
        if parsed.get("direction") != original_directions.get(agent_name):
            sycophancy_flags.append(agent_name)
            logger.info(
                "[COUNCIL] SYCOPHANCY FLAG: %s flipped %s → %s",
                agent_name, original_directions[agent_name], parsed["direction"],
            )

        if session_id:
            _store_debug_log(
                session_id, agent_name, 2, system_prompt, user_prompt,
                debug, parsed, db_path,
            )

    return updated, sycophancy_flags


# ── Vote aggregation ──────────────────────────────────────────────
# FIX #3: Replaces old tally_votes() — uses new direction/confidence schema

def aggregate_votes(
    assessments: list[dict],
    session_type: str = "daily",
) -> dict:
    """Confidence-weighted aggregated vote.

    Returns dict with aggregated_score, direction, vote_distribution,
    consensus_reached, round2_needed, and parameter_recommendations.
    """
    weights = DOMAIN_WEIGHTS.get(session_type, DOMAIN_WEIGHTS["daily"])

    numerator = 0.0
    denominator = 0.0
    vote_dist = {"bullish": 0, "neutral": 0, "bearish": 0}
    confidences = []

    # Parameter aggregation (confidence-weighted average)
    param_num = {"position_sizing_multiplier": 0.0, "cash_reserve_target_pct": 0.0}
    param_den = 0.0
    scan_votes = {"conservative": 0.0, "normal": 0.0, "aggressive": 0.0}

    for a in assessments:
        agent = a.get("agent", "unknown")
        direction = a.get("direction", "neutral")
        confidence = a.get("confidence", 0.5)
        domain_weight = weights.get(agent, 1.0)

        vote_val = DIRECTION_MAP.get(direction, 0.0)
        w = confidence * domain_weight

        numerator += vote_val * w
        denominator += w
        vote_dist[direction] = vote_dist.get(direction, 0) + 1
        confidences.append(confidence)

        # Aggregate parameters
        params = a.get("parameters", {})
        for pname in param_num:
            pval = params.get(pname, PARAMETER_DEFAULTS.get(pname, 1.0))
            param_num[pname] += float(pval) * w
        param_den += w

        # Scan aggressiveness (weighted vote)
        scan_agg = params.get("scan_aggressiveness", "normal")
        if scan_agg in scan_votes:
            scan_votes[scan_agg] += w

    score = numerator / denominator if denominator > 0 else 0.0
    confidence_avg = sum(confidences) / len(confidences) if confidences else 0.0

    # Consensus
    max_votes = max(vote_dist.values()) if vote_dist else 0
    total_agents = len(assessments)
    consensus_reached = max_votes >= 3
    consensus_type = f"{max_votes}-{total_agents - max_votes}" if total_agents > 0 else "0-0"

    # Direction from score
    if score > DECISION_THRESHOLDS["lean_bullish"]:
        direction = "bullish"
    elif score < DECISION_THRESHOLDS["neutral_low"]:
        direction = "bearish"
    else:
        direction = "neutral"

    # Aggregated parameters
    param_recs = {}
    if param_den > 0:
        for pname in param_num:
            param_recs[pname] = round(param_num[pname] / param_den, 3)
    param_recs["scan_aggressiveness"] = max(scan_votes, key=scan_votes.get) if scan_votes else "normal"

    return {
        "aggregated_score": round(score, 4),
        "direction": direction,
        "confidence_avg": round(confidence_avg, 3),
        "vote_distribution": vote_dist,
        "consensus_reached": consensus_reached,
        "consensus_type": consensus_type,
        "round2_needed": not consensus_reached,
        "parameter_recommendations": param_recs,
    }


# Keep backward-compat alias
def tally_votes(final_assessments: list[dict]) -> dict:
    """Backward-compat wrapper → aggregate_votes with daily weights."""
    result = aggregate_votes(final_assessments, "daily")
    # Map to old format for callers expecting it
    return {
        "consensus": result["direction"] if result["consensus_reached"] else "contested",
        "leading_vote": {"bullish": "increase_exposure", "neutral": "hold_steady", "bearish": "reduce_exposure"}.get(
            result["direction"], "hold_steady"
        ),
        "confidence_weighted_score": round(abs(result["aggregated_score"]) * 100, 1),
        "is_contested": not result["consensus_reached"],
        "vote_breakdown": result["vote_distribution"],
        "reason": f"{result['consensus_type']} consensus" if result["consensus_reached"] else "contested",
        # New fields (available to callers that know about them)
        "_v2": result,
    }


# ── Rate limiters ─────────────────────────────────────────────────
# FIX #4: Implements weekly cumulative check

def apply_rate_limiters(
    recommended: dict,
    current: dict,
    db_path: str = "ai_research_desk.sqlite3",
) -> dict:
    """Apply rate limiters to council parameter recommendations.

    Checks both daily (±25%) and weekly (±50% cumulative from baseline) limits.
    """
    applied = {}
    rate_limited = False

    for param, rec_val in recommended.items():
        if param == "scan_aggressiveness":
            applied[param] = rec_val
            continue

        curr_val = float(current.get(param, PARAMETER_DEFAULTS.get(param, 1.0)))
        rec_val = float(rec_val)

        # Hard bounds
        bounds = PARAMETER_BOUNDS.get(param)
        if bounds:
            rec_val = max(bounds[0], min(bounds[1], rec_val))

        # Daily rate limit: ±25%
        max_daily = max(abs(curr_val) * RATE_LIMITS["max_daily_change_pct"], 0.05)
        if abs(rec_val - curr_val) > max_daily:
            rec_val = curr_val + max_daily if rec_val > curr_val else curr_val - max_daily
            rate_limited = True
            logger.info("[COUNCIL] Daily rate limit on %s: clipped to %.3f", param, rec_val)

        # Weekly cumulative limit: ±50% from baseline
        try:
            week_ago = (datetime.now(ET) - timedelta(days=7)).isoformat()
            baseline = PARAMETER_DEFAULTS.get(param, 1.0)
            with sqlite3.connect(db_path) as conn:
                # Get the parameter value from 7 days ago
                row = conn.execute(
                    "SELECT applied_value FROM council_parameter_log "
                    "WHERE parameter_name = ? AND attribution_start <= ? "
                    "ORDER BY attribution_start DESC LIMIT 1",
                    (param, week_ago),
                ).fetchone()
                if row:
                    baseline = float(row[0])

            max_weekly = abs(baseline) * RATE_LIMITS["max_weekly_change_pct"]
            if abs(rec_val - baseline) > max_weekly:
                rec_val = baseline + max_weekly if rec_val > baseline else baseline - max_weekly
                rate_limited = True
                logger.info("[COUNCIL] Weekly rate limit on %s: clipped to %.3f (baseline=%.3f)", param, rec_val, baseline)
        except Exception as e:
            logger.debug("[COUNCIL] Weekly rate limit check failed: %s", e)

        # Re-apply hard bounds after rate limiting
        if bounds:
            rec_val = max(bounds[0], min(bounds[1], rec_val))

        applied[param] = round(rec_val, 3)

    applied["_rate_limited"] = rate_limited
    return applied


# ── Debug log storage ─────────────────────────────────────────────

def _store_debug_log(
    session_id: str,
    agent_name: str,
    round_num: int,
    system_prompt: str,
    user_prompt: str,
    debug: dict,
    assessment: dict,
    db_path: str = "ai_research_desk.sqlite3",
) -> None:
    """Store debug log entry for full replay capability."""
    try:
        import hashlib
        with sqlite3.connect(db_path) as conn:
            conn.execute(
                "INSERT OR IGNORE INTO council_debug_log "
                "(debug_id, session_id, agent_name, round, system_prompt_hash, "
                "user_message, raw_response, parsed_successfully, parse_error, "
                "latency_ms, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    str(uuid.uuid4()),
                    session_id,
                    agent_name,
                    round_num,
                    hashlib.md5(system_prompt.encode()).hexdigest()[:12],
                    user_prompt[:5000],  # Truncate to prevent DB bloat
                    debug.get("raw", "")[:5000],
                    0 if assessment.get("_parse_failed") else 1,
                    assessment.get("key_reasoning", "")[:500] if assessment.get("_parse_failed") else None,
                    debug.get("latency_ms", 0),
                    datetime.now(ET).isoformat(),
                ),
            )
    except Exception as e:
        logger.debug("[COUNCIL] Debug log insert failed: %s", e)
