"""Verify AGENTS.md counts match code reality."""
import subprocess
import re
import sys
import os


def count_files(pattern, exclude=None):
    """Count files matching a find pattern."""
    cmd = f"find {pattern}"
    if exclude:
        cmd += f" {exclude}"
    cmd += " | wc -l"
    try:
        return int(subprocess.check_output(cmd, shell=True, stderr=subprocess.DEVNULL).strip())
    except Exception:
        return 0


def count_py_files():
    """Count Python source files (excluding __pycache__ and backups)."""
    return count_files(
        "src -name '*.py'",
        "! -path '*__pycache__*' ! -name '*backup*'"
    )


def count_test_files():
    """Count test files."""
    return count_files("tests -name '*.py'", "! -path '*__pycache__*'")


def count_db_tables():
    """Count tables in the SQLite database."""
    db = "ai_research_desk.sqlite3"
    if not os.path.exists(db):
        return 0
    import sqlite3
    conn = sqlite3.connect(db)
    tables = conn.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    ).fetchone()[0]
    conn.close()
    return tables


def count_cli_commands():
    """Count CLI commands from click groups."""
    try:
        result = subprocess.check_output(
            "grep -r '@cli\\.' src/cli/ --include='*.py' -h | grep -c '@cli\\.'",
            shell=True, stderr=subprocess.DEVNULL
        )
        return int(result.strip())
    except Exception:
        # Fallback: count from AGENTS.md CLI section
        return 0


def count_research_docs():
    """Count research documents."""
    doc_count = 0
    for d in ["docs", "research"]:
        if os.path.isdir(d):
            doc_count += count_files(f"{d} -name '*.md'")
    return doc_count


def parse_agents_md():
    """Parse counts from AGENTS.md line 1."""
    with open("AGENTS.md") as f:
        line1 = f.readline()

    counts = {}
    # Extract numbers with labels
    py_match = re.search(r"(\d+)\s+Python\s+files?", line1)
    test_match = re.search(r"(\d+)\s+test\s+files?", line1)
    db_match = re.search(r"(\d+)\s+DB\s+tables?", line1)
    doc_match = re.search(r"(\d+)\+?\s+research\s+docs?", line1)

    if py_match:
        counts["python_files"] = int(py_match.group(1))
    if test_match:
        counts["test_files"] = int(test_match.group(1))
    if db_match:
        counts["db_tables"] = int(db_match.group(1))
    if doc_match:
        counts["research_docs"] = int(doc_match.group(1))

    return counts


def main():
    actual = {
        "python_files": count_py_files(),
        "test_files": count_test_files(),
        "db_tables": count_db_tables(),
        "research_docs": count_research_docs(),
    }

    claimed = parse_agents_md()

    mismatches = []
    for key in actual:
        a = actual[key]
        c = claimed.get(key, "?")
        status = "OK" if a == c else "MISMATCH"
        if status == "MISMATCH":
            mismatches.append(key)
        print(f"  {key}: actual={a}, claimed={c}  [{status}]")

    if mismatches:
        print(f"\nMISMATCHES: {', '.join(mismatches)}")
        print("Update AGENTS.md line 1 to match reality.")
        sys.exit(1)
    else:
        print("\nAll counts match.")
        sys.exit(0)


if __name__ == "__main__":
    main()
