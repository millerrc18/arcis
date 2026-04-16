"""Tests for SD#41 IB cold storage behavior.

Verifies that with trading.ib_enabled=false:
1. broker_factory falls back to Alpaca even when broker=ib is configured
2. broker_factory honors trading.ib_enabled=true (escape hatch)
3. The default config ships with ib_enabled=false

Ralph-loop note: these are behavior-preservation tests, not feature
tests. They prevent regression when we reactivate IB later.
"""

from unittest.mock import MagicMock, patch


def test_broker_factory_falls_back_to_alpaca_when_ib_disabled():
    """SD#41: broker=ib + ib_enabled=false → Alpaca, no IB instantiation."""
    import src.trading.broker_factory as bf
    bf._brokers.clear()

    config = {
        "trading": {"ib_enabled": False},
        "live_trading": {"broker": "ib", "ib": {"host": "127.0.0.1", "port": 4002}},
    }
    with patch("src.trading.alpaca_broker.AlpacaLiveBroker") as mock_alpaca:
        mock_alpaca.return_value = MagicMock()
        bf.get_live_broker(config)

    # Alpaca was instantiated; IB never reached the cache.
    assert "alpaca" in bf._brokers
    assert "ib" not in bf._brokers


def test_broker_factory_uses_ib_when_explicitly_enabled():
    """SD#41 escape hatch: broker=ib + ib_enabled=true → IBBroker (cache populated)."""
    import src.trading.broker_factory as bf
    bf._brokers.clear()

    config = {
        "trading": {"ib_enabled": True},
        "live_trading": {"broker": "ib", "ib": {"host": "127.0.0.1", "port": 4002}},
    }
    with patch("src.trading.ib_broker.IBBroker") as mock_ib:
        mock_ib.return_value = MagicMock()
        bf.get_live_broker(config)

    assert "ib" in bf._brokers


def test_default_config_has_ib_disabled():
    """SD#41: new installs default to IB dormant.

    Loads the actual settings.local.yaml (or example fallback) to confirm
    the flag landed in the config the system will boot with.
    """
    from src.config import reload_config
    config = reload_config()
    assert config.get("trading", {}).get("ib_enabled") is False, (
        "SD#41 requires trading.ib_enabled=false by default. "
        "If this fails, check config/settings.local.yaml or settings.example.yaml"
    )
