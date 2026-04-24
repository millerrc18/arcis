"""Tests for #630 — deployment info banner + drift detection."""

from __future__ import annotations

import sys
from unittest.mock import patch

import pytest


def test_get_deployment_info_returns_required_fields():
    from src.utils.deploy_info import get_deployment_info

    info = get_deployment_info()
    assert "git_sha" in info
    assert "git_short_sha" in info
    assert "git_commit_age" in info
    assert "python_version" in info
    # short SHA is 7-12 hex chars when in a real repo, "unknown" otherwise
    assert isinstance(info["git_short_sha"], str)


def test_get_deployment_info_handles_missing_git_gracefully():
    from src.utils.deploy_info import get_deployment_info

    with patch("src.utils.deploy_info._run_git", side_effect=FileNotFoundError):
        info = get_deployment_info()
    assert info["git_sha"] == "unknown"
    assert info["git_short_sha"] == "unknown"
    assert info["git_commit_age"] == "unknown"
    # python version should still be present
    assert info["python_version"].startswith(str(sys.version_info.major))


def test_log_deployment_info_emits_log_and_activity_row(caplog):
    import logging
    from src.utils.deploy_info import log_deployment_info

    activity_calls: list[tuple[str, str, str]] = []

    def fake_log_activity(event_type, detail, *args, **kwargs):
        activity_calls.append((event_type, detail, kwargs.get("level", "info")))

    with patch("src.utils.deploy_info.log_activity", side_effect=fake_log_activity):
        with caplog.at_level(logging.INFO, logger="src.utils.deploy_info"):
            log_deployment_info("watch_start")

    # The startup banner must surface in the structured log AND activity_log.
    assert any("[STARTUP]" in r.message for r in caplog.records)
    assert activity_calls, "log_activity must be called at startup"
    event_type, detail, _level = activity_calls[0]
    assert event_type  # non-empty event type written to activity_log
    assert "git_sha" in detail or "watch_start" in detail


def test_log_deployment_info_does_not_raise_when_activity_log_fails():
    """Startup must not abort if activity_log write blows up."""
    from src.utils.deploy_info import log_deployment_info

    with patch("src.utils.deploy_info.log_activity", side_effect=RuntimeError("db locked")):
        # Must not raise — startup should continue even if logging fails.
        log_deployment_info("watch_start")
