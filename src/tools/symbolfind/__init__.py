# Purpose: Public API surface for the SymbolFind tool.
# Called by: agents, operators, tests
# Calls: src.tools.symbolfind.core
# Owns tables: none
# Config keys: none
# Tests: tests/tools/test_symbolfind_integration.py
"""SymbolFind — rg-backed Python symbol definition and reference lookup.

Public exports:
    find(symbol, *, kind='any', path=None) -> list[dict]
    SymbolFindError — raised when rg is missing or returns a non-zero exit.
"""

from __future__ import annotations

from src.tools.symbolfind.core import SymbolFindError, find

__all__ = ["find", "SymbolFindError"]
