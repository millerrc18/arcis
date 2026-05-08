"""Foundation send-path test for Telegram (CC5).

Module: tests.notifications.test_telegram_send_path
Purpose: End-to-end send → API mock → assertion foundation test.
         Verifies that send_telegram() calls the Telegram API with the
         correct payload and returns True on HTTP 200.
Called by: pytest
Owns tables: none
Config keys: none
"""

from unittest.mock import MagicMock, patch


class TestTelegramSendPath:
    """Foundation send-path: send_telegram → POST to Telegram API → returns True."""

    def test_send_telegram_calls_api_and_returns_true(self):
        """send_telegram posts to API with correct payload and returns True on 200."""
        mock_cfg = {
            "enabled": True,
            "bot_token": "12345:TESTTOKEN",
            "chat_id": "99999",
        }
        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch(
            "src.notifications.telegram._get_telegram_config",
            return_value=mock_cfg,
        ):
            with patch(
                "src.notifications.telegram.requests.post",
                return_value=mock_response,
            ) as mock_post:
                from src.notifications.telegram import send_telegram

                result = send_telegram("hello test message")

        assert result is True
        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args
        payload = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json") or call_kwargs[0][1]
        assert payload["chat_id"] == "99999"
        assert payload["text"] == "hello test message"
