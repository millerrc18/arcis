# Purpose: Public API surface for the DocConsistency tool (v1 — class (a) only).
# Called by: agents, operators, tests, future periodic skill-audit (#111)
# Calls: src.tools.docconsistency.core
# Owns tables: none
# Config keys: none
# Tests: tests/tools/test_docconsistency_integration.py
"""DocConsistency v1 — dead file:line reference scanner for markdown documentation.

Scans CHANGELOG.md, README.md, docs/standards/, docs/operator-guide.md,
docs/cli-reference.md, and recent docs/audits/ entries for inline
`file.py:N` references and verifies each referred file exists with at
least that many lines.

v1 implements class (a) ONLY — dead file:line refs. Classes (b) API
signature drift, (c) docstring-vs-code drift, and (d) symbol existence
are deferred to v2/Tier 4.

Public exports:
    scan(targets, *, allowlist_path, repo_root) -> dict
    DocConsistencyError
    DocConsistencyAllowlistError
    DocConsistencyTargetMissingError
"""

from __future__ import annotations

from src.tools.docconsistency.core import (
    DocConsistencyAllowlistError,
    DocConsistencyError,
    DocConsistencyTargetMissingError,
    scan,
)

__all__ = [
    "scan",
    "DocConsistencyError",
    "DocConsistencyAllowlistError",
    "DocConsistencyTargetMissingError",
]
