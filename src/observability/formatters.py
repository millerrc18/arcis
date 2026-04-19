"""Shared log formatter classes.

Extracted from src/log_config.py to break the circular import between
src.log_config and src.observability.loki_handler (#461 Cycle 3).
log_config.py imported setup_loki_handler (deferred), and loki_handler.py
imported StructuredFormatter (also deferred) — both hidden from static
analysis. Moving the formatter here removes the shared symbol.

Called by: log_config.setup_logging (root logger), observability.loki_handler
Calls: logging, json
Owns tables: none
Config keys: none
Tests: tests/test_circular_imports.py
"""
from __future__ import annotations

import json
import logging


class StructuredFormatter(logging.Formatter):
    """Log formatter that appends structured context as |ctx:{JSON}.

    When a LogRecord has a non-empty ``ctx`` attribute (set via
    ``extra={"ctx": {...}}``), the JSON is appended after the message.
    Plain messages are unchanged — backwards-compatible.

    Example output:
        2026-04-06 09:01:00 [executor] ERROR: Exit failed for TGT |ctx:{"event":"exit_failed","ticker":"TGT"}
    """

    def format(self, record: logging.LogRecord) -> str:
        base = super().format(record)
        ctx = getattr(record, "ctx", None)
        if ctx:
            return f"{base} |ctx:{json.dumps(ctx, separators=(',', ':'), default=str)}"
        return base
