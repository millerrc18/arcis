"""Transaction-cost application for walk-forward (R4).

Called by: src.platform.rigor.walkforward_runner.
Calls: dataclasses (replace).
Owns tables: none.
Config keys: none.
Tests: tests/platform/rigor/test_walkforward_costs.py.

The walk-forward runner calls the underlying backtest engine with zero
commission/slippage/spread and applies costs uniformly here — so the
framework has a single obvious cost accounting point and tests can
assert every metric is net-of-cost.

Per-side cost = 0.5 bp (default). Round-trip = 1.0 bp. Applied symmetrically:
    entry_effective = entry * (1 + per_side_bps / 10_000)
    exit_effective  = exit  * (1 - per_side_bps / 10_000)
    pnl_pct         = (exit_effective - entry_effective) / entry_effective

All mutations return NEW trade objects; input list is untouched. Works
with both BacktestTrade dataclasses and plain dicts.
"""

from __future__ import annotations

import math
from dataclasses import replace, is_dataclass
from typing import Any, Iterable


def _get(t: Any, key: str, default=None):
    if hasattr(t, key):
        return getattr(t, key)
    if isinstance(t, dict):
        return t.get(key, default)
    return default


def _with_updates(t: Any, updates: dict) -> Any:
    """Return a copy of t with updates applied. Preserves dataclass type
    for BacktestTrade; returns a fresh dict for dict input."""
    if is_dataclass(t) and not isinstance(t, type):
        return replace(t, **updates)
    if isinstance(t, dict):
        new = dict(t)
        new.update(updates)
        return new
    raise TypeError(
        f"cannot apply cost to trade of type {type(t).__name__}; "
        "expected dataclass or dict"
    )


def apply_per_side_cost(
    trade: Any, per_side_bps: float = 0.5,
) -> Any:
    """Apply symmetric per-side bps cost to a single trade. Returns a new
    trade with adjusted entry_price, exit_price, pnl_pct, and pnl_dollars
    (if present)."""
    if per_side_bps < 0:
        raise ValueError("per_side_bps must be >= 0")
    entry = _get(trade, "entry_price")
    exit_ = _get(trade, "exit_price")
    if entry is None or exit_ is None:
        # No prices — cannot compute; return input unchanged to keep shape
        return trade
    if entry <= 0:
        return trade
    factor = per_side_bps / 10_000.0
    entry_adj = entry * (1.0 + factor)
    exit_adj = exit_ * (1.0 - factor)
    pnl_pct = (exit_adj - entry_adj) / entry_adj
    updates: dict = {
        "entry_price": entry_adj,
        "exit_price": exit_adj,
        "pnl_pct": pnl_pct,
    }
    shares = _get(trade, "shares")
    if shares is not None:
        updates["pnl_dollars"] = float(shares) * (exit_adj - entry_adj)
    return _with_updates(trade, updates)


def apply_per_side_cost_batch(
    trades: Iterable[Any], per_side_bps: float = 0.5,
) -> list[Any]:
    """Apply per-side cost to a batch. Returns a list of new trade objects
    in the original order."""
    return [apply_per_side_cost(t, per_side_bps) for t in trades]


def round_trip_cost_bps(per_side_bps: float) -> float:
    """Convenience: 2 * per_side_bps. Used for reporting."""
    return 2.0 * per_side_bps


def pnl_gross_vs_net(
    gross_pnl_pct: float, per_side_bps: float,
) -> float:
    """Given a gross pnl_pct and per-side bps, return the net. Identity
    used by the regression-style guard test that makes sure the framework
    never silently reports gross."""
    if not math.isfinite(gross_pnl_pct):
        return gross_pnl_pct
    factor = per_side_bps / 10_000.0
    # If gross was (exit/entry - 1), the net = ((1 - f) exit) / ((1 + f) entry) - 1.
    # Equivalently: net = (1 + gross) * (1 - f) / (1 + f) - 1.
    return (1.0 + gross_pnl_pct) * (1.0 - factor) / (1.0 + factor) - 1.0
