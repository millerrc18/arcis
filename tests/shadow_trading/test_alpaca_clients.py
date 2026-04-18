"""Tests for src.shadow_trading.alpaca_clients — per-desk client factory."""
from unittest.mock import MagicMock, patch

import pytest


def test_get_client_returns_cached_instance_per_desk(monkeypatch):
    """Calling get_client(desk) twice returns the same instance."""
    monkeypatch.setenv("ALPACA_API_KEY", "swing_key")
    monkeypatch.setenv("ALPACA_API_SECRET", "swing_sec")

    from src.shadow_trading.alpaca_clients import get_client, _CLIENT_CACHE
    _CLIENT_CACHE.clear()

    with patch(
        "src.shadow_trading.alpaca_clients.load_config",
        return_value={
            "desks": {
                "swing": {
                    "alpaca_key_env": "ALPACA_API_KEY",
                    "alpaca_secret_env": "ALPACA_API_SECRET",
                    "enabled": True,
                },
                "research": {
                    "alpaca_key_env": "ALPACA_RESEARCH_API_KEY",
                    "alpaca_secret_env": "ALPACA_RESEARCH_API_SECRET",
                    "enabled": True,
                },
            },
        },
    ), patch("src.shadow_trading.alpaca_clients.TradingClient") as mock_tc:
        mock_tc.return_value = MagicMock(desk_tag=None)
        c1 = get_client("swing")
        c2 = get_client("swing")
    assert c1 is c2
    # TradingClient constructor called exactly once (cached)
    assert mock_tc.call_count == 1


def test_get_client_tags_desk_attribute(monkeypatch):
    monkeypatch.setenv("ALPACA_API_KEY", "swing_key")
    monkeypatch.setenv("ALPACA_API_SECRET", "swing_sec")

    from src.shadow_trading.alpaca_clients import get_client, _CLIENT_CACHE
    _CLIENT_CACHE.clear()
    with patch(
        "src.shadow_trading.alpaca_clients.load_config",
        return_value={
            "desks": {
                "swing": {
                    "alpaca_key_env": "ALPACA_API_KEY",
                    "alpaca_secret_env": "ALPACA_API_SECRET",
                    "enabled": True,
                },
                "research": {
                    "alpaca_key_env": "ALPACA_RESEARCH_API_KEY",
                    "alpaca_secret_env": "ALPACA_RESEARCH_API_SECRET",
                    "enabled": True,
                },
            },
        },
    ), patch("src.shadow_trading.alpaca_clients.TradingClient") as mock_tc:
        mock_tc.return_value = MagicMock()
        client = get_client("swing")
    assert getattr(client, "desk_tag", None) == "swing"


def test_get_client_unknown_desk_raises():
    from src.shadow_trading.alpaca_clients import get_client, _CLIENT_CACHE
    _CLIENT_CACHE.clear()
    with patch(
        "src.shadow_trading.alpaca_clients.load_config",
        return_value={
            "desks": {
                "swing": {
                    "alpaca_key_env": "ALPACA_API_KEY",
                    "alpaca_secret_env": "ALPACA_API_SECRET",
                    "enabled": True,
                },
                "research": {
                    "alpaca_key_env": "ALPACA_RESEARCH_API_KEY",
                    "alpaca_secret_env": "ALPACA_RESEARCH_API_SECRET",
                    "enabled": True,
                },
            },
        },
    ), pytest.raises(ValueError, match="unknown desk"):
        get_client("nonexistent_desk")


def test_verify_accounts_distinct_raises_on_same_account(monkeypatch):
    """If both desks resolve to the same Alpaca account_number, raise."""
    monkeypatch.setenv("ALPACA_API_KEY", "same_key")
    monkeypatch.setenv("ALPACA_API_SECRET", "same_sec")
    monkeypatch.setenv("ALPACA_RESEARCH_API_KEY", "same_key")
    monkeypatch.setenv("ALPACA_RESEARCH_API_SECRET", "same_sec")

    from src.shadow_trading.alpaca_clients import (
        verify_accounts_distinct, _CLIENT_CACHE,
    )
    _CLIENT_CACHE.clear()

    # Also ensure research desk is enabled for this test
    with patch(
        "src.shadow_trading.alpaca_clients.load_config",
        return_value={
            "desks": {
                "swing": {
                    "alpaca_key_env": "ALPACA_API_KEY",
                    "alpaca_secret_env": "ALPACA_API_SECRET",
                    "enabled": True,
                },
                "research": {
                    "alpaca_key_env": "ALPACA_RESEARCH_API_KEY",
                    "alpaca_secret_env": "ALPACA_RESEARCH_API_SECRET",
                    "enabled": True,
                },
            },
        },
    ), patch("src.shadow_trading.alpaca_clients.TradingClient") as mock_tc:
        same_account = MagicMock()
        same_account.get_account.return_value = MagicMock(account_number="A123")
        mock_tc.return_value = same_account
        with pytest.raises(RuntimeError, match="same"):
            verify_accounts_distinct()


def test_verify_accounts_distinct_passes_on_different_accounts(monkeypatch):
    monkeypatch.setenv("ALPACA_API_KEY", "swing_k")
    monkeypatch.setenv("ALPACA_API_SECRET", "swing_s")
    monkeypatch.setenv("ALPACA_RESEARCH_API_KEY", "research_k")
    monkeypatch.setenv("ALPACA_RESEARCH_API_SECRET", "research_s")

    from src.shadow_trading.alpaca_clients import (
        verify_accounts_distinct, _CLIENT_CACHE,
    )
    _CLIENT_CACHE.clear()

    call_ix = {"n": 0}

    def make_client(*args, **kwargs):
        call_ix["n"] += 1
        m = MagicMock()
        m.get_account.return_value = MagicMock(
            account_number=f"A{call_ix['n']}"
        )
        return m

    with patch(
        "src.shadow_trading.alpaca_clients.load_config",
        return_value={
            "desks": {
                "swing": {
                    "alpaca_key_env": "ALPACA_API_KEY",
                    "alpaca_secret_env": "ALPACA_API_SECRET",
                    "enabled": True,
                },
                "research": {
                    "alpaca_key_env": "ALPACA_RESEARCH_API_KEY",
                    "alpaca_secret_env": "ALPACA_RESEARCH_API_SECRET",
                    "enabled": True,
                },
            },
        },
    ), patch("src.shadow_trading.alpaca_clients.TradingClient",
             side_effect=make_client):
        verify_accounts_distinct()  # no raise


def test_verify_accounts_distinct_skips_if_research_disabled(monkeypatch):
    """Research desk not enabled → verify_accounts_distinct returns cleanly."""
    from src.shadow_trading.alpaca_clients import (
        verify_accounts_distinct, _CLIENT_CACHE,
    )
    _CLIENT_CACHE.clear()
    with patch(
        "src.shadow_trading.alpaca_clients.load_config",
        return_value={
            "desks": {
                "swing": {
                    "alpaca_key_env": "ALPACA_API_KEY",
                    "alpaca_secret_env": "ALPACA_API_SECRET",
                    "enabled": True,
                },
                "research": {
                    "alpaca_key_env": "ALPACA_RESEARCH_API_KEY",
                    "alpaca_secret_env": "ALPACA_RESEARCH_API_SECRET",
                    "enabled": False,  # disabled
                },
            },
        },
    ):
        verify_accounts_distinct()  # no raise, no call to TradingClient


def test_get_client_env_var_missing_raises(monkeypatch):
    monkeypatch.delenv("ALPACA_API_KEY", raising=False)
    monkeypatch.delenv("ALPACA_API_SECRET", raising=False)

    from src.shadow_trading.alpaca_clients import get_client, _CLIENT_CACHE
    _CLIENT_CACHE.clear()
    with patch(
        "src.shadow_trading.alpaca_clients.load_config",
        return_value={
            "desks": {
                "swing": {
                    "alpaca_key_env": "ALPACA_API_KEY",
                    "alpaca_secret_env": "ALPACA_API_SECRET",
                    "enabled": True,
                },
                "research": {
                    "alpaca_key_env": "ALPACA_RESEARCH_API_KEY",
                    "alpaca_secret_env": "ALPACA_RESEARCH_API_SECRET",
                    "enabled": True,
                },
            },
        },
    ), pytest.raises(RuntimeError, match="env var"):
        get_client("swing")
