"""Regression tests for I10 fix — no lazy notification imports in cli/commands.py.

T5: Verifies that `from src.notifications import ...` (and any
`from src.notifications.X import ...`) imports do NOT appear inside any
function body in src/cli/commands.py.  AST walk catches both FunctionDef
and async functions; the test fails as long as even one lazy import
remains, giving a pinpoint failure message.
"""

import ast
import importlib
import pathlib


# Phase 5 PR-C T13 split cli/commands.py into category sub-modules; the
# command bodies (and thus any lazy notification imports) now live in
# commands_data.py / commands_training.py / commands_ops.py. The I10 guard
# AST-walks all three so a lazy `from src.notifications ...` inside any
# command body is still caught.
_CLI_DIR = pathlib.Path(__file__).resolve().parents[2] / "src" / "cli"
_COMMANDS_PATHS = (
    _CLI_DIR / "commands_data.py",
    _CLI_DIR / "commands_training.py",
    _CLI_DIR / "commands_ops.py",
)


def _notification_import_nodes_inside_functions(tree: ast.AST) -> list[tuple[int, str]]:
    """Return (lineno, module) for every ImportFrom with module starting
    with 'src.notifications' that lives inside a FunctionDef (or
    AsyncFunctionDef) at any nesting depth."""

    hits: list[tuple[int, str]] = []

    class Visitor(ast.NodeVisitor):
        def __init__(self) -> None:
            self._in_function: int = 0

        def _visit_funcdef(self, node: ast.AST) -> None:
            self._in_function += 1
            self.generic_visit(node)
            self._in_function -= 1

        visit_FunctionDef = _visit_funcdef
        visit_AsyncFunctionDef = _visit_funcdef

        def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
            if self._in_function > 0:
                module = node.module or ""
                if module == "src.notifications" or module.startswith(
                    "src.notifications."
                ):
                    hits.append((node.lineno, module))
            self.generic_visit(node)

    Visitor().visit(tree)
    return hits


def test_no_lazy_notification_imports() -> None:
    """AST-walk the cli command sub-modules — assert zero src.notifications
    ImportFrom nodes live inside any FunctionDef."""
    lazy_hits: list[tuple[str, int, str]] = []
    for path in _COMMANDS_PATHS:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
        for ln, mod in _notification_import_nodes_inside_functions(tree):
            lazy_hits.append((path.name, ln, mod))
    assert lazy_hits == [], (
        f"Found {len(lazy_hits)} lazy src.notifications import(s) inside function "
        f"bodies in the cli command sub-modules — relocate to module level:\n"
        + "\n".join(f"  {name} line {ln}: from {mod} import ..." for name, ln, mod in lazy_hits)
    )


def test_module_level_import_succeeds() -> None:
    """Importing src.cli.commands must succeed without errors."""
    mod = importlib.import_module("src.cli.commands")
    assert mod is not None
