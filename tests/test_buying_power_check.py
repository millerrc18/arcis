"""Tests for paper entry buying power validation."""

from unittest.mock import patch, MagicMock


class TestPaperBuyingPowerCheck:
    @patch("src.shadow_trading.alpaca_adapter.get_account_info")
    @patch("src.shadow_trading.alpaca_adapter._check_enabled")
    def test_entry_rejected_when_insufficient_buying_power(self, mock_check, mock_acct):
        mock_acct.return_value = {"buying_power": 100.0, "equity": 1000.0}

        from src.shadow_trading.executor import _check_paper_buying_power
        result = _check_paper_buying_power(entry_price=150.0, shares=10)
        assert result is False

    @patch("src.shadow_trading.alpaca_adapter.get_account_info")
    @patch("src.shadow_trading.alpaca_adapter._check_enabled")
    def test_entry_allowed_when_sufficient_buying_power(self, mock_check, mock_acct):
        mock_acct.return_value = {"buying_power": 5000.0, "equity": 10000.0}

        from src.shadow_trading.executor import _check_paper_buying_power
        result = _check_paper_buying_power(entry_price=150.0, shares=10)
        assert result is True
