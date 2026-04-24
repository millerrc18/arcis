"""Logging configuration for the Arcis system.

Called by: api.app, main
Calls: none
Owns tables: none
Config keys: none
Tests: none
"""

import json  # noqa: F401 — retained for external callers that import from log_config
import logging
import sys
from pathlib import Path
from logging.handlers import RotatingFileHandler

from src.observability.formatters import StructuredFormatter  # noqa: F401 — re-export for back-compat


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
        # encoding="utf-8" is required so emoji/CJK in log records are
        # written intact. Without it, Windows defaults to cp1252 and
        # silently drops records via logging.handleError() (#619).
        file_handler = RotatingFileHandler(
            log_path,
            maxBytes=10 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8",
        )
        file_handler.setFormatter(fmt)
        root.addHandler(file_handler)

    # Grafana Cloud Loki handler (non-blocking, ships logs to cloud).
    # Never allowed to crash logging setup — wrapped in broad try/except.
    try:
        from src.config import load_config
        from src.observability.loki_handler import setup_loki_handler
        loki_handler = setup_loki_handler(load_config())
        if loki_handler:
            root.addHandler(loki_handler)
            logging.getLogger(__name__).info(
                "[OBSERVABILITY] Grafana Loki handler active — shipping logs to cloud"
            )
    except Exception as exc:
        logging.getLogger(__name__).warning(
            "[OBSERVABILITY] Loki setup failed (non-fatal): %s", exc
        )
