"""Validate that all training examples can be parsed by the inference parser.

Usage: python scripts/validate_training_format.py
"""

import os
import re
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.config import DB_PATH


def test_parse(text: str) -> tuple:
    """Test if text can be parsed by _parse_llm_response logic."""
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
        conn = sqlite3.connect(db_path)
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
