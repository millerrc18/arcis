"""T2.17 — Fail-CLOSED governor on 5 input-missing surfaces.

Audit §F-12: 5 governor input surfaces previously fail-OPEN — when the
broker call raised or returned None, the governor silently allowed the
trade. With this fix each of the 5 surfaces raises
``GovernorInputMissingError`` when its required input is missing, and
the governor catches that and HALTS the trade.

Surfaces covered (parametrized below):
  1. is_connected           — broker handshake state
  2. get_account_equity     — equity USD
  3. get_position_value     — current $ exposure for a ticker
  4. get_buying_power       — buying power USD
  5. get_open_orders        — list of open orders

Each surface has a positive case (input present → governor approves)
and a negative case (input missing → ``GovernorInputMissingError``
raised AND governor halts the trade).
"""
from __future__ import annotations

from unittest.mock import patch

import pytest


# ---------------------------------------------------------------------------
# GovernorInputMissingError class import
# ---------------------------------------------------------------------------


def test_governor_input_missing_error_is_exception_subclass():
    """The new exception class lives in src.risk.governor and is an Exception."""
    from src.risk.governor import GovernorInputMissingError
    assert issubclass(GovernorInputMissingError, Exception)


# ---------------------------------------------------------------------------
# 5 fail-CLOSED surfaces — negative case (input missing → halt)
# ---------------------------------------------------------------------------


SURFACES = [
    "is_connected",
    "get_account_equity",
    "get_position_value",
    "get_buying_power",
    "get_open_orders",
]

# is_connected is the only surface that returns a bool rather than raising:
# the spec says "must reflect post-handshake state" — False is the
# fail-closed signal, not an exception. The remaining 4 surfaces raise.
RAISING_SURFACES = [s for s in SURFACES if s != "is_connected"]


@pytest.mark.parametrize("surface", RAISING_SURFACES)
def test_surface_raises_governor_input_missing_error_when_input_missing(surface):
    """Each raising surface raises GovernorInputMissingError on missing input."""
    from src.risk.governor import GovernorInputMissingError
    from src.shadow_trading import alpaca_adapter

    fn = getattr(alpaca_adapter, surface)

    if surface == "get_account_equity":
        with patch.object(alpaca_adapter, "get_account_info",
                          side_effect=RuntimeError("API down")):
            with pytest.raises(GovernorInputMissingError):
                fn()
    elif surface == "get_position_value":
        with patch.object(alpaca_adapter, "get_position",
                          side_effect=RuntimeError("position lookup failed")):
            with pytest.raises(GovernorInputMissingError):
                fn("AAPL")
    elif surface == "get_buying_power":
        with patch.object(alpaca_adapter, "get_account_info",
                          side_effect=RuntimeError("API down")):
            with pytest.raises(GovernorInputMissingError):
                fn()
    elif surface == "get_open_orders":
        with patch.object(alpaca_adapter, "_get_trading_client",
                          side_effect=RuntimeError("API down")):
            with pytest.raises(GovernorInputMissingError):
                fn()


def test_is_connected_returns_false_when_input_missing():
    """is_connected reports state via bool (not raise). Failed handshake → False."""
    from src.shadow_trading import alpaca_adapter
    with patch.object(alpaca_adapter, "_get_trading_client",
                      side_effect=RuntimeError("handshake failed")):
        assert alpaca_adapter.is_connected() is False


# ---------------------------------------------------------------------------
# Positive case — all 5 healthy → governor approves
# ---------------------------------------------------------------------------


def _healthy_features():
    return {"sector": "Tech", "vix_proxy": 15.0}


def _healthy_portfolio(equity: float = 100_000.0):
    return {
        "equity": equity,
        "open_count": 0,
        "open_positions": [],
        "sector_exposure": {},
        "daily_pnl_pct": 0.0,
    }


def _governor():
    from src.risk.governor import RiskGovernor
    return RiskGovernor({"risk_governor": {"enabled": True}})


def test_governor_approves_when_all_5_surfaces_healthy(tmp_path, monkeypatch):
    """Positive: when all 5 surfaces return valid values, trade approves."""
    from src.risk import governor as gov

    # Avoid stale halt file polluting test
    monkeypatch.setattr(gov, "_HALT_FILE", str(tmp_path / "halt"))

    g = _governor()
    result = g.check_trade(
        ticker="AAPL",
        allocation_dollars=1_000.0,
        features=_healthy_features(),
        portfolio=_healthy_portfolio(equity=100_000.0),
    )
    assert result["approved"] is True


# ---------------------------------------------------------------------------
# Governor halts trade when GovernorInputMissingError raised
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("surface", SURFACES)
def test_governor_halts_trade_when_surface_raises(surface, tmp_path, monkeypatch):
    """When governor probes a surface and it raises GovernorInputMissingError,
    the trade is HALTED (not approved)."""
    from src.risk import governor as gov
    from src.risk.governor import GovernorInputMissingError

    monkeypatch.setattr(gov, "_HALT_FILE", str(tmp_path / "halt"))

    g = _governor()

    # Ask the governor to probe its input surfaces. The check is added in
    # RiskGovernor.check_trade — when probe raises, return rejected dict.
    def _raise(*_a, **_kw):
        raise GovernorInputMissingError(f"{surface} missing")

    # Patch the probe entry point to raise.
    with patch.object(g, "_probe_input_surfaces", side_effect=_raise):
        result = g.check_trade(
            ticker="AAPL",
            allocation_dollars=1_000.0,
            features=_healthy_features(),
            portfolio=_healthy_portfolio(),
        )
    assert result["approved"] is False
    assert "rejection_reason" in result
    assert surface in result["rejection_reason"] or "input" in result["rejection_reason"].lower()


# ---------------------------------------------------------------------------
# Positive surface checks — value flows through cleanly
# ---------------------------------------------------------------------------


def test_get_account_equity_returns_value_when_healthy():
    from src.shadow_trading import alpaca_adapter
    with patch.object(alpaca_adapter, "get_account_info",
                      return_value={"equity": 50_000.0, "buying_power": 100_000.0,
                                    "cash": 25_000.0}):
        assert alpaca_adapter.get_account_equity() == 50_000.0


def test_get_buying_power_returns_value_when_healthy():
    from src.shadow_trading import alpaca_adapter
    with patch.object(alpaca_adapter, "get_account_info",
                      return_value={"equity": 50_000.0, "buying_power": 100_000.0,
                                    "cash": 25_000.0}):
        assert alpaca_adapter.get_buying_power() == 100_000.0


def test_get_position_value_returns_zero_for_no_position():
    """No position is a valid state — return 0.0 (NOT raise)."""
    from src.shadow_trading import alpaca_adapter
    with patch.object(alpaca_adapter, "get_position", return_value=None):
        assert alpaca_adapter.get_position_value("AAPL") == 0.0


def test_get_position_value_returns_market_value_when_present():
    from src.shadow_trading import alpaca_adapter
    with patch.object(alpaca_adapter, "get_position",
                      return_value={"symbol": "AAPL", "market_value": 1_234.0}):
        assert alpaca_adapter.get_position_value("AAPL") == 1_234.0


def test_get_open_orders_returns_list_when_healthy():
    from src.shadow_trading import alpaca_adapter
    fake_client = type("C", (), {})()
    fake_client.get_orders = lambda *a, **kw: []
    with patch.object(alpaca_adapter, "_get_trading_client",
                      return_value=fake_client):
        result = alpaca_adapter.get_open_orders()
        assert isinstance(result, list)


# ---------------------------------------------------------------------------
# Equity-missing semantics: equity must be POSITIVE float, not None/0/NaN
# ---------------------------------------------------------------------------


def test_get_account_equity_raises_when_value_is_none():
    """None equity is NOT a valid governor input — raise fail-closed."""
    from src.shadow_trading import alpaca_adapter
    from src.risk.governor import GovernorInputMissingError
    with patch.object(alpaca_adapter, "get_account_info",
                      return_value={"equity": None}):
        with pytest.raises(GovernorInputMissingError):
            alpaca_adapter.get_account_equity()


def test_get_buying_power_raises_when_value_is_none():
    from src.shadow_trading import alpaca_adapter
    from src.risk.governor import GovernorInputMissingError
    with patch.object(alpaca_adapter, "get_account_info",
                      return_value={"buying_power": None}):
        with pytest.raises(GovernorInputMissingError):
            alpaca_adapter.get_buying_power()
