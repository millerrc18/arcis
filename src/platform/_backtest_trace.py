"""Test-only instrumentation hook for the backtest engine.

Exposes a module-level list that, when set, captures (ticker, entry_iso,
max_history_date) for every _build_trade call. Production runs leave the
list at None so the hook is a zero-cost branch.

Kept in its own module so the backtest_engine file stays under the 400-line
guardrail.

Called by: platform.backtest_engine._build_trade.
Calls: none (stdlib only).
Owns tables: none.
Config keys: none.
Tests: tests/platform/test_backtest_engine.py::test_backtest_no_lookahead_bias.
"""
from __future__ import annotations

import pandas as pd

_LOOKAHEAD_TRACE: list[tuple[str, str, str]] | None = None


def set_trace(enabled: bool) -> list[tuple[str, str, str]] | None:
    """Enable or disable trace collection. Returns the active list (or None)."""
    global _LOOKAHEAD_TRACE
    _LOOKAHEAD_TRACE = [] if enabled else None
    return _LOOKAHEAD_TRACE


def get_trace() -> list[tuple[str, str, str]] | None:
    """Return the current trace list (None if disabled)."""
    return _LOOKAHEAD_TRACE


def record(ticker: str, entry_iso: str, history_df: pd.DataFrame | None) -> None:
    """Append max history date to trace. No-op unless trace is enabled."""
    if _LOOKAHEAD_TRACE is None or history_df is None or history_df.empty:
        return
    max_date = history_df.index[-1].strftime("%Y-%m-%d")
    _LOOKAHEAD_TRACE.append((ticker, entry_iso, max_date))
