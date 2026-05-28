"""T15 — digest-preview + digest-handover-check CLI tests (#115 Sprint).

Verifies:
  - cmd_digest_preview imports decorated public API (preview_tier) from email_digest,
    NOT _impl helpers (per `feedback_cli_decorated_public_api`).
  - --tier {preopen,postclose,weekly} prints plain-text body to stdout
  - --pending prints a table of pending queue rows for that tier
  - invalid --tier value errors (argparse choices)
  - --dry-run alias behaves the same as default-preview mode
  - cmd_digest_handover_check imports decorated public API (handover_check)
  - PASS yields exit code 0
  - FAIL (abandoned rows) yields exit code 1
  - --compare-window 7d triggers row-ID inclusion check (DA-MAJ-11)
"""
from __future__ import annotations

import ast
import io
import pathlib
import sys
from contextlib import redirect_stdout
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest


# Phase 5 PR-C T13 split cli/commands.py: the digest commands now live in
# commands_ops.py (commands.py is a pure re-export facade).
_COMMANDS_PATH = (
    pathlib.Path(__file__).resolve().parents[2] / "src" / "cli" / "commands_ops.py"
)


def _func_source(name: str) -> str:
    src = _COMMANDS_PATH.read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return ast.get_source_segment(src, node) or ""
    raise AssertionError(f"function {name!r} not found in cli/commands_ops.py")


# ── (a) default preview prints body to stdout ─────────────────────────────

def test_digest_preview_default_prints_body_to_stdout():
    """cmd_digest_preview --tier preopen prints preview_tier() output to stdout."""
    from src.cli import commands as cli_cmds

    expected_body = "ARCIS PRE-OPEN — May 26\n\nSection 1: ...\nSection 2: ...\n"
    with patch(
        "src.notifications.email_digest.preview_tier", return_value=expected_body
    ) as mock_preview:
        args = SimpleNamespace(tier="preopen", pending=False, dry_run=False)
        buf = io.StringIO()
        with redirect_stdout(buf):
            cli_cmds.cmd_digest_preview(args)
        mock_preview.assert_called_once_with("preopen")
        assert expected_body in buf.getvalue()


# ── (b) --pending prints table of pending queue rows ──────────────────────

def test_digest_preview_pending_prints_table():
    """cmd_digest_preview --tier preopen --pending prints a table of pending rows."""
    from src.cli import commands as cli_cmds

    # Fake DB cursor returning two pending rows for the preopen tier.
    fake_rows = [
        {
            "id": 7,
            "event_type": "audit_critical",
            "severity": "critical",
            "source_tag": "email:preopen:critical-overflow",
            "created_at": "2026-05-26T07:25:00Z",
        },
        {
            "id": 8,
            "event_type": "morning_watchlist",
            "severity": "normal",
            "source_tag": "email:preopen",
            "created_at": "2026-05-26T07:29:00Z",
        },
    ]

    fake_cur = MagicMock()
    fake_cur.fetchall.return_value = fake_rows
    fake_conn = MagicMock()
    fake_conn.execute.return_value = fake_cur
    fake_conn.__enter__ = MagicMock(return_value=fake_conn)
    fake_conn.__exit__ = MagicMock(return_value=False)

    with patch("src.cli.commands_ops.connect_db", return_value=fake_conn):
        args = SimpleNamespace(tier="preopen", pending=True, dry_run=False)
        buf = io.StringIO()
        with redirect_stdout(buf):
            cli_cmds.cmd_digest_preview(args)

    output = buf.getvalue()
    # Each pending row's id, event_type, severity, source_tag, created_at must appear
    assert "7" in output
    assert "audit_critical" in output
    assert "critical" in output
    assert "email:preopen:critical-overflow" in output
    assert "2026-05-26T07:25:00Z" in output
    assert "8" in output
    assert "morning_watchlist" in output
    assert "email:preopen" in output


# ── (c) invalid tier errors ───────────────────────────────────────────────

def test_digest_preview_invalid_tier_errors():
    """Calling cmd_digest_preview with an unknown tier raises (argparse rejects
    before dispatch, but defensive code in the cmd should also error)."""
    from src.cli import commands as cli_cmds

    args = SimpleNamespace(tier="bogus", pending=False, dry_run=False)
    with pytest.raises((ValueError, KeyError, SystemExit)):
        cli_cmds.cmd_digest_preview(args)


# ── (d) --dry-run alias ────────────────────────────────────────────────────

def test_digest_preview_dry_run_alias():
    """--dry-run is equivalent to default preview (calls preview_tier, prints body)."""
    from src.cli import commands as cli_cmds

    expected_body = "ARCIS POST-CLOSE — May 26\n\n(empty)\n"
    with patch(
        "src.notifications.email_digest.preview_tier", return_value=expected_body
    ) as mock_preview:
        args = SimpleNamespace(tier="postclose", pending=False, dry_run=True)
        buf = io.StringIO()
        with redirect_stdout(buf):
            cli_cmds.cmd_digest_preview(args)
        mock_preview.assert_called_once_with("postclose")
        assert expected_body in buf.getvalue()


# ── (e) handover-check PASS → exit 0 ──────────────────────────────────────

def test_digest_handover_check_passes_clean():
    """When handover_check() returns PASS, cmd exits with code 0."""
    from src.cli import commands as cli_cmds

    pass_result = {
        "status": "PASS",
        "tripwires": {
            "zero_abandoned_rows": "PASS (0 abandoned)",
            "preopen_flushed_weekdays": "PASS (5/5)",
            "postclose_flushed_weekdays": "PASS (5/5)",
            "weekly_flushed_once": "PASS (1/1)",
        },
    }
    with patch(
        "src.notifications.email_digest.handover_check", return_value=pass_result
    ) as mock_check:
        args = SimpleNamespace(window_days=7, compare_window=None)
        buf = io.StringIO()
        with redirect_stdout(buf):
            with pytest.raises(SystemExit) as ei:
                cli_cmds.cmd_digest_handover_check(args)
        mock_check.assert_called_once_with(window_days=7)
        assert ei.value.code == 0
        assert "PASS" in buf.getvalue()


# ── (f) handover-check FAIL → exit 1 ──────────────────────────────────────

def test_digest_handover_check_fails_on_abandoned_rows():
    """When handover_check() returns FAIL, cmd exits with code 1."""
    from src.cli import commands as cli_cmds

    fail_result = {
        "status": "FAIL",
        "tripwires": {
            "zero_abandoned_rows": "FAIL (3 abandoned rows in past 7d)",
            "preopen_flushed_weekdays": "PASS (5/5)",
            "postclose_flushed_weekdays": "FAIL (3/5)",
            "weekly_flushed_once": "PASS (1/1)",
        },
    }
    with patch(
        "src.notifications.email_digest.handover_check", return_value=fail_result
    ) as mock_check:
        args = SimpleNamespace(window_days=7, compare_window=None)
        buf = io.StringIO()
        with redirect_stdout(buf):
            with pytest.raises(SystemExit) as ei:
                cli_cmds.cmd_digest_handover_check(args)
        assert ei.value.code == 1
        out = buf.getvalue()
        assert "FAIL" in out
        assert "3 abandoned rows" in out


# ── (g) --compare-window 7d row-ID inclusion check (DA-MAJ-11) ────────────

def test_digest_handover_check_compare_window_inclusion():
    """--compare-window 7d triggers handover_check with compare_window kw OR a
    distinct row-ID inclusion code path. Verifies the flag is plumbed through
    AND that the cmd prints the row-ID inclusion verdict."""
    from src.cli import commands as cli_cmds

    pass_result = {
        "status": "PASS",
        "tripwires": {
            "row_id_inclusion": "PASS (12/12 old-eod rows present in new postclose+preopen)",
        },
    }
    with patch(
        "src.notifications.email_digest.handover_check", return_value=pass_result
    ) as mock_check:
        args = SimpleNamespace(window_days=7, compare_window="7d")
        buf = io.StringIO()
        with redirect_stdout(buf):
            with pytest.raises(SystemExit) as ei:
                cli_cmds.cmd_digest_handover_check(args)
        # handover_check must be called with compare_window passed through
        call = mock_check.call_args
        assert call is not None
        # accept either positional or kw, but compare_window must appear
        assert "compare_window" in call.kwargs or "7d" in str(call)
        assert call.kwargs.get("window_days") == 7
        assert ei.value.code == 0
        assert "row_id_inclusion" in buf.getvalue()


# ── Static guard: CLI imports the decorated public API, not _impl helpers ─

def test_cmd_digest_preview_imports_decorated_public_api():
    """Per feedback_cli_decorated_public_api: CLI MUST import preview_tier from
    src.notifications.email_digest (the decorated public surface), not from
    src.notifications.email_digest._impl or any other private helper module."""
    src = _func_source("cmd_digest_preview")
    # Importing preview_tier from email_digest (top level) is the contract.
    assert "preview_tier" in src
    # Forbid _impl shortcuts.
    assert "_impl" not in src, (
        "cmd_digest_preview MUST import preview_tier from src.notifications.email_digest, "
        "NOT from any _impl helper"
    )


def test_cmd_digest_handover_check_imports_decorated_public_api():
    src = _func_source("cmd_digest_handover_check")
    assert "handover_check" in src
    assert "_impl" not in src, (
        "cmd_digest_handover_check MUST import handover_check from "
        "src.notifications.email_digest, NOT from any _impl helper"
    )
