"""Tests for _sanitize_error / _sanitize_text — the credential-leak guard (#414).

Ensures exception strings and persisted payloads have credentials redacted
before they reach validation_results, Telegram digest, or any log handler.
"""
from __future__ import annotations

import json

import pytest

from src.evaluation.system_validator import _sanitize_error, _sanitize_text


class TestSanitizeError:
    def test_redacts_telegram_bot_token(self):
        exc = ConnectionError(
            "HTTPSConnectionPool(host='api.telegram.org', port=443): "
            "Max retries exceeded with url: /bot123456789:ABCdefGHIjklMNOpqrSTUvwxYZ0123456789/getMe"
        )
        out = _sanitize_error(exc)
        assert "ABCdefGHIjklMNOpqrSTUvwxYZ0123456789" not in out
        assert "123456789:ABC" not in out
        assert "<REDACTED>" in out
        assert out.startswith("ConnectionError:")

    def test_redacts_postgres_url_creds(self):
        exc = RuntimeError(
            "could not connect to server at postgres://dbuser:supersecret@host.render.com:5432/arcis"
        )
        out = _sanitize_error(exc)
        assert "dbuser:supersecret" not in out
        assert "supersecret" not in out
        assert "<REDACTED>" in out

    def test_redacts_password_kv(self):
        exc = ValueError("config invalid: password=hunter2 missing quotes")
        out = _sanitize_error(exc)
        assert "hunter2" not in out
        assert "<REDACTED>" in out

    def test_redacts_api_key_kv(self):
        exc = RuntimeError("auth failed: api_key=sk-abc123xyz456 is expired")
        out = _sanitize_error(exc)
        assert "sk-abc123xyz456" not in out

    def test_redacts_bearer_token(self):
        exc = RuntimeError("401 Unauthorized: Bearer eyJhbGciOi12345.foo.bar rejected")
        out = _sanitize_error(exc)
        assert "eyJhbGciOi12345" not in out

    def test_preserves_exception_type(self):
        assert _sanitize_error(ValueError("x")).startswith("ValueError:")
        assert _sanitize_error(TimeoutError("y")).startswith("TimeoutError:")

    def test_empty_exception_safe(self):
        assert _sanitize_error(Exception("")) == "Exception: "

    def test_multiline_keeps_first_line_only(self):
        exc = RuntimeError("first line\nsecond line\nthird line")
        out = _sanitize_error(exc)
        assert "second line" not in out
        assert "first line" in out

    def test_caps_length(self):
        exc = RuntimeError("x" * 5000)
        out = _sanitize_error(exc)
        assert len(out) < 500

    def test_no_false_positive_on_benign_text(self):
        exc = RuntimeError("user timeout after 60s, retry count=3")
        out = _sanitize_error(exc)
        assert "<REDACTED>" not in out
        assert "user timeout" in out


class TestSanitizeText:
    def test_redacts_token_inside_json_blob(self):
        payload = json.dumps({
            "status": "fail",
            "detail": "Could not verify bot token: ConnectionError https://api.telegram.org/bot999:XYZtoken123ABCtoken456/getMe",
        })
        out = _sanitize_text(payload)
        assert "XYZtoken123ABCtoken456" not in out
        assert "<REDACTED>" in out

    def test_empty_passthrough(self):
        assert _sanitize_text("") == ""
        assert _sanitize_text(None) is None  # type: ignore

    def test_benign_text_unchanged(self):
        text = "all checks passed; 50 rows inserted"
        assert _sanitize_text(text) == text
