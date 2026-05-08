"""Shared notification config loader. Single source of truth for telegram bot config.

Called by: notifications.telegram, notifications.telegram_commands
Calls: config
Owns tables: none
Config keys: bot_token, chat_id, enabled, telegram
Tests: tests/notifications/test_check_action_reminders_isolation.py

Resolves CC2: eliminates duplicate `_get_telegram_config` definitions in
src/notifications/telegram.py:104 + src/notifications/telegram_commands.py:32.
Both modules import from this module.
"""

import os

from src.config import load_config


def _get_telegram_config() -> dict:
    """Load Telegram config from settings. .env takes precedence over YAML.

    Environment variables override YAML so that Render can set tokens via
    env vars without touching the config file.
    """
    config = load_config()
    tg = config.get("telegram", {})
    return {
        "enabled": tg.get("enabled", False),
        "bot_token": os.environ.get("TELEGRAM_BOT_TOKEN") or tg.get("bot_token", ""),
        "chat_id": os.environ.get("TELEGRAM_CHAT_ID") or str(tg.get("chat_id", "")),
    }
