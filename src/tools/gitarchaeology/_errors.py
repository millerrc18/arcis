"""GitArchaeology error classes (extracted from core.py for line-budget compliance).

Purpose: Centralize the 5 typed errors raised by gitarchaeology ops so core.py
         stays under the 400-line file budget. Re-exported by core.py and
         __init__.py for backward-compat with existing consumers.

Called by: src.tools.gitarchaeology.core (raise sites for all 7 ops)
Calls:     none (pure exception subclasses)
Owns tables: none
Config keys: none
Tests: tests/tools/test_gitarchaeology_integration.py (T7)
"""

from __future__ import annotations


class GitArchaeologyError(RuntimeError):
    """Root error class for GitArchaeology ops."""


class GitInvocationError(GitArchaeologyError):
    """Raised when git subprocess exits non-zero."""


class GitArgError(GitArchaeologyError):
    """Raised on invalid arguments to a GitArchaeology API call.

    Examples:
      - blame() called with start_line > end_line
      - log() called with custom format= but no format_columns=
      - blame() called on a >5000-line file without line-range
    """


class GitParseError(GitArchaeologyError):
    """Raised when git output cannot be mapped to the expected shape (DA3).

    Fields:
      offending_line:   the raw output line that could not be parsed
      expected_columns: how many tab-separated columns were expected
      op:               which op triggered the error (e.g., 'log')
    """

    def __init__(
        self,
        message: str,
        offending_line: str,
        expected_columns: int,
        op: str,
    ) -> None:
        super().__init__(message)
        self.offending_line = offending_line
        self.expected_columns = expected_columns
        self.op = op


class GitOutputTruncatedError(GitArchaeologyError):
    """Raised when git output exceeds per-op max_output_bytes (DA4).

    Fields:
      partial_output:      first max_output_bytes of stdout (codepoint-safe)
      original_size_bytes: actual UTF-8 byte count of full output
      op:                  which op triggered the error
    """

    def __init__(
        self,
        message: str,
        partial_output: str,
        original_size_bytes: int,
        op: str,
    ) -> None:
        super().__init__(message)
        self.partial_output = partial_output
        self.original_size_bytes = original_size_bytes
        self.op = op
