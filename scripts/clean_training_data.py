"""Batch-clean all training examples to standardized XML-only format.

When to run:
    One-time migration, or after importing a new batch of training examples
    from ChatGPT or other external sources. The inference parser expects
    clean XML, so training data must match that format exactly.

What it reads:
    - training_examples.output_text column from SQLite

What it writes (only with --apply):
    - Updates training_examples.output_text in-place (destructive — back up first)

Prerequisites:
    - Database at src/config.DB_PATH with populated training_examples table

Fixes 4 problems:
1. Markdown headers before XML tags
2. Bold markers inside analysis/metadata
3. Conviction format inconsistency (decimals, /10 suffix, bold)
4. Trailing content after </metadata>

Usage:
    python scripts/clean_training_data.py             # dry-run (prints diff counts)
    python scripts/clean_training_data.py --apply     # commit the UPDATE
"""

import argparse
import os
import re
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.config import DB_PATH
from src.utils.db import connect_db


def clean_output(text: str) -> str:
    """Standardize training output to clean XML-only format."""
    if not text:
        return text

    # 1. Remove any text before first <why_now> tag.
    # ChatGPT often prepends "Here is the analysis:" or similar preamble.
    wn_match = re.search(r'<why_now>', text, re.IGNORECASE)
    if wn_match:
        text = text[wn_match.start():]

    # 2. Remove any text after </metadata>
    meta_end_match = re.search(r'</metadata>', text, re.IGNORECASE)
    if meta_end_match:
        text = text[:meta_end_match.end()]

    # 3. Strip ALL bold markers everywhere
    text = re.sub(r'\*\*([^*]+)\*\*', r'\1', text)

    # 4. Fix conviction: extract number, round to int, strip /10.
    # ChatGPT outputs "7.5/10" or "**8**" but our parser expects bare "Conviction: 7".
    meta_match = re.search(r'<metadata>(.*?)</metadata>', text, re.DOTALL | re.IGNORECASE)
    if meta_match:
        meta = meta_match.group(1)
        conv_match = re.search(r'Conviction:\s*(\d+\.?\d*)', meta)
        if conv_match:
            conv_val = max(1, min(10, round(float(conv_match.group(1)))))
            meta = re.sub(r'Conviction:\s*\d+\.?\d*(?:/\d+)?', f'Conviction: {conv_val}', meta)
        text = text[:meta_match.start(1) - len('<metadata>')] + '<metadata>' + meta + '</metadata>'

    # 5. Strip markdown code fences if wrapping everything
    text = re.sub(r'^```(?:xml)?\s*\n?', '', text.strip(), flags=re.MULTILINE)
    text = re.sub(r'\n?```\s*$', '', text.strip(), flags=re.MULTILINE)

    return text.strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument(
        "--apply", action="store_true",
        help="Actually commit the UPDATE. Without this flag, runs in "
             "dry-run mode and only reports what would change.",
    )
    args = parser.parse_args()
    dry_run = not args.apply

    db_path = DB_PATH
    try:
        conn = connect_db(db_path)
    except Exception as e:
        print(f"Cannot connect to {db_path}: {e}")
        sys.exit(1)

    rows = conn.execute('SELECT example_id, output_text FROM training_examples').fetchall()
    if not rows:
        print("No training examples found.")
        return

    cleaned = 0
    for eid, output in rows:
        if not output:
            continue
        new_output = clean_output(output)
        if new_output != output:
            if not dry_run:
                conn.execute(
                    'UPDATE training_examples SET output_text = ? WHERE example_id = ?',
                    (new_output, eid),
                )
            cleaned += 1

    if dry_run:
        conn.close()
        print(f"[DRY-RUN] Would clean {cleaned}/{len(rows)} examples. "
              f"Re-run with --apply to commit changes.")
    else:
        conn.commit()
        conn.close()
        print(f"Cleaned {cleaned}/{len(rows)} examples")


if __name__ == "__main__":
    main()
