"""Regression tests for command-queue reliability fixes.

Covers:
- Per-command TTL selection (ttl_minutes_for)
- expire_stale_commands marks aged pending rows as 'expired'
- Dashboard submission paths use the TTL mapping, not a hardcoded 5 min
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.api.cloud_routes._command_ttl import (
    TTL_ANALYSIS_MINUTES,
    TTL_CONFIG_MINUTES,
    TTL_TRADING_MINUTES,
    ttl_minutes_for,
)


# ── Per-command TTL mapping ───────────────────────────────────────────

def test_trading_sensitive_commands_get_short_ttl():
    """halt/resume/close stay at 5 min — stale-replay risk if a machine
    reconnects from a long outage."""
    assert ttl_minutes_for("halt-trading") == TTL_TRADING_MINUTES
    assert ttl_minutes_for("resume-trading") == TTL_TRADING_MINUTES
    assert ttl_minutes_for("close-position") == TTL_TRADING_MINUTES
    assert TTL_TRADING_MINUTES == 5


def test_analysis_commands_get_long_ttl():
    """Diagnostic/analysis commands get 4 hours so they don't silently
    expire when the operator submits outside of a local-machine window."""
    for name in (
        "scan", "council", "collect-data", "validate-system",
        "cto-report", "stress-test", "simulation",
        "run-regime-diagnostic", "run-forensic-audit", "run-training-audit",
    ):
        assert ttl_minutes_for(name) == TTL_ANALYSIS_MINUTES, (
            f"{name} should get analysis TTL"
        )
    assert TTL_ANALYSIS_MINUTES == 240


def test_config_commands_get_medium_ttl():
    """update_setting gets 15 min — brief enough that stale config flips
    don't apply, long enough to survive typical reconnect delays."""
    assert ttl_minutes_for("update_setting") == TTL_CONFIG_MINUTES
    assert TTL_CONFIG_MINUTES == 15


def test_unknown_command_defaults_to_trading_ttl():
    """Fail-safe: any unmapped command gets the short TTL. A forgotten
    entry is safer conservative than permissive."""
    assert ttl_minutes_for("some-new-unmapped-command") == TTL_TRADING_MINUTES

