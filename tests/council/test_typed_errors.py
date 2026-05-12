"""Tests for council typed exception hierarchy (#68).

Module: tests.council.test_typed_errors
Purpose: Verify the 5-class exception hierarchy in src/council/errors.py and
         assert that src/council/agent_data.py contains zero bare `except Exception`
         blocks (all 28 converted to typed catches).
Called by: pytest
Owns tables: none
Config keys: none
"""

import ast
import textwrap

import pytest

from src.council.errors import (
    CouncilAgentDataError,
    CouncilError,
    CouncilParseError,
    CouncilProviderError,
    CouncilTimeoutError,
    CouncilUnavailableError,
)


# ---------------------------------------------------------------------------
# Group 1: instantiation — each class can be raised and caught
# ---------------------------------------------------------------------------


class TestInstantiation:
    def test_council_error_instantiates(self):
        exc = CouncilError("base error")
        assert str(exc) == "base error"

    def test_council_parse_error_instantiates(self):
        exc = CouncilParseError("bad json")
        assert str(exc) == "bad json"

    def test_council_timeout_error_instantiates(self):
        exc = CouncilTimeoutError("llm timed out")
        assert str(exc) == "llm timed out"

    def test_council_agent_data_error_instantiates(self):
        exc = CouncilAgentDataError("db fetch failed")
        assert str(exc) == "db fetch failed"

    def test_council_provider_error_instantiates(self):
        exc = CouncilProviderError("provider unavailable")
        assert str(exc) == "provider unavailable"


# ---------------------------------------------------------------------------
# Group 2: hierarchy — each subclass IS-A CouncilError
# ---------------------------------------------------------------------------


class TestHierarchy:
    def test_council_parse_error_is_council_error(self):
        assert issubclass(CouncilParseError, CouncilError)

    def test_council_timeout_error_is_council_error(self):
        assert issubclass(CouncilTimeoutError, CouncilError)

    def test_council_agent_data_error_is_council_error(self):
        assert issubclass(CouncilAgentDataError, CouncilError)

    def test_council_provider_error_is_council_error(self):
        assert issubclass(CouncilProviderError, CouncilError)

    def test_council_unavailable_error_is_council_error(self):
        assert issubclass(CouncilUnavailableError, CouncilError)

    def test_council_error_is_exception(self):
        assert issubclass(CouncilError, Exception)

    def test_council_unavailable_error_is_runtime_error(self):
        assert issubclass(CouncilUnavailableError, RuntimeError)


# ---------------------------------------------------------------------------
# Group 3: AST scan — zero bare `except Exception` in agent_data.py
# ---------------------------------------------------------------------------


class TestAgentDataNoBareExceptException:
    """AST-based enforcement: all 28 bare `except Exception` blocks must be
    converted to typed catches. This test fails if any remain."""

    def _load_agent_data_ast(self):
        import importlib.util
        import pathlib

        src_file = (
            pathlib.Path(__file__).parent.parent.parent
            / "src"
            / "council"
            / "agent_data.py"
        )
        source = src_file.read_text(encoding="utf-8")
        return ast.parse(source)

    def _bare_except_exception_count(self, tree):
        """Count `except Exception` handlers (bare: no sub-type narrowing).

        A handler counts as bare if it matches `except Exception` or
        `except Exception as <var>` — i.e. the type is exactly the built-in
        `Exception`, not a subclass.
        """
        count = 0
        for node in ast.walk(tree):
            if isinstance(node, ast.ExceptHandler):
                if (
                    node.type is not None
                    and isinstance(node.type, ast.Name)
                    and node.type.id == "Exception"
                ):
                    count += 1
        return count

    def test_zero_bare_except_exception_in_agent_data(self):
        tree = self._load_agent_data_ast()
        count = self._bare_except_exception_count(tree)
        assert count == 0, (
            f"Found {count} bare `except Exception` block(s) in "
            "src/council/agent_data.py — all must be converted to typed catches."
        )
