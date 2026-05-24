"""LogTail tool — public API.

Called by: operator agents, src/tools/logtail/__main__.py
Exports: tail, LogTailError
"""

from src.tools.logtail.core import LogTailError, tail

__all__ = ["tail", "LogTailError"]
