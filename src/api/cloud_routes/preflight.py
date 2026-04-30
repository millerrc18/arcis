"""Preflight transcript echo endpoint — surfaces go/no-go gate result to the dashboard.

Called by: src.api.app (router registered at /api/preflight/latest)
Calls: scripts/preflight_monday.py transcript on disk (local SQLite path);
  preflight_runs table on Render Postgres (cloud path).
Owns tables: none (reads preflight_runs)
Config keys: DATABASE_URL env var (Postgres routing)
Tests: tests/api/test_preflight_route.py

Reads the most recent preflight_transcript.txt written by
scripts/preflight_monday.py (default path: audits/<date>/preflight_transcript.txt)
and exposes last_run_at, overall_status (green/yellow/red/unknown), per-item
statuses, and a link to the full transcript path on disk.

Empty state is returned when no transcript has been written yet so the
dashboard can display a graceful "Preflight has not been run yet" message.

#87: On Render the audits/ directory does not exist (it is local to the
operator's machine), so this route returned overall_status='unknown'
permanently. When DATABASE_URL is set, we instead read the most recent row
from the preflight_runs table; the writer side (scripts/preflight_monday.py)
must be updated in a follow-up PR to land rows in that table — until that
ships, the cloud route's empty-state behavior is unchanged.
"""
from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends

router = APIRouter()
logger = logging.getLogger(__name__)

# Default audits directory relative to repo root.
def _find_project_root() -> Path:
    """Walk up from this file to find the repo root (has MASTER.md or CLAUDE.md).

    More robust than ``Path(__file__).resolve().parents[3]`` — survives the file
    being moved between package depths (Sprint 0 cluster-07). Mirrors
    ``src/api/routes/docs.py::_find_project_root``.
    """
    p = Path(__file__).resolve()
    for parent in [p, *p.parents]:
        if (parent / "MASTER.md").exists() or (parent / "CLAUDE.md").exists():
            return parent
    return Path.cwd()


_REPO_ROOT = _find_project_root()
_AUDITS_DIR = _REPO_ROOT / "audits"

_GENERATED_RE = re.compile(r"^Generated:\s*(.+)$", re.MULTILINE)
_SUMMARY_RE = re.compile(r"^Summary:\s*(\d+)\s+PASS\s*/\s*(\d+)\s+FAIL", re.MULTILINE)
_ITEM_RE = re.compile(
    r"^\[[\s\d]+\]\s+\[.+?\]\s+(PASS|FAIL)\s+\(\w+\)\s+(\S+)",
    re.MULTILINE,
)


# #632 — verify_auth placeholder, overridden by cloud_app.py in production.
def verify_auth() -> None:
    return None


def _find_latest_transcript(audits_dir: Path) -> Path | None:
    """Return the most recently written preflight_transcript.txt under audits_dir.

    Walks one level of subdirectories (date-named dirs like 2026-04-27) and
    selects the transcript with the latest mtime. Sorting by mtime is more
    robust than lexicographic sort: it survives non-zero-padded date
    directories (e.g. ``2026-5-1`` vs ``2026-04-27``) and re-runs that
    overwrite an older dir's transcript. Returns None when no transcript has
    been written yet.
    """
    candidates: list[Path] = []
    for child in audits_dir.iterdir() if audits_dir.is_dir() else []:
        if child.is_dir():
            t = child / "preflight_transcript.txt"
            if t.is_file():
                candidates.append(t)
        elif child.name == "preflight_transcript.txt":
            candidates.append(child)
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


def _parse_transcript(text: str) -> dict[str, Any]:
    """Parse a preflight transcript string into a structured dict.

    Returns a dict with keys: last_run_at, overall_status, items,
    n_pass, n_fail.

    overall_status rules:
      green  — n_fail == 0
      yellow — n_fail == 1
      red    — n_fail >= 2
    """
    last_run_at: str | None = None
    m = _GENERATED_RE.search(text)
    if m:
        last_run_at = m.group(1).strip()

    n_pass = 0
    n_fail = 0
    sm = _SUMMARY_RE.search(text)
    if sm:
        n_pass = int(sm.group(1))
        n_fail = int(sm.group(2))

    if n_fail == 0:
        overall_status = "green"
    elif n_fail == 1:
        overall_status = "yellow"
    else:
        overall_status = "red"

    items: list[dict[str, str]] = []
    for match in _ITEM_RE.finditer(text):
        items.append({
            "status": match.group(1).lower(),
            "name": match.group(2),
        })

    return {
        "last_run_at": last_run_at,
        "overall_status": overall_status,
        "n_pass": n_pass,
        "n_fail": n_fail,
        "items": items,
    }


def _empty_state() -> dict[str, Any]:
    return {
        "last_run_at": None,
        "overall_status": "unknown",
        "n_pass": 0,
        "n_fail": 0,
        "items": [],
        "transcript_path": None,
    }


def _is_missing_preflight_schema(exc: Exception) -> bool:
    """True when Postgres is missing the preflight table/column.

    Render can legitimately lag the local SQLite/schema registry during rollout.
    In that state the dashboard should surface the same empty-state message as
    "no preflight run yet", not a hard 500.
    """
    pgcode = getattr(exc, "pgcode", None)
    return pgcode in {"42P01", "42703"} or type(exc).__name__ in {
        "UndefinedTable",
        "UndefinedColumn",
    }


def _read_latest_from_postgres(database_url: str) -> dict[str, Any] | None:
    """Read the most recent preflight_runs row from Render Postgres.

    Returns None when the table is empty — the caller then surfaces the
    same empty-state dict the filesystem path uses, so the dashboard
    behavior is identical regardless of backend.
    """
    import psycopg2
    import psycopg2.extras
    sql = (
        "SELECT last_run_at, overall_status, n_pass, n_fail, "
        "items_json, transcript_path "
        "FROM preflight_runs ORDER BY created_at DESC LIMIT 1"
    )
    try:
        with psycopg2.connect(database_url) as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(sql)
                row = cur.fetchone()
    except Exception as exc:  # noqa: BLE001
        if _is_missing_preflight_schema(exc):
            logger.warning(
                "[PREFLIGHT] preflight_runs not available in Render Postgres yet; "
                "returning empty state instead of 500: %s",
                exc,
            )
            return None
        raise
    if row is None:
        return None
    items_json = row.get("items_json") or "[]"
    try:
        items = json.loads(items_json)
    except (TypeError, ValueError):
        items = []
    return {
        "last_run_at": row.get("last_run_at"),
        "overall_status": row.get("overall_status") or "unknown",
        "n_pass": int(row.get("n_pass") or 0),
        "n_fail": int(row.get("n_fail") or 0),
        "items": items,
        "transcript_path": row.get("transcript_path"),
    }


@router.get("/preflight/latest", dependencies=[Depends(verify_auth)])
def get_preflight_latest() -> dict:
    """Return the most recent preflight transcript status.

    Cloud (DATABASE_URL set): reads the latest row from preflight_runs.
    Local: scans audits/ for the newest preflight_transcript.txt. Both
    branches return the same empty-state dict when no data is present,
    so the dashboard can render its 'Preflight has not been run yet'
    message identically.
    """
    database_url = os.environ.get("DATABASE_URL", "")
    if database_url:
        row = _read_latest_from_postgres(database_url)
        if row is None:
            return _empty_state()
        return row

    transcript_path = _find_latest_transcript(_AUDITS_DIR)
    if transcript_path is None:
        return _empty_state()
    text = transcript_path.read_text(encoding="utf-8")
    parsed = _parse_transcript(text)
    parsed["transcript_path"] = str(transcript_path)
    return parsed
