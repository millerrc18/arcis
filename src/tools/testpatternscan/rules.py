"""TestPatternScan rules — 4 AST-based test anti-pattern detectors.

Called by: src/tools/testpatternscan/core.py
Calls: ast (stdlib), importlib.util (stdlib — find_spec ONLY, NEVER import_module)
Owns tables: none
Config keys: none
Tests: tests/tools/test_testpatternscan_integration.py

CRITICAL DA4 CONSTRAINT: PatchDriftRule MUST NEVER call importlib.import_module
or __import__. Importing target modules would trigger load_dotenv, DB connections,
FastAPI app instantiation, and other side effects in CI. Only importlib.util.find_spec
(import-free per Python contract) + ast.parse of spec.origin is permitted.

Rule classes:
  VacuousRule           — @patch/Mock with no .assert_* calls (default ON)
  PatchDriftRule        — @patch target symbol not in module's top-level AST (default ON)
  MockOnlyRule          — only mock assertions, never SUT return value checked (opt-in)
  SideEffectUnreachedRule — mock.side_effect set but test takes return_value branch (opt-in)
"""

from __future__ import annotations

import ast
import importlib.util
from functools import lru_cache
from pathlib import Path

from src.tools.testpatternscan.core import Finding


# ═══════════════════════════════════════════════════════════════════
# Shared helpers
# ═══════════════════════════════════════════════════════════════════


@lru_cache(maxsize=512)
def _module_top_level_names(module_name: str) -> frozenset[str] | None:
    """Return frozenset of top-level names defined in module_name's source file.

    Returns None if:
      - find_spec returns None (module not findable)
      - spec.origin is None or 'built-in' (no source file)
      - spec.origin suffix != '.py' (.pyd / .so / namespace package)
      - source ast.parse fails (SyntaxError / UnicodeDecodeError)

    NEVER imports the module (DA4 — no side effects).
    Only importlib.util.find_spec is called, which is import-free per Python contract.
    """
    try:
        spec = importlib.util.find_spec(module_name)
    except (ImportError, ValueError):
        return None
    if spec is None or spec.origin is None or spec.origin == "built-in":
        return None
    source_path = Path(spec.origin)
    if source_path.suffix != ".py":
        return None
    try:
        source = source_path.read_text(encoding="utf-8")
        tree = ast.parse(source)
    except (SyntaxError, UnicodeDecodeError, OSError):
        return None
    names: set[str] = set()
    for node in tree.body:  # TOP-LEVEL ONLY — do NOT recurse into FunctionDef/ClassDef bodies
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    names.add(target.id)
                elif isinstance(target, ast.Tuple):
                    for elt in target.elts:
                        if isinstance(elt, ast.Name):
                            names.add(elt.id)
        elif isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name):
                names.add(node.target.id)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.asname or alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                names.add(alias.asname or alias.name)
    return frozenset(names)


def _enclosing_function_name(tree: ast.Module, target_node: ast.AST) -> str | None:
    """Return the name of the innermost FunctionDef that contains target_node."""
    for parent in ast.walk(tree):
        if isinstance(parent, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for child in ast.walk(parent):
                if child is target_node:
                    return parent.name
    return None


# ═══════════════════════════════════════════════════════════════════
# VacuousRule
# ═══════════════════════════════════════════════════════════════════


class VacuousRule:
    """Default ON. HIGH precision (false positives rare), MEDIUM recall.

    Detects test functions where @patch or Mock() is in scope but the body
    contains NO .assert_* method call and no plain assert statement.
    """

    def detect(self, tree: ast.Module, source: str, filepath: str) -> list[Finding]:
        findings = []
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if not node.name.startswith("test_"):
                continue
            if not self._has_mock_setup(node):
                continue
            if not self._has_assert_call(node):
                findings.append(
                    Finding(
                        rule="vacuous",
                        file=filepath,
                        line=node.lineno,
                        function=node.name,
                        detail="@patch/Mock setup with no .assert_* call in body",
                        confidence="high",
                    )
                )
        return findings

    @staticmethod
    def _has_mock_setup(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
        for dec in node.decorator_list:
            dec_name = ast.unparse(dec) if hasattr(ast, "unparse") else ""
            if dec_name and "patch" in dec_name:
                return True
        for child in ast.walk(node):
            if isinstance(child, ast.Call) and isinstance(child.func, ast.Name):
                if child.func.id in ("Mock", "MagicMock"):
                    return True
        return False

    @staticmethod
    def _has_assert_call(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
        for child in ast.walk(node):
            if isinstance(child, ast.Assert):
                return True
            if isinstance(child, ast.Call) and isinstance(child.func, ast.Attribute):
                attr = child.func.attr
                if attr.startswith("assert_") or attr == "assert":
                    return True
                if attr in ("fail", "warns", "deprecated_call"):
                    if isinstance(child.func.value, ast.Name) and child.func.value.id == "pytest":
                        return True
            if isinstance(child, ast.With):
                for item in child.items:
                    ce = item.context_expr
                    if isinstance(ce, ast.Call) and isinstance(ce.func, ast.Attribute):
                        if ce.func.attr in ("raises", "warns", "deprecated_call"):
                            return True
        return False


# ═══════════════════════════════════════════════════════════════════
# PatchDriftRule
# ═══════════════════════════════════════════════════════════════════


class PatchDriftRule:
    """Default ON. HIGH precision, MEDIUM-HIGH recall.

    Detects @patch('module.symbol') where the target module's source file
    cannot be ast-parsed OR the symbol is not in the module's TOP-LEVEL AST.

    DA4 PURE-AST RESOLVER: uses importlib.util.find_spec (import-FREE per
    Python contract) + ast.parse of spec.origin. NEVER calls
    importlib.import_module or __import__ — those would EXECUTE the target
    module's top-level code (load_dotenv, DB connections, FastAPI app
    instantiation), turning the static scanner into a side-effect bomb in CI.
    """

    def detect(self, tree: ast.Module, source: str, filepath: str) -> list[Finding]:
        findings = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if not self._is_patch_call(node):
                continue
            if not node.args:
                continue
            arg0 = node.args[0]
            if not isinstance(arg0, ast.Constant) or not isinstance(arg0.value, str):
                continue
            full_target = arg0.value
            if "." not in full_target:
                continue
            module_name, _, symbol = full_target.rpartition(".")
            names = _module_top_level_names(module_name)
            if names is None:
                findings.append(
                    Finding(
                        rule="patch_drift",
                        file=filepath,
                        line=node.lineno,
                        function=_enclosing_function_name(tree, node) or "<module>",
                        detail=f"module {module_name!r} not importable / source not parseable",
                        confidence="high",
                    )
                )
                continue
            if symbol not in names:
                findings.append(
                    Finding(
                        rule="patch_drift",
                        file=filepath,
                        line=node.lineno,
                        function=_enclosing_function_name(tree, node) or "<module>",
                        detail=f"symbol {symbol!r} not in top-level AST of {module_name}",
                        confidence="medium",
                    )
                )
        return findings

    @staticmethod
    def _is_patch_call(node: ast.Call) -> bool:
        if isinstance(node.func, ast.Name) and node.func.id == "patch":
            return True
        if isinstance(node.func, ast.Attribute) and node.func.attr == "patch":
            return True
        return False


# ═══════════════════════════════════════════════════════════════════
# MockOnlyRule
# ═══════════════════════════════════════════════════════════════════


class MockOnlyRule:
    """OPT-IN (not in default kinds). MEDIUM precision.

    Detects test functions whose ONLY assertions are mock.assert_*() or
    mock.call_args checks — never asserts on the real return value from SUT.

    Heuristic: function has mock setup AND has assert calls but NONE of the
    assert calls involve a non-mock expression (i.e., all assert statements
    test mock attributes like call_count, call_args, assert_called_with, etc.)
    """

    def detect(self, tree: ast.Module, source: str, filepath: str) -> list[Finding]:
        findings = []
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if not node.name.startswith("test_"):
                continue
            if not self._has_mock_setup(node):
                continue
            if not self._has_any_assertion(node):
                continue
            if self._all_assertions_are_mock_checks(node):
                findings.append(
                    Finding(
                        rule="mock_only",
                        file=filepath,
                        line=node.lineno,
                        function=node.name,
                        detail="all assertions are mock interaction checks; SUT return value never asserted",
                        confidence="medium",
                    )
                )
        return findings

    @staticmethod
    def _has_mock_setup(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
        for dec in node.decorator_list:
            dec_name = ast.unparse(dec) if hasattr(ast, "unparse") else ""
            if dec_name and "patch" in dec_name:
                return True
        for child in ast.walk(node):
            if isinstance(child, ast.Call) and isinstance(child.func, ast.Name):
                if child.func.id in ("Mock", "MagicMock"):
                    return True
        return False

    @staticmethod
    def _has_any_assertion(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
        for child in ast.walk(node):
            if isinstance(child, ast.Assert):
                return True
            if isinstance(child, ast.Call) and isinstance(child.func, ast.Attribute):
                if child.func.attr.startswith("assert_"):
                    return True
        return False

    @staticmethod
    def _all_assertions_are_mock_checks(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
        """Return True if every assertion in the function is a mock-related check.

        Mock-related checks:
          - .assert_called_*(...)  / .assert_any_call(...) etc.
          - plain assert statements that reference .call_count / .call_args / .called
        """
        has_non_mock_assert = False
        has_mock_assert = False

        for child in ast.walk(node):
            if isinstance(child, ast.Call) and isinstance(child.func, ast.Attribute):
                if child.func.attr.startswith("assert_"):
                    has_mock_assert = True
                    continue
            if isinstance(child, ast.Assert):
                # Check if the assert test expression references mock attributes
                test_src = ast.unparse(child.test) if hasattr(ast, "unparse") else ""
                if any(
                    attr in test_src
                    for attr in ("call_count", "call_args", "called", "call_args_list")
                ):
                    has_mock_assert = True
                else:
                    has_non_mock_assert = True

        return has_mock_assert and not has_non_mock_assert


# ═══════════════════════════════════════════════════════════════════
# SideEffectUnreachedRule
# ═══════════════════════════════════════════════════════════════════


class SideEffectUnreachedRule:
    """OPT-IN (not in default kinds). LOW precision.

    Detects mock.side_effect = Exception(...) set in the test body but the
    test also sets mock.return_value = <value> AND the test has assert
    statements that check the return value (T18 pattern).

    This is a loose heuristic: it flags when both side_effect and return_value
    are assigned on the same mock, which often means the side_effect path is
    never exercised.
    """

    def detect(self, tree: ast.Module, source: str, filepath: str) -> list[Finding]:
        findings = []
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if not node.name.startswith("test_"):
                continue
            if self._has_unreached_side_effect_pattern(node):
                findings.append(
                    Finding(
                        rule="side_effect_unreached",
                        file=filepath,
                        line=node.lineno,
                        function=node.name,
                        detail="mock.side_effect set alongside mock.return_value; side_effect may be unreachable",
                        confidence="low",
                    )
                )
        return findings

    @staticmethod
    def _has_unreached_side_effect_pattern(
        node: ast.FunctionDef | ast.AsyncFunctionDef,
    ) -> bool:
        """Return True if test sets .side_effect AND .return_value on the same expression base."""
        side_effect_bases: set[str] = set()
        return_value_bases: set[str] = set()

        for child in ast.walk(node):
            if not isinstance(child, ast.Assign):
                continue
            for target in child.targets:
                if not isinstance(target, ast.Attribute):
                    continue
                base = ast.unparse(target.value) if hasattr(ast, "unparse") else ""
                attr = target.attr
                if attr == "side_effect":
                    side_effect_bases.add(base)
                elif attr == "return_value":
                    return_value_bases.add(base)

        return bool(side_effect_bases & return_value_bases)
