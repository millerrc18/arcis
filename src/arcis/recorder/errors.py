"""Typed errors for the news recorder. Every failure mode has its own
type; nothing is raised as a bare Exception outside the CLI boundary."""
from __future__ import annotations


class RecorderError(Exception):
    """Base type for all recorder failures."""


class ConfigError(RecorderError):
    """Configuration is missing, invalid, or unsafe."""


class UniverseError(RecorderError):
    """Universe snapshot is missing, mismatched, or would be mutated."""


class StoreError(RecorderError):
    """Append-only store or manifest invariant violated."""


class StorageLayoutError(StoreError):
    """A path escaped the data root or the layout was violated."""


class VerifyError(RecorderError):
    """Verification of stored data failed."""


class ClientError(RecorderError):
    """Alpaca API client failure (transport, auth, rate limit, schema)."""


class AuthError(ClientError):
    """Alpaca rejected the credentials (401/403)."""


class RateLimitError(ClientError):
    """Rate limit still in effect after retries (429)."""


class ClockError(RecorderError):
    """Alpaca clock skew exceeds the allowed maximum; refusing to record."""


class LockError(RecorderError):
    """Another poll holds the recorder lock."""
