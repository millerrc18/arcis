"""Startup validation checks for Arcis.

Called by: cli.commands (cmd_startup)
Calls: startup_checks, config, evaluation.system_validator
Owns tables: none (writes to validation_results via system_validator.save_validation_result)
Config keys: alpaca, render, telegram, email, shadow_trading, live_trading, risk, llm, training
Tests: tests/test_startup.py

Runs tiered validation (critical / warning) before launching the watch loop.
Each check_* function is independent and returns results immediately for
progressive CLI output. Check implementations live in src/startup_checks.py.
"""

import logging
import os
import re
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from src.config import DB_PATH
from src.utils.db import connect_db

logger = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")


# ── Data classes ─────────────────────────────────────────────────────


@dataclass
class CheckResult:
    name: str
    category: str       # "config", "schema", "environment", "connectivity", "services"
    status: str         # "ok", "warn", "critical"
    detail: str
    fix_hint: str       # MANDATORY — actionable fix message


@dataclass
class StartupResult:
    checks: list[CheckResult] = field(default_factory=list)
    schema_fixes_applied: int = 0
    duration_ms: int = 0
    timestamp: str = ""

    @property
    def criticals(self) -> list[CheckResult]:
        return [c for c in self.checks if c.status == "critical"]

    @property
    def warnings(self) -> list[CheckResult]:
        return [c for c in self.checks if c.status == "warn"]

    @property
    def passed(self) -> list[CheckResult]:
        return [c for c in self.checks if c.status == "ok"]

    @property
    def overall_status(self) -> str:
        if self.criticals:
            return "critical"
        if self.warnings:
            return "degraded"
        return "healthy"


# ── PID lockfile check ───────────────────────────────────────────────


def is_watch_loop_running() -> int | None:
    """Check data/watch.lock. Returns PID if another watch loop is running, None otherwise."""
    lockfile = Path("data/watch.lock")
    if not lockfile.exists():
        return None
    try:
        old_pid = int(lockfile.read_text().strip())
        import psutil
        if psutil.pid_exists(old_pid):
            return old_pid
    except ImportError:
        try:
            os.kill(old_pid, 0)
            return old_pid
        except (OSError, ProcessLookupError):
            pass
    except (ValueError, OSError):
        pass
    return None


# ── Re-export check functions (preserve import interface) ────────────

from src.startup_checks import (  # noqa: E402
    check_config,
    check_connectivity,
    check_environment,
    check_schema,
    check_services,
)


# ── Persistence ──────────────────────────────────────────────────────


def persist_startup_result(result: StartupResult, db_path: str = DB_PATH) -> str:
    """Save startup result to validation_results table. Returns result_id."""
    from src.evaluation.system_validator import save_validation_result

    checks_by_category = {}
    for c in result.checks:
        checks_by_category.setdefault(c.category, []).append({
            "name": c.name,
            "status": c.status,
            "detail": c.detail,
            "fix_hint": c.fix_hint,
        })

    payload = {
        "timestamp": result.timestamp,
        "overall_status": result.overall_status,
        "checks_passed": len(result.passed),
        "checks_failed": len(result.criticals),
        "checks_warning": len(result.warnings),
        "checks_total": len(result.checks),
        "trigger": "startup",
        "duration_ms": result.duration_ms,
        "schema_fixes_applied": result.schema_fixes_applied,
        "categories": checks_by_category,
    }

    return save_validation_result(payload, db_path)


def get_previous_startup_status(db_path: str = DB_PATH) -> str | None:
    """Get the overall_status from the most recent startup validation result."""
    try:
        with connect_db(db_path) as conn:
            row = conn.execute(
                "SELECT overall_status FROM validation_results "
                "WHERE results_json LIKE '%\"trigger\": \"startup\"%' "
                "ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
            return row[0] if row else None
    except Exception:
        return None


# ── Run all checks ───────────────────────────────────────────────────

STARTUP_CATEGORIES = [
    ("Config", check_config),
    ("Schema", check_schema),
    ("Environment", check_environment),
    ("Connectivity", check_connectivity),
    ("Services", check_services),
]


def run_startup_checks(config: dict, db_path: str = DB_PATH) -> StartupResult:
    """Run all startup validation checks. Returns structured result."""
    start = time.time()
    all_checks = []

    for _label, check_fn in STARTUP_CATEGORIES:
        results = check_fn(config, db_path)
        all_checks.extend(results)

    schema_fixes = 0
    for c in all_checks:
        if c.category == "schema" and "auto-fixed" in c.detail:
            m = re.search(r"(\d+) auto-fixed", c.detail)
            if m:
                schema_fixes = int(m.group(1))

    elapsed = int((time.time() - start) * 1000)
    return StartupResult(
        checks=all_checks,
        schema_fixes_applied=schema_fixes,
        duration_ms=elapsed,
        timestamp=datetime.now(ET).isoformat(),
    )


# ── Capability Registry registration (Sprint 1B) ───────────────────────

from datetime import date as _reg_date  # noqa: E402

from src.platform.capability_registry import register_system  # noqa: E402


@register_system(
    name="watch_loop",
    description=(
        "The main daemon that schedules scans, reconciliation, overnight "
        "jobs, and notifications. Presence detected via data/watch.lock "
        "PID file. Without it, no automated trading activity occurs."
    ),
    category="orchestration",
    version="1.0",
    maintainer="operator",
    introduced_in="v0.10.0",
    last_reviewed_date=_reg_date(2026, 4, 18),
    expected_runtime="always (24/7)",
)
def watch_loop_health() -> dict:
    pid = is_watch_loop_running()
    if pid is None:
        return {
            "status": "down",
            "detail": "no watch.lock PID file or stale PID",
        }
    return {
        "status": "ok",
        "detail": f"running under PID {pid}",
        "pid": int(pid),
    }
