"""Credential redaction for exception strings and persisted payloads.

Called by: evaluation.system_validator, startup_checks
Calls: none (stdlib only)
Owns tables: none
Config keys: none
Tests: tests/test_system_validator_sanitize.py, tests/test_secret_redact.py

Exception messages from ``requests`` and ``psycopg2`` routinely embed the
full URL — Telegram bot tokens, postgres user:password, bearer keys — and
``str(e)[:N]`` truncation at call sites does not reliably strip them.  Any
such string reaching ``validation_results`` (90-day retention) or log
handlers is a credential leak.  Audit #414.

Lives in ``src.utils`` (not ``src.evaluation``) so that ``startup_checks``
— which must run before heavy modules like ``system_validator`` load —
can import the helper without pulling evaluation's dep graph.
"""
from __future__ import annotations

import re

# Patterns ordered longest-first so URL-embedded creds are scrubbed before
# the shorter ``password=`` or ``api_key=`` fallbacks catch the tail.
_TOKEN_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"bot\d+:[A-Za-z0-9_-]{20,}"),           # Telegram bot tokens
    re.compile(r"://[^/\s]+:[^/\s@]+@"),                 # URL-embedded creds
    re.compile(r"(?i)password=[^\s&]+"),
    re.compile(r"(?i)api[_-]?key=[^\s&]+"),
    re.compile(r"(?i)secret[_-]?key=[^\s&]+"),
    re.compile(r"Bearer\s+[A-Za-z0-9._-]+"),
)


def sanitize_error(exc: BaseException | None) -> str:
    """Return a safe string form of ``exc`` with known credential patterns redacted.

    Replaces ``str(e)[:N]`` at call sites where exceptions may embed secrets.
    Also drops stack-trace noise beyond the first line.
    """
    if exc is None:
        return ""
    msg = str(exc) or ""
    for pattern in _TOKEN_PATTERNS:
        msg = pattern.sub("<REDACTED>", msg)
    first = msg.splitlines()[0] if msg else ""
    return f"{type(exc).__name__}: {first[:160]}"


def sanitize_text(text: str) -> str:
    """Redact credential patterns in an arbitrary string (used before persist)."""
    if not text:
        return text
    for pattern in _TOKEN_PATTERNS:
        text = pattern.sub("<REDACTED>", text)
    return text
