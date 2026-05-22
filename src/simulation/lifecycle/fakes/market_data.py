"""Deterministic FakeMarketData at the OHLCV-cache boundary (Task 6).

This fake stands in for ``src.simulation.cache.fetch_cached_ohlcv`` — the
function the simulation engine calls to obtain a ticker's price history. The
real function returns a pandas DataFrame with the yfinance column shape
(``Open``, ``High``, ``Low``, ``Close``, ``Volume``) indexed by trading date;
this fake emits the SAME shape from a seeded random walk so no network / yfinance
call is made and identical seeds reproduce identical bars (spec §7.2).

Determinism: the per-ticker stream is seeded from ``(seed, ticker, start, end)``
so two FakeMarketData instances with the same seed return frame-equal bars, and
different tickers produce independent series.

Fault hooks (Task 10): gap / halt / regime injection is intentionally NOT
implemented here. Clean seams are left — ``_bar_hook`` is applied to every bar
row before assembly (identity by default), so a later task can wrap it to punch
gaps, freeze a halt, or bend a regime without touching this generator.

Called by: the ScenarioRunner (later task) — NOT wired here.
Calls: nothing (pure numpy/pandas). Owns tables: none. Config keys: none.
Tests: tests/simulation/lifecycle/test_fake_market_llm.py
"""

from __future__ import annotations

import hashlib
from typing import Callable, Optional

import numpy as np
import pandas as pd

_OHLCV_COLUMNS = ["Open", "High", "Low", "Close", "Volume"]

# A bar row passed through the fault hook before frame assembly.
BarRow = dict
BarHook = Callable[[BarRow], BarRow]


def _identity_bar_hook(bar: BarRow) -> BarRow:
    """Default fault hook: pass each bar through unchanged (Task 10 seam)."""
    return bar


class FakeMarketData:
    """Seeded OHLCV generator standing in for cache.fetch_cached_ohlcv."""

    def __init__(
        self,
        *,
        seed: int = 0,
        base_price: float = 100.0,
        bar_hook: Optional[BarHook] = None,
    ) -> None:
        self._seed = seed
        self._base_price = base_price
        self._bar_hook = bar_hook or _identity_bar_hook

    def _stream_seed(self, ticker: str, start: str, end: str) -> int:
        """Derive a stable per-(seed, ticker, window) integer seed."""
        key = f"{self._seed}|{ticker}|{start}|{end}".encode("utf-8")
        return int.from_bytes(hashlib.sha256(key).digest()[:8], "big")

    def fetch_cached_ohlcv(self, ticker: str, start: str, end: str) -> pd.DataFrame:
        """Return seeded OHLCV bars shaped like cache.fetch_cached_ohlcv."""
        rng = np.random.default_rng(self._stream_seed(ticker, start, end))
        dates = pd.bdate_range(start=start, end=end)
        rows: list[BarRow] = []
        price = self._base_price
        for ts in dates:
            open_p = price
            ret = rng.normal(0.0, 0.015)
            close_p = open_p * (1.0 + ret)
            high_p = max(open_p, close_p) * (1.0 + abs(rng.normal(0.0, 0.005)))
            low_p = min(open_p, close_p) * (1.0 - abs(rng.normal(0.0, 0.005)))
            volume = int(rng.integers(1_000_000, 10_000_000))
            rows.append(self._bar_hook({
                "Open": round(open_p, 4),
                "High": round(high_p, 4),
                "Low": round(low_p, 4),
                "Close": round(close_p, 4),
                "Volume": volume,
            }))
            price = close_p
        frame = pd.DataFrame(rows, index=dates, columns=_OHLCV_COLUMNS)
        frame.index.name = "Date"
        return frame
