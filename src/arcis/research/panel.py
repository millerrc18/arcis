"""Session-indexed bar panel for the S07 bracket simulator.

The bar panel is the S04 data plane output: one parquet file per symbol at
`<data_root>/raw/bars/<SYMBOL>.parquet` with Alpaca daily-bar fields
(t, o, h, l, c, v, n, vw), split- and dividend-adjusted. A day is a
session iff SPY has a bar (the S04 reference calendar).

Bars are plain Python objects (not pandas): the strategy features and the
simulator both work on float lists, and pandas is a research-extra
dependency. The parquet read does a lazy pandas import and raises a clear
error when it is absent.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Bar:
    """One daily bar. `date` is the America/New_York session date."""

    date: date
    open: float
    high: float
    low: float
    close: float
    volume: int


class PanelError(Exception):
    """The panel cannot answer a calendar or data question (fail-closed)."""


def _session_date(ts: Any) -> date:
    """Alpaca bar timestamps are NY midnight; take the calendar date."""
    return date(ts.year, ts.month, ts.day)


def load_symbol_bars(data_root: str | Path, symbol: str) -> list[Bar]:
    """Load one symbol's bars, oldest first. Raises PanelError on any gap."""
    try:
        import pandas as pd  # type: ignore[import-untyped]  # lazy: research-extra
    except ImportError as exc:
        raise PanelError(
            "load_symbol_bars needs pandas (research extra); "
            "install with `uv sync --group research`") from exc
    path = Path(data_root) / "raw" / "bars" / f"{symbol}.parquet"
    if not path.exists():
        raise PanelError(f"no bar file for {symbol}: {path}")
    df = pd.read_parquet(path, columns=["t", "o", "h", "l", "c", "v"])
    df = df.sort_values("t").reset_index(drop=True)
    bars = [
        Bar(date=_session_date(row.t), open=float(row.o), high=float(row.h),
            low=float(row.l), close=float(row.c), volume=int(row.v))
        for row in df.itertuples()
    ]
    for prev, cur in zip(bars, bars[1:], strict=False):
        if cur.date <= prev.date:
            raise PanelError(f"{symbol}: bars not strictly increasing "
                             f"at {cur.date}")
    return bars


class Panel:
    """Session-indexed panel over many symbols.

    `calendar` is the ordered session list (SPY's bar dates). Every symbol
    maps each of its bar dates to a Bar; symbols may start late (their
    leading sessions simply have no bar).
    """

    def __init__(self, bars_by_symbol: dict[str, list[Bar]],
                 calendar: list[date]):
        if not calendar:
            raise PanelError("empty session calendar")
        for prev, cur in zip(calendar, calendar[1:], strict=False):
            if cur <= prev:
                raise PanelError("calendar not strictly increasing")
        self._bars = bars_by_symbol
        self._calendar = calendar
        self._index = {d: i for i, d in enumerate(calendar)}

    @property
    def calendar(self) -> list[date]:
        return list(self._calendar)

    @property
    def symbols(self) -> list[str]:
        return sorted(self._bars)

    def session_index(self, d: date) -> int:
        try:
            return self._index[d]
        except KeyError as exc:
            raise PanelError(f"{d} is not a session") from exc

    def is_session(self, d: date) -> bool:
        return d in self._index

    def next_session(self, d: date) -> date:
        i = self.session_index(d)
        if i + 1 >= len(self._calendar):
            raise PanelError(f"no session after {d}")
        return self._calendar[i + 1]

    def add_sessions(self, d: date, n: int) -> date:
        """Session n steps after d (n may be negative). Fail-closed."""
        i = self.session_index(d)
        j = i + n
        if not 0 <= j < len(self._calendar):
            raise PanelError(f"session {d} +/- {n} out of range")
        return self._calendar[j]

    def charge_date(self, trade_date: date) -> date:
        """SEC Section 31 charge date ≈ settlement = T+1 session."""
        return self.next_session(trade_date)

    def bar(self, symbol: str, d: date) -> Bar | None:
        """The symbol's bar on session d, or None if it has none."""
        bars = self._bars.get(symbol)
        if bars is None:
            raise PanelError(f"unknown symbol {symbol}")
        # Bars are dense per symbol after inception; binary search by date.
        import bisect
        dates = [b.date for b in bars]
        i = bisect.bisect_left(dates, d)
        if i < len(bars) and bars[i].date == d:
            return bars[i]
        return None

    def trailing(self, symbol: str, end: date, n: int) -> list[Bar]:
        """The n bars ending on session `end` (inclusive), oldest first."""
        bars = self._bars.get(symbol)
        if bars is None:
            raise PanelError(f"unknown symbol {symbol}")
        if n <= 0:
            raise PanelError(f"trailing count must be positive, got {n}")
        import bisect
        dates = [b.date for b in bars]
        i = bisect.bisect_right(dates, end) - 1
        if i < 0 or bars[i].date != end:
            raise PanelError(f"{symbol} has no bar on {end}")
        if i + 1 < n:
            raise PanelError(
                f"{symbol} has only {i + 1} bars through {end}, need {n}")
        return bars[i - n + 1:i + 1]


def load_panel(data_root: str | Path,
               symbols: list[str]) -> Panel:
    """Load a panel; the calendar is SPY's bar dates (S04 convention)."""
    if "SPY" not in symbols:
        raise PanelError("symbol list must include SPY for the calendar")
    bars_by_symbol = {}
    for symbol in symbols:
        bars_by_symbol[symbol] = load_symbol_bars(data_root, symbol)
    calendar = [b.date for b in bars_by_symbol["SPY"]]
    return Panel(bars_by_symbol, calendar)
