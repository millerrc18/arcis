"""AST guardrail test: src/notifications/policy.py must be pure — no I/O imports
or logging calls. (T10 Sprint 5 Wave D D1)
"""

import ast
import pathlib


_BANNED_IMPORTS = {
    "os", "pathlib", "requests", "urllib", "socket",
    "logging", "sqlite3", "psycopg2", "datetime",
}

_BANNED_LOG_ATTRS = {"warning", "info", "error", "debug", "critical"}


def _walk_policy_ast():
    src = pathlib.Path(__file__).parent.parent.parent / "src" / "notifications" / "policy.py"
    return ast.parse(src.read_text(encoding="utf-8"))


def test_policy_has_no_banned_imports():
    tree = _walk_policy_ast()
    violations = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                top_level = alias.name.split(".")[0]
                if top_level in _BANNED_IMPORTS:
                    violations.append(f"Import: {alias.name} (line {node.lineno})")
        elif isinstance(node, ast.ImportFrom):
            module = (node.module or "").split(".")[0]
            if module in _BANNED_IMPORTS:
                violations.append(f"ImportFrom: {node.module} (line {node.lineno})")
    assert not violations, (
        f"src/notifications/policy.py has banned imports (no I/O allowed):\n"
        + "\n".join(violations)
    )


def test_policy_has_no_logging_calls():
    tree = _walk_policy_ast()
    violations = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Attribute) and func.attr in _BANNED_LOG_ATTRS:
                violations.append(f"Logging call .{func.attr}() at line {node.lineno}")
    assert not violations, (
        f"src/notifications/policy.py has logging calls (pure function must have none):\n"
        + "\n".join(violations)
    )
