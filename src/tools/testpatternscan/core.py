"""TestPatternScan core — AST-based test anti-pattern scanner.

Called by: src/tools/testpatternscan/__main__.py, agents, operators (Python API)
Calls: ast (stdlib), pathlib, logging, src.tools._safety.safe_op
Calls: src.tools.testpatternscan.rules (Rule classes)
Owns tables: none
Config keys: none
Tests: tests/tools/test_testpatternscan_integration.py

Public API:
    scan(*, path, kinds) -> list[Finding]
    Finding — frozen dataclass (rule, file, line, function, detail, confidence)
    TestPatternScanError — raised on unknown rule kind or missing path

Default kinds: ['vacuous', 'patch_drift'] (both ON by default).
Opt-in only:   ['mock_only', 'side_effect_unreached'].
"""

from __future__ import annotations

import ast
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from src.tools._safety import safe_op

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════
# Public types
# ═══════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class Finding:
    rule: str
    file: str
    line: int
    function: str
    detail: str
    confidence: str


class TestPatternScanError(RuntimeError):
    """Unknown rule kind or path doesn't exist."""


# ═══════════════════════════════════════════════════════════════════
# Rule registry
# ═══════════════════════════════════════════════════════════════════

_DEFAULT_KINDS = ["vacuous", "patch_drift"]


def _get_rule_registry() -> dict:
    from src.tools.testpatternscan.rules import (
        MockOnlyRule,
        PatchDriftRule,
        SideEffectUnreachedRule,
        VacuousRule,
    )

    return {
        "vacuous": VacuousRule,
        "patch_drift": PatchDriftRule,
        "mock_only": MockOnlyRule,
        "side_effect_unreached": SideEffectUnreachedRule,
    }


# ═══════════════════════════════════════════════════════════════════
# scan()
# ═══════════════════════════════════════════════════════════════════


@safe_op(name="testpatternscan", mutates=False)
def scan(
    *,
    path: Optional[Path] = None,
    kinds: Optional[list[str]] = None,
) -> list[Finding]:
    """Scan test files for anti-patterns using AST analysis.

    Default path: repo_root / 'tests'.
    Default kinds: ['vacuous', 'patch_drift'].
    """
    search_path = path if path is not None else Path.cwd() / "tests"
    if not search_path.exists():
        raise TestPatternScanError(f"path does not exist: {search_path}")

    rule_kinds = kinds if kinds is not None else _DEFAULT_KINDS
    registry = _get_rule_registry()
    for k in rule_kinds:
        if k not in registry:
            raise TestPatternScanError(
                f"unknown rule kind: {k!r}. Known: {sorted(registry)}"
            )
    rules = [registry[k]() for k in rule_kinds]

    findings: list[Finding] = []
    test_files = list(search_path.rglob("test_*.py"))
    for f in test_files:
        if f.name.startswith("_"):
            continue
        try:
            source = f.read_text(encoding="utf-8")
            tree = ast.parse(source)
        except (SyntaxError, UnicodeDecodeError) as e:
            logger.warning("skipping %s: %s", f, e)
            continue
        if search_path.name == "tests":
            relpath = str(f.relative_to(search_path.parent))
        else:
            relpath = str(f.relative_to(search_path))
        for rule in rules:
            findings.extend(rule.detect(tree, source, relpath))
    return findings
