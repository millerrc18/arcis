"""Single-source north-star gate targets for the Founder Console.

Called by: src.console.decisions (capital_advance source); later tasks repoint
           src.api.cloud_routes.console_now to import from here too.
Calls: none
Owns tables: none
Config keys: none
Tests: tests/test_console_decisions.py

The bar each north-star gate metric must clear before Phase-1 capital can
advance. Defined exactly once here so the NOW-region gate display and the
DECIDE-region capital_advance source agree on the same thresholds (no drift).
"""
from __future__ import annotations

GATE_TARGETS: dict[str, float] = {
    "closed_trade_count": 100,
    "excess_sharpe_vs_spy": 0.5,
    "sharpe_t_stat": 2.0,
    "max_drawdown": 0.20,
}
