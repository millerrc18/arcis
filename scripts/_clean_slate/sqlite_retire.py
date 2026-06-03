"""Retire the legacy SQLite trade/learning residue — archive, fsync, then empty.

Spec §Phase5 / DD-SQLITE (minor (d)). The canonical SQLite (+ -wal/-shm) is
archived via `VACUUM INTO` (fallback: file copy capturing WAL/SHM), the archive
file AND its directory are fsync'd BEFORE the live file is emptied (so an
interruption can never leave both the live file emptied and the archive
unflushed), and the WIPE-classified trade/learning tables are then DELETEd
in place — NEVER the file blind-deleted. `connect_db` recreates an empty file at
db.py:638; deleting the canonical file would change the fallback for any
non-gated tool/test.

Read/empties SQLite only — never touches PG, never edits YAML.

Tests: tests/scripts/test_clean_slate_e2e.py, tests/scripts/test_clean_slate_interrupted.py
"""

from __future__ import annotations

import hashlib
import logging
import os
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from scripts._clean_slate.classification import WIPE_TABLES

logger = logging.getLogger(__name__)

_ET = ZoneInfo("America/New_York")


def _sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    """SHA-256 of a file in 1 MiB chunks (handles 1+ GB archives)."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _fsync_file(path: Path) -> None:
    """fsync a file's bytes to stable storage.

    Opens O_RDWR, not O_RDONLY: on Windows `os.fsync()` on a read-only descriptor
    raises EBADF ('Bad file descriptor'). The bytes were already flushed+closed by
    VACUUM INTO / shutil.copy2, so this is durability hardening — tolerate a
    platform fsync failure rather than abort the retire (the archive is on disk).
    """
    try:
        fd = os.open(str(path), os.O_RDWR)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def _fsync_dir(path: Path) -> None:
    """fsync a directory entry (best-effort; not all platforms support it)."""
    try:
        fd = os.open(str(path), os.O_RDONLY)
    except (OSError, PermissionError):
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def _sqlite_tables(db_path: Path) -> set[str]:
    """Return the set of table names present in the SQLite file."""
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        return {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
    finally:
        conn.close()


def archive_and_empty_sqlite(
    src_path: Path | str,
    archive_dir: Path | str,
) -> dict[str, Any]:
    """Archive the canonical SQLite then empty its WIPE tables in place.

    Returns a verdict dict:
        {result, source, archive_path, archive_sha, archive_size_bytes,
         emptied_tables}

    result is one of:
        SQLITE_RETIRED  — archived (fsync'd) + WIPE tables emptied in place.
        SQLITE_ABSENT   — source did not exist; nothing done (WARN, no raise).

    The archive is fsync'd (file + dir) BEFORE the empty step so an interruption
    after the empty can never lose both copies. The live file is emptied, never
    deleted (DD-SQLITE).
    """
    src = Path(src_path)
    arc_dir = Path(archive_dir)

    if not src.exists():
        logger.warning("SQLite source absent — skipping retire: %s", src)
        return {
            "result": "SQLITE_ABSENT",
            "source": str(src),
            "archive_path": None,
            "archive_sha": None,
            "archive_size_bytes": 0,
            "emptied_tables": [],
        }

    arc_dir.mkdir(parents=True, exist_ok=True)
    archive_path = arc_dir / src.name

    # 1. Archive via VACUUM INTO (compacts + captures full schema/data); fall
    #    back to a raw file copy (with WAL/SHM siblings) if VACUUM INTO fails.
    vacuum_ok = False
    conn: sqlite3.Connection | None = None
    try:
        conn = sqlite3.connect(str(src))
        escaped = str(archive_path).replace("'", "''")
        conn.execute(f"VACUUM INTO '{escaped}'")
        vacuum_ok = True
    except sqlite3.Error as exc:
        logger.warning("VACUUM INTO failed (%s) — falling back to file copy", exc)
    finally:
        if conn is not None:
            conn.close()

    if not vacuum_ok or not archive_path.exists():
        shutil.copy2(str(src), str(archive_path))
        for suffix in ("-wal", "-shm"):
            sibling = src.with_name(src.name + suffix)
            if sibling.exists():
                shutil.copy2(str(sibling), str(arc_dir / sibling.name))

    # 2. fsync the archive (file + directory) BEFORE emptying the live file.
    _fsync_file(archive_path)
    _fsync_dir(arc_dir)

    archive_sha = _sha256_file(archive_path)
    archive_size = archive_path.stat().st_size

    # 3. Empty the WIPE-classified trade/learning tables IN PLACE — never delete
    #    the file. Tables absent from this SQLite are skipped (PG-only tables).
    present = _sqlite_tables(src)
    emptied: list[str] = []
    live_conn = sqlite3.connect(str(src))
    try:
        for name in sorted(WIPE_TABLES):
            if name not in present:
                continue
            live_conn.execute(f"DELETE FROM {name}")
            emptied.append(name)
        live_conn.commit()
    finally:
        live_conn.close()

    logger.info(
        "SQLite retired: archived %s (sha=%s), emptied %d WIPE table(s) in place",
        archive_path, archive_sha[:12], len(emptied),
    )
    return {
        "result": "SQLITE_RETIRED",
        "source": str(src),
        "archive_path": str(archive_path),
        "archive_sha": archive_sha,
        "archive_size_bytes": archive_size,
        "emptied_tables": emptied,
        "archived_at_et": datetime.now(_ET).isoformat(),
    }
