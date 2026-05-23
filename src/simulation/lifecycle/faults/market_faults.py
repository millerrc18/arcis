"""Market fault injectors (Task 10).

Reproduce market-side fault classes via the FakeMarketData ``_bar_hook`` seam
(from T6) and the FakeLLM candidate-volume knob. The fakes are NEVER edited:
faults swap ``market._bar_hook`` / wrap ``market.fetch_cached_ohlcv`` / set
``llm._n_candidates`` on the INSTANCE and restore on disarm.

Faults provided:
  * MarketGapFault — every bar gaps by ``gap_pct`` (close pushed off open).
  * MarketHaltFault — price is frozen (open == high == low == close): no trade.
  * RegimeShiftFault — a cumulative drift bends the whole Close series.
  * HighCandidateVolumeFault — the scan emits a flood of candidates.

Called by: the ScenarioRunner (Task 11) — NOT wired here.
Calls: src.simulation.lifecycle.fakes (FakeMarketData / FakeLLM seams only).
Owns tables: none. Config keys: none.
Tests: tests/simulation/lifecycle/test_faults.py
"""

from __future__ import annotations

from typing import Optional

from src.simulation.lifecycle.faults import FaultInjector


class _BarHookFault(FaultInjector):
    """Base for faults that swap a FakeMarketData instance's ``_bar_hook``."""

    def __init__(self, market) -> None:
        super().__init__()
        self._market = market
        self._original = None

    def _install(self) -> None:
        self._original = self._market._bar_hook
        self._market._bar_hook = self._hook

    def _restore(self) -> None:
        self._market._bar_hook = self._original

    def _hook(self, bar):  # pragma: no cover - overridden
        raise NotImplementedError


class MarketGapFault(_BarHookFault):
    """Push every bar's close off its open by ``gap_pct`` (a price gap)."""

    def __init__(self, market, *, gap_pct: float = -0.1) -> None:
        super().__init__(market)
        self._gap_pct = gap_pct

    def _hook(self, bar):
        gapped = dict(bar)
        gapped["Close"] = round(bar["Open"] * (1.0 + self._gap_pct), 4)
        gapped["High"] = max(gapped["Open"], gapped["Close"])
        gapped["Low"] = min(gapped["Open"], gapped["Close"])
        return gapped


class MarketHaltFault(_BarHookFault):
    """Freeze price: open == high == low == close (no trading possible)."""

    def _hook(self, bar):
        frozen = dict(bar)
        open_p = bar["Open"]
        frozen["High"] = open_p
        frozen["Low"] = open_p
        frozen["Close"] = open_p
        frozen["Volume"] = 0
        return frozen


class RegimeShiftFault(FaultInjector):
    """Apply a cumulative drift to the whole Close series (a regime shift)."""

    def __init__(self, market, *, drift: float = -0.3) -> None:
        super().__init__()
        self._market = market
        self._drift = drift
        self._original = None

    def _install(self) -> None:
        self._original = self._market.fetch_cached_ohlcv
        drift = self._drift

        def _fetch(ticker, start, end):
            frame = self._original(ticker, start, end)
            n = len(frame)
            if n == 0:
                return frame
            factors = [1.0 + drift * (i + 1) / n for i in range(n)]
            frame = frame.copy()
            frame["Close"] = [round(c * f, 4) for c, f in zip(frame["Close"], factors)]
            return frame

        self._market.fetch_cached_ohlcv = _fetch

    def _restore(self) -> None:
        self._market.fetch_cached_ohlcv = self._original


class HighCandidateVolumeFault(FaultInjector):
    """Flood the scan with a high volume of candidates."""

    def __init__(self, llm, *, n_candidates: int = 100) -> None:
        super().__init__()
        self._llm = llm
        self._n = n_candidates
        self._original: Optional[int] = None

    def _install(self) -> None:
        self._original = self._llm._n_candidates
        self._llm._n_candidates = self._n

    def _restore(self) -> None:
        self._llm._n_candidates = self._original
