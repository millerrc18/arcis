"""Validate that all training examples can be parsed by the inference parser.

When to run:
    After running fix_training_format.py or clean_training_data.py, or
    after importing new training examples. Target: 100% parse rate.
    Any failure means the fine-tuned model may produce unparseable output.

What it reads:
    - training_examples.output_text from SQLite

What it writes:
    - Nothing — stdout-only validation report

Prerequisites:
    - Database at src/config.DB_PATH with training_examples populated

Usage: python scripts/validate_training_format.py
"""

import os
import re
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.config import DB_PATH
from src.utils.db import connect_db


def test_parse(text: str) -> tuple:
    """Test if text can be parsed by _parse_llm_response logic.
    Mirrors the regex patterns in src/llm/packet_writer.py's parser."""
    if not text:
        return None, False, False
    wn = re.search(r'<why_now>(.*?)</why_now>', text, re.DOTALL | re.IGNORECASE)
    an = re.search(r'<analysis>(.*?)</analysis>', text, re.DOTALL | re.IGNORECASE)
    md = re.search(r'<metadata>(.*?)</metadata>', text, re.DOTALL | re.IGNORECASE)
    conviction = None
    if md:
        cm = re.search(r'Conviction:\s*(\d+)', md.group(1))
        if cm:
            conviction = int(cm.group(1))
    return conviction, bool(wn), bool(an)


def main():
    db_path = DB_PATH
    try:
        conn = connect_db(db_path)
    except Exception as e:
        print(f"Cannot connect to {db_path}: {e}")
        sys.exit(1)

    rows = conn.execute(
        'SELECT example_id, ticker, source, output_text FROM training_examples'
    ).fetchall()

    if not rows:
        print("No training examples found.")
        return

    failures = []
    for eid, ticker, source, output in rows:
        conv, has_wn, has_an = test_parse(output)
        if not has_wn or not has_an or conv is None:
            failures.append((eid, ticker, source, has_wn, has_an, conv))

    total = len(rows)
    passed = total - len(failures)
    print(f"Parse test: {passed}/{total} pass ({passed/total*100:.1f}%)")

    if failures:
        print(f"\n{len(failures)} failures:")
        for f in failures[:20]:
            print(f"  FAIL: {f[1]} ({f[2]}) — why_now={f[3]}, analysis={f[4]}, conviction={f[5]}")
        if len(failures) > 20:
            print(f"  ... and {len(failures) - 20} more")
    else:
        print("All examples parse successfully!")

    conn.close()


if __name__ == "__main__":
    main()
