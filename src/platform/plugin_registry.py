"""Plugin registry for Python strategy plugins.

Called by: src.platform.backtest_engine, src.platform.shadow_harness
           (both v0.24.1).
Calls: src.platform.strategy_plugin (StrategyPlugin).
Owns tables: none.
Config keys: none.
Tests: tests/platform/test_strategy_plugin.py.
"""
from __future__ import annotations

from typing import Optional

from src.platform.strategy_plugin import StrategyPlugin

_PLUGINS: dict[str, type[StrategyPlugin]] = {}


def register_plugin(cls: type[StrategyPlugin]) -> type[StrategyPlugin]:
    """Decorator: registers a plugin class under its strategy_id.

    Usage:
        @register_plugin
        class MyStrategy(StrategyPlugin):
            def strategy_id(self) -> str:
                return "my_strategy_v1"
            ...
    """
    instance = cls()
    _PLUGINS[instance.strategy_id()] = cls
    return cls


def get_plugin(strategy_id: str) -> Optional[StrategyPlugin]:
    """Return an instance of the registered plugin for this strategy_id,
    or None if no plugin is registered (e.g. for YAML-only strategies)."""
    cls = _PLUGINS.get(strategy_id)
    return cls() if cls else None


def list_registered_plugins() -> list[str]:
    """For operator inspection: strategy_ids with Python plugins."""
    return sorted(_PLUGINS.keys())


def _clear_registry_for_tests() -> None:
    """Test hook — clear registry between test cases to avoid pollution."""
    _PLUGINS.clear()
