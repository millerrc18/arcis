"""T2.17 — Alpaca is_connected reflects real handshake state.

Audit §F-11: ``is_connected`` previously returned ``True`` unconditionally
(``src/trading/alpaca_broker.py:188`` and the new ``alpaca_adapter`` surface),
which let governor checks proceed even when the broker hadn't authenticated.

This module tests the new ``alpaca_adapter.is_connected()`` surface:
  - Pre-handshake (no client constructed yet, or client raised)  → False
  - Post-handshake (handshake succeeded — get_account returned)  → True
  - On exception during handshake                                → False (NOT True)
"""
from __future__ import annotations

from unittest.mock import patch, MagicMock

import pytest


def test_is_connected_true_after_successful_handshake():
    """Post-handshake (get_account returns OK) → True."""
    from src.shadow_trading import alpaca_adapter
    fake_account = MagicMock()
    fake_account.id = "abc"
    fake_account.status = "ACTIVE"
    fake_client = MagicMock()
    fake_client.get_account.return_value = fake_account
    with patch.object(alpaca_adapter, "_get_trading_client",
                      return_value=fake_client):
        assert alpaca_adapter.is_connected() is True


def test_is_connected_false_when_client_construction_fails():
    """Pre-handshake (TradingClient raised on construction) → False."""
    from src.shadow_trading import alpaca_adapter
    with patch.object(alpaca_adapter, "_get_trading_client",
                      side_effect=RuntimeError("config missing")):
        assert alpaca_adapter.is_connected() is False


def test_is_connected_false_when_handshake_raises():
    """Handshake call (get_account) raises → False (not True)."""
    from src.shadow_trading import alpaca_adapter
    fake_client = MagicMock()
    fake_client.get_account.side_effect = ConnectionError("network down")
    with patch.object(alpaca_adapter, "_get_trading_client",
                      return_value=fake_client):
        assert alpaca_adapter.is_connected() is False


def test_is_connected_false_when_account_status_not_active():
    """Account status not ACTIVE → False (handshake reached server but
    account is not in a tradable state)."""
    from src.shadow_trading import alpaca_adapter
    fake_account = MagicMock()
    fake_account.id = "abc"
    fake_account.status = "INACTIVE"
    fake_client = MagicMock()
    fake_client.get_account.return_value = fake_account
    with patch.object(alpaca_adapter, "_get_trading_client",
                      return_value=fake_client):
        assert alpaca_adapter.is_connected() is False


def test_is_connected_does_not_unconditionally_return_true():
    """Regression: function body must not be a literal ``return True``.

    Audit §F-11 — pre-fix the body was ``return True`` with a comment
    'Alpaca is always connected'. The fix calls a real handshake and
    returns the boolean result.
    """
    import inspect
    from src.shadow_trading import alpaca_adapter
    src = inspect.getsource(alpaca_adapter.is_connected)
    # Body must not be just ``return True`` (with optional comment).
    # Cheapest sentinel: function source must reference _get_trading_client
    # so we know it actually probes a client rather than literal True.
    assert "_get_trading_client" in src, (
        "is_connected must probe an actual client, not return True unconditionally"
    )
