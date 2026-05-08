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


_COMMANDS_PATH = (
    pathlib.Path(__file__).resolve().parents[2] / "src" / "cli" / "commands.py"
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
    """AST-walk src/cli/commands.py — assert zero src.notifications ImportFrom
    nodes live inside any FunctionDef."""
    source = _COMMANDS_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(_COMMANDS_PATH))
    lazy_hits = _notification_import_nodes_inside_functions(tree)
    assert lazy_hits == [], (
        f"Found {len(lazy_hits)} lazy src.notifications import(s) inside function "
        f"bodies in src/cli/commands.py — relocate to module level:\n"
        + "\n".join(f"  line {ln}: from {mod} import ..." for ln, mod in lazy_hits)
    )


def test_module_level_import_succeeds() -> None:
    """Importing src.cli.commands must succeed without errors."""
    mod = importlib.import_module("src.cli.commands")
    assert mod is not None
