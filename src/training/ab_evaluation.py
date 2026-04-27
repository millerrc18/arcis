"""A/B shadow model evaluation with promotion logic.

Called by: cli.commands
Calls: config, llm.client, llm.prompts, training.claude_client, training.versioning
Owns tables: none
Config keys: llm
Tests: tests/test_ab_evaluation.py, tests/test_leakage_detector.py
"""

import logging
import sqlite3
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

from src.config import DB_PATH, load_config
from src.utils.db import connect_db
from src.training.versioning import init_training_tables

logger = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")


def run_shadow_evaluation(new_model: str, current_model: str,
                          input_text: str, ticker: str = "",
                          recommendation_id: str = "",
                          db_path: str = DB_PATH) -> dict:
    """Generate commentary from both models for the same input.

    Both models see identical input. Neither knows the other exists.
    Outputs are stored for later comparison.
    """
    import hashlib
    from src.llm.client import generate
    from src.llm.prompts import PACKET_SYSTEM_PROMPT
    from src.training.claude_client import generate_training_example

    input_hash = hashlib.md5(input_text.encode()).hexdigest()[:12]

    # Generate from current model
    current_output = generate(input_text, PACKET_SYSTEM_PROMPT)

    # Generate from new model — temporarily override the model
    config = load_config()
    original_model = config.get("llm", {}).get("model", "qwen3:8b")

    # Call Ollama directly with the new model name
    try:
        import requests
        base_url = config.get("llm", {}).get("base_url", "http://localhost:11434")
        resp = requests.post(
            f"{base_url}/api/generate",
            json={
                "model": new_model,
                "prompt": input_text,
                "system": PACKET_SYSTEM_PROMPT,
                "stream": False,
            },
            timeout=120,
        )
        new_output = resp.json().get("response") if resp.ok else None
    except Exception as e:
        logger.warning("A/B evaluation: new model generation failed: %s", e)
        new_output = None

    if not current_output or not new_output:
        return {"input_hash": input_hash, "error": "One or both models failed to generate"}

    # Score both outputs using Claude as judge
    JUDGE_PROMPT = (
        "Rate this trade analysis on a 1-5 scale for overall quality. "
        "Consider: thesis clarity, evidence quality, risk assessment, technical accuracy, actionability. "
        'Return ONLY a number 1-5.'
    )

    current_score = _score_output(JUDGE_PROMPT, current_output)
    new_score = _score_output(JUDGE_PROMPT, new_output)

    winner = "tie"
    score_delta = 0.0
    if current_score is not None and new_score is not None:
        score_delta = new_score - current_score
        if new_score > current_score:
            winner = "new"
        elif current_score > new_score:
            winner = "current"

    # Store result
    evaluation_id = str(uuid.uuid4())
    created_at = datetime.now(ET).isoformat()

    init_training_tables(db_path)
    with connect_db(db_path) as conn:
        conn.execute(
            """INSERT INTO model_evaluations
               (evaluation_id, created_at, recommendation_id, ticker, input_text,
                current_model, current_output, current_score,
                new_model, new_output, new_score, winner, score_delta)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (evaluation_id, created_at, recommendation_id, ticker, input_text,
             current_model, current_output, current_score,
             new_model, new_output, new_score, winner, score_delta),
        )
        conn.commit()

    result = {
        "input_hash": input_hash,
        "current_model": current_model,
        "current_score": current_score,
        "new_model": new_model,
        "new_score": new_score,
        "winner": winner,
        "score_delta": score_delta,
    }

    logger.info("[A/B] %s vs %s for %s: winner=%s delta=%.1f",
                current_model, new_model, ticker, winner, score_delta)
    return result


def _score_output(judge_prompt: str, output: str) -> float | None:
    """Score an output using Claude as judge."""
    from src.training.claude_client import generate_training_example
    try:
        result = generate_training_example(judge_prompt, f"ANALYSIS:\n{output}", purpose="ab_evaluation")
        if result:
            # Extract number from response
            import re
            match = re.search(r'[1-5]', result.strip())
            if match:
                return float(match.group())
    except Exception as e:
        logger.debug("AB evaluation scoring failed: %s", e)
    return None


def check_promotion_ready(new_model: str, min_evaluations: int = 20,
                          min_win_rate: float = 0.60,
                          db_path: str = DB_PATH) -> dict:
    """Check if a model in evaluation status should be promoted.

    Returns dict with ready status, evaluations count, win rate, and recommendation.
    """
    init_training_tables(db_path)

    with connect_db(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM model_evaluations WHERE new_model = ? ORDER BY created_at DESC",
            (new_model,),
        ).fetchall()

    evaluations = [dict(r) for r in rows]
    total = len(evaluations)

    if total < min_evaluations:
        return {
            "ready": False,
            "evaluations": total,
            "win_rate": 0,
            "recommendation": "needs_more_data",
            "needed": min_evaluations - total,
        }

    new_wins = sum(1 for e in evaluations if e.get("winner") == "new")
    win_rate = new_wins / total if total > 0 else 0

    avg_delta = sum(e.get("score_delta", 0) or 0 for e in evaluations) / total if total else 0

    if win_rate >= min_win_rate:
        recommendation = "promote"
    else:
        recommendation = "reject"

    return {
        "ready": win_rate >= min_win_rate,
        "evaluations": total,
        "win_rate": round(win_rate, 3),
        "avg_score_delta": round(avg_delta, 2),
        "recommendation": recommendation,
    }


def get_evaluation_status(db_path: str = DB_PATH) -> dict | None:
    """Get the current A/B evaluation progress."""
    from src.training.versioning import get_evaluation_model

    eval_model = get_evaluation_model(db_path)
    if not eval_model:
        return None

    status = check_promotion_ready(eval_model["version_name"], db_path=db_path)
    status["model_name"] = eval_model["version_name"]
    status["model_id"] = eval_model["version_id"]
    return status
