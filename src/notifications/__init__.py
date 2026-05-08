"""Notification subsystem — telegram + email channels.

Public API:
    safe_send: central dispatcher; catches ONLY network errors.
    is_telegram_enabled: gate function for callers.

Direct notify_* imports remain available for backward compat during T4 migration.
"""

from src.notifications.telegram import safe_send, is_telegram_enabled

__all__ = ["safe_send", "is_telegram_enabled"]
