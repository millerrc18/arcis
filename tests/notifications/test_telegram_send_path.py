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


def test_notify_manual_intervention_drift_html_escapes_user_fields():
    """Regression-lock: notify_manual_intervention_drift must escape ticker, expected_state, actual_state, severity before HTML interpolation.

    Security review of T4 (sp5-c4) flagged that the function bypassed the module-wide _html_escape discipline.
    If a broker response ever produces a state string containing '<' / '>' / '&', Telegram's HTML parser
    400s the message — silently losing the drift alert. This test fails loudly if the escape regresses.
    """
    from src.notifications.telegram import notify_manual_intervention_drift

    payload = {
        "ticker": "AAPL",
        "expected_state": "open<script>",
        "actual_state": "closed & gone",
        "divergence_age_minutes": 47,
    }

    with patch("src.notifications.telegram.send_telegram", return_value=True) as mock_send:
        notify_manual_intervention_drift(payload, severity="high")

    assert mock_send.call_count == 1
    msg = mock_send.call_args[0][0]

    assert "<script>" not in msg, (
        "Raw HTML tag survived in message — _html_escape was bypassed. "
        f"Got: {msg!r}"
    )
    assert "&lt;" in msg, (
        "Expected '<' to be escaped to '&lt;'. "
        f"Got: {msg!r}"
    )
    assert "&amp;" in msg, (
        "Expected '&' to be escaped to '&amp;'. "
        f"Got: {msg!r}"
    )
