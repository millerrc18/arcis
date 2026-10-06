"""Session-indexed bar panel for the S07 bracket simulator.

The panel is the simulator's sole view of market data: a mapping
symbol -> list of daily bars plus the session calendar (SPY bar dates).
It owns two preregistered data-plane rules:

- T+1 charge-date derivation for SEC fees (PREREG §1.2: "≈ settlement").
  Settlement was T+3 before 2017-09-05 and T+2 from 2017-09-05 until the
  2024-05-28 move to T+1, so the charge lag follows the historical
  regime (fee_schedules.py documents the same dates).
- Fail-closed bars: every calendar session inside a symbol's
  [first_bar, last_bar] range must have a bar or be a *declared* halt.
  Anything else is a data gap and raises PanelError at construction.
  Declared halts are skipped (not counted) by the simulator; undeclared
  gaps can never silently extend a holding period.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

# Settlement regime boundaries (SRO T+3 -> T+2 -> T+1 history).
_T2_START = date(2017, 9, 5)
_T1_START = date(2024, 5, 28)


class PanelError(Exception):
    """Fail-closed data problem: gaps, unknown sessions, short history."""


@dataclass(frozen=True)
class Bar:
    date: date
    open: float
    high: float
    low: float
    close: float
    volume: int


def _session_date(ts: Any) -> date:
    """Alpaca bar timestamps are NY midnight; take the calendar date."""
    return date(ts.year, ts.month, ts.day)


class Panel:
    """Session calendar + per-symbol bars with fail-closed gap checks."""

    def __init__(self, bars: dict[str, list[Bar]],
                 halts: dict[str, set[date]] | None = None) -> None:
        self._bars: dict[str, dict[date, Bar]] = {}
        self._halts: dict[str, frozenset[date]] = {
            s: frozenset(h) for s, h in (halts or {}).items()
        }
        cal: set[date] = set()
        for symbol, blist in bars.items():
            by_date = {b.date: b for b in blist}
            self._bars[symbol] = by_date
            cal.update(by_date)
        self._calendar = sorted(cal)
        if not self._calendar:
            raise PanelError("empty calendar: no bars")
        self._index = {d: i for i, d in enumerate(self._calendar)}
        for symbol, by_date in self._bars.items():
            self._check_gaps(symbol, by_date)

    def _check_gaps(self, symbol: str, by_date: dict[date, Bar]) -> None:
        """Fail-closed: no undeclared gaps inside the symbol's bar range."""
        if not by_date:
            raise PanelError(f"{symbol}: no bars")
        first, last = min(by_date), max(by_date)
        halts = self._halts.get(symbol, frozenset())
        for d in self._calendar:
            if d < first or d > last:
                continue  # outside the symbol's range: not listed/delisted
            if d not in by_date and d not in halts:
                raise PanelError(
                    f"{symbol}: missing bar for session {d} "
                    "(not a declared halt)")

    # -- calendar ---------------------------------------------------------
    @property
    def calendar(self) -> list[date]:
        return list(self._calendar)

    def is_session(self, d: date) -> bool:
        return d in self._index

    def session_index(self, d: date) -> int:
        try:
            return self._index[d]
        except KeyError:
            raise PanelError(f"{d} is not a session") from None

    def next_session(self, d: date) -> date:
        try:
            i = self._index[d]
        except KeyError:
            raise PanelError(f"{d} is not a session") from None
        if i + 1 >= len(self._calendar):
            raise PanelError(f"no session after {d}")
        return self._calendar[i + 1]

    def prev_session(self, d: date) -> date:
        try:
            i = self._index[d]
        except KeyError:
            raise PanelError(f"{d} is not a session") from None
        if i == 0:
            raise PanelError(f"no session before {d}")
        return self._calendar[i - 1]

    def add_sessions(self, d: date, n: int) -> date:
        """Session n steps after d (n may be negative). Fail-closed."""
        try:
            i = self._index[d]
        except KeyError:
            raise PanelError(f"{d} is not a session") from None
        j = i + n
        if not 0 <= j < len(self._calendar):
            raise PanelError(f"session {n:+d} from {d} out of range")
        return self._calendar[j]

    def charge_date(self, session: date) -> date:
        """SEC fee charge date ≈ settlement: T+3 / T+2 / T+1 by regime."""
        if session >= _T1_START:
            lag = 1
        elif session >= _T2_START:
            lag = 2
        else:
            lag = 3
        return self.add_sessions(session, lag)

    # -- bars --------------------------------------------------------------
    @property
    def symbols(self) -> list[str]:
        return sorted(self._bars)

    def bars_for(self, symbol: str) -> dict[date, Bar]:
        if symbol not in self._bars:
            raise PanelError(f"unknown symbol: {symbol}")
        return dict(self._bars[symbol])

    def bar(self, symbol: str, d: date) -> Bar | None:
        if symbol not in self._bars:
            raise PanelError(f"unknown symbol: {symbol}")
        return self._bars[symbol].get(d)

    def is_halt(self, symbol: str, d: date) -> bool:
        """Whether (symbol, session) was declared a halt up front."""
        return d in self._halts.get(symbol, frozenset())

    def trailing(self, symbol: str, session: date, n: int) -> list[Bar]:
        """Last n bars ending at `session` (all must exist)."""
        if symbol not in self._bars:
            raise PanelError(f"unknown symbol: {symbol}")
        i = self._index.get(session)
        if i is None:
            raise PanelError(f"{session} is not a session")
        start = i - n + 1
        if start < 0:
            raise PanelError(
                f"{symbol}: only {i + 1} bars through {session}, need {n}")
        by_date = self._bars[symbol]
        bars = [by_date.get(self._calendar[k]) for k in range(start, i + 1)]
        if any(b is None for b in bars):
            raise PanelError(f"{symbol}: missing bar in trailing window")
        return [b for b in bars if b is not None]


def load_symbol_bars(symbol: str, path: str | Path,
                     halts: set[date] | None = None
                     ) -> tuple[list[Bar], set[date]]:
    """Read one Alpaca parquet bar file. Returns (bars, calendar_dates).

    Expects columns o/h/l/c/v (t = NY-midnight timestamp). Raises
    PanelError on non-monotonic dates. Gaps vs the SPY calendar are
    checked at Panel construction; pass `halts` for declared halt dates.
    """
    try:
        import pandas as pd  # type: ignore[import-untyped]  # research extra
    except ImportError as exc:
        raise PanelError(
            "load_symbol_bars needs pandas (research extra)") from exc
    df = pd.read_parquet(path)
    need = {"o", "h", "l", "c", "v"}
    if not need.issubset(df.columns):
        raise PanelError(f"{symbol}: missing columns {need - set(df.columns)}")
    bars = [
        Bar(_session_date(row.t), float(row.o), float(row.h),
            float(row.l), float(row.c), int(row.v))
        for row in df.itertuples()
    ]
    for prev, cur in zip(bars, bars[1:], strict=False):
        if cur.date <= prev.date:
            raise PanelError(f"{symbol}: bars not strictly increasing "
                             f"at {cur.date}")
    return bars, {b.date for b in bars}


def build_panel(symbols: list[str], bar_dir: str | Path,
                halts: dict[str, set[date]] | None = None) -> Panel:
    """Load <SYMBOL>.parquet files and build a gap-checked Panel."""
    bar_dir = Path(bar_dir)
    bars = {}
    for symbol in symbols:
        blist, _ = load_symbol_bars(symbol, bar_dir / f"{symbol}.parquet")
        bars[symbol] = blist
    return Panel(bars, halts)


def load_panel(bar_dir: str | Path, symbols: list[str],
               halts: dict[str, set[date]] | None = None) -> Panel:
    """Build a Panel, requiring SPY (the session-calendar source)."""
    if "SPY" not in symbols:
        raise PanelError("SPY is required (session-calendar source)")
    return build_panel(symbols, bar_dir, halts)
