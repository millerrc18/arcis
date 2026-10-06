"""Walk-forward harness with purge and embargo (PREREG §4).

"Any walk-forward evaluation purges training rows whose label intervals
overlap validation labels; applies a 15-session embargo (16 if label
intervals include both endpoints); keeps all stocks from one date in the
same fold."

- Purge: drop training rows whose [signal_date, label_end] overlaps the
  validation label region (label leakage through the bracket horizon).
- Embargo: drop training rows whose label ends within 15 sessions before
  the validation start — i.e. label_end_idx > valid_start_idx − 16
  (the "16" is the both-endpoints counting). The embargo subsumes the
  overlap purge and is always reachable.
- Date-grouped folds: all rows from one signal date stay in the same
  fold (assignment is by signal_date).

Label intervals come from the ledger rows: ``label_end`` is the exit
session when filled, else t+1 (the next-open counterfactual horizon).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from arcis.research.ledger import build_ledger, ledger_metrics
from arcis.research.panel import Panel


@dataclass(frozen=True)
class Fold:
    train_end: date      # last signal date eligible for training
    valid_start: date    # first signal date in validation
    valid_end: date      # last signal date in validation


def _as_date(value: str | date) -> date:
    return date.fromisoformat(value) if isinstance(value, str) else value


def make_folds(calendar: list[date], n_splits: int = 5,
               val_size: int = 63, embargo_sessions: int = 15) -> list[Fold]:
    """Expanding walk-forward folds over the session calendar.

    Validation blocks of ``val_size`` sessions walk backward from the
    calendar end. For each fold, ``train_end`` is ``embargo_sessions + 1``
    sessions before ``valid_start`` — the explicit 15-session embargo gap
    (PREREG §4). Training rows whose labels reach into the gap are purged
    in apply_purge_embargo.
    """
    n = len(calendar)
    if n_splits < 2:
        raise ValueError("need at least 2 splits")
    if val_size < 1:
        raise ValueError("val_size must be >= 1")
    if embargo_sessions < 0:
        raise ValueError("embargo_sessions must be >= 0")
    need = n_splits * val_size + embargo_sessions + 1
    if n < need:
        raise ValueError(f"need {need} sessions for {n_splits} folds, "
                         f"got {n}")
    folds = []
    for i in range(n_splits):
        valid_end = calendar[n - 1 - i * val_size]
        valid_start = calendar[n - val_size - i * val_size]
        train_end = calendar[n - val_size - i * val_size
                             - embargo_sessions - 1]
        folds.append(Fold(train_end, valid_start, valid_end))
    folds.reverse()
    return folds


def apply_purge_embargo(rows: list[dict[str, Any]], fold: Fold,
                        calendar: list[date],
                        embargo_sessions: int = 15
                        ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Split rows into (train, validation) with purge + embargo.

    - Validation: signal_date in [fold.valid_start, fold.valid_end].
    - Training: signal_date <= fold.train_end, then purge + embargo:
      drop rows whose label interval ends within ``embargo_sessions`` of
      the validation start (label_end_idx > valid_start_idx − 16 for the
      15-session embargo with both-endpoint counting). This subsumes the
      label-overlap purge.
    """
    cal_index = {d: i for i, d in enumerate(calendar)}
    try:
        v_idx = cal_index[_as_date(fold.valid_start)]
    except KeyError:
        raise ValueError("fold.valid_start not in calendar") from None
    # Earliest label-end index a training row may have (both-endpoint
    # counting: 16 sessions back for a 15-session embargo).
    cutoff = v_idx - embargo_sessions - 1

    valid, train = [], []
    for row in rows:
        sig = _as_date(row["signal_date"])
        if fold.valid_start <= sig <= fold.valid_end:
            valid.append(row)
            continue
        if sig > fold.train_end:
            continue  # after the training window entirely
        label_end = _as_date(row["label_end"])
        try:
            le_idx = cal_index[label_end]
        except KeyError:
            raise ValueError(
                f"label_end {label_end} not in calendar") from None
        if le_idx > cutoff:
            continue  # purge + embargo: label reaches into the gap
        train.append(row)
    return train, valid


def fold_pnl(rows: list[dict[str, Any]]) -> float:
    """Sum of pnl_dollars over rows (filled rows carry the P&L)."""
    return float(sum(r.get("pnl_dollars", 0.0) for r in rows))


def run_evaluation(panel: Panel, candidates: list[Any],
                   folds: list[Fold], *, registry: Any,
                   trial_id: str, description: str,
                   params: dict[str, Any],
                   cost_model: str = "conservative",
                   commission_model: str = "modern") -> dict[str, Any]:
    """Walk-forward evaluation with mandatory trial logging (PREREG §0.5).

    Builds the candidate-day ledger (per-trade cost wiring), splits it
    into purged/embargoed folds, and records per-fold P&L and metrics.
    The registry is required: an evaluation cannot run without being
    logged. Uses registry.logged_run, so a failed evaluation still
    appends a "failed" record (breach evidence is preserved).
    """
    code_sha = registry.code_hash_of_package()
    # Data hash covers both the bars and the candidate list: different
    # signals/levels on the same bars must log different data_shas.
    data_sha = (registry.data_hash_of_panel(panel) + ":"
                + registry.data_hash_of_candidates(candidates))
    summary: dict[str, Any]
    with registry.logged_run(trial_id, description, code_sha, data_sha,
                             params) as summary:
        rows = build_ledger(panel, candidates, cost_model=cost_model,
                            commission_model=commission_model)
        fold_results: list[dict[str, Any]] = []
        for fold in folds:
            train, valid = apply_purge_embargo(rows, fold, panel.calendar)
            met = ledger_metrics(valid)
            fold_results.append({
                "train_end": fold.train_end.isoformat(),
                "valid_start": fold.valid_start.isoformat(),
                "valid_end": fold.valid_end.isoformat(),
                "n_train": len(train),
                "n_valid": len(valid),
                "valid_pnl_dollars": fold_pnl(valid),
                "valid_metrics": met,
            })
        summary.update({
            "n_folds": len(folds),
            "n_candidates": len(rows),
            "folds": fold_results,
            "total_valid_pnl_dollars": float(sum(
                float(f["valid_pnl_dollars"]) for f in fold_results)),
        })
        return summary
