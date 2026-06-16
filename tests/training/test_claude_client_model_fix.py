"""Regression: the Claude teacher path must work on current models.

Two defects, both surfaced 2026-06-16 when the configured teacher models
(claude-sonnet-4-20250514, claude-opus-4-20250514) were retired by Anthropic
on June 15:

1. `generate_training_example` hardcoded `temperature=0.5`, which Opus 4.8 / 4.7
   / Fable removed (they 400 on it). The operator chose Opus for the corpus, so
   the call must NOT send temperature/top_p/top_k.
2. A 404 `not_found_error` (retired/wrong model ID) was classified as a transient
   failure (silent None) instead of an unrecoverable one — so a retired model ID
   silently froze the corpus for 4 days with no halt/alert. It must raise
   ClaudeAuthError so the caller halts + surfaces it (data_collector.py:417).

verify-by-mutation: each assertion fails on the pre-fix code.
"""
from __future__ import annotations

import pytest

from src.training.claude_client import (
    ClaudeAuthError,
    _classify_anthropic_exception,
    generate_training_example,
)


class _FakeMsg:
    model = "claude-opus-4-8"

    def __init__(self):
        self.content = [type("B", (), {"text": "OK"})()]
        self.usage = type("U", (), {"input_tokens": 1, "output_tokens": 1})()


def test_generate_training_example_omits_sampling_params(monkeypatch):
    """Opus 4.8 400s on temperature/top_p/top_k — they must not be sent."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-not-real")
    captured: dict = {}

    class _FakeMessages:
        def create(self, **kwargs):
            captured.update(kwargs)
            return _FakeMsg()

    class _FakeClient:
        messages = _FakeMessages()

    monkeypatch.setattr(
        "src.training.claude_client._get_anthropic_client", lambda _k: _FakeClient()
    )
    out = generate_training_example(
        "system", "user", purpose="backfill_blinded", model_override="claude-opus-4-8"
    )
    assert out == "OK"
    assert "temperature" not in captured, f"temperature must not be sent: {sorted(captured)}"
    assert "top_p" not in captured
    assert "top_k" not in captured


def test_classify_not_found_raises_loud():
    """A 404 model-not-found (retired model ID) must halt loudly, not return None."""
    exc = Exception(
        "Error code: 404 - {'type': 'error', 'error': {'type': 'not_found_error', "
        "'message': 'model: claude-sonnet-4-20250514'}}"
    )
    with pytest.raises(ClaudeAuthError):
        _classify_anthropic_exception(exc)


def test_classify_auth_still_raises():
    """Regression: genuine auth/billing failures still raise ClaudeAuthError."""
    with pytest.raises(ClaudeAuthError):
        _classify_anthropic_exception(Exception("authentication_error: invalid x-api-key"))


def test_classify_transient_stays_silent():
    """Regression: transient errors (rate limit / 5xx) still return None (swallowed)."""
    assert _classify_anthropic_exception(Exception("Error code: 429 - rate_limit_error")) is None
    assert _classify_anthropic_exception(Exception("Error code: 529 - overloaded_error")) is None
