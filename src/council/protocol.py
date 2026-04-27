"""Council protocol orchestration for vote-first sessions.

Called by: council/engine.py
Calls: council/agents.py, council/aggregation.py, council/constants.py, council/context.py, council/parsing.py, council/rate_limiter.py, training/claude_client.py
Owns tables: none
Config keys: none
Tests: tests/test_council.py
"""

import logging
import sqlite3
import time
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

from src.config import DB_PATH
from src.utils.db import connect_db
from src.council.aggregation import aggregate_votes, tally_votes
from src.council.constants import (
    PARAMETER_DEFAULTS,
    RATE_LIMITS,
)
from src.council.context import build_shared_context
from src.council.parsing import (
    default_response as _default_response,
    parse_agent_response as _parse_agent_response,
)
from src.council.rate_limiter import apply_rate_limiters

logger = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")


def _call_claude(system_prompt: str, user_prompt: str) -> tuple[str | None, dict]:
    """Call Claude via the shared training client with timing metadata.

    #117 — Retries with exponential backoff on Anthropic rate limit errors.
    """
    debug = {"latency_ms": 0, "raw": None}
    start = time.monotonic()

    max_retries = 3
    for attempt in range(max_retries):
        try:
            from src.training.claude_client import generate_training_example

            raw = generate_training_example(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                purpose="council",
            )
            debug["latency_ms"] = int((time.monotonic() - start) * 1000)
            debug["raw"] = raw
            return raw, debug
        except Exception as exc:
            exc_name = type(exc).__name__
            # #117 — Catch rate limit errors (RateLimitError or HTTP 429)
            if "RateLimitError" in exc_name or "429" in str(exc):
                wait = (attempt + 1) * 10  # 10s, 20s, 30s
                logger.warning(
                    "[COUNCIL] Rate limited, retrying in %ds (attempt %d/%d)",
                    wait, attempt + 1, max_retries,
                )
                time.sleep(wait)
                continue
            debug["latency_ms"] = int((time.monotonic() - start) * 1000)
            debug["raw"] = str(exc)
            logger.error("[COUNCIL] Claude API call failed: %s", exc)
            return None, debug

    # All retries exhausted
    debug["latency_ms"] = int((time.monotonic() - start) * 1000)
    debug["raw"] = "Rate limit retries exhausted"
    logger.error("[COUNCIL] Rate limit retries exhausted after %d attempts", max_retries)
    return None, debug


def _normalize_claude_result(result: object) -> tuple[str | None, dict]:
    """Accept the standard tuple or simplified mocked Claude return values."""
    if isinstance(result, tuple) and len(result) == 2 and isinstance(result[1], dict):
        return result[0], result[1]
    if result is None:
        return None, {"latency_ms": 0, "raw": None}
    return str(result), {"latency_ms": 0, "raw": result}


def _build_round_1_prompt(shared_context: str, agent_data: str, custom_question: str | None) -> str:
    """Construct the user prompt for a Round 1 council call."""
    if custom_question:
        return (
            f"STRATEGIC QUESTION FROM FOUNDER:\n{custom_question}\n\n"
            f"SHARED MARKET CONTEXT:\n{shared_context}\n\n"
            f"YOUR SPECIALIST DATA:\n{agent_data}\n\n"
            "Analyze this question through your specific analytical framework.\n"
            "Direction: bullish = proceed/yes, neutral = wait/unclear, bearish = don't/no.\n"
            "Produce your assessment as a JSON object. No preamble, no markdown fences."
        )
    return (
        f"SHARED MARKET CONTEXT:\n{shared_context}\n\n"
        f"YOUR SPECIALIST DATA:\n{agent_data}\n\n"
        "Produce your assessment as a JSON object. No preamble, no markdown fences."
    )


def run_round_1(
    shared_context: str,
    session_id: str | None = None,
    db_path: str = DB_PATH,
    custom_question: str | None = None,
) -> list[dict]:
    """Round 1: all agents assess independently."""
    from src.council.agents import AGENT_DATA_FUNCTIONS, AGENT_PROMPTS

    assessments = []
    for agent_name, system_prompt in AGENT_PROMPTS.items():
        data_fn = AGENT_DATA_FUNCTIONS.get(agent_name)
        agent_data = data_fn(db_path) if data_fn else "No specialist data available."
        user_prompt = _build_round_1_prompt(shared_context, agent_data, custom_question)
        raw, debug = _normalize_claude_result(_call_claude(system_prompt, user_prompt))
        assessment = _parse_agent_response(raw, agent_name)
        assessments.append(assessment)

        logger.info(
            "Round 1 — %s: direction=%s confidence=%.2f",
            agent_name,
            assessment["direction"],
            assessment["confidence"],
        )

        if session_id:
            _store_debug_log(
                session_id,
                agent_name,
                1,
                system_prompt,
                user_prompt,
                debug,
                assessment,
                db_path,
            )

    return assessments


def run_round_2(
    round1_assessments: list[dict],
    shared_context: str = "",
    session_id: str | None = None,
    db_path: str = DB_PATH,
) -> tuple[list[dict], list[str]]:
    """Round 2: agents see the Round 1 summary and may revise their view."""
    from src.council.agents import AGENT_PROMPTS

    summary_lines = ["ROUND 1 RESULTS (other agents' assessments):"]
    for assessment in round1_assessments:
        summary_lines.append(
            f"  {assessment.get('agent', '?')}: {assessment.get('direction', '?')} "
            f"(confidence {assessment.get('confidence', 0):.2f}) — "
            f"{assessment.get('key_reasoning', '')[:120]}"
        )
    round_1_summary = "\n".join(summary_lines)
    original_directions = {
        assessment["agent"]: assessment.get("direction", "neutral")
        for assessment in round1_assessments
    }

    updated = []
    sycophancy_flags = []

    for assessment in round1_assessments:
        agent_name = assessment["agent"]
        system_prompt = AGENT_PROMPTS.get(agent_name, "")
        user_prompt = (
            f"SHARED CONTEXT:\n{shared_context}\n\n"
            f"{round_1_summary}\n\n"
            f"You previously assessed: {assessment.get('direction', 'neutral')} "
            f"with confidence {assessment.get('confidence', 0):.2f}.\n"
            f"Your reasoning: {assessment.get('key_reasoning', '')}\n\n"
            "After seeing others' views, you may update your assessment or maintain it.\n"
            "If you change direction, explain why. Respond with a JSON object."
        )

        raw, debug = _normalize_claude_result(_call_claude(system_prompt, user_prompt))
        parsed = _parse_agent_response(raw, agent_name)
        updated.append(parsed)

        if parsed.get("direction") != original_directions.get(agent_name):
            sycophancy_flags.append(agent_name)
            logger.info(
                "[COUNCIL] SYCOPHANCY FLAG: %s flipped %s -> %s",
                agent_name,
                original_directions[agent_name],
                parsed["direction"],
            )

        if session_id:
            _store_debug_log(
                session_id,
                agent_name,
                2,
                system_prompt,
                user_prompt,
                debug,
                parsed,
                db_path,
            )

    return updated, sycophancy_flags


def _store_debug_log(
    session_id: str,
    agent_name: str,
    round_num: int,
    system_prompt: str,
    user_prompt: str,
    debug: dict,
    assessment: dict,
    db_path: str = DB_PATH,
) -> None:
    """Store a council debug log entry for replay and incident review."""
    try:
        import hashlib

        with connect_db(db_path) as conn:
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
                    user_prompt[:5000],
                    str(debug.get("raw", ""))[:5000],
                    0 if assessment.get("_parse_failed") else 1,
                    assessment.get("key_reasoning", "")[:500] if assessment.get("_parse_failed") else None,
                    debug.get("latency_ms", 0),
                    datetime.now(ET).isoformat(),
                ),
            )
    except Exception as exc:
        logger.debug("[COUNCIL] Debug log insert failed: %s", exc)
