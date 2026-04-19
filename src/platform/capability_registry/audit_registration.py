"""Capability registration for the nightly audit agent (Claude Code /audit).

The /audit slash command is a Claude Code plugin, not a Python daemon.
Its "health" is a derived signal from the baseline file:

- config/daily_repo_audit_baseline.json exists → configured
- mtime within 14 days → recently reviewed
- expected_failures count → tracks known open issues

Since the command runs via Claude Code, not an in-process daemon, there
is no lockfile or running process to probe — the file-based signal is
the best honest answer.

Called by: src.platform.capability_registry.bootstrap (import-time side effect)
Calls: src.platform.capability_registry.register_system
Owns tables: none (reads config/daily_repo_audit_baseline.json)
Config keys: none
Tests: tests/platform/test_capability_registry.py (end-to-end via bootstrap)
"""
from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path

from src.platform.capability_registry import register_system

_BASELINE_PATH = Path("config/daily_repo_audit_baseline.json")
_STALE_AFTER_DAYS = 14


def _audit_status() -> dict:
    if not _BASELINE_PATH.exists():
        return {
            "status": "down",
            "detail": "daily_repo_audit_baseline.json missing",
        }
    try:
        content = json.loads(_BASELINE_PATH.read_text())
        expected_failures = content.get("expected_failures", [])
    except Exception as exc:  # noqa: BLE001
        return {
            "status": "unavailable",
            "detail": f"baseline unreadable: {exc}",
        }
    mtime = datetime.fromtimestamp(_BASELINE_PATH.stat().st_mtime, tz=timezone.utc)
    age_days = (datetime.now(timezone.utc) - mtime).days
    status = "ok" if age_days <= _STALE_AFTER_DAYS else "degraded"
    return {
        "status": status,
        "detail": (
            f"baseline last updated {age_days}d ago, "
            f"{len(expected_failures)} known findings"
        ),
        "age_days": age_days,
        "known_findings": len(expected_failures),
    }


@register_system(
    name="nightly_audit_agent",
    description=(
        "The /audit Claude Code command runs parallel domain audit "
        "agents and files GitHub issues. Not a running daemon; health "
        "= baseline file present + recent mtime + known_findings count."
    ),
    category="audit",
    version="1.0",
    maintainer="operator",
    introduced_in="v0.20.0",
    last_reviewed_date=date(2026, 4, 18),
    expected_runtime="on-demand (operator invokes)",
)
def nightly_audit_agent_health() -> dict:
    return _audit_status()
