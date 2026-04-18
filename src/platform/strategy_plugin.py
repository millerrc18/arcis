"""Python plugin strategy interface — the v0.24.1 hook for custom strategies.

Called by: src.platform.backtest_engine (python_plugin entry.kind — v0.24.1),
           src.platform.shadow_harness._find_candidates (python_plugin path — v0.24.1).
Calls: abc (ABC), dataclasses.
Owns tables: none.
Config keys: none.
Tests: tests/platform/test_strategy_plugin.py.

Python plugins fit the same interface YAML strategies satisfy — load_spec
by strategy_id, then either a YAML spec interprets the entry block or
a Python class produces candidates directly. v0.24.1 wires this in.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class Candidate:
    """A strategy's proposed trade before bracket/risk checks.

    Shape matches what src.platform.shadow_harness._open_position expects,
    plus what src.platform.signal_eval.find_candidates_for_date returns.
    """
    ticker: str
    as_of: str                    # ISO timestamp
    signal_direction: str         # 'long' | 'short'
    signal_strength: float        # 0.0 to 1.0 — determines sizing
    metadata: dict = field(default_factory=dict)


class StrategyPlugin(ABC):
    """Python plugin interface for complex strategies.

    YAML specs can implement any declarative strategy (Lazy Prices,
    Connors RSI(2), simple event-driven signals). Strategies that need
    custom signal computation — ML models, multi-source synthesis,
    non-trivial numeric pipelines — use this Python interface instead.

    Plugins register via @register_plugin decorator from
    src.platform.plugin_registry.

    v0.24.0: interface definition only. v0.24.1 wires python_plugin
    entry.kind into backtest_engine + shadow_harness.
    """

    @abstractmethod
    def strategy_id(self) -> str:
        """Unique identifier — matches the strategy_registry row."""
        ...

    @abstractmethod
    def find_candidates(
        self, as_of: str, universe: list[str], context: dict,
    ) -> list[Candidate]:
        """Scan universe at `as_of` date. Context contains 'db_path'
        and any other platform-provided resources. Returns zero or
        more Candidate objects — caller applies hard exposure limits
        and bracket placement.
        """
        ...

    def validate_candidate(
        self, candidate: Candidate, market_data: dict,
    ) -> bool:
        """Optional: plugin-specific validation after market data is
        available. Default: always True. Override for ML confidence
        gates, volatility filters, or anything that needs live data."""
        return True
