"""Visual progress tracker for manual backfill generation.

Usage:
    python scripts/backfill_progress.py

Reads training_data/progress.json and prints a visual progress bar for
each regime. Optionally queries the database for imported/scored counts.
"""

import json
import logging
import os
import sqlite3
import sys
from datetime import datetime

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PROGRESS_PATH = "training_data/progress.json"
RESULTS_DIR = "training_data/results"
BAR_WIDTH = 12


def count_results(results_dir: str) -> dict[str, int]:
    """Count result files per regime by cross-referencing with outcomes."""
    outcomes_path = os.path.join(os.path.dirname(results_dir), "outcomes", "outcomes.json")
    if not os.path.exists(outcomes_path):
        return {}

    with open(outcomes_path) as f:
        outcomes = json.load(f)

    # Build reverse map: filename prefix -> regime
    id_to_regime = {}
    for pid, entry in outcomes.items():
        id_to_regime[pid] = entry.get("regime", "unknown")

    counts: dict[str, int] = {}
    if os.path.isdir(results_dir):
        for filename in os.listdir(results_dir):
            if not filename.endswith(".md"):
                continue
            # Extract prompt_id from filename
            parts = filename.split("_", 1)
            if parts:
                pid = parts[0].lstrip("0") or "0"
                regime = id_to_regime.get(pid, id_to_regime.get(parts[0], "unknown"))
                counts[regime] = counts.get(regime, 0) + 1

    return counts


def progress_bar(current: int, target: int, width: int = BAR_WIDTH) -> str:
    """Generate a visual progress bar."""
    if target <= 0:
        return " " * width
    ratio = min(current / target, 1.0)
    filled = int(width * ratio)
    return "\u2588" * filled + "\u2591" * (width - filled)


def main():
    if not os.path.exists(PROGRESS_PATH):
        logger.info("No progress file found at %s", PROGRESS_PATH)
        logger.info("Run: python scripts/export_backfill_prompts.py first")
        return

    with open(PROGRESS_PATH) as f:
        progress = json.load(f)

    # Count result files
    result_counts = count_results(RESULTS_DIR)

    # Try to get DB counts
    db_counts: dict[str, int] = {}
    try:
        from src.config import DB_PATH
        if os.path.exists(DB_PATH):
            with sqlite3.connect(DB_PATH) as conn:
                rows = conn.execute(
                    "SELECT regime, COUNT(*) FROM training_examples "
                    "WHERE source LIKE 'manual_%' GROUP BY regime"
                ).fetchall()
                db_counts = {r[0]: r[1] for r in rows}
    except Exception:
        pass

    today = datetime.now().strftime("%Y-%m-%d")
    logger.info("BACKFILL PROGRESS \u2014 %s", today)
    logger.info("\u2550" * 55)

    total_target = 0
    total_completed = 0
    total_imported = 0
    total_rejected = 0
    focus_regime = None
    focus_pct = 100.0

    for regime, info in progress.items():
        target = info["target"]
        exported = info["exported"]
        completed = result_counts.get(regime, 0)
        imported = db_counts.get(regime, info.get("imported", 0))

        pct = (completed / target * 100) if target > 0 else 0
        bar = progress_bar(completed, target)

        label = regime.replace("_", " ").title()
        logger.info("%-12s %s %d/%d (%d%%)", label + ":", bar, completed, target, int(pct))

        total_target += target
        total_completed += completed
        total_imported += imported

        if pct < focus_pct:
            focus_pct = pct
            focus_regime = regime

    logger.info("")
    logger.info("Total: %d/%d (%d%%)  |  Imported: %d",
                total_completed, total_target,
                int(total_completed / total_target * 100) if total_target > 0 else 0,
                total_imported)

    if focus_regime and focus_pct < 100:
        label = focus_regime.replace("_", " ").title()
        logger.info("\n\u2190 FOCUS: %s needs the most attention (%d%%)", label, int(focus_pct))


if __name__ == "__main__":
    main()
