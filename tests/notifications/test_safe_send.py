"""Sprint 4 T3 — safe_send central wrapper regression tests.

Design principle: safe_send catches ONLY network errors. ImportError / NameError /
AttributeError propagate. This file locks in that contract so future "make it more
defensive" PRs can't silently re-introduce the bare-except anti-pattern.
"""

import socket
from unittest.mock import patch, MagicMock
import pytest
import requests.exceptions

from src.notifications import safe_send


class TestSafeSendNetworkFailure:
    def test_request_exception_caught_returns_false(self):
        """RequestException → caught, logged warning, returns False (not raise)."""
        with patch("src.notifications.telegram.is_telegram_enabled", return_value=True):
            with patch("src.notifications.telegram.notify_trade_opened",
                       side_effect=requests.exceptions.RequestException("network down")):
                with patch("src.notifications.telegram._record_send_failure") as mock_record:
                    result = safe_send("trade_opened", ticker="AAPL", entry_price=100.0,
                                       stop=95.0, target=110.0, score=80, shares=10)
                    assert result is False
                    mock_record.assert_called_once()


class TestSafeSendImportError:
    def test_import_error_propagates(self):
        """ImportError on a notify_* function → propagates (does NOT return False)."""
        with patch("src.notifications.telegram.is_telegram_enabled", return_value=True):
            with patch("src.notifications.telegram.notify_trade_opened",
                       side_effect=ImportError("missing module")):
                with pytest.raises(ImportError, match="missing module"):
                    safe_send("trade_opened", ticker="AAPL", entry_price=100.0,
                              stop=95.0, target=110.0, score=80, shares=10)


class TestSafeSendNameError:
    def test_name_error_propagates(self):
        """NameError inside notify_X body → propagates."""
        with patch("src.notifications.telegram.is_telegram_enabled", return_value=True):
            with patch("src.notifications.telegram.notify_trade_opened",
                       side_effect=NameError("undefined_function")):
                with pytest.raises(NameError, match="undefined_function"):
                    safe_send("trade_opened", ticker="AAPL", entry_price=100.0,
                              stop=95.0, target=110.0, score=80, shares=10)


class TestSafeSendCounter:
    def test_failed_dispatch_increments_counter(self):
        """On network failure, _record_send_failure is invoked with event_type + error string."""
        error_msg = "connection refused"
        with patch("src.notifications.telegram.is_telegram_enabled", return_value=True):
            with patch("src.notifications.telegram.notify_trade_opened",
                       side_effect=requests.exceptions.RequestException(error_msg)):
                with patch("src.notifications.telegram._record_send_failure") as mock_record:
                    safe_send("trade_opened", ticker="AAPL", entry_price=100.0,
                              stop=95.0, target=110.0, score=80, shares=10)
                    mock_record.assert_called_once_with("trade_opened", error_msg)


class TestSafeSendDisabledShortCircuit:
    def test_telegram_disabled_returns_false_no_dispatch(self):
        """is_telegram_enabled() False → returns False; no notify_X invocation."""
        with patch("src.notifications.telegram.is_telegram_enabled", return_value=False):
            with patch("src.notifications.telegram.notify_trade_opened") as mock_notify:
                result = safe_send("trade_opened", ticker="AAPL", entry_price=100.0,
                                   stop=95.0, target=110.0, score=80, shares=10)
                assert result is False
                mock_notify.assert_not_called()


class TestSafeSendSuccessPath:
    def test_success_path_invokes_notify_and_returns_true(self):
        """Happy path: notify_X invoked with kwargs, returns its return value."""
        with patch("src.notifications.telegram.is_telegram_enabled", return_value=True):
            mock_fn = MagicMock(return_value=True)
            with patch("src.notifications.telegram.notify_trade_opened", mock_fn):
                result = safe_send("trade_opened", ticker="AAPL", entry_price=100.0,
                                   stop=95.0, target=110.0, score=80, shares=10)
                assert result is True
                mock_fn.assert_called_once_with(ticker="AAPL", entry_price=100.0,
                                                stop=95.0, target=110.0, score=80,
                                                shares=10)
