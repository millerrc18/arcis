"""Notifications exception types (T10 Sprint 5 Wave D D1).

Called by: src/notifications/telegram.py, src/notifications/policy.py, src/main.py
Calls: none
Owns tables: none
Config keys: notifications.*
Tests: tests/notifications/test_policy.py
"""


class NotificationsError(Exception):
    """Base class for all notifications exceptions."""


class NotificationsConfigError(NotificationsError):
    """Raised when the notifications config fails validation."""
