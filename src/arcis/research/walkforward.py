"""Walk-forward harness with purge and embargo (PREREG §4).

Implements the López de Prado label-overlap purge for the 15-session
bracket horizon: every label is an interval [signal_date, label_end], and
training rows whose intervals overlap any validation interval are purged.
A 15-session embargo follows each validation block (16 if the label
convention includes both endpoints — ours does not double-count, so 15).

Date-grouped folds: all rows from one signal date stay in the same fold.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any


@dataclass(frozen=True)
class Fold:
    train_end: date      # last signal date eligible for training
    valid_start: date    # first signal date in validation
    valid_end: date      # last signal date in validation


def _as_date(value: str | date) -> date:
    return date.fromisoformat(value) if isinstance(value, str) else value


def _label_end(row: dict[str, Any]) -> date:
    """Label interval end: exit session if filled, else the signal date."""
    if row.get("filled") and row.get("exit_session"):
        return _as_date(row["exit_session"])
    return _as_date(row["signal_date"])


def make_folds(signal_dates: list[date], n_splits: int = 5,
               embargo_sessions: int = 15) -> list[Fold]:
    """Contiguous validation blocks over the sorted signal dates.

    Expanding walk-forward: fold k validates on block k and trains on
    everything before it (purge/embargo applied later per row).
    """
    uniq = sorted(set(signal_dates))
    if n_splits < 2:
        raise ValueError("need at least 2 splits")
    if len(uniq) < n_splits:
        raise ValueError(f"only {len(uniq)} signal dates for {n_splits}")
    size = len(uniq) // n_splits
    folds = []
    for k in range(n_splits):
        v_start = uniq[k * size]
        v_end = uniq[(k + 1) * size - 1] if k < n_splits - 1 else uniq[-1]
        t_end = uniq[k * size - 1] if k > 0 else None
        folds.append((t_end, v_start, v_end))
    # First fold has no training data; drop it (nothing to purge against).
    return [Fold(t_end, vs, ve) for t_end, vs, ve in folds if t_end is not None]


def apply_purge_embargo(rows: list[dict[str, Any]], fold: Fold,
                        calendar: list[date],
                        embargo_sessions: int = 15
                        ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Split rows into (train, validation) with purge + embargo.

    - Validation: signal_date in [fold.valid_start, fold.valid_end].
    - Purge: drop training rows whose [signal_date, label_end] overlaps the
      validation interval (label leakage through the 15-session horizon).
    - Embargo: drop training rows with signal_date after the validation
      block within embargo_sessions (for rolling, not just expanding,
      windows).
    """
    cal_index = {d: i for i, d in enumerate(calendar)}
    try:
        emb_end = calendar[cal_index[_as_date(fold.valid_end)]
                           + embargo_sessions]
    except (KeyError, IndexError):
        emb_end = None  # validation at calendar end: embargo moot

    valid, train = [], []
    for row in rows:
        sig = _as_date(row["signal_date"])
        if fold.valid_start <= sig <= fold.valid_end:
            valid.append(row)
            continue
        if sig > fold.train_end:
            continue  # after the training window entirely
        # Purge: label interval overlaps the validation interval.
        if _label_end(row) >= fold.valid_start and sig <= fold.valid_end:
            continue
        # Embargo: too close after the validation block.
        if emb_end is not None and sig > fold.valid_end and sig <= emb_end:
            continue
        train.append(row)
    return train, valid


def fold_pnl(rows: list[dict[str, Any]]) -> float:
    """Sum of pnl_dollars over rows (filled rows carry the P&L)."""
    return float(sum(r.get("pnl_dollars", 0.0) for r in rows))
