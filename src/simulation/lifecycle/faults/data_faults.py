"""Data fault injectors (Task 10).

Reproduce data-shape / data-supply fault classes by wrapping the fakes'
read surfaces on the INSTANCE (never editing the fake):

  * SchemaDriftFault — the OHLCV frame loses an expected column (an upstream
    rename/drop), so any code that assumes the column shape breaks loudly.
  * CorpusStarvationFault — the scan/corpus surface returns NOTHING (the
    holdout-empty / corpus-starved fault that wedged training).

Called by: the ScenarioRunner (Task 11) — NOT wired here.
Calls: src.simulation.lifecycle.fakes (FakeMarketData / FakeLLM seams only).
Owns tables: none. Config keys: none.
Tests: tests/simulation/lifecycle/test_faults.py
"""

from __future__ import annotations

from src.simulation.lifecycle.faults import FaultInjector


class SchemaDriftFault(FaultInjector):
    """Drop a column from every OHLCV frame the fake returns (schema drift)."""

    def __init__(self, market, *, drop: str = "Volume") -> None:
        super().__init__()
        self._market = market
        self._drop = drop
        self._original = None

    def _install(self) -> None:
        self._original = self._market.fetch_cached_ohlcv
        column = self._drop

        def _fetch(ticker, start, end):
            frame = self._original(ticker, start, end)
            if column in frame.columns:
                frame = frame.drop(columns=[column])
            return frame

        self._market.fetch_cached_ohlcv = _fetch

    def _restore(self) -> None:
        self._market.fetch_cached_ohlcv = self._original


class CorpusStarvationFault(FaultInjector):
    """The candidate corpus is starved — the scan yields no candidates."""

    def __init__(self, llm) -> None:
        super().__init__()
        self._llm = llm
        self._original = None

    def _install(self) -> None:
        self._original = self._llm.generate_candidates
        self._llm.generate_candidates = lambda: []

    def _restore(self) -> None:
        self._llm.generate_candidates = self._original
