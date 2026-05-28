"""T12 — CLI email passthrough tests (#115 Sprint, DD-13 + DA-MAJ-8).

Verifies:
  - send-test-email CLI invokes send_email directly (operator escape hatch)
  - cto-report --email invokes send_email directly (operator escape hatch)
  - cto-report --email does NOT also enqueue to postclose digest
    (DA-MAJ-8 anti-double-deliver)
  - cmd_scan / cmd_eod_recap / cmd_morning_watchlist pass via_cli=True down
    to their service functions
"""
from __future__ import annotations

import ast
import inspect
import pathlib
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest


# Phase 5 PR-C T13 split cli/commands.py into category sub-modules. The
# command bodies now live in commands_data.py / commands_training.py /
# commands_ops.py (commands.py is a pure re-export facade). _func_source
# searches all three so the source-text assertions below follow the moved
# functions to their new home.
_CLI_DIR = pathlib.Path(__file__).resolve().parents[2] / "src" / "cli"
_COMMANDS_PATHS = (
    _CLI_DIR / "commands_data.py",
    _CLI_DIR / "commands_training.py",
    _CLI_DIR / "commands_ops.py",
)


def _func_source(name: str) -> str:
    """Pull the source text of a top-level function from the cli command modules."""
    for path in _COMMANDS_PATHS:
        src = path.read_text(encoding="utf-8")
        tree = ast.parse(src)
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
                return ast.get_source_segment(src, node) or ""
    raise AssertionError(f"function {name!r} not found in any cli command sub-module")


def test_send_test_email_cli_bypasses_aggregator():
    """cmd_send_test_email must call send_email directly (no enqueue).
    DD-13: operator escape hatch."""
    src = _func_source("cmd_send_test_email")
    assert "send_email(" in src, "cmd_send_test_email must call send_email directly"
    assert "enqueue_for_email_digest" not in src, (
        "cmd_send_test_email MUST NOT enqueue — it's the operator escape hatch (DD-13)"
    )


def test_cto_report_email_cli_bypasses_aggregator():
    """cmd_cto_report must call send_email directly when --email is given."""
    src = _func_source("cmd_cto_report")
    assert "send_email(" in src, "cmd_cto_report must retain send_email call"


def test_cli_cto_report_does_not_enqueue_to_postclose():
    """DA-MAJ-8: cmd_cto_report --email must NOT also enqueue.
    Verifies the function body never references enqueue_for_email_digest."""
    src = _func_source("cmd_cto_report")
    assert "enqueue_for_email_digest" not in src, (
        "DA-MAJ-8 anti-double-deliver: cmd_cto_report MUST NOT enqueue when "
        "--email is passed (would cause double-delivery via postclose digest)"
    )


def test_cmd_scan_passes_via_cli_true():
    """cmd_scan must pass via_cli=True to run_scan."""
    src = _func_source("cmd_scan")
    assert "via_cli=True" in src, (
        "cmd_scan must pass via_cli=True to run_scan (DD-13 CLI escape hatch)"
    )


def test_cmd_eod_recap_passes_via_cli_true():
    src = _func_source("cmd_eod_recap")
    assert "via_cli=True" in src, (
        "cmd_eod_recap must pass via_cli=True to generate_eod_recap"
    )


def test_cmd_morning_watchlist_passes_via_cli_true():
    src = _func_source("cmd_morning_watchlist")
    assert "via_cli=True" in src, (
        "cmd_morning_watchlist must pass via_cli=True to generate_morning_watchlist"
    )


def test_cmd_send_test_email_invokes_send_email_directly():
    """Functional: when cmd_send_test_email runs, send_email is called once."""
    from src.cli import commands as cli_cmds

    with patch("src.cli.commands_ops.send_email", return_value=True) as mock_send:
        args = SimpleNamespace()
        cli_cmds.cmd_send_test_email(args)
        mock_send.assert_called_once()


def test_cmd_cto_report_email_does_not_enqueue():
    """Functional: cmd_cto_report --email calls send_email once; never enqueue."""
    from src.cli import commands as cli_cmds

    with patch("src.cli.commands_training.send_email", return_value=True) as mock_send, \
         patch("src.evaluation.cto_report.generate_cto_report",
               return_value={"summary": "test"}), \
         patch("src.evaluation.cto_report.format_cto_report", return_value="formatted"), \
         patch("src.notifications.email_digest.enqueue_for_email_digest") as mock_enqueue:
        args = SimpleNamespace(email=True, days=7, json=False)
        cli_cmds.cmd_cto_report(args)
        mock_send.assert_called_once()
        mock_enqueue.assert_not_called()
