"""Platform data-access adapter.

Called by: src.platform.backtest_engine
Calls: src.simulation.cache (fetch_cached_ohlcv), src.analytics.spy_benchmark,
       src.universe.sp100
Owns tables: none.
Tests: tests/platform/test_data_loader.py.

Thin wrapper so the backtest engine has a single clean import surface.
"""

from __future__ import annotations

import logging

import pandas as pd

from src.analytics.spy_benchmark import spy_return_over_range
from src.simulation.cache import fetch_cached_ohlcv
from src.universe.sp100 import get_sp100_universe

logger = logging.getLogger(__name__)


def load_ohlcv_range(ticker: str, start: str, end: str) -> pd.DataFrame | None:
    """Delegate to simulation.cache. Returns None on missing data."""
    return fetch_cached_ohlcv(ticker, start, end)


def load_spy_return(entry_iso: str, exit_iso: str) -> float | None:
    """Delegate to analytics.spy_benchmark. Returns None on missing data."""
    return spy_return_over_range(entry_iso, exit_iso)


def load_universe_as_of(universe_tag: str, date: str) -> list[str]:
    """S&P 100 membership. Static for MVP (current membership only).

    LIMITATION: no point-in-time universe corrections. A stock that
    joined SPX in 2022 will be in the 2015 backtest universe. This is a
    known bias; acceptable for MVP, must be fixed before live capital.
    """
    if universe_tag == "sp500":
        logger.warning(
            "[PLATFORM] %s universe requested but not implemented; "
            "falling back to sp100 (date=%s)",
            universe_tag, date,
        )
    return get_sp100_universe()
