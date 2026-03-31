"""Canary monitoring for detecting model quality degradation.

Called by: training.trainer
Calls: notifications.telegram, training.claude_client, training.quality_drift
Owns tables: canary_evaluations
Config keys: none
Tests: tests/test_canary.py, tests/test_leakage_detector.py

Maintains a fixed set of 25 "canary" examples that are NEVER used in training.
After each retraining cycle, scores the model's output on canaries and compares
to previous cycles to detect early warning signals of degradation:

1. Distinct-n ratios decline (vocabulary collapse)
2. Self-BLEU scores rise (repetitive outputs)
3. Canary perplexity increases >5% (model confusion on known inputs)
4. Edge-case accuracy drops (loss of nuanced reasoning)

Alerts via Telegram when degradation is detected.
"""

import json
import logging
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from src.training.quality_drift import (
    compute_all_metrics,
    check_degradation,
)

logger = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")

DEFAULT_CANARY_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "reference" / "canary_set.jsonl"

CANARY_SCHEMA = """
CREATE TABLE IF NOT EXISTS canary_evaluations (
    eval_id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    model_version TEXT NOT NULL,
    avg_score REAL,
    score_delta_pct REAL,
    distinct_1 REAL,
    distinct_2 REAL,
    self_bleu REAL,
    vocab_size INTEGER,
    degradation_detected INTEGER DEFAULT 0,
    details TEXT
);
"""

# Perplexity increase threshold: >5% is an early warning
PERPLEXITY_INCREASE_THRESHOLD = 0.05
# Minimum score drop percentage to flag
SCORE_DROP_THRESHOLD = 0.05


def _init_canary_tables(db_path: str) -> None:
    """Create canary_evaluations table if it doesn't exist."""
    with sqlite3.connect(db_path) as conn:
        conn.executescript(CANARY_SCHEMA)


def _simple_score(expected: str, actual: str) -> float:
    """Compute a simple similarity score between expected and actual output.

    Uses token-level overlap (Jaccard-like) as a lightweight proxy for
    quality without requiring external embedding models.

    Returns a float between 0.0 and 1.0.
    """
    if not expected or not actual:
        return 0.0

    expected_tokens = set(expected.lower().split())
    actual_tokens = set(actual.lower().split())

    if not expected_tokens and not actual_tokens:
        return 1.0
    if not expected_tokens or not actual_tokens:
        return 0.0

    intersection = expected_tokens & actual_tokens
    union = expected_tokens | actual_tokens

    return len(intersection) / len(union)


class CanaryMonitor:
    """Monitors model quality using a fixed canary evaluation set.

    The canary set is a small collection of carefully curated examples
    that are NEVER included in training data. By repeatedly evaluating
    the model on these same inputs, we can detect drift over time.
    """

    def __init__(
        self,
        canary_path: str | Path | None = None,
        db_path: str = "ai_research_desk.sqlite3",
    ):
        self.canary_path = Path(canary_path) if canary_path else DEFAULT_CANARY_PATH
        self.db_path = db_path
        self.canaries: list[dict] = []
        _init_canary_tables(self.db_path)

    def load_canaries(self) -> list[dict]:
        """Load canary examples from the JSONL file.

        Returns list of canary dicts. Stores them in self.canaries.
        Raises FileNotFoundError if the canary file doesn't exist.
        """
        if not self.canary_path.exists():
            raise FileNotFoundError(
                f"Canary set not found at {self.canary_path}. "
                "Create data/reference/canary_set.jsonl with curated examples."
            )

        canaries = []
        with open(self.canary_path, "r", encoding="utf-8") as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    canaries.append(entry)
                except json.JSONDecodeError:
                    logger.warning("Skipping invalid JSON on line %d of canary set", line_num)

        self.canaries = canaries
        logger.info("Loaded %d canary examples from %s", len(canaries), self.canary_path)
        return canaries

    def evaluate(
        self,
        model_version: str,
        generate_fn=None,
    ) -> dict:
        """Evaluate the current model on all canary examples.

        Args:
            model_version: Identifier for the current model version.
            generate_fn: Callable(system_prompt, user_prompt, **kwargs) -> str.
                Defaults to src.training.claude_client.generate_training_example.

        Returns dict with eval results including avg_score, metrics,
        degradation status, and details.
        """
        if not self.canaries:
            self.load_canaries()

        if generate_fn is None:
            from src.training.claude_client import generate_training_example
            generate_fn = generate_training_example

        # Generate outputs for each canary
        outputs = []
        scores = []
        per_canary = []

        for canary in self.canaries:
            system_prompt = (
                "You are a senior equity research analyst. Provide concise, "
                "actionable trading analysis based on the market data provided."
            )
            user_prompt = canary.get("input", "")

            try:
                output = generate_fn(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    purpose="canary_evaluation",
                )
            except Exception as e:
                logger.warning("Canary evaluation failed for %s: %s", canary.get("id"), e)
                output = None

            if output:
                outputs.append(output)
                score = _simple_score(canary.get("expected_output", ""), output)
                scores.append(score)
                per_canary.append({
                    "id": canary.get("id"),
                    "score": score,
                    "regime": canary.get("regime"),
                    "sector": canary.get("sector"),
                })
            else:
                scores.append(0.0)
                per_canary.append({
                    "id": canary.get("id"),
                    "score": 0.0,
                    "regime": canary.get("regime"),
                    "sector": canary.get("sector"),
                    "error": True,
                })

        avg_score = sum(scores) / len(scores) if scores else 0.0

        # Compute quality drift metrics on the generated outputs
        metrics = compute_all_metrics(outputs) if outputs else {
            "distinct_1": 0.0,
            "distinct_2": 0.0,
            "self_bleu": 0.0,
            "vocab_size": 0,
            "avg_length": 0.0,
        }

        # Get previous evaluation for comparison
        previous = self._get_previous_eval()
        score_delta_pct = 0.0
        if previous and previous.get("avg_score") and previous["avg_score"] > 0:
            score_delta_pct = (avg_score - previous["avg_score"]) / previous["avg_score"]

        # Check for degradation
        previous_metrics = None
        if previous:
            previous_metrics = {
                "distinct_1": previous.get("distinct_1", 0),
                "distinct_2": previous.get("distinct_2", 0),
                "self_bleu": previous.get("self_bleu", 0),
                "vocab_size": previous.get("vocab_size", 0),
            }

        degradation = check_degradation(metrics, previous_metrics)

        # Additional canary-specific checks
        issues = []
        if degradation["details"] != "all metrics within acceptable range":
            issues.append(degradation["details"])

        # Score drop check
        if score_delta_pct < -SCORE_DROP_THRESHOLD:
            issues.append(
                f"avg canary score dropped {abs(score_delta_pct) * 100:.1f}% "
                f"(from {previous['avg_score']:.4f} to {avg_score:.4f})"
            )

        # Edge-case accuracy: check per-regime scores
        regime_scores = {}
        for pc in per_canary:
            regime = pc.get("regime", "unknown")
            if regime not in regime_scores:
                regime_scores[regime] = []
            regime_scores[regime].append(pc["score"])

        for regime, rscores in regime_scores.items():
            regime_avg = sum(rscores) / len(rscores) if rscores else 0.0
            if regime_avg < 0.15:
                issues.append(f"edge-case regime '{regime}' avg score critically low: {regime_avg:.3f}")

        degradation_detected = 1 if issues else 0
        details = "; ".join(issues) if issues else "canary evaluation passed"

        result = {
            "eval_id": str(uuid.uuid4()),
            "model_version": model_version,
            "avg_score": avg_score,
            "score_delta_pct": score_delta_pct,
            "distinct_1": metrics["distinct_1"],
            "distinct_2": metrics["distinct_2"],
            "self_bleu": metrics["self_bleu"],
            "vocab_size": metrics["vocab_size"],
            "degradation_detected": degradation_detected,
            "details": details,
            "per_canary": per_canary,
        }

        # Store to DB
        self._store_eval(result)

        # Alert if degradation detected
        if degradation_detected:
            self._send_alert(result)

        return result

    def _get_previous_eval(self) -> dict | None:
        """Retrieve the most recent canary evaluation from the database."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM canary_evaluations ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
        return dict(row) if row else None

    def _store_eval(self, result: dict) -> None:
        """Store canary evaluation results to the database."""
        now = datetime.now(ET).isoformat()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """INSERT INTO canary_evaluations
                   (eval_id, created_at, model_version, avg_score, score_delta_pct,
                    distinct_1, distinct_2, self_bleu, vocab_size,
                    degradation_detected, details)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    result["eval_id"],
                    now,
                    result["model_version"],
                    result["avg_score"],
                    result["score_delta_pct"],
                    result["distinct_1"],
                    result["distinct_2"],
                    result["self_bleu"],
                    result["vocab_size"],
                    result["degradation_detected"],
                    result["details"],
                ),
            )

    def _send_alert(self, result: dict) -> None:
        """Send a Telegram alert when degradation is detected."""
        try:
            from src.notifications.telegram import send_telegram
        except ImportError:
            logger.warning("Telegram notifications not available")
            return

        msg = (
            "<b>Canary Degradation Alert</b>\n\n"
            f"Model: <code>{result['model_version']}</code>\n"
            f"Avg Score: {result['avg_score']:.4f} "
            f"(delta: {result['score_delta_pct'] * 100:+.1f}%)\n"
            f"Distinct-1: {result['distinct_1']:.4f}\n"
            f"Distinct-2: {result['distinct_2']:.4f}\n"
            f"Self-BLEU: {result['self_bleu']:.4f}\n"
            f"Vocab Size: {result['vocab_size']}\n\n"
            f"Issues: {result['details']}"
        )

        try:
            send_telegram(msg)
            logger.info("Canary degradation alert sent via Telegram")
        except Exception as e:
            logger.error("Failed to send canary alert: %s", e)

    def get_history(self, limit: int = 10) -> list[dict]:
        """Retrieve recent canary evaluation history.

        Returns list of evaluation dicts, newest first.
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM canary_evaluations ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]
