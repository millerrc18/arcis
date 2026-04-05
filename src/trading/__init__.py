"""Multi-broker trading abstraction layer.

Provides a unified BrokerAdapter interface for live trading across
different brokers (Alpaca, Interactive Brokers). Paper trading is NOT
routed through this layer — it continues calling alpaca_adapter.py directly.

Modules:
    broker_interface: Abstract base class + normalized dataclasses
    alpaca_broker: Wraps existing alpaca_adapter.py live functions
    ib_broker: Interactive Brokers adapter via ib_async
    broker_factory: Config-driven singleton factory

Config: live_trading.broker = "alpaca" | "ib"
"""
