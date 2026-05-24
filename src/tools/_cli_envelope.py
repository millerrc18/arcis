"""Shared --json error-envelope wrapper consumed by every Tier-1 tool's __main__.py.

Called by: src/tools/db_query/__main__.py, src/tools/log_tail/__main__.py, etc. (T2-T7)
Calls: sys.exit, json.dumps (stdlib only)
Owns tables: none
Config keys: none
Tests: covered indirectly by each tool's __main__ tests (T2-T7)
"""

from __future__ import annotations

import json
import sys
from typing import Any, Callable


def run_cli(
    tool_name: str,
    fn: Callable[..., Any],
    args_namespace: Any,
    *,
    json_mode: bool,
) -> None:
    """Invoke fn(**vars(args_namespace)), render output or JSON error envelope.

    Exactly one of two outcomes:
      - fn raises and json_mode=True  → print JSON error envelope to stdout,
                                        sys.exit(1).
      - fn raises and json_mode=False → re-raise (Python default traceback to
                                        stderr, exit 1).
      - fn returns successfully       → print result to stdout, sys.exit(0).

    Error envelope schema (per spec §4.6):
        {"error": {"type": "<ExceptionClassName>", "message": "<str(e)>", "tool": "<tool_name>"}}

    The 'type' is the exception class __name__ (e.g. 'WriteNotPermittedError').
    No traceback is included in the envelope.
    """
    try:
        result = fn(**vars(args_namespace))
    except Exception as exc:
        if json_mode:
            envelope = {
                "error": {
                    "type": type(exc).__name__,
                    "message": str(exc),
                    "tool": tool_name,
                }
            }
            print(json.dumps(envelope))
            sys.exit(1)
        raise

    print(result)
    sys.exit(0)
