# Purpose: Public API surface for the TestPatternScan tool.
# Called by: agents, operators, tests
# Calls: src.tools.testpatternscan.core
# Owns tables: none
# Config keys: none
# Tests: tests/tools/test_testpatternscan_integration.py
"""TestPatternScan — AST-based detector for test anti-patterns.

Public exports:
    scan(*, path, kinds) -> list[Finding]
    Finding — frozen dataclass (rule, file, line, function, detail, confidence)
    TestPatternScanError — raised on unknown rule kind or missing path

Default kinds: ['vacuous', 'patch_drift'].
Opt-in only:   'mock_only', 'side_effect_unreached'.
"""

from __future__ import annotations

from src.tools.testpatternscan.core import Finding, TestPatternScanError, scan

__all__ = ["scan", "Finding", "TestPatternScanError"]
