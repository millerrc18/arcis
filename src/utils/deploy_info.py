"""Deployment info banner + drift detection (#630).

Called by: cli.commands.cmd_startup, scheduler.watch.WatchLoop.run
Calls: utils.activity_logger
Owns tables: none
Config keys: none
Tests: tests/test_deploy_info.py

Captures the deployed git SHA + commit age at startup so operators can spot when
a long-running watch loop is still running stale bytecode after a fix has landed
on main. Without this, the loop continues to emit errors that look like "fix
didn't work" when the real cause is "fix is on disk but the running process
predates it." The 2026-04-23 audit found two examples (#619 emoji crash post-
bf63dc5, #622 signal-handler ValueError).
"""

from __future__ import annotations

import json
import logging
import subprocess
import sys

from src.utils.activity_logger import SYSTEM_EVENT, log_activity

logger = logging.getLogger(__name__)


def _run_git(*args: str) -> str:
    """Run a git command and return stripped stdout. Raises on non-zero or missing git."""
    out = subprocess.check_output(["git", *args], stderr=subprocess.DEVNULL, text=True)
    return out.strip()


def get_deployment_info() -> dict[str, str]:
    """Return git SHA + commit age + python version for the running process."""
    info: dict[str, str] = {
        "python_version": ".".join(str(p) for p in sys.version_info[:3]),
    }
    try:
        info["git_sha"] = _run_git("rev-parse", "HEAD")
        info["git_short_sha"] = info["git_sha"][:8]
        info["git_commit_age"] = _run_git("log", "-1", "--format=%cr")
        info["git_branch"] = _run_git("rev-parse", "--abbrev-ref", "HEAD")
    except (FileNotFoundError, subprocess.CalledProcessError) as exc:
        # Not in a git checkout, or git not on PATH — degrade gracefully.
        logger.debug("[DEPLOY] git info unavailable: %s", exc)
        info.setdefault("git_sha", "unknown")
        info.setdefault("git_short_sha", "unknown")
        info.setdefault("git_commit_age", "unknown")
        info.setdefault("git_branch", "unknown")
    return info


def log_deployment_info(event: str = "startup") -> dict[str, str]:
    """Emit a structured startup banner + write to activity_log.

    The banner provides immediate visual feedback ("am I running the latest
    code?") and the activity_log row provides historical drift audit. Failure
    to write either must NOT abort startup — best-effort observability.
    """
    info = get_deployment_info()
    logger.info(
        "[STARTUP] event=%s sha=%s branch=%s committed=%s python=%s",
        event,
        info.get("git_short_sha"),
        info.get("git_branch"),
        info.get("git_commit_age"),
        info.get("python_version"),
    )
    try:
        log_activity(
            SYSTEM_EVENT,
            json.dumps({"event": event, **info}),
        )
    except Exception as exc:
        # Never let a failed activity-log write crash startup.
        logger.warning("[DEPLOY] activity_log write failed: %s", exc)
    return info
