"""Import manually-generated backfill results into the training database.

Usage:
    python scripts/import_backfill_results.py --model claude_opus
    python scripts/import_backfill_results.py --results-dir training_data/results --outcomes training_data/outcomes/outcomes.json --model claude_opus

Reads completed results from training_data/results/, pairs with outcomes
from training_data/outcomes/outcomes.json, validates XML format, and
inserts into training_examples table.
"""

import argparse
import json
import logging
import os
import re
import sqlite3
import sys
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.config import DB_PATH
from src.training.ingestion_gate import validate_training_example
from src.training.versioning import init_training_tables

ET = ZoneInfo("America/New_York")

REQUIRED_XML_TAGS = ["<why_now>", "</why_now>", "<analysis>", "</analysis>", "<metadata>", "</metadata>"]

# Pattern to extract prompt_id from filename: 001_AAPL_2021-03-15.md
FILENAME_PATTERN = re.compile(r"^(\d+)_([A-Z]+)_(\d{4}-\d{2}-\d{2})\.md$")


def extract_xml_content(text: str) -> str | None:
    """Extract the XML-tagged content from a result file.

    Handles minor format differences: extra whitespace, markdown fences, etc.
    Returns the cleaned text containing the three XML sections, or None.
    """
    # Strip markdown code fences if present
    text = re.sub(r"```xml\s*", "", text)
    text = re.sub(r"```\s*$", "", text, flags=re.MULTILINE)

    # Check all required tags present
    for tag in REQUIRED_XML_TAGS:
        if tag not in text:
            return None

    # Extract from first <why_now> to last </metadata>
    start = text.index("<why_now>")
    end = text.index("</metadata>") + len("</metadata>")
    return text[start:end].strip()


def load_imported_tracker(tracker_path: str) -> set[str]:
    """Load the set of already-imported prompt IDs."""
    if os.path.exists(tracker_path):
        with open(tracker_path) as f:
            return set(json.load(f))
    return set()


def save_imported_tracker(tracker_path: str, imported: set[str]):
    """Save the set of imported prompt IDs."""
    with open(tracker_path, "w") as f:
        json.dump(sorted(imported), f, indent=2)


def find_prompt_file(prompts_dir: str, filename: str) -> str | None:
    """Find the matching prompt file across all regime subdirectories."""
    if not os.path.isdir(prompts_dir):
        return None
    for regime_dir in os.listdir(prompts_dir):
        candidate = os.path.join(prompts_dir, regime_dir, filename)
        if os.path.isfile(candidate):
            return candidate
    return None


def extract_input_text_from_prompt(prompt_path: str) -> tuple[str, str]:
    """Extract the feature data and system prompt from an exported prompt file.

    Prompt files have this structure:
        # Setup ... header
        ## System Prompt
        <system prompt text>
        ## Feature Data
        <feature data text>
        ---
        SAVE THE RESPONSE AS: ...

    Returns:
        (system_prompt, feature_data) — the instruction and input_text
        for the training example.
    """
    with open(prompt_path) as f:
        content = f.read()

    # Extract system prompt: between "## System Prompt" and "## Feature Data"
    system_prompt = ""
    sys_marker = "## System Prompt"
    feat_marker = "## Feature Data"
    if sys_marker in content and feat_marker in content:
        sys_start = content.index(sys_marker) + len(sys_marker)
        sys_end = content.index(feat_marker)
        system_prompt = content[sys_start:sys_end].strip()

    # Extract feature data: between "## Feature Data" and the trailing "---"
    input_text = ""
    if feat_marker in content:
        feat_start = content.index(feat_marker) + len(feat_marker)
        # Find the trailing separator
        rest = content[feat_start:]
        separator = "\n---\n"
        if separator in rest:
            input_text = rest[:rest.index(separator)].strip()
        else:
            input_text = rest.strip()

    return system_prompt, input_text


def main():
    parser = argparse.ArgumentParser(description="Import backfill results into training DB")
    parser.add_argument("--results-dir", default="training_data/results", help="Directory with result .md files")
    parser.add_argument("--prompts-dir", default="training_data/prompts", help="Directory with exported prompt files")
    parser.add_argument("--outcomes", default="training_data/outcomes/outcomes.json", help="Sealed outcomes file")
    parser.add_argument("--model", required=True, help="Model that generated results (e.g. claude_opus, chatgpt)")
    parser.add_argument("--db-path", default=DB_PATH, help="Database path")
    args = parser.parse_args()

    if not os.path.isdir(args.results_dir):
        logger.info("Results directory %s does not exist. Nothing to import.", args.results_dir)
        return

    # Load outcomes
    if os.path.exists(args.outcomes):
        with open(args.outcomes) as f:
            outcomes = json.load(f)
    else:
        logger.warning("Outcomes file %s not found. PASS examples only.", args.outcomes)
        outcomes = {}

    # Load import tracker for idempotency
    tracker_path = os.path.join(os.path.dirname(args.results_dir), "imported.json")
    already_imported = load_imported_tracker(tracker_path)

    init_training_tables(args.db_path)

    # Scan results directory
    result_files = sorted(f for f in os.listdir(args.results_dir) if f.endswith(".md"))
    logger.info("=== IMPORT BACKFILL RESULTS ===")
    logger.info("Found %d result files in %s", len(result_files), args.results_dir)
    logger.info("Model: manual_%s", args.model)

    imported_count = 0
    skipped_count = 0
    rejected_count = 0
    source = f"manual_{args.model}"

    for filename in result_files:
        match = FILENAME_PATTERN.match(filename)
        if not match:
            logger.warning("  SKIP (bad filename): %s", filename)
            skipped_count += 1
            continue

        prompt_id = match.group(1)
        ticker = match.group(2)
        scan_date = match.group(3)

        # Idempotency: skip already imported
        if prompt_id in already_imported:
            skipped_count += 1
            continue

        filepath = os.path.join(args.results_dir, filename)
        with open(filepath) as f:
            raw_text = f.read()

        # Extract XML content
        xml_content = extract_xml_content(raw_text)
        if xml_content is None:
            logger.warning("  SKIP (missing XML tags): %s", filename)
            rejected_count += 1
            continue

        # Validate via ingestion gate
        is_valid, rejection_reason = validate_training_example(xml_content, args.db_path)
        if not is_valid:
            logger.warning("  REJECT (%s): %s", rejection_reason, filename)
            rejected_count += 1
            continue

        # Look up outcome from sealed file
        outcome_entry = outcomes.get(prompt_id, {})
        outcome_data = outcome_entry.get("outcome")
        regime = outcome_entry.get("regime", "unknown")
        example_type = outcome_entry.get("type", "trade")
        outcome_type = "pass" if example_type == "pass" else (
            outcome_data.get("outcome_quality") if outcome_data else "unknown"
        )

        # Read matching prompt file to extract feature data (input_text) and instruction
        prompt_file = find_prompt_file(args.prompts_dir, filename)
        if prompt_file:
            instruction, input_text = extract_input_text_from_prompt(prompt_file)
        else:
            logger.warning("  WARN (no prompt file found): %s — input_text will be empty", filename)
            instruction = f"manual_backfill_{example_type}"
            input_text = ""

        # Build feature snapshot from outcome metadata
        feature_snapshot = json.dumps({
            "scan_date": scan_date,
            "prompt_id": int(prompt_id),
            "regime": regime,
            "type": example_type,
        })
        trade_outcome = json.dumps(outcome_data) if outcome_data else None

        # Insert into training_examples
        example_id = str(uuid.uuid4())
        created_at = datetime.now(ET).isoformat()

        with sqlite3.connect(args.db_path) as conn:
            conn.execute(
                """INSERT INTO training_examples
                   (example_id, created_at, source, ticker, recommendation_id,
                    feature_snapshot, trade_outcome, instruction, input_text,
                    output_text, outcome_type, regime)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (example_id, created_at, source, ticker, None,
                 feature_snapshot, trade_outcome,
                 instruction, input_text,
                 xml_content, outcome_type, regime),
            )
            conn.commit()

        already_imported.add(prompt_id)
        imported_count += 1

    # Save tracker
    save_imported_tracker(tracker_path, already_imported)

    # Update progress.json if it exists
    progress_path = os.path.join(os.path.dirname(args.results_dir), "progress.json")
    if os.path.exists(progress_path):
        with open(progress_path) as f:
            progress = json.load(f)
        # Count imported per regime
        for pid in already_imported:
            entry = outcomes.get(pid, {})
            regime = entry.get("regime", "unknown")
            if regime in progress:
                pass  # Will recount below
        # Recount from outcomes
        for regime in progress:
            progress[regime]["imported"] = sum(
                1 for pid in already_imported
                if outcomes.get(pid, {}).get("regime") == regime
            )
        with open(progress_path, "w") as f:
            json.dump(progress, f, indent=2)

    # Summary
    logger.info("\n=== IMPORT COMPLETE ===")
    logger.info("Imported:  %d", imported_count)
    logger.info("Skipped:   %d (already imported or bad filename)", skipped_count)
    logger.info("Rejected:  %d (validation failed)", rejected_count)
    logger.info("Total in tracker: %d", len(already_imported))


if __name__ == "__main__":
    main()
