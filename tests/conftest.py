"""Shared test fixtures and helpers.

Provides init_test_db() to create all schema tables in a temp database,
replacing the per-module CREATE TABLE statements removed during the
schema registry migration (PR #189).

Also provides mock Alpaca modules via sys.modules injection so that
deferred imports inside alpaca_adapter.py resolve to mocks without
requiring the alpaca-py SDK at test time.
"""

import sqlite3
import sys
import types
from unittest.mock import MagicMock

import pytest

from src.schema.registry import TABLES
from src.schema.sqlite import generate_create_sql


def init_test_db(db_path: str, tables: list[str] | None = None) -> None:
    """Create schema tables in a test database.

    Args:
        db_path: Path to the SQLite database file.
        tables: Optional list of table names to create. If None, creates all.
    """
    with sqlite3.connect(db_path) as conn:
        if tables is None:
            for tdef in TABLES.values():
                conn.executescript(generate_create_sql(tdef))
        else:
            for name in tables:
                if name in TABLES:
                    conn.executescript(generate_create_sql(TABLES[name]))


# ---------------------------------------------------------------------------
# Mock Alpaca SDK modules for deferred-import compatibility
# ---------------------------------------------------------------------------

class _MockEnum:
    """Enum-like object whose attributes return named values."""
    def __init__(self, name, value):
        self._name = name
        self._value = value
        self.value = value
    def __repr__(self):
        return f"{self._name}"


class _MockEnumClass:
    """Factory that produces _MockEnum instances for attribute access."""
    def __init__(self, name):
        self._name = name
    def __getattr__(self, item):
        return _MockEnum(f"{self._name}.{item}", item.lower())


class _MockOrderRequest:
    """Mock for MarketOrderRequest / LimitOrderRequest.

    Stores all constructor kwargs as attributes so tests can inspect
    request.symbol, request.qty, request.time_in_force.value, etc.
    """
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


def _build_mock_alpaca_modules():
    """Create a tree of mock alpaca modules for sys.modules injection."""
    alpaca = types.ModuleType("alpaca")
    trading = types.ModuleType("alpaca.trading")
    trading_client = types.ModuleType("alpaca.trading.client")
    trading_requests = types.ModuleType("alpaca.trading.requests")
    trading_enums = types.ModuleType("alpaca.trading.enums")
    data = types.ModuleType("alpaca.data")
    data_historical = types.ModuleType("alpaca.data.historical")
    data_requests = types.ModuleType("alpaca.data.requests")

    # Wire up parent-child relationships
    alpaca.trading = trading
    alpaca.data = data
    trading.client = trading_client
    trading.requests = trading_requests
    trading.enums = trading_enums
    data.historical = data_historical
    data.requests = data_requests

    # Populate classes
    trading_client.TradingClient = MagicMock(name="TradingClient")
    trading_requests.MarketOrderRequest = _MockOrderRequest
    trading_requests.LimitOrderRequest = _MockOrderRequest
    trading_enums.OrderSide = _MockEnumClass("OrderSide")
    trading_enums.TimeInForce = _MockEnumClass("TimeInForce")
    trading_enums.OrderClass = _MockEnumClass("OrderClass")
    data_historical.StockHistoricalDataClient = MagicMock(name="StockHistoricalDataClient")
    data_requests.StockLatestTradeRequest = MagicMock(name="StockLatestTradeRequest")

    return {
        "alpaca": alpaca,
        "alpaca.trading": trading,
        "alpaca.trading.client": trading_client,
        "alpaca.trading.requests": trading_requests,
        "alpaca.trading.enums": trading_enums,
        "alpaca.data": data,
        "alpaca.data.historical": data_historical,
        "alpaca.data.requests": data_requests,
    }


@pytest.fixture(autouse=True)
def _mock_alpaca_sdk(monkeypatch):
    """Inject mock alpaca modules into sys.modules.

    This ensures deferred imports like ``from alpaca.trading.enums import
    OrderSide`` inside alpaca_adapter.py resolve to lightweight mocks,
    satisfying CLAUDE.md's "mock all external APIs in tests" rule.
    """
    mods = _build_mock_alpaca_modules()
    for mod_name, mod_obj in mods.items():
        monkeypatch.setitem(sys.modules, mod_name, mod_obj)
