"""Assign curriculum stages to training examples based on enrichment data.

Stages:
- structure: Technical-only data (no enrichment)
- evidence: 1-2 enrichment sources (fundamentals, insider, macro, news)
- decision: 3+ enrichment sources (full-context analysis)

Usage: python scripts/assign_curriculum_stages.py
"""

import sqlite3
import sys


def detect_enrichment(text: str) -> dict:
    """Detect which enrichment sources are present in the input text."""
    if not text:
        return {"fund": False, "insider": False, "macro": False, "news": False}

    def has_data(section_marker: str) -> bool:
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
    db_path = "ai_research_desk.sqlite3"
    try:
        conn = sqlite3.connect(db_path)
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
