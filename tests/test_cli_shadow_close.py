"""Regression tests for #502: cmd_shadow_close must surface Alpaca errors.

Before this fix the bare `except Exception: pass` silently swallowed every
Alpaca SDK exception, leaving the local ledger closed while the broker still
held the position. Tests verify specific exception types are logged + printed
loudly; unknown exceptions re-raise.
"""
from __future__ import annotations

import logging
from unittest.mock import patch

import pytest


class _Args:
    def __init__(self, ticker: str, reason: str = "manual"):
        self.ticker = ticker
        self.reason = reason


def test_cmd_shadow_close_logs_apierror_and_continues_local_close(caplog, capsys):
    """When place_paper_exit raises APIError, cmd_shadow_close must log at ERROR
    level and print a warning — NOT swallow silently. Local close still proceeds
    so reconciliation can catch the mismatch (#502)."""
    from alpaca.common.exceptions import APIError

    from src.cli import commands as cli_cmds

    trade = {"trade_id": "t-abc", "ticker": "JPM", "entry_price": 150.0,
             "actual_entry_price": 150.0, "planned_shares": 10}

    # cmd_shadow_close imports these at call time — patch the source modules
    with patch("src.journal.store.get_open_shadow_trades", return_value=[trade]), \
         patch("src.journal.store.close_shadow_trade") as mock_close, \
         patch("src.shadow_trading.executor._get_current_price_safe", return_value=152.0), \
         patch("src.shadow_trading.alpaca_adapter.place_paper_exit",
               side_effect=APIError({"code": 40010001, "message": "rejected"})):
        caplog.set_level(logging.ERROR)
        cli_cmds.cmd_shadow_close(_Args("JPM"))

    # Local close MUST still run (preserves behavior; reconciliation is the net)
    mock_close.assert_called_once()
    # Error logged with stack trace
    alpaca_errors = [r for r in caplog.records if "Alpaca APIError" in r.message]
    assert alpaca_errors, "APIError from Alpaca must log at ERROR level (#502)"
    # Warning printed so the CLI user sees it
    captured = capsys.readouterr()
    assert "Alpaca rejected" in captured.out, (
        "cmd_shadow_close must print a visible warning on APIError (#502)"
    )


def test_cmd_shadow_close_reraises_unknown_exception(caplog):
    """Unknown exceptions must propagate (do NOT swallow, per #502)."""
    from src.cli import commands as cli_cmds

    trade = {"trade_id": "t-xyz", "ticker": "BAC", "entry_price": 40.0,
             "actual_entry_price": 40.0, "planned_shares": 20}

    with patch("src.journal.store.get_open_shadow_trades", return_value=[trade]), \
         patch("src.journal.store.close_shadow_trade"), \
         patch("src.shadow_trading.executor._get_current_price_safe", return_value=41.0), \
         patch("src.shadow_trading.alpaca_adapter.place_paper_exit",
               side_effect=ValueError("unexpected bug")):
        caplog.set_level(logging.ERROR)
        with pytest.raises(ValueError, match="unexpected bug"):
            cli_cmds.cmd_shadow_close(_Args("BAC"))

    unexpected = [r for r in caplog.records if "Unexpected error on paper exit" in r.message]
    assert unexpected, "Unknown exceptions must log at ERROR before re-raise (#502)"
