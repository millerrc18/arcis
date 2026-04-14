"""Logging configuration for the Arcis system.

Called by: api.app, main
Calls: none
Owns tables: none
Config keys: none
Tests: none
"""

import json
import logging
import sys
from pathlib import Path
from logging.handlers import RotatingFileHandler


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


def setup_logging(level: str = "INFO", log_file: str | None = None):
    """Configure logging for the application.

    Args:
        level: Log level (DEBUG, INFO, WARNING, ERROR).
        log_file: Optional log file path. If provided, adds a rotating file handler.
    """
    # Windows console defaults to cp1252 which cannot encode emoji (e.g.
    # \u274c ❌). Without this reconfigure, logging.handleError() silently
    # drops records containing such characters and writes a traceback to
    # stderr. Force utf-8 with errors='replace' so records are never lost.
    for stream in (sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                pass

    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Clear existing handlers
    root.handlers.clear()

    fmt = StructuredFormatter("%(asctime)s [%(name)s] %(levelname)s: %(message)s")

    # Console handler
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(fmt)
    root.addHandler(console)

    # Optional rotating file handler
    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            log_path, maxBytes=10 * 1024 * 1024, backupCount=5
        )
        file_handler.setFormatter(fmt)
        root.addHandler(file_handler)
