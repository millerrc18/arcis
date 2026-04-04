"""Collector error classes for surfacing failures to the watch loop.

CollectorConfigError: raised when a required API key or config is missing.
CollectorPartialFailureError: raised when >50% of items in a batch fail.
"""


class CollectorConfigError(RuntimeError):
    """A required configuration value (API key, etc.) is missing."""


class CollectorPartialFailureError(RuntimeError):
    """Too many items failed in a collection batch."""

    def __init__(self, message: str, errors: int = 0, total: int = 0):
        super().__init__(message)
        self.errors = errors
        self.total = total
