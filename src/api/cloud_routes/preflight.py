"""Preflight transcript echo endpoint — surfaces go/no-go gate result to the dashboard.

Called by: src.api.app (router registered at /api/preflight/latest)
Calls: scripts/preflight_monday.py transcript on disk (read-only)
Owns tables: none
Config keys: none
Tests: tests/api/test_preflight_route.py

Reads the most recent preflight_transcript.txt written by
scripts/preflight_monday.py (default path: audits/<date>/preflight_transcript.txt)
and exposes last_run_at, overall_status (green/yellow/red/unknown), per-item
statuses, and a link to the full transcript path on disk.

Empty state is returned when no transcript has been written yet so the
dashboard can display a graceful "Preflight has not been run yet" message.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends

router = APIRouter()

# Default audits directory relative to repo root.
_REPO_ROOT = Path(__file__).resolve().parents[3]
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

    Walks one level of subdirectories (date-named dirs like 2026-04-27) sorted
    descending so the most recent transcript wins. Returns None when no
    transcript has been written yet.
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
    return sorted(candidates, key=lambda p: str(p))[-1]


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


@router.get("/preflight/latest", dependencies=[Depends(verify_auth)])
def get_preflight_latest() -> dict:
    """Return the most recent preflight transcript status.

    When no transcript exists (preflight has not run yet), returns an empty
    state with overall_status='unknown' so the dashboard can show a
    graceful empty state.
    """
    transcript_path = _find_latest_transcript(_AUDITS_DIR)
    if transcript_path is None:
        return {
            "last_run_at": None,
            "overall_status": "unknown",
            "n_pass": 0,
            "n_fail": 0,
            "items": [],
            "transcript_path": None,
        }
    text = transcript_path.read_text(encoding="utf-8")
    parsed = _parse_transcript(text)
    parsed["transcript_path"] = str(transcript_path)
    return parsed
