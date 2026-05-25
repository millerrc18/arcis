# Purpose: PRComments subpackage — post and read PR comments via gh CLI.
# Called by: operator agents, src/tools/prcomments/__main__.py
# Calls: src.tools.prcomments.core
# Owns tables: none
# Config keys: none
# Tests: tests/tools/test_prcomments_integration.py

from src.tools.prcomments.core import (
    GhCommandFailedError,
    GhJsonParseError,
    GhMissingError,
    PRComment,
    PRCommentLeakError,
    PRCommentsError,
    post,
    read,
)

__all__ = [
    "read",
    "post",
    "PRComment",
    "PRCommentsError",
    "PRCommentLeakError",
    "GhCommandFailedError",
    "GhJsonParseError",
    "GhMissingError",
]
