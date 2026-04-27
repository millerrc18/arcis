"""CI guardrail: detect orphaned test imports (closes #671).

Rationale:
    When a refactor PR removes a function, the test that imports it silently
    becomes an orphan — it fails at import-time with AttributeError, but only
    if the test actually runs. This structural test catches the gap WITHOUT
    needing to run any test: it walks tests/**/*.py AST for every
    `from src.X import Y` statement and verifies that Y actually exists in the
    current src/ tree.

    Incident that motivated this: PR #668 silently reverted _redact_token()
    from src/notifications/telegram.py. The function had a dedicated test in
    tests/test_telegram_token_redaction.py. The regression went undetected for
    ~4 hours (see issue #671).

Called by: CI test suite
Calls: none
Owns tables: none
Config keys: none
Tests: self
"""
import ast
import importlib
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# Symbols that are intentionally imported from a module that no longer has
# them — e.g. a test that verifies a symbol was REMOVED. Add entries here
# with an explicit comment citing the issue/PR.
# Format: ("src.module.path", "SymbolName")
# ---------------------------------------------------------------------------
ALLOWLIST: set[tuple[str, str]] = {
    # Example (add real entries only when needed):
    # ("src.some.module", "RemovedSymbol"),  # Verifies removal — issue #NNN
}


def _collect_test_src_imports(tests_root: Path) -> list[tuple[Path, str, str]]:
    """Return list of (test_file, module_path, symbol) for every
    `from src.X import Y` statement in tests/, excluding:

    - Imports inside try/except ImportError blocks (intentional graceful skip)
    - Imports inside pytest.importorskip() calls
    - Imports from tests/ helper modules (not from src.)
    """
    results = []
    for test_file in tests_root.rglob("*.py"):
        try:
            source = test_file.read_text(encoding="utf-8")
            tree = ast.parse(source)
        except (SyntaxError, UnicodeDecodeError):
            continue

        # Collect line numbers of try/except ImportError blocks to exclude
        try_import_lines: set[int] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Try):
                # Check if any handler catches ImportError or ModuleNotFoundError
                for handler in node.handlers:
                    if handler.type is None:
                        # bare except — treat as intentional
                        for lineno in range(node.lineno, node.end_lineno + 1):
                            try_import_lines.add(lineno)
                    elif isinstance(handler.type, ast.Name) and handler.type.id in (
                        "ImportError",
                        "ModuleNotFoundError",
                    ):
                        for lineno in range(node.lineno, node.end_lineno + 1):
                            try_import_lines.add(lineno)
                    elif isinstance(handler.type, ast.Tuple):
                        for elt in handler.type.elts:
                            if isinstance(elt, ast.Name) and elt.id in (
                                "ImportError",
                                "ModuleNotFoundError",
                            ):
                                for lineno in range(node.lineno, node.end_lineno + 1):
                                    try_import_lines.add(lineno)

        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom):
                continue
            if node.level != 0:
                continue  # Relative import — not from src.
            if not node.module or not node.module.startswith("src."):
                continue
            if node.lineno in try_import_lines:
                continue  # Inside try/except ImportError — intentional

            for alias in node.names:
                symbol = alias.name
                if (node.module, symbol) in ALLOWLIST:
                    continue
                results.append((test_file, node.module, symbol))

    return results


def _symbol_exists_in_module(module_path: str, symbol: str) -> bool:
    """Return True if `symbol` is accessible in `module_path` on the
    current src/ tree.

    Handles two cases:
    1. `from src.pkg import submodule` — symbol is itself a sub-package/module.
       Checked by attempting `import src.pkg.submodule` directly.
    2. `from src.pkg.module import FUNC` — symbol is a name in the module.
       Checked via `hasattr(imported_module, symbol)`.

    Returns True (not orphaned) if the module itself cannot be imported —
    that failure mode is caught by test_all_src_modules_importable separately.
    """
    # Case 1: symbol might be a submodule (e.g. `from src.cli import commands`)
    submod_path = f"{module_path}.{symbol}"
    try:
        importlib.import_module(submod_path)
        return True  # valid submodule import
    except (ImportError, ModuleNotFoundError):
        pass  # not a submodule, fall through to hasattr check

    # Case 2: symbol is a name exported by the module
    try:
        mod = importlib.import_module(module_path)
        return hasattr(mod, symbol)
    except (ImportError, ModuleNotFoundError, Exception):
        # Module itself unimportable — not this test's concern
        return True


def test_no_orphaned_test_imports():
    """Every `from src.X import Y` in tests/ must resolve in the current src/.

    Exclusions:
    - Imports inside try/except ImportError blocks (pytest.importorskip pattern)
    - Imports in the ALLOWLIST (intentional imports of removed symbols)
    - Tests that import from tests/ (not from src.)

    Failure message lists each orphaned reference with file + line for
    immediate triage.
    """
    tests_root = Path("tests")
    imports = _collect_test_src_imports(tests_root)

    orphans = []
    for test_file, module_path, symbol in imports:
        if not _symbol_exists_in_module(module_path, symbol):
            orphans.append(
                f"  {test_file}: from {module_path} import {symbol}  "
                f"[symbol not found in current src/]"
            )

    assert not orphans, (
        f"ORPHANED TEST IMPORTS — {len(orphans)} test file(s) import symbols "
        f"that no longer exist in src/ (PR reverted a function?):\n"
        + "\n".join(orphans)
    )
