"""Assign curriculum stages to training examples based on enrichment data.

When to run:
    One-time migration or after bulk-importing new training examples.
    The fine-tuning pipeline uses curriculum_stage to order examples
    from simple (structure-only) to complex (full-context) during training.

What it reads:
    - training_examples table (input_text column for enrichment detection)

What it writes:
    - Updates training_examples.curriculum_stage column in-place

Prerequisites:
    - Database at src/config.DB_PATH with training_examples table populated

Stages:
- structure: Technical-only data (no enrichment)
- evidence: 1-2 enrichment sources (fundamentals, insider, macro, news)
- decision: 3+ enrichment sources (full-context analysis)

Usage: python scripts/assign_curriculum_stages.py
"""

import sqlite3
import sys

from src.config import DB_PATH
from src.utils.db import connect_db


def detect_enrichment(text: str) -> dict:
    """Detect which enrichment sources are present in the input text."""
    if not text:
        return {"fund": False, "insider": False, "macro": False, "news": False}

    def has_data(section_marker: str) -> bool:
        """Check if a section marker is present AND has real data after it.
        The 60-char lookahead catches 'Not available' / 'N/A' placeholders
        that enrichment inserts when an API returned no data."""
        if section_marker not in text:
            return False
        idx = text.index(section_marker)
        after = text[idx:idx + len(section_marker) + 60]
        return 'Not available' not in after and 'N/A' not in after

    return {
        "fund": has_data('FUNDAMENTAL') or has_data('fundamental_snapshot'),
        "insider": has_data('INSIDER') or has_data('insider_activity'),
        "macro": has_data('MACRO') or has_data('macro_context'),
        "news": has_data('NEWS') or has_data('recent_news'),
    }


def main():
    db_path = DB_PATH
    try:
        conn = connect_db(db_path)
    except Exception as e:
        print(f"Cannot connect to {db_path}: {e}")
        sys.exit(1)

    rows = conn.execute(
        'SELECT example_id, input_text FROM training_examples'
    ).fetchall()

    if not rows:
        print("No training examples found.")
        return

    updated = 0
    for eid, input_text in rows:
        enrichment = detect_enrichment(input_text or "")
        count = sum(enrichment.values())

        if count >= 3:
            stage = 'decision'
        elif count >= 1:
            stage = 'evidence'
        else:
            stage = 'structure'

        conn.execute(
            'UPDATE training_examples SET curriculum_stage = ? WHERE example_id = ?',
            (stage, eid)
        )
        updated += 1

    conn.commit()

    print(f"Updated {updated} examples. Distribution:")
    for stage in ['structure', 'evidence', 'decision']:
        count = conn.execute(
            'SELECT COUNT(*) FROM training_examples WHERE curriculum_stage = ?',
            (stage,)
        ).fetchone()[0]
        print(f"  {stage}: {count}")

    conn.close()


if __name__ == "__main__":
    main()
