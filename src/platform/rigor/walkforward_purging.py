"""Purge + embargo logic for walk-forward validation (R2).

Called by: src.platform.rigor.walkforward_runner.
Calls: datetime.
Owns tables: none.
Config keys: none.
Tests: tests/platform/rigor/test_walkforward_purging.py.

Two defenses against train/test leakage:

  PURGE — remove from the IS window any trade whose (entry, exit) interval
  overlaps the OOS window. A trade that enters in IS but exits in OOS has
  realized PnL contaminated by OOS price action; the fix is to drop it
  from the IS statistics entirely.

  EMBARGO — remove from the OOS window any trade whose entry falls within
  `embargo_days` trading days of the OOS start. This is signal-leak
  defense: information that shaped the strategy (news, earnings bleed
  from IS period) can still influence early OOS entries.

Both operate on trade intervals by ISO date string. We intentionally
avoid pandas/BusinessDay arithmetic to keep the module dependency-free
and hand-auditable.
"""

from __future__ import annotations

from datetime import date, timedelta
from dataclasses import dataclass
from typing import Any, Iterable


@dataclass
class TradeInterval:
    """Minimal trade shape the purging module needs. Any object with
    .entry_date / .exit_date (ISO yyyy-mm-dd strings) is accepted; callers
    pass BacktestTrade in practice."""

    entry_date: str
    exit_date: str | None


def _parse(d: str) -> date:
    try:
        return date.fromisoformat(d)
    except (TypeError, ValueError) as e:
        raise ValueError(f"expected ISO yyyy-mm-dd, got {d!r}") from e


def _entry_of(trade: Any) -> date:
    raw = getattr(trade, "entry_date", None)
    if raw is None and isinstance(trade, dict):
        raw = trade.get("entry_date")
    if raw is None:
        raise ValueError("trade has no entry_date")
    return _parse(raw)


def _exit_of(trade: Any) -> date | None:
    raw = getattr(trade, "exit_date", None)
    if raw is None and isinstance(trade, dict):
        raw = trade.get("exit_date")
    if raw is None or raw == "":
        return None
    return _parse(raw)


def _add_trading_days(start: date, n: int) -> date:
    """Move forward n trading days (Mon–Fri). Does not account for holidays
    — matches backtest_engine._iter_trading_days convention."""
    if n <= 0:
        return start
    cur = start
    added = 0
    while added < n:
        cur = cur + timedelta(days=1)
        if cur.weekday() < 5:  # Mon=0..Fri=4
            added += 1
    return cur


def purge_is_trades(
    is_trades: Iterable[Any],
    oos_start: str,
    oos_end: str,
) -> list[Any]:
    """Return the IS trades that do NOT overlap the [oos_start, oos_end]
    interval. A trade overlaps if its [entry, exit] interval intersects
    the OOS interval (open/closed semantics: we treat both as closed).

    Specifically, a trade is PURGED if:
        (entry <= oos_end) AND (exit is None OR exit >= oos_start)

    Trades entirely before (exit < oos_start) or entirely after
    (entry > oos_end) are retained.
    """
    oos_s = _parse(oos_start)
    oos_e = _parse(oos_end)
    if oos_e < oos_s:
        raise ValueError(f"oos_end {oos_end} < oos_start {oos_start}")
    kept = []
    for t in is_trades:
        entry = _entry_of(t)
        exit_ = _exit_of(t)
        # Overlap test. A trade with no exit date is treated as still open
        # through the end of time — conservatively purged if entry <= oos_end.
        if exit_ is None:
            if entry <= oos_e:
                continue
            kept.append(t)
            continue
        if entry > oos_e or exit_ < oos_s:
            kept.append(t)
    return kept


def embargo_oos_trades(
    oos_trades: Iterable[Any],
    oos_start: str,
    oos_end: str,
    embargo_days: int = 5,
) -> list[Any]:
    """Remove OOS trades whose entry falls within `embargo_days` trading
    days of oos_start (inclusive of oos_start). Trades after the embargo
    window are retained.

    Embargo only applies at the *start* of the OOS window — the end does
    not have a symmetric embargo because there is nothing after the final
    OOS to leak backwards into it. (This matches López de Prado 2018
    §7.4.)

    If embargo_days == 0 the function is a pass-through — returns a list
    copy of the input preserving order.
    """
    if embargo_days < 0:
        raise ValueError("embargo_days must be >= 0")
    oos_s = _parse(oos_start)
    oos_e = _parse(oos_end)
    if oos_e < oos_s:
        raise ValueError(f"oos_end {oos_end} < oos_start {oos_start}")
    if embargo_days == 0:
        return list(oos_trades)
    cutoff = _add_trading_days(oos_s, embargo_days)
    kept = []
    for t in oos_trades:
        entry = _entry_of(t)
        if entry >= cutoff:
            kept.append(t)
    return kept


def classify_trades_for_audit(
    all_trades: Iterable[Any],
    oos_start: str,
    oos_end: str,
    embargo_days: int = 5,
) -> dict[str, list[Any]]:
    """Split a combined trade list into {purged, embargoed, is_kept, oos_kept}.

    Used by the runner for audit logging into walkforward_trades. A trade
    can be counted once: classification precedence is embargo (OOS only)
    > purge (IS only) > is_kept (entry before oos_start) > oos_kept.
    """
    oos_s = _parse(oos_start)
    result: dict[str, list[Any]] = {
        "purged": [], "embargoed": [], "is_kept": [], "oos_kept": [],
    }
    embargo_cutoff = (
        _add_trading_days(oos_s, embargo_days) if embargo_days > 0 else oos_s
    )
    for t in all_trades:
        entry = _entry_of(t)
        exit_ = _exit_of(t)
        is_oos_side = entry >= oos_s
        if is_oos_side:
            # OOS side: embargo then keep
            if embargo_days > 0 and entry < embargo_cutoff:
                result["embargoed"].append(t)
            else:
                result["oos_kept"].append(t)
            continue
        # IS side: purge if overlap with OOS
        overlaps_oos = (
            exit_ is None or exit_ >= oos_s
        )
        if overlaps_oos:
            result["purged"].append(t)
        else:
            result["is_kept"].append(t)
    return result
