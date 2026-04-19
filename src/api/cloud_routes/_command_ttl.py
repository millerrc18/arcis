"""Per-command-name TTL for pending_commands.expires_at.

Background: the default 5-minute TTL is deliberately short for trading
actions (halt/resume/close) so a stale command submitted while the local
machine is offline does not fire hours later when the machine reconnects
and the market has moved. Diagnostic / analysis commands don't have that
risk — they're read-only — so a short TTL there just causes dashboard
button clicks to silently expire before the operator returns to the
machine. See GH audit trail on the command-queue investigation.

Called by: api.cloud_routes.core._submit_command, cloud_routes.diagnostics._submit_diagnostic
Calls: none (stdlib-only constants)
Owns tables: none
Config keys: none
Tests: tests/api/test_command_ttl.py
"""
from __future__ import annotations

# Trading-sensitive commands keep a short TTL so a stale submission cannot
# execute after the local machine reconnects from a long outage.
_SAFE_TRADING_COMMANDS = frozenset({
    "halt-trading", "resume-trading", "close-position",
})

# Config changes get a medium TTL — enough to survive a typical brief
# outage but short enough that stale setting-flips don't silently apply.
_CONFIG_COMMANDS = frozenset({
    "update_setting",
})

# Analysis / diagnostic / long-running commands get a long TTL. Safe to
# delay because they're read-only from the trading system's perspective.
_ANALYSIS_COMMANDS = frozenset({
    "scan", "council", "collect-data", "collect-training", "train-pipeline",
    "validate-system", "cto-report", "stress-test", "simulation",
    "get_logs", "run-regime-diagnostic", "run-forensic-audit",
    "run-training-audit",
})

TTL_TRADING_MINUTES = 5
TTL_CONFIG_MINUTES = 15
TTL_ANALYSIS_MINUTES = 240  # 4 hours — covers typical machine-off windows


def ttl_minutes_for(command_name: str) -> int:
    """Return the appropriate expires_at window for the given command name.

    Unknown commands default to TTL_TRADING_MINUTES (conservative — short
    TTL is always safer than long). Adding a command means adding an entry
    here; the default protects forgotten additions.
    """
    if command_name in _SAFE_TRADING_COMMANDS:
        return TTL_TRADING_MINUTES
    if command_name in _CONFIG_COMMANDS:
        return TTL_CONFIG_MINUTES
    if command_name in _ANALYSIS_COMMANDS:
        return TTL_ANALYSIS_MINUTES
    return TTL_TRADING_MINUTES
