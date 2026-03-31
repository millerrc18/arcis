"""Repository structure enforcement — prevents drift.

Called by: none (test suite)
Calls: none
Owns tables: none
Config keys: none
Tests: self
"""
import ast
import json
import re
import warnings
from pathlib import Path

KNOWN = json.loads(Path("config/known_violations.json").read_text(encoding="utf-8"))


def test_no_file_over_400_lines():
    for p in Path("src").rglob("*.py"):
        if p.name == "__init__.py":
            continue
        lines = len(p.read_text(encoding="utf-8").splitlines())
        if lines > 400:
            if str(p).replace("\\", "/") in KNOWN.get("oversized_files", []):
                warnings.warn(f"GRANDFATHERED: {p} ({lines} lines)")
            else:
                assert False, f"NEW VIOLATION: {p} is {lines} lines (max 400)"


def test_no_function_over_60_lines():
    for p in Path("src").rglob("*.py"):
        if p.name == "__init__.py":
            continue
        try:
            tree = ast.parse(p.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                length = node.end_lineno - node.lineno
                if length > 60:
                    key = f"{str(p).replace(chr(92), '/')}:{node.name}"
                    if key in KNOWN.get("oversized_functions", []):
                        warnings.warn(f"GRANDFATHERED: {key} ({length} lines)")
                    else:
                        assert False, f"NEW VIOLATION: {key} is {length} lines (max 60)"


def test_all_modules_have_standard_docstring():
    required = ["Called by:", "Calls:", "Owns tables:", "Config keys:", "Tests:"]
    for p in Path("src").rglob("*.py"):
        if p.name == "__init__.py":
            continue
        try:
            tree = ast.parse(p.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        has = (
            tree.body
            and isinstance(tree.body[0], ast.Expr)
            and isinstance(tree.body[0].value, ast.Constant)
            and isinstance(tree.body[0].value.value, str)
        )
        if not has or not all(f in tree.body[0].value.value for f in required):
            key = str(p).replace("\\", "/")
            if key in KNOWN.get("missing_docstring_headers", []):
                warnings.warn(f"GRANDFATHERED: {p} missing standard docstring")
            else:
                missing = [
                    f
                    for f in required
                    if not has or f not in tree.body[0].value.value
                ]
                assert False, f"NEW VIOLATION: {p} missing: {missing}"


def test_every_new_table_in_render_migrate():
    migrate = Path("scripts/render_migrate.py").read_text(encoding="utf-8").lower()
    for p in Path("src").rglob("*.py"):
        for line in p.read_text(encoding="utf-8").splitlines():
            m = re.search(
                r"CREATE TABLE IF NOT EXISTS (\w+)", line, re.IGNORECASE
            )
            if m:
                table = m.group(1).lower()
                if table not in migrate:
                    if table in KNOWN.get("missing_migrate_tables", []):
                        warnings.warn(f"GRANDFATHERED: table '{table}'")
                    else:
                        assert (
                            False
                        ), f"NEW VIOLATION: table '{table}' in {p} not in render_migrate.py"
