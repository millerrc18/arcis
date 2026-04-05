"""Collector error classes for surfacing failures to the watch loop.

CollectorConfigError: raised when a required API key or config is missing (#124, #227).
    Before these error classes existed, collectors would silently return a success
    dict with an "error" field, which the watch loop treated as success. Now they
    raise, which _safe_run catches and properly tracks in the failure dict.

CollectorPartialFailureError: raised when >50% of items in a batch fail (#232).
    Individual item failures are expected (API rate limits, missing data for
    delisted tickers). Mass failures indicate a systemic issue (API key revoked,
    endpoint changed) that needs operator attention.
"""


class CollectorConfigError(RuntimeError):
    """A required configuration value (API key, etc.) is missing."""


class CollectorPartialFailureError(RuntimeError):
    """Too many items failed in a collection batch."""

    def __init__(self, message: str, errors: int = 0, total: int = 0):
        super().__init__(message)
        self.errors = errors
        self.total = total
