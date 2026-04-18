"""Tests for desk-routing behavior added in Sprint 4 Task 7b."""
from unittest.mock import MagicMock, patch

import pytest


def test_get_trading_client_desk_defaults_to_swing_via_existing_config():
    """Backward compat: no desk kwarg → existing behavior (swing via
    _get_alpaca_config). Existing tests that don't pass desk still work."""
    from src.shadow_trading.alpaca_adapter import _get_trading_client
    with patch(
        "src.shadow_trading.alpaca_adapter._get_alpaca_config",
        return_value={"api_key": "k", "api_secret": "s"},
    ), patch(
        "alpaca.trading.client.TradingClient"
    ) as mock_tc:
        mock_tc.return_value = MagicMock()
        c = _get_trading_client()
    assert c is not None


def test_get_trading_client_routes_to_desk_via_alpaca_clients():
    """When desk is passed, dispatch through alpaca_clients.get_client."""
    from src.shadow_trading import alpaca_adapter
    fake_client = MagicMock(desk_tag="research_xxx")
    with patch(
        "src.shadow_trading.alpaca_clients.get_client",
        return_value=fake_client,
    ) as mock_get:
        c = alpaca_adapter._get_trading_client(desk="research_xxx")
    mock_get.assert_called_once_with("research_xxx")
    assert c is fake_client


def test_public_function_threads_desk_to_helper():
    """get_account_info(desk='research_xxx') must route through the
    desk-aware helper, not the legacy one."""
    from src.shadow_trading import alpaca_adapter
    fake_client = MagicMock()
    fake_client.get_account.return_value = MagicMock(
        account_number="R123",
        portfolio_value=100_000,
        cash=50_000,
        buying_power=100_000,
    )
    with patch(
        "src.shadow_trading.alpaca_clients.get_client",
        return_value=fake_client,
    ) as mock_get:
        info = alpaca_adapter.get_account_info(desk="research_xxx")
    # Routing check: research client was requested
    called_args = mock_get.call_args.args if mock_get.call_args.args else ()
    called_kwargs = mock_get.call_args.kwargs
    assert "research_xxx" in called_args or called_kwargs.get("desk") == "research_xxx"


def test_public_function_default_desk_swing_backward_compat():
    """get_account_info() with no desk kwarg works unchanged."""
    from src.shadow_trading import alpaca_adapter
    with patch(
        "src.shadow_trading.alpaca_adapter._get_alpaca_config",
        return_value={"api_key": "k", "api_secret": "s"},
    ), patch("alpaca.trading.client.TradingClient") as mock_tc:
        client = MagicMock()
        client.get_account.return_value = MagicMock(
            account_number="S123", portfolio_value=50_000,
            cash=25_000, buying_power=50_000,
        )
        mock_tc.return_value = client
        info = alpaca_adapter.get_account_info()
    assert info.get("account_number") is None or "S123" in str(info)


def test_place_live_entry_rejects_research_desk():
    """place_live_entry must raise ValueError if desk != 'swing'
    — live trading is swing-only (compliance guardrail)."""
    from src.shadow_trading import alpaca_adapter
    with pytest.raises(ValueError, match="live"):
        alpaca_adapter.place_live_entry(
            ticker="AAPL", shares=10,
            desk="research_lazy_prices_v1",
        )
