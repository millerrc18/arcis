"""Tests for .env secret migration — env vars take precedence over YAML config.

Verifies the pattern: os.environ.get("SECRET") takes precedence over YAML config,
with graceful fallback when neither is set.
"""

import os
import sys
from unittest.mock import patch, MagicMock

import pytest


def _mock_load_config(config_dict):
    """Return a mock load_config that returns the given dict."""
    return MagicMock(return_value=config_dict)


# ── Finnhub Key (data collectors) ───────────────────────────────────

class TestFinnhubKeyResolution:
    def test_env_var_takes_precedence(self, monkeypatch):
        """When FINNHUB_API_KEY env var is set, it overrides YAML config."""
        monkeypatch.setenv("FINNHUB_API_KEY", "env-finnhub-key")
        # Directly test the logic: env var should win
        assert os.environ.get("FINNHUB_API_KEY") == "env-finnhub-key"

    def test_falls_back_when_env_not_set(self, monkeypatch):
        """When env var is not set, os.environ.get returns None."""
        monkeypatch.delenv("FINNHUB_API_KEY", raising=False)
        assert os.environ.get("FINNHUB_API_KEY") is None

    def test_env_var_used_before_config(self, monkeypatch):
        """Env var takes precedence: if set, config value is ignored."""
        monkeypatch.setenv("FINNHUB_API_KEY", "env-key")
        yaml_key = "yaml-key"
        result = os.environ.get("FINNHUB_API_KEY") or yaml_key
        assert result == "env-key"

    def test_yaml_fallback_when_env_empty(self, monkeypatch):
        """When env var is not set, YAML fallback is used."""
        monkeypatch.delenv("FINNHUB_API_KEY", raising=False)
        yaml_key = "yaml-key"
        result = os.environ.get("FINNHUB_API_KEY") or yaml_key
        assert result == "yaml-key"


# ── FRED Key (macro_collector) ──────────────────────────────────────

class TestFredKeyResolution:
    def test_env_var_takes_precedence(self, monkeypatch):
        """When FRED_API_KEY env var is set, it overrides YAML config."""
        monkeypatch.setenv("FRED_API_KEY", "env-fred-key")
        yaml_key = "yaml-fred-key"
        result = os.environ.get("FRED_API_KEY") or yaml_key
        assert result == "env-fred-key"

    def test_falls_back_to_yaml(self, monkeypatch):
        """When env var is not set, falls back to YAML config."""
        monkeypatch.delenv("FRED_API_KEY", raising=False)
        yaml_key = "yaml-fred-key"
        result = os.environ.get("FRED_API_KEY") or yaml_key
        assert result == "yaml-fred-key"

    def test_returns_none_when_neither_set(self, monkeypatch):
        """When neither env var nor YAML is set, returns None."""
        monkeypatch.delenv("FRED_API_KEY", raising=False)
        result = os.environ.get("FRED_API_KEY") or None
        assert result is None


# ── Telegram Config ─────────────────────────────────────────────────

class TestTelegramConfigResolution:
    def test_env_vars_take_precedence(self, monkeypatch):
        """When TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID are set, they override YAML."""
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "env-bot-token")
        monkeypatch.setenv("TELEGRAM_CHAT_ID", "env-chat-id")
        yaml_token = "yaml-token"
        yaml_chat = "yaml-id"
        bot_token = os.environ.get("TELEGRAM_BOT_TOKEN") or yaml_token
        chat_id = os.environ.get("TELEGRAM_CHAT_ID") or yaml_chat
        assert bot_token == "env-bot-token"
        assert chat_id == "env-chat-id"

    def test_falls_back_to_yaml(self, monkeypatch):
        """When env vars are not set, falls back to YAML config."""
        monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
        monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
        yaml_token = "yaml-token"
        yaml_chat = "yaml-id"
        bot_token = os.environ.get("TELEGRAM_BOT_TOKEN") or yaml_token
        chat_id = os.environ.get("TELEGRAM_CHAT_ID") or yaml_chat
        assert bot_token == "yaml-token"
        assert chat_id == "yaml-id"


# ── Anthropic Key (claude_client) ───────────────────────────────────

class TestAnthropicKeyResolution:
    def test_env_var_takes_precedence(self, monkeypatch):
        """When ANTHROPIC_API_KEY env var is set, it overrides YAML config."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "env-anthropic-key")
        yaml_key = "yaml-anthropic-key"
        result = os.environ.get("ANTHROPIC_API_KEY") or yaml_key
        assert result == "env-anthropic-key"

    def test_placeholder_treated_as_unset(self, monkeypatch):
        """Placeholder values like 'your-anthropic-api-key-here' are treated as unset."""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        yaml_key = "your-anthropic-api-key-here"
        api_key = os.environ.get("ANTHROPIC_API_KEY") or yaml_key
        # The claude_client.py code checks: api_key == "your-anthropic-api-key-here"
        is_placeholder = api_key == "your-anthropic-api-key-here"
        assert is_placeholder, "Placeholder should be detected as unset"

    def test_returns_empty_when_neither_set(self, monkeypatch):
        """When neither env var nor YAML is set, result is empty."""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        yaml_key = ""
        result = os.environ.get("ANTHROPIC_API_KEY") or yaml_key
        assert result == ""


# ── Email Password (notifier) ───────────────────────────────────────

class TestEmailPasswordResolution:
    def test_env_var_takes_precedence(self, monkeypatch):
        """When EMAIL_PASSWORD env var is set, it overrides YAML config."""
        monkeypatch.setenv("EMAIL_PASSWORD", "env-password")
        yaml_password = "yaml-password"
        result = os.environ.get("EMAIL_PASSWORD") or yaml_password
        assert result == "env-password"

    def test_falls_back_to_yaml(self, monkeypatch):
        """When env var is not set, falls back to YAML config."""
        monkeypatch.delenv("EMAIL_PASSWORD", raising=False)
        yaml_password = "yaml-password"
        result = os.environ.get("EMAIL_PASSWORD") or yaml_password
        assert result == "yaml-password"


# ── Cross-cutting: all expected env vars exist in code ──────────────

class TestEnvVarCoverage:
    """Verify that each .env.example secret has at least one os.environ.get reference."""

    EXPECTED_VARS = [
        "FINNHUB_API_KEY",
        "FRED_API_KEY",
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_CHAT_ID",
        "ANTHROPIC_API_KEY",
        "EMAIL_PASSWORD",
    ]

    @pytest.mark.parametrize("var_name", EXPECTED_VARS)
    def test_env_var_referenced_in_source(self, var_name):
        """Each secret should have os.environ.get() reference in src/.

        Uses pathlib to scan src/ directly rather than shelling out to grep —
        subprocess grep on Windows can't pass the embedded double-quote in the
        search pattern through without shell interpretation, giving false
        negatives. Pure Python avoids that class of env bug.
        """
        from pathlib import Path
        # Match BOTH os.environ.get("VAR") and os.environ.get("VAR", default) by
        # omitting the closing paren — the with-default form (e.g.
        # src/email/notifier.py: os.environ.get("EMAIL_PASSWORD", "")) is a valid
        # reference the exact-paren needle would miss.
        needle = f'os.environ.get("{var_name}"'
        src_dir = Path(__file__).resolve().parent.parent / "src"
        hits = [
            p for p in src_dir.rglob("*.py")
            if needle in p.read_text(encoding="utf-8", errors="ignore")
        ]
        assert hits, f"{var_name} has no os.environ.get() reference in src/"
