"""Between-scan inference scoring using the already-loaded Ollama model.

Called by: scheduler.watch
Calls: llm.client, training.quality_filter, training.versioning
Owns tables: none
Config keys: none
Tests: tests/test_scorer.py

The key insight: the Ollama inference model is already loaded in VRAM for scans.
Scoring training examples between scans requires zero VRAM overhead — just API calls
to the same running Ollama instance. We stop 3 minutes before each scan to guarantee
zero interference.

Throughput: ~3 examples/minute × 14 min/window × 10 windows/day = ~420 examples/day
"""

import json
import logging
import re
import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo

from src.config import DB_PATH
from src.training.quality_filter import QUALITY_JUDGE_PROMPT
from src.training.versioning import init_training_tables

logger = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")


class GuardedScorer:
    """Scores training examples between market scans with automatic guard band cutoff.

    Uses the local Ollama model (already loaded in VRAM for scans) to score
    training examples, supplementing Claude API scores with local evaluation.
    """

    def __init__(
        self,
        guard_minutes: int = 3,
        scan_minutes: list[int] | None = None,
        skip_windows: list[int] | None = None,
        max_per_window: int = 50,
        db_path: str = DB_PATH,
    ):
        self.guard_minutes = guard_minutes
        self.scan_minutes = scan_minutes or [0, 30]
        self.skip_windows = skip_windows or [0, 12]
        self.max_per_window = max_per_window
        self.db_path = db_path

    def minutes_until_next_scan(self) -> float:
        """Returns minutes until the next :00 or :30 scan."""
        now = datetime.now(ET)
        minute = now.minute
        if minute < 30:
            return 30 - minute
        return 60 - minute

    def is_scoring_window(self) -> bool:
        """Returns True if we're in a valid between-scan window."""
        now = datetime.now(ET)
        hour = now.hour
        minute = now.minute

        # Only during market hours
        if hour < 9 or (hour == 9 and minute < 30) or hour >= 16:
            return False

        # Must be past scan + CPU task time (minute 8-27 or 38-57)
        in_window = (8 <= minute <= 27) or (38 <= minute <= 57)
        if not in_window:
            return False

        # Skip first window of day (9:30 scan — let system stabilize)
        if hour == 9 and minute < 38:
            return False

        # Skip last 30 min before close (3:30-4:00)
        if hour == 15 and minute >= 30:
            return False

        return True

    def _get_unscored_examples(self) -> list[dict]:
        """Query training examples that haven't been auto-scored."""
        init_training_tables(self.db_path)

        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT example_id, input_text, output_text, source "
                "FROM training_examples WHERE quality_score_auto IS NULL "
                "ORDER BY created_at DESC"
            ).fetchall()
        return [dict(r) for r in rows]

    def _score_with_ollama(self, input_text: str, output_text: str) -> dict | None:
        """Score a training example using the local Ollama model.

        Uses the same process-first rubric as Claude scoring but via the
        already-loaded Ollama inference model.
        """
        from src.llm.client import generate

        prompt = (
            f"Rate this trade commentary for training data quality.\n\n"
            f"INPUT DATA:\n{input_text[:1500]}\n\n"
            f"COMMENTARY TO SCORE:\n{output_text[:2000]}"
        )

        response = generate(prompt, QUALITY_JUDGE_PROMPT, temperature=0.3)
        if response is None:
            return None

        try:
            clean = response.strip()
            if clean.startswith("```"):
                clean = clean.removeprefix("```json").removeprefix("```")
            if clean.endswith("```"):
                clean = clean.removesuffix("```")
            clean = clean.strip()

            try:
                scores = json.loads(clean)
            except json.JSONDecodeError:
                json_match = re.search(r'\{[^}]+\}', clean, re.DOTALL)
                if json_match:
                    scores = json.loads(json_match.group())
                else:
                    return None

            # Compute weighted overall
            dims = {
                "thesis_clarity": 0.25,
                "evidence_grounding": 0.20,
                "risk_identification": 0.20,
                "calibration": 0.15,
                "structure": 0.10,
                "actionability": 0.10,
            }
            weighted = sum(scores.get(d, 3) * w for d, w in dims.items())
            scores["weighted_overall"] = round(weighted, 1)

            if weighted >= 4.0:
                scores["process_quality"] = "excellent"
            elif weighted >= 3.0:
                scores["process_quality"] = "good"
            elif weighted >= 2.0:
                scores["process_quality"] = "adequate"
            else:
                scores["process_quality"] = "poor"

            return scores

        except (json.JSONDecodeError, ValueError, AttributeError):
            logger.warning("[SCORER] Failed to parse Ollama judge response")
            return None

    def _save_score(self, example_id: str, score: float) -> None:
        """Update quality_score_auto for a training example."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE training_examples SET quality_score_auto = ? "
                "WHERE example_id = ?",
                (score, example_id),
            )
            conn.commit()

    def score_batch(self) -> dict:
        """Score unscored training examples until guard band or backlog empty.

        Returns:
            {"scored": count, "remaining": backlog_count,
             "stopped_reason": "guard_band" | "backlog_empty" | "max_reached"}
        """
        unscored = self._get_unscored_examples()
        if not unscored:
            return {"scored": 0, "remaining": 0, "stopped_reason": "backlog_empty"}

        scored = 0
        for example in unscored:
            # Check guard band before each example
            remaining_min = self.minutes_until_next_scan()
            if remaining_min <= self.guard_minutes:
                logger.info(
                    "[SCORER] Guard band reached (%.1f min to scan), stopping",
                    remaining_min,
                )
                return {
                    "scored": scored,
                    "remaining": len(unscored) - scored,
                    "stopped_reason": "guard_band",
                }

            if scored >= self.max_per_window:
                return {
                    "scored": scored,
                    "remaining": len(unscored) - scored,
                    "stopped_reason": "max_reached",
                }

            scores = self._score_with_ollama(
                example["input_text"], example["output_text"]
            )
            if scores and "weighted_overall" in scores:
                overall = scores["weighted_overall"]
                self._save_score(example["example_id"], overall)
                scored += 1
                logger.info(
                    "[SCORER] Scored example %s: %.1f/5.0 (%.0fmin remaining)",
                    example["example_id"][:12],
                    overall,
                    remaining_min,
                )

        return {
            "scored": scored,
            "remaining": 0,
            "stopped_reason": "backlog_empty",
        }
