"""DPO preference pair generation and export pipeline."""

import json
import logging
import sqlite3
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

from src.training.versioning import init_training_tables

logger = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")


def _ensure_preference_table(db_path: str) -> None:
    """Create preference_pairs table if it doesn't exist."""
    with sqlite3.connect(db_path) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS preference_pairs (
                pair_id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                ticker TEXT,
                scan_date TEXT,
                input_text TEXT NOT NULL,
                chosen_output TEXT NOT NULL,
                rejected_output TEXT NOT NULL,
                chosen_source TEXT,
                rejected_source TEXT,
                quality_delta REAL,
                notes TEXT
            )
        """)
        conn.commit()


def generate_preference_pairs(n_pairs: int = 100,
                               db_path: str = "ai_research_desk.sqlite3") -> int:
    """Generate preference pairs for DPO training.

    For each pair:
    1. Take a training example's input
    2. Generate 4-6 alternatives using current fine-tuned model via Ollama (temperature 0.9)
    3. Score all alternatives using LLM-as-judge (Claude)
    4. Pair highest-scored with lowest-scored
    5. Store if score delta >= 1.0

    Returns count of pairs generated.
    """
    init_training_tables(db_path)
    _ensure_preference_table(db_path)

    from src.llm.client import generate as ollama_generate
    from src.training.quality_filter import score_training_example

    # Get training examples to use as inputs
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT example_id, ticker, input_text, output_text, instruction "
            "FROM training_examples "
            "WHERE quality_score_auto IS NOT NULL AND quality_score_auto >= 3.5 "
            "ORDER BY RANDOM() LIMIT ?",
            (n_pairs * 2,),  # Fetch extra since some may fail
        ).fetchall()

    if not rows:
        logger.info("[DPO] No scored training examples available")
        return 0

    created = 0
    now = datetime.now(ET).isoformat()

    for row in rows:
        if created >= n_pairs:
            break

        input_text = row["input_text"]
        instruction = row["instruction"]

        # Generate alternatives via Ollama
        alternatives = []
        for _ in range(4):
            alt = ollama_generate(input_text, instruction)
            if alt:
                alternatives.append(alt)

        if len(alternatives) < 2:
            continue

        # Score all alternatives
        scored = []
        for alt in alternatives:
            scores = score_training_example(input_text, alt)
            if scores and "overall" in scores:
                scored.append({"output": alt, "score": scores["overall"]})

        if len(scored) < 2:
            continue

        # Sort by score
        scored.sort(key=lambda x: x["score"])
        worst = scored[0]
        best = scored[-1]
        delta = best["score"] - worst["score"]

        if delta < 1.0:
            continue

        # Store the pair
        pair_id = str(uuid.uuid4())
        with sqlite3.connect(db_path) as conn:
            conn.execute(
                "INSERT INTO preference_pairs "
                "(pair_id, created_at, ticker, input_text, chosen_output, rejected_output, "
                "chosen_source, rejected_source, quality_delta, notes) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (pair_id, now, row["ticker"], input_text,
                 best["output"], worst["output"],
                 "ollama_generated", "ollama_generated",
                 round(delta, 2), f"Best: {best['score']:.1f}, Worst: {worst['score']:.1f}"),
            )
            conn.commit()
        created += 1

    logger.info("[DPO] Generated %d preference pairs", created)
    return created


def export_preference_pairs(output_dir: str = "training_data",
                            db_path: str = "ai_research_desk.sqlite3") -> int:
    """Export preference pairs to JSONL for DPO training.

    Format per line:
    {"prompt": [messages], "chosen": "better output", "rejected": "worse output"}

    Returns count exported.
    """
    _ensure_preference_table(db_path)

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT input_text, chosen_output, rejected_output FROM preference_pairs"
        ).fetchall()

    if not rows:
        return 0

    from pathlib import Path
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    output_path = str(Path(output_dir) / "preference_pairs.jsonl")

    with open(output_path, "w") as f:
        for row in rows:
            f.write(json.dumps({
                "prompt": [
                    {"role": "system", "content": "You are a senior equity research analyst."},
                    {"role": "user", "content": row["input_text"]},
                ],
                "chosen": row["chosen_output"],
                "rejected": row["rejected_output"],
            }) + "\n")

    logger.info("[DPO] Exported %d preference pairs to %s", len(rows), output_path)
    return len(rows)


def get_preference_pair_count(db_path: str = "ai_research_desk.sqlite3") -> int:
    """Return the count of preference pairs in the database."""
    _ensure_preference_table(db_path)
    with sqlite3.connect(db_path) as conn:
        row = conn.execute("SELECT COUNT(*) FROM preference_pairs").fetchone()
    return row[0] if row else 0
