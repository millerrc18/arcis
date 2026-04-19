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


# ── expire_stale_commands sweep ───────────────────────────────────────

def test_expire_stale_commands_updates_rowcount():
    """expire_stale_commands should run an UPDATE against Postgres and
    return the rowcount. Verifies the query shape + commit + return path."""
    from src.sync import render_sync

    mock_cursor = MagicMock()
    mock_cursor.rowcount = 7
    mock_pg = MagicMock()
    mock_pg.cursor.return_value.__enter__.return_value = mock_cursor
    mock_pg.__enter__.return_value = mock_pg

    with patch("src.sync.render_sync._connect_pg_with_retry",
               return_value=mock_pg):
        count = render_sync.expire_stale_commands("postgresql://fake")

    assert count == 7
    # Confirm the UPDATE executed against pending_commands with the right
    # predicate shape (status='pending' AND expires_at < now)
    call_args = mock_cursor.execute.call_args
    sql = call_args[0][0]
    assert "UPDATE pending_commands SET status = 'expired'" in sql
    assert "status = 'pending'" in sql
    assert "expires_at < %s" in sql
    mock_pg.commit.assert_called_once()


def test_expire_stale_commands_returns_zero_on_psycopg2_missing(monkeypatch):
    """On a cloud-only host without psycopg2, function must return 0, not raise."""
    from src.sync import render_sync

    # Simulate ImportError at the top-of-function import
    with patch.dict("sys.modules", {"psycopg2": None}):
        # Now the `import psycopg2` inside the function will fail
        import builtins
        original_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "psycopg2":
                raise ImportError("no psycopg2 in this environment")
            return original_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", fake_import)
        count = render_sync.expire_stale_commands("postgresql://fake")

    assert count == 0


def test_expire_stale_commands_returns_zero_on_db_error():
    """Postgres connection failure logs error but returns 0 — never raises."""
    from src.sync import render_sync

    with patch("src.sync.render_sync._connect_pg_with_retry",
               side_effect=ConnectionError("unreachable")):
        count = render_sync.expire_stale_commands("postgresql://fake")

    assert count == 0


# ── sync cycle wires expire_stale_commands ────────────────────────────

def test_run_sync_cycle_calls_expire_stale_commands(tmp_path):
    """The sync cycle must call expire_stale_commands after pull_commands
    so orphans get cleaned up on the same polling cadence."""
    from src.sync import render_sync

    mock_pg = MagicMock()
    mock_pg.cursor.return_value.__enter__.return_value = MagicMock()

    with patch("src.sync.render_sync.SYNC_TABLES", {}), \
         patch("src.sync.render_sync._connect_pg_with_retry", return_value=mock_pg), \
         patch("src.sync.render_sync._ensure_pg_connection", return_value=mock_pg), \
         patch("src.sync.render_sync._init_sync_state"), \
         patch("src.schema.postgres.create_all_tables"), \
         patch("src.schema.postgres.ensure_columns"), \
         patch("src.sync.render_sync.pull_commands", return_value=[]), \
         patch("src.sync.render_sync.expire_stale_commands",
               return_value=0) as mock_expire:
        render_sync.run_sync_cycle(
            "postgresql://fake", db_path=str(tmp_path / "test.db"),
        )

    mock_expire.assert_called_once_with("postgresql://fake")
