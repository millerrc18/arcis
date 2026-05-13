"""Walk-forward harness — anchored expanding × N folds × embargo.

CLI entrypoint and fold-driver implementing pre-registration §3 methodology.

Called by: CLI (python -m src.evaluation.walkforward)
Calls: src.evaluation.backtester.backtest_model, src.scheduler.holidays,
       src.universe.pit (for coverage range)
Owns tables: none
Config keys: none
Tests: tests/evaluation/test_walkforward.py

Pre-registration §3 (committed 2026-04-28):
  §3.1  Anchored expanding window — train_start fixed; train_end advances per fold
  §3.2  N successive folds over the test period
  §3.3  8 folds × ~4 months from 2023-09 (default)
  §3.4  21 trading-day embargo between train_end and test_start
  §3.5  Folds with <15 trades flagged underpowered; excluded from primary aggregate
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import date, timedelta
from typing import Any

import pandas_market_calendars as mcal

from src.evaluation.backtester import backtest_model
from src.scheduler.holidays import is_market_holiday, subtract_trading_days

# ─── constants ────────────────────────────────────────────────────────────────

_UNDERPOWERED_THRESHOLD = 15
_DEFAULT_FOLD_COUNT = 8
_DEFAULT_EMBARGO_DAYS = 21
_DEFAULT_ANCHOR = "2023-09-01"
_COVERAGE_START = "2015-03-19"

_NYSE = mcal.get_calendar("NYSE")


# ─── trading-day utilities ────────────────────────────────────────────────────

def _is_trading_day(d: date) -> bool:
    return d.weekday() < 5 and not is_market_holiday(check_date=d)


def _next_trading_day(d: date) -> date:
    """Return d if it's a trading day, otherwise advance to the next one."""
    candidate = d
    while not _is_trading_day(candidate):
        candidate += timedelta(days=1)
    return candidate


def _prev_trading_day(d: date) -> date:
    """Return d if it's a trading day, otherwise retreat to the previous one."""
    candidate = d
    while not _is_trading_day(candidate):
        candidate -= timedelta(days=1)
    return candidate


# ─── single-fold boundary helper ─────────────────────────────────────────────

def _single_fold_boundary(
    fold_idx: int,
    anchor_date: date,
    train_anchor: date,
    fold_calendar_days: int,
    embargo_days: int,
) -> dict[str, Any]:
    """Compute one fold's boundary dict (train_start/end, test_start/end)."""
    test_start_raw = anchor_date + timedelta(days=fold_idx * fold_calendar_days)
    test_end_raw = anchor_date + timedelta(days=(fold_idx + 1) * fold_calendar_days)

    test_start = _next_trading_day(test_start_raw)
    test_end = _prev_trading_day(test_end_raw)

    train_end = subtract_trading_days(test_start, embargo_days)
    if train_end < train_anchor:
        train_end = train_anchor

    return {
        "fold_idx": fold_idx,
        "train_start": train_anchor.isoformat(),
        "train_end": train_end.isoformat(),
        "test_start": test_start.isoformat(),
        "test_end": test_end.isoformat(),
    }


# ─── fold-boundary computation ────────────────────────────────────────────────

def compute_fold_boundaries(
    anchor: str = _DEFAULT_ANCHOR,
    fold_count: int = _DEFAULT_FOLD_COUNT,
    embargo_days: int = _DEFAULT_EMBARGO_DAYS,
) -> list[dict[str, Any]]:
    """Compute anchored-expanding walk-forward fold boundaries (pre-reg §3).

    Returns list of fold dicts with fold_idx, train_start, train_end,
    test_start, test_end (all ISO date strings).
    """
    anchor_date = date.fromisoformat(anchor)
    train_anchor = _next_trading_day(date.fromisoformat(_COVERAGE_START))
    coverage_end = date.today()

    total_test_days = (coverage_end - anchor_date).days
    if total_test_days <= 0:
        raise ValueError(f"anchor {anchor} is on or after coverage_end {coverage_end}")

    fold_calendar_days = math.ceil(total_test_days / fold_count)
    return [
        _single_fold_boundary(i, anchor_date, train_anchor, fold_calendar_days, embargo_days)
        for i in range(fold_count)
    ]


# ─── underpowered flag ────────────────────────────────────────────────────────

def _apply_underpowered_flag(trades_count: int) -> bool:
    """Return True if the fold has fewer than 15 trades (per pre-reg §3.5)."""
    return trades_count < _UNDERPOWERED_THRESHOLD


# ─── per-fold metrics ─────────────────────────────────────────────────────────

def _compute_fold_sharpe(trades: list[dict]) -> float:
    """Compute annualized Sharpe from per-trade pnl_pct values."""
    from src.analytics.canonical_sharpe import compute_sharpe
    pnls = [t.get("pnl_pct", 0.0) for t in trades]
    if not pnls:
        return 0.0
    result = compute_sharpe(pnls, periods_per_year=252)
    return result if result is not None else 0.0


def _compute_fold_return_total(trades: list[dict]) -> float:
    """Sum of pnl_pct across all trades in the fold."""
    return sum(t.get("pnl_pct", 0.0) for t in trades)


def _primary_t_stat(pnls: list[float], sharpe: float) -> float:
    """Compute t-stat = (mean/stdev) * sqrt(n) from the raw pnl series."""
    n = len(pnls)
    if n <= 1 or sharpe == 0.0:
        return 0.0
    mean_r = sum(pnls) / n
    var_r = sum((r - mean_r) ** 2 for r in pnls) / (n - 1)
    std_r = var_r ** 0.5
    return ((mean_r / std_r) * math.sqrt(n)) if std_r > 0 else 0.0


# ─── aggregate computation ────────────────────────────────────────────────────

def compute_aggregate(folds: list[dict]) -> dict:
    """Compute aggregate metrics, excluding underpowered folds from primary stats.

    Returns dict: primary_sharpe, primary_t_stat, primary_trades_count,
    underpowered_footnote.
    """
    from src.analytics.canonical_sharpe import compute_sharpe

    powered = [f for f in folds if not f["underpowered"]]
    underpowered = [f for f in folds if f["underpowered"]]

    pnls = [t.get("pnl_pct", 0.0) for f in powered for t in f.get("trades", [])]
    primary_trades_count = sum(f["trades_count"] for f in powered)

    if pnls:
        val = compute_sharpe(pnls, periods_per_year=252)
        primary_sharpe = val if val is not None else 0.0
    else:
        primary_sharpe = 0.0

    primary_t_stat = _primary_t_stat(pnls, primary_sharpe)

    return {
        "primary_sharpe": round(primary_sharpe, 4),
        "primary_t_stat": round(primary_t_stat, 4),
        "primary_trades_count": primary_trades_count,
        "underpowered_footnote": {
            "underpowered_fold_count": len(underpowered),
            "underpowered_trades_count": sum(f["trades_count"] for f in underpowered),
        },
    }


# ─── per-fold runner ──────────────────────────────────────────────────────────

def _run_fold(
    model: str,
    boundary: dict,
    corpus_id: str | None = None,
    *,
    shadow: bool = False,
) -> dict:
    """Call backtest_model for one fold and assemble the fold result dict.

    When ``shadow=True`` (#82, pre-reg §A1.6 deterministic-ranker shadow),
    the per-fold backtest_model call is invoked with the shadow path
    (LLM filter stripped). Used by run_walkforward(with_shadow=True).
    """
    train_start = boundary["train_start"]
    train_end = boundary["train_end"]
    test_start = boundary["test_start"]
    test_end = boundary["test_end"]

    test_start_d = date.fromisoformat(test_start)
    test_end_d = date.fromisoformat(test_end)
    approx_months = max(1, math.ceil((test_end_d - test_start_d).days / 30))

    bt = backtest_model(
        model, months=approx_months,
        train_start=train_start, train_end=train_end,
        test_start=test_start, test_end=test_end,
        corpus_id=corpus_id,
        shadow=shadow,
    )

    trades = bt.get("trades", [])
    trades_count = len(trades) if trades else bt.get("trades_generated", 0)
    underpowered = _apply_underpowered_flag(trades_count)
    fold_sharpe = _compute_fold_sharpe(trades) if trades else bt.get("sharpe_ratio", 0.0)
    fold_return = _compute_fold_return_total(trades) if trades else bt.get("total_pnl_pct", 0.0)

    return {
        "fold_idx": boundary["fold_idx"],
        "train_start": train_start,
        "train_end": train_end,
        "test_start": test_start,
        "test_end": test_end,
        "trades_count": trades_count,
        "underpowered": underpowered,
        "trades": trades,
        "fold_sharpe": round(fold_sharpe, 4),
        "fold_return_total": round(fold_return, 4),
    }


# ─── corpus admissibility + window coverage gate (pre-reg §A3) ───────────────

def _gate_corpus_or_raise(corpus_id: str, boundaries: list[dict]) -> tuple[str, int]:
    """Load corpus manifest, validate admissibility + window coverage, return provenance.

    Pre-reg §A3 — admissibility gate fires BEFORE any fold runs so the harness
    never wastes fold work on a corpus that can't ground a primary-metric
    claim. Manifest window must also cover every fold's test range or raise.

    Returns:
        (manifest_admissibility, parse_failure_count) — for the result dict.

    Raises:
        RuntimeError if not admissible OR if any fold falls outside corpus window.
    """
    from src.evaluation.corpus import load_manifest
    manifest = load_manifest(corpus_id)
    if not manifest.is_admissible():
        raise RuntimeError(
            f"Corpus {corpus_id} is not admissible: {manifest.admissibility}"
        )
    manifest_start = date.fromisoformat(manifest.walkforward_window_start)
    manifest_end = date.fromisoformat(manifest.walkforward_window_end)
    for b in boundaries:
        test_start_d = date.fromisoformat(b["test_start"])
        test_end_d = date.fromisoformat(b["test_end"])
        if test_start_d < manifest_start or test_end_d > manifest_end:
            raise RuntimeError(
                f"Corpus {corpus_id} window "
                f"[{manifest.walkforward_window_start}, {manifest.walkforward_window_end}] "
                f"does not cover fold {b['fold_idx']} test range "
                f"[{b['test_start']}, {b['test_end']}]"
            )
    return manifest.admissibility, manifest.parse_failure_count


# ─── main driver ──────────────────────────────────────────────────────────────

def _compute_shadow_delta(primary: dict, shadow: dict) -> dict:
    """Compose §A1.6 delta dict: primary minus shadow on each headline axis."""
    def _powered_pnl(folds: list[dict]) -> float:
        return sum(f.get("fold_return_total", 0.0)
                   for f in folds if not f.get("underpowered", False))
    p_s = primary["aggregate"].get("primary_sharpe", 0.0)
    s_s = shadow["aggregate"].get("primary_sharpe", 0.0)
    p_p = _powered_pnl(primary["folds"])
    s_p = _powered_pnl(shadow["folds"])
    p_n = primary["aggregate"].get("primary_trades_count", 0)
    s_n = shadow["aggregate"].get("primary_trades_count", 0)
    return {
        "primary_excess_sharpe": p_s, "shadow_excess_sharpe": s_s,
        "delta_excess_sharpe": p_s - s_s,
        "primary_total_pnl_pct": p_p, "shadow_total_pnl_pct": s_p,
        "delta_total_pnl_pct": p_p - s_p,
        "primary_n_trades": p_n, "shadow_n_trades": s_n,
    }


def _build_flat_result(folds: list[dict], **prov) -> dict:
    """Wrap completed folds in the flat run_walkforward shape."""
    return {
        "anchor_date": prov["anchor"], "fold_count": prov["fold_count"],
        "embargo_days": prov["embargo_days"], "folds": folds,
        "aggregate": compute_aggregate(folds),
        "corpus_id": prov["corpus_id"],
        "manifest_admissibility": prov["manifest_admissibility"],
        "parse_failed_excluded": prov["parse_failed_excluded"],
    }


def _assemble_with_shadow_result(model: str, boundaries: list[dict], **prov) -> dict:
    """Run primary + shadow + compose delta (#82, §A1.6 — same boundaries)."""
    cid = prov["corpus_id"]
    p_folds = [_run_fold(model, b, corpus_id=cid, shadow=False) for b in boundaries]
    s_folds = [_run_fold(model, b, corpus_id=cid, shadow=True) for b in boundaries]
    primary = _build_flat_result(p_folds, **prov)
    shadow = _build_flat_result(s_folds, **prov)
    return {
        "primary": primary, "shadow": shadow,
        "delta": _compute_shadow_delta(primary, shadow),
        "corpus_id": cid,
        "manifest_admissibility": prov["manifest_admissibility"],
    }


def run_walkforward(
    model: str,
    anchor: str = _DEFAULT_ANCHOR,
    fold_count: int = _DEFAULT_FOLD_COUNT,
    embargo_days: int = _DEFAULT_EMBARGO_DAYS,
    output_json: str | None = None,
    corpus_id: str | None = None,
    with_shadow: bool = False,
) -> dict:
    """Run the walk-forward harness (pre-reg §3).

    Calls backtest_model once per fold, applies underpowered flag, and
    aggregates primary metrics over powered folds only.

    When ``corpus_id`` is set, the manifest is loaded once and validated via
    _gate_corpus_or_raise (pre-reg §A3 admissibility + window coverage).
    Result dict gains ``corpus_id``, ``manifest_admissibility``, and
    ``parse_failed_excluded`` for downstream provenance.

    When ``with_shadow=True`` (#82, §6 + §A1.6): runs BOTH primary AND
    deterministic-ranker shadow over the SAME fold boundaries with the SAME
    corpus, returns ``{"primary": ..., "shadow": ..., "delta": ..., ...}``.
    When False (default): preserves the existing flat shape for #81 +
    every other consumer (regression-locked).
    """
    boundaries = compute_fold_boundaries(anchor, fold_count, embargo_days)
    manifest_admissibility: str | None = None
    parse_failed_excluded = 0
    if corpus_id is not None:
        manifest_admissibility, parse_failed_excluded = _gate_corpus_or_raise(
            corpus_id, boundaries
        )
    provenance = dict(
        anchor=anchor, fold_count=fold_count, embargo_days=embargo_days,
        corpus_id=corpus_id, manifest_admissibility=manifest_admissibility,
        parse_failed_excluded=parse_failed_excluded,
    )
    if with_shadow:
        result = _assemble_with_shadow_result(model, boundaries, **provenance)
    else:
        completed = [_run_fold(model, b, corpus_id=corpus_id) for b in boundaries]
        result = _build_flat_result(completed, **provenance)
    if output_json:
        with open(output_json, "w", encoding="utf-8") as fh:
            json.dump(result, fh, indent=2, default=str)
    return result


# ─── CLI ─────────────────────────────────────────────────────────────────────

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m src.evaluation.walkforward",
        description=(
            "Walk-forward harness — anchored expanding × N folds × embargo. "
            "Implements pre-registration §3 Stage 1 methodology."
        ),
    )
    parser.add_argument("--model", default="arcis:v1.0.0",
                        help="Model identifier (default: arcis:v1.0.0)")
    parser.add_argument("--anchor", default=_DEFAULT_ANCHOR,
                        help=f"Start of test period ISO date (default: {_DEFAULT_ANCHOR})")
    parser.add_argument("--folds", type=int, default=_DEFAULT_FOLD_COUNT, dest="folds",
                        help=f"Number of test folds (default: {_DEFAULT_FOLD_COUNT})")
    parser.add_argument("--embargo", type=int, default=_DEFAULT_EMBARGO_DAYS,
                        help=f"Trading-day embargo (default: {_DEFAULT_EMBARGO_DAYS})")
    parser.add_argument("--output-json", default=None, metavar="PATH",
                        help="Write JSON output to this path")
    parser.add_argument("--corpus-id", default=None, dest="corpus_id", metavar="ID",
                        help="LLM-scoring corpus directory name under ARCIS_CORPUS_ROOT "
                             "(if set, scores are read from corpus instead of live LLM)")
    parser.add_argument("--with-shadow", action="store_true", dest="with_shadow",
                        help="Run deterministic-ranker shadow portfolio in parallel "
                             "(#82, §6 + §A1.6 — emits primary + shadow + delta)")
    return parser


def main(argv: list[str] | None = None) -> None:
    parser = _build_parser()
    args = parser.parse_args(argv)
    result = run_walkforward(
        model=args.model, anchor=args.anchor,
        fold_count=args.folds, embargo_days=args.embargo,
        output_json=args.output_json,
        corpus_id=args.corpus_id,
        with_shadow=args.with_shadow,
    )
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
