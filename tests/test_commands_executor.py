"""Regression tests for src/commands/executor.py.

Covers:
- #481: beautifulsoup4 and psutil must stay in requirements.txt
- #501: every COMMAND_HANDLERS entry must have resolvable imports
- #503: execute_command must distinguish ImportError (handler_not_available)
        from generic runtime failures (command_execution_error)

See tests/test_cli_shadow_close.py for #502 coverage.
"""
from __future__ import annotations

import ast
import importlib
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent


# ── #481: dependency guardrail ────────────────────────────────────────

def test_critical_runtime_dependencies_in_requirements():
    """beautifulsoup4 and psutil are production deps; test_all_src_modules_importable
    relies on them. Regression guard for #481."""
    req = (REPO_ROOT / "requirements.txt").read_text()
    assert "beautifulsoup4" in req, "beautifulsoup4 missing from requirements.txt (#481)"
    assert "psutil" in req, "psutil missing from requirements.txt (#481)"


# ── #501: all handler imports resolve ─────────────────────────────────

def _collect_handler_imports(executor_path: Path) -> dict[str, list[tuple[str, str]]]:
    """Walk executor.py AST and return {handler_name: [(module, attr), ...]}."""
    tree = ast.parse(executor_path.read_text())
    out: dict[str, list[tuple[str, str]]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name.startswith("_handle_"):
            imports: list[tuple[str, str]] = []
            for stmt in ast.walk(node):
                if isinstance(stmt, ast.ImportFrom) and stmt.module:
                    for alias in stmt.names:
                        imports.append((stmt.module, alias.name))
            out[node.name] = imports
    return out


def test_every_handler_import_resolves():
    """Every `from X import Y` inside a _handle_* function must resolve to a real
    attribute. Regression guard for #501 (8 handlers referenced non-existent
    modules/functions before this fix)."""
    executor_path = REPO_ROOT / "src" / "commands" / "executor.py"
    failures: list[str] = []
    for handler, imports in _collect_handler_imports(executor_path).items():
        for module, attr in imports:
            try:
                mod = importlib.import_module(module)
            except ImportError as exc:
                failures.append(f"{handler}: cannot import module {module}: {exc}")
                continue
            if not hasattr(mod, attr):
                failures.append(f"{handler}: {module} has no attribute '{attr}'")
    assert not failures, "Broken handler imports:\n  " + "\n  ".join(failures)


def test_command_handlers_dict_only_has_live_entries():
    """COMMAND_HANDLERS must not register handlers whose imports are broken.
    Guards against re-introducing dead entries like collect-training, train-pipeline,
    or close-position (#501)."""
    from src.commands import executor

    # The 3 dead handlers removed in this fix MUST NOT reappear
    dead = {"collect-training", "train-pipeline", "close-position"}
    live = set(executor.COMMAND_HANDLERS.keys())
    assert not (dead & live), (
        f"Dead handler(s) re-registered: {dead & live}. "
        "Modules/functions they referenced do not exist."
    )


# ── #503: execute_command distinguishes ImportError ──────────────────

def test_execute_command_import_error_produces_handler_not_available(schema_db, monkeypatch):
    """A handler raising ImportError must produce 'handler_not_available', not
    'command_execution_error'. Dashboard users need to distinguish code bugs
    from transient failures (#503)."""
    from src.commands import executor

    def broken(_payload, _config):
        raise ImportError("no module named fake")

    monkeypatch.setitem(executor.COMMAND_HANDLERS, "broken-test", broken)

    result = executor.execute_command(
        {"command_id": "t1", "command_name": "broken-test", "payload_json": "{}"},
        config={},
        db_path=schema_db,
    )
    assert result["status"] == "error"
    assert result["error"] == "handler_not_available", (
        f"ImportError must yield handler_not_available, got {result['error']!r}"
    )


def test_execute_command_generic_exception_produces_execution_error(schema_db, monkeypatch):
    """Non-import runtime failures still produce command_execution_error (#503)."""
    from src.commands import executor

    def throws(_payload, _config):
        raise RuntimeError("something else broke")

    monkeypatch.setitem(executor.COMMAND_HANDLERS, "throws-test", throws)

    result = executor.execute_command(
        {"command_id": "t2", "command_name": "throws-test", "payload_json": "{}"},
        config={},
        db_path=schema_db,
    )
    assert result["status"] == "error"
    assert result["error"] == "command_execution_error"


