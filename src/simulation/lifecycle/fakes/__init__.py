"""Stateful fakes for the lifecycle simulator (Task 5).

Called by: the ScenarioRunner (later task) — NOT wired here.
Calls: src.simulation.lifecycle.clock (VirtualClock).
Owns tables: none. Config keys: none.
Tests: tests/simulation/lifecycle/test_fake_trading_client.py
"""

from src.simulation.lifecycle.fakes.llm import FakeLLM
from src.simulation.lifecycle.fakes.market_data import FakeMarketData
from src.simulation.lifecycle.fakes.trading_client import (
    FakeOrder,
    FakePosition,
    FakeTradingClient,
)

__all__ = [
    "FakeLLM",
    "FakeMarketData",
    "FakeOrder",
    "FakePosition",
    "FakeTradingClient",
]
