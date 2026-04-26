"""Regression tests for Sprint 0 cluster-03 Critical #4 — paper API secret required.

Pre-fix: ``_get_alpaca_config`` accepted empty ``api_secret`` without raising,
silently constructing ``TradingClient(api_secret="")`` which fails with an
opaque alpaca-py SDK error far from the misconfig source. The live path
(``_get_live_config``) already raises ``LiveTradingError`` on this condition;
this test locks the parity in.

Tests must FAIL on pre-fix code (silent flow-through) and PASS on the fix
(``PaperTradingError`` with explicit env-var hint).

Called by: pytest (CI)
Calls: src.shadow_trading.alpaca_adapter
Owns tables: none
"""
from __future__ import annotations

from unittest.mock import patch

import pytest


# ── Paper-config tests ──────────────────────────────────────────────────────


class TestPaperConfigRequiresApiSecret:
    """``_get_alpaca_config`` must raise PaperTradingError when API secret
    is missing. Pre-fix it silently passed empty strings to the SDK."""

    def test_paper_config_raises_when_api_secret_empty(self, monkeypatch):
        """Empty ALPACA_API_SECRET (and no YAML fallback) → PaperTradingError."""
        from src.shadow_trading.alpaca_adapter import (
            PaperTradingError, _get_alpaca_config,
        )

        # Force-set empty environment values; the load_config patch makes
        # sure the YAML fallback also returns empty so we exercise the
        # post-resolve check.
        monkeypatch.setenv("ALPACA_API_KEY", "non_empty_key")
        monkeypatch.setenv("ALPACA_API_SECRET", "")
        monkeypatch.delenv("ALPACA_BASE_URL", raising=False)

        fake_config = {"alpaca": {"api_key": "", "api_secret": ""}, "shadow_trading": {}}
        with patch(
            "src.shadow_trading.alpaca_adapter.load_config",
            return_value=fake_config,
        ):
            with pytest.raises(PaperTradingError) as exc_info:
                _get_alpaca_config()

        # Message must reference the env var so operators can self-diagnose.
        msg = str(exc_info.value)
        assert "ALPACA_API_SECRET" in msg or "api_secret" in msg.lower()

    def test_paper_config_raises_when_api_key_empty(self, monkeypatch):
        """Empty ALPACA_API_KEY (and no YAML fallback) → PaperTradingError.

        Symmetric guard: empty key must fail loudly the same way an empty
        secret does. Without this check, callers would still fail (the SDK
        rejects empty key) but with an opaque downstream error.
        """
        from src.shadow_trading.alpaca_adapter import (
            PaperTradingError, _get_alpaca_config,
        )

        monkeypatch.setenv("ALPACA_API_KEY", "")
        monkeypatch.setenv("ALPACA_API_SECRET", "non_empty_secret")
        monkeypatch.delenv("ALPACA_BASE_URL", raising=False)

        fake_config = {"alpaca": {"api_key": "", "api_secret": ""}, "shadow_trading": {}}
        with patch(
            "src.shadow_trading.alpaca_adapter.load_config",
            return_value=fake_config,
        ):
            with pytest.raises(PaperTradingError) as exc_info:
                _get_alpaca_config()

        msg = str(exc_info.value)
        assert "ALPACA_API_KEY" in msg or "api_key" in msg.lower()

    def test_paper_config_succeeds_with_api_secret_set(self, monkeypatch):
        """Valid env credentials → no raise, returns config dict."""
        from src.shadow_trading.alpaca_adapter import _get_alpaca_config

        monkeypatch.setenv("ALPACA_API_KEY", "test_key_123")
        monkeypatch.setenv("ALPACA_API_SECRET", "test_secret_456")
        monkeypatch.delenv("ALPACA_BASE_URL", raising=False)

        fake_config = {"alpaca": {}, "shadow_trading": {"enabled": True}}
        with patch(
            "src.shadow_trading.alpaca_adapter.load_config",
            return_value=fake_config,
        ):
            cfg = _get_alpaca_config()

        assert cfg["api_key"] == "test_key_123"
        assert cfg["api_secret"] == "test_secret_456"
        assert cfg["enabled"] is True

    def test_paper_config_falls_back_to_yaml_when_env_unset(self, monkeypatch):
        """If env is unset, YAML config provides the credentials.

        Confirms the new check honors the env-then-YAML resolution order:
        empty env doesn't override a populated YAML value.
        """
        from src.shadow_trading.alpaca_adapter import _get_alpaca_config

        monkeypatch.delenv("ALPACA_API_KEY", raising=False)
        monkeypatch.delenv("ALPACA_API_SECRET", raising=False)
        monkeypatch.delenv("ALPACA_BASE_URL", raising=False)

        fake_config = {
            "alpaca": {"api_key": "yaml_key", "api_secret": "yaml_secret"},
            "shadow_trading": {},
        }
        with patch(
            "src.shadow_trading.alpaca_adapter.load_config",
            return_value=fake_config,
        ):
            cfg = _get_alpaca_config()

        assert cfg["api_key"] == "yaml_key"
        assert cfg["api_secret"] == "yaml_secret"


# ── Live-path parity tests ──────────────────────────────────────────────────


class TestLiveConfigAlsoRequiresApiSecret:
    """The paper guard mirrors the live guard. This test is a parity
    check — if the live path's check is ever weakened, this test catches
    it (sibling-search rule)."""

    def test_live_config_raises_when_api_secret_empty(self, monkeypatch):
        """Empty ALPACA_LIVE_SECRET_KEY → LiveTradingError (existing behavior)."""
        from src.shadow_trading.alpaca_adapter import (
            LiveTradingError, _get_live_config,
        )

        monkeypatch.setenv("ALPACA_LIVE_API_KEY", "live_key_present")
        monkeypatch.setenv("ALPACA_LIVE_SECRET_KEY", "")

        fake_config = {"live_trading": {"api_key": "", "secret_key": ""}}
        with patch(
            "src.shadow_trading.alpaca_adapter.load_config",
            return_value=fake_config,
        ):
            with pytest.raises(LiveTradingError) as exc_info:
                _get_live_config()

        msg = str(exc_info.value)
        # Live error message should reference credentials being missing.
        assert "credential" in msg.lower() or "secret_key" in msg.lower()

    def test_live_config_raises_when_api_key_empty(self, monkeypatch):
        """Empty ALPACA_LIVE_API_KEY → LiveTradingError."""
        from src.shadow_trading.alpaca_adapter import (
            LiveTradingError, _get_live_config,
        )

        monkeypatch.setenv("ALPACA_LIVE_API_KEY", "")
        monkeypatch.setenv("ALPACA_LIVE_SECRET_KEY", "live_secret_present")

        fake_config = {"live_trading": {"api_key": "", "secret_key": ""}}
        with patch(
            "src.shadow_trading.alpaca_adapter.load_config",
            return_value=fake_config,
        ):
            with pytest.raises(LiveTradingError):
                _get_live_config()

    def test_live_and_paper_both_raise_on_missing_secret(self, monkeypatch):
        """Symmetric check: paper raises PaperTradingError, live raises
        LiveTradingError. If either path silently succeeds on empty
        creds, this test fails — preventing a regression to the asymmetric
        pre-fix behavior."""
        from src.shadow_trading.alpaca_adapter import (
            LiveTradingError, PaperTradingError,
            _get_alpaca_config, _get_live_config,
        )

        monkeypatch.setenv("ALPACA_API_KEY", "k")
        monkeypatch.setenv("ALPACA_API_SECRET", "")
        monkeypatch.setenv("ALPACA_LIVE_API_KEY", "k")
        monkeypatch.setenv("ALPACA_LIVE_SECRET_KEY", "")
        monkeypatch.delenv("ALPACA_BASE_URL", raising=False)

        fake_config = {
            "alpaca": {},
            "shadow_trading": {},
            "live_trading": {},
        }
        with patch(
            "src.shadow_trading.alpaca_adapter.load_config",
            return_value=fake_config,
        ):
            with pytest.raises(PaperTradingError):
                _get_alpaca_config()
            with pytest.raises(LiveTradingError):
                _get_live_config()
