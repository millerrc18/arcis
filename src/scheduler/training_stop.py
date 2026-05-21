"""Single source of truth for the cooperative training-stop signal.

Called by: scheduler.training_control, training.stop_callback, scheduler.watch_handlers
Calls: config (DB_PATH)
Owns tables: none
Owns files: STOP_OVERNIGHT (absolute, beside the SQLite DB)
Config keys: none
Tests: tests/scheduler/test_training_stop.py

The STOP_OVERNIGHT flag is resolved to an ABSOLUTE path derived from
``src.config.DB_PATH``. Under the NSSM LocalSystem service the working
directory is ``C:\\Windows\\System32``, so a bare relative ``data/STOP_OVERNIGHT``
would silently no-op (``os.path.exists`` always False) — the absolute
resolution removes that landmine.
"""

import os
from pathlib import Path

from src.config import DB_PATH


def _resolve_stop_flag() -> str:
    """Resolve STOP_OVERNIGHT to an absolute path beside the SQLite DB.

    Falls back to a repo-relative ``data`` directory only when DB_PATH is
    unset (Postgres-only deploys), still resolved to an absolute path so the
    relative-cwd landmine never applies.
    """
    if DB_PATH:
        base_dir = os.path.dirname(os.path.abspath(DB_PATH))
    else:
        base_dir = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "..", "data")
        )
    return os.path.join(base_dir, "STOP_OVERNIGHT")


STOP_FLAG = _resolve_stop_flag()


def request_training_stop(flag_path: str | None = None) -> None:
    """Touch the STOP_OVERNIGHT flag, creating its parent directory if absent."""
    target = flag_path or STOP_FLAG
    parent = os.path.dirname(target)
    if parent:
        os.makedirs(parent, exist_ok=True)
    Path(target).touch()


def clear_training_stop(flag_path: str | None = None) -> None:
    """Remove the STOP_OVERNIGHT flag idempotently."""
    target = flag_path or STOP_FLAG
    Path(target).unlink(missing_ok=True)


def is_stop_requested(flag_path: str | None = None) -> bool:
    """Return whether a stop has been requested.

    Resolution order: ``ARCIS_STOP_FLAG`` env override, then the passed
    ``flag_path``, then the absolute ``STOP_FLAG`` default.
    """
    target = os.environ.get("ARCIS_STOP_FLAG") or flag_path or STOP_FLAG
    return os.path.exists(target)
