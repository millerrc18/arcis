"""Trade performance metric helpers (expectancy, win rate).

Called by: evaluation.cto_report, shadow_trading.metrics
Calls: none
Owns tables: none
Config keys: none
Tests: tests/test_metrics.py
"""

from typing import Iterable


def expectancy(trade_pnls: Iterable[float]) -> float:
    pnls = list(trade_pnls)
    if not pnls:
        return 0.0
    return sum(pnls) / len(pnls)
