"""Regression: Telegram bot token must never leak via exception logs.

Pre-#424, src/notifications/telegram.py:131 and :134 logged
`requests.post` exceptions with `logger.warning(..., %s, e)`. The
exception message often included the URL `https://api.telegram.org/
bot<TOKEN>/sendMessage`, leaking the bot token to wherever logs ship
(Loki, files, dashboard streams). This test ensures the redaction
helper sanitizes the token from any exception representation that
includes the standard Telegram URL pattern.
"""
import logging
from unittest.mock import patch, MagicMock

import pytest


def test_redact_token_strips_telegram_bot_url():
    """Exception messages containing the bot URL must have the token replaced."""
    from src.notifications.telegram import _redact_token

    raw = (
        "HTTPSConnectionPool(host='api.telegram.org', port=443): "
        "Max retries exceeded with url: /bot1234567890:ABC-DEF_real-secret-here/sendMessage"
    )
    redacted = _redact_token(raw)
    assert "1234567890:ABC-DEF_real-secret-here" not in redacted
    assert "[REDACTED]" in redacted


def test_redact_token_handles_exception_object():
    """Should accept an Exception instance directly, not just str."""
    from src.notifications.telegram import _redact_token

    exc = Exception(
        "ConnectionError at https://api.telegram.org/bot987:XYZ_secret/sendMessage"
    )
    redacted = _redact_token(exc)
    assert "987:XYZ_secret" not in redacted
    assert "[REDACTED]" in redacted


def test_redact_token_passthrough_when_no_token():
    """Non-token-bearing strings should pass through unchanged."""
    from src.notifications.telegram import _redact_token

    safe = "ConnectionError: timed out"
    assert _redact_token(safe) == safe


def test_send_telegram_logs_redacted_on_exception(caplog):
    """End-to-end: send_telegram's except block must log redacted text."""
    from src.notifications.telegram import send_telegram

    with patch(
        "src.notifications.telegram._get_telegram_config",
        return_value={"enabled": True, "bot_token": "987:XYZ_real_token", "chat_id": "1"},
    ), patch(
        "src.notifications.telegram.requests.post",
        side_effect=Exception(
            "ConnectionError at https://api.telegram.org/bot987:XYZ_real_token/sendMessage"
        ),
    ):
        with caplog.at_level(logging.WARNING):
            result = send_telegram("test")

    assert result is False
    # The token must NOT appear anywhere in the captured log output.
    full_log = "\n".join(r.getMessage() for r in caplog.records)
    assert "987:XYZ_real_token" not in full_log, (
        f"Token leaked in log output:\n{full_log}"
    )
