"""Verify AGENTS.md headline counts against the live repo.

Checks source/test counts, collected tests, CLI commands, API routes, DB tables,
and research document totals so governance docs stay synchronized with code.
"""

from __future__ import annotations

import argparse
import ast
import re
import sqlite3
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AGENTS_PATH = ROOT / "AGENTS.md"


def count_python_files() -> int:
    return len(
        [
            path
            for path in (ROOT / "src").rglob("*.py")
            if "__pycache__" not in path.parts and not path.name.endswith("_backup.py")
        ]
    )


def count_test_files() -> int:
    return len(list((ROOT / "tests").glob("*.py")))


def count_tests() -> int:
    command = [str(ROOT / ".venv" / "Scripts" / "python.exe"), "-m", "pytest", "tests/", "--collect-only", "-q"]
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=True)
    lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    summary = next((line for line in reversed(lines) if re.search(r"\b\d+ tests collected\b", line)), "")
    match = re.search(r"(\d+) tests collected", summary)
    if not match:
        raise RuntimeError("Could not determine collected test count from pytest output.")
    return int(match.group(1))


def count_cli_commands() -> int:
    main_path = ROOT / "src" / "main.py"
    tree = ast.parse(main_path.read_text(encoding="utf-8"))
    count = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr == "add_parser" and node.args and isinstance(node.args[0], ast.Constant):
                count += 1
    return count


def count_api_routes() -> int:
    route_files = [ROOT / "src" / "api" / "cloud_app.py", *(ROOT / "src" / "api" / "routes").glob("*.py")]
    pattern = re.compile(r"@(app|router)\.(get|post|put|delete|patch|websocket)\(")
    total = 0
    for path in route_files:
        if path.name == "__init__.py":
            continue
        total += len(pattern.findall(path.read_text(encoding="utf-8")))
    return total


def count_db_tables(db_path: Path) -> int:
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            """
            SELECT COUNT(*)
            FROM sqlite_master
            WHERE type = 'table'
              AND name NOT LIKE 'sqlite_%'
            """
        ).fetchone()
    return int(row[0])


def count_research_docs() -> int:
    return len(list((ROOT / "docs" / "research").glob("*.md")))


def parse_agents_counts() -> dict[str, int]:
    text = AGENTS_PATH.read_text(encoding="utf-8")
    match = re.search(
        r"Counts verified .*?: (?P<python>\d+) Python files, (?P<tests>\d+) test files, "
        r"(?P<collected>\d+)\+? tests, (?P<cli>\d+) CLI commands, "
        r"(?P<routes>\d+)\+? API routes, (?P<tables>\d+) DB tables .*?, "
        r"(?P<research>\d+)\+? research docs\.",
        text,
        re.DOTALL,
    )
    if not match:
        raise RuntimeError("Could not parse counts header in AGENTS.md.")
    return {key: int(value) for key, value in match.groupdict().items()}


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify AGENTS.md repo counts.")
    parser.add_argument("--db", default="ai_research_desk.sqlite3", help="SQLite DB path for table counting.")
    args = parser.parse_args()

    actual = {
        "python": count_python_files(),
        "tests": count_test_files(),
        "collected": count_tests(),
        "cli": count_cli_commands(),
        "routes": count_api_routes(),
        "tables": count_db_tables(ROOT / args.db),
        "research": count_research_docs(),
    }
    documented = parse_agents_counts()

    print("AGENTS.md count verification")
    print("---------------------------")
    failures = []
    labels = {
        "python": "Python files",
        "tests": "Test files",
        "collected": "Collected tests",
        "cli": "CLI commands",
        "routes": "API routes",
        "tables": "DB tables",
        "research": "Research docs",
    }
    for key, label in labels.items():
        status = "OK" if actual[key] == documented[key] else "MISMATCH"
        print(f"{label:16} documented={documented[key]:>4} actual={actual[key]:>4} [{status}]")
        if actual[key] != documented[key]:
            failures.append(key)

    if failures:
        raise SystemExit(1)

    print("All AGENTS.md counts match.")


if __name__ == "__main__":
    main()
