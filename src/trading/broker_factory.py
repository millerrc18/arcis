"""Broker factory — returns the configured live trading broker.

Called by: shadow_trading.executor
Config keys: live_trading.broker, live_trading.ib.*

WHY singleton pattern: IB Gateway supports a limited number of concurrent
connections (typically 8). Each IBBroker that connects consumes one slot.
The singleton ensures one connection is reused across all calls. If the
connection drops, the factory detects it and reconnects.

WHY config-driven:
  config: live_trading.broker = "ib"      -> IBBroker
  config: live_trading.broker = "alpaca"  -> AlpacaLiveBroker
  config: live_trading.broker omitted     -> AlpacaLiveBroker (backward compatible)
"""

import logging
from src.trading.broker_interface import BrokerAdapter

logger = logging.getLogger(__name__)

# Singleton instances — one connection per broker type
_brokers: dict[str, BrokerAdapter] = {}


def get_live_broker(config: dict) -> BrokerAdapter:
    """Get the configured live trading broker adapter.

    Config:
        live_trading.broker: "alpaca" (default) or "ib"
        live_trading.ib.host: "127.0.0.1" (default)
        live_trading.ib.port: 4002 (paper) or 4001 (live)
        live_trading.ib.client_id: 1 (default)
    """
    live_cfg = config.get("live_trading", {})
    broker_name = live_cfg.get("broker", "alpaca")

    # SD#41 — IB cold storage. Gate IB selection behind trading.ib_enabled.
    # When false, fall back to Alpaca regardless of live_trading.broker. Code
    # below remains intact so reactivation only requires flipping the flag.
    if broker_name == "ib" and not config.get("trading", {}).get("ib_enabled", False):
        logger.warning(
            "[BROKER] IB requested but trading.ib_enabled=false (SD#41 dormant). "
            "Falling back to Alpaca. To reactivate, set trading.ib_enabled=true."
        )
        broker_name = "alpaca"

    if broker_name in _brokers:
        broker = _brokers[broker_name]
        if broker.is_connected():
            return broker
        logger.warning("[BROKER] %s connection lost, reconnecting...", broker_name)

    if broker_name == "ib":
        from src.trading.ib_broker import IBBroker
        ib_cfg = live_cfg.get("ib", {})
        broker = IBBroker(
            host=ib_cfg.get("host", "127.0.0.1"),
            port=ib_cfg.get("port", 4002),  # Default to PAPER port
            client_id=ib_cfg.get("client_id", 1),
            timeout=ib_cfg.get("timeout", 10),
        )
        _brokers["ib"] = broker
        logger.info("[BROKER] Using IB broker (port %d)", ib_cfg.get("port", 4002))
        return broker

    # Default: Alpaca (backward compatible — no config change needed)
    from src.trading.alpaca_broker import AlpacaLiveBroker
    broker = AlpacaLiveBroker()
    _brokers["alpaca"] = broker
    logger.info("[BROKER] Using Alpaca live broker")
    return broker


def reset_brokers():
    """Disconnect and clear all cached broker instances.

    Used by tests and when config changes require reconnection.
    """
    for name, broker in _brokers.items():
        try:
            if hasattr(broker, 'disconnect'):
                broker.disconnect()
        except Exception as e:
            logger.debug("[BROKER] Error disconnecting %s: %s", name, e)
    _brokers.clear()
