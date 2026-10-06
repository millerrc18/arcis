"""Candidate-day ledger for the S07 bracket simulator.

Per PREREG §1.1, every signal produces a ledger row whether or not it
fills: next-open counterfactual return, filled/unfilled outcomes, MAE/MFE,
time to exit, and all ambiguity/gap/corporate-action flags. The ledger is
the raw material for the §2.4 historical check, the walk-forward harness,
and the ambiguity-rate report (SCOPE §5 done-means).

Cost wiring (Task 4): when `buffer`/`spread_frac` are not given,
build_ledger derives them per trade — the 21-session trailing median
spread at the entry session and the R06 predeclared buffer
(estimate_buffer). Every adverse buffer and execution add-on in the
ledger is therefore trade-specific, not a constant.

MAE/MFE are measured from the session AFTER entry: the entry-day bar's
intraday timing (pre- vs post-fill) is unknowable from daily bars, so
including it would overstate favorable excursion on trade-through
entries. The entry-day stop-out is already modeled as an implied
traversal in the trade outcome itself.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

from arcis.research import metrics as m
from arcis.research.panel import Panel, PanelError
from arcis.research.simulator import (
    BracketSpec,
    TradeResult,
    estimate_buffer,
    simulate_trade,
    trailing_median_spread,
)


@dataclass(frozen=True)
class Candidate:
    """One signal-day candidate."""

    symbol: str
    signal_date: date
    limit: float
    stop: float
    target: float
    shares: int
    events: dict[date, str] = field(default_factory=dict)
    blackouts: frozenset[date] = frozenset()
    splits: dict[date, float] = field(default_factory=dict)
    exdiv_dates: frozenset[date] = frozenset()


def _counterfactual(panel: Panel, cand: Candidate) -> float | None:
    """Next-open counterfactual return (%) for every signal (PREREG §1.1)."""
    try:
        entry_session = panel.next_session(cand.signal_date)
    except PanelError:
        return None
    sig_bar = panel.bar(cand.symbol, cand.signal_date)
    nxt_bar = panel.bar(cand.symbol, entry_session)
    if sig_bar is None or nxt_bar is None:
        return None
    if sig_bar.close <= 0:
        return None
    return (nxt_bar.open - sig_bar.close) / sig_bar.close * 100.0


def _excursions(panel: Panel, result: TradeResult) -> tuple[float, float]:
    """MAE/MFE (%) from the fill, measured over post-entry sessions.

    (entry_session, exit_session]: the entry-day bar is excluded because
    its pre- vs post-fill timing is unknowable from daily bars.
    """
    entry, exit_fill = result.entry, result.exit
    if entry is None or exit_fill is None:
        return 0.0, 0.0
    symbol = result.spec.symbol
    session = entry.session
    maes, mfes = [], []
    while session < exit_fill.session:
        try:
            session = panel.next_session(session)
        except PanelError:
            break
        bar = panel.bar(symbol, session)
        if bar is None:
            continue  # declared halt (Panel guarantees nothing else)
        if entry.price > 0:
            maes.append((bar.low - entry.price) / entry.price * 100.0)
            mfes.append((bar.high - entry.price) / entry.price * 100.0)
    mae = min(maes) if maes else 0.0
    mfe = max(mfes) if mfes else 0.0
    return mae, mfe


def _label_end(panel: Panel, cand: Candidate,
               result: TradeResult) -> date:
    """Label interval end for purge/embargo (PREREG §4).

    Filled: the exit session (outcome known). Unfilled: t+1, the horizon
    of the next-open counterfactual.
    """
    if result.exit is not None:
        return result.exit.session
    try:
        return panel.next_session(cand.signal_date)
    except PanelError:
        return cand.signal_date


def summarize(panel: Panel, cand: Candidate,
            result: TradeResult) -> dict[str, Any]:
    """One candidate-day ledger row (PREREG §1.1 recording rule)."""
    entry, exit_fill = result.entry, result.exit
    mae, mfe = _excursions(panel, result)
    return {
        "symbol": cand.symbol,
        "signal_date": cand.signal_date.isoformat(),
        "entry_session": (entry.session.isoformat() if entry else None),
        "exit_session": (exit_fill.session.isoformat() if exit_fill else None),
        "label_end": _label_end(panel, cand, result).isoformat(),
        "filled": entry is not None,
        "unfilled_reason": result.unfilled_reason,
        "entry_kind": entry.kind if entry else None,
        "exit_kind": exit_fill.kind if exit_fill else None,
        "entry_gap": entry.gap if entry else False,
        "exit_gap": exit_fill.gap if exit_fill else False,
        "counterfactual_next_open_pct": _counterfactual(panel, cand),
        "mae_pct": mae,
        "mfe_pct": mfe,
        "sessions_held": result.sessions_held,
        "pnl_dollars": result.pnl_dollars,
        "return_pct": result.return_pct,
        "entry_cost": result.entry_cost,
        "exit_cost": result.exit_cost,
        "execution_addon_dollars": result.execution_addon_dollars,
        "ambiguous_bar": result.ambiguous_bar,
        "corporate_action": result.corporate_action,
        "late_time_exit": result.late_time_exit,
        "exdiv_stop": result.exdiv_stop,
        "split_adjusted": result.split_adjusted,
        "limit": cand.limit,
        "stop": cand.stop,
        "target": cand.target,
        "shares": cand.shares,
    }


def build_ledger(panel: Panel, candidates: list[Candidate], buffer: float | None = None,
                 spread_frac: float | None = None,
                 cost_model: str = "conservative",
                 commission_model: str = "modern") -> list[dict[str, Any]]:
    """Simulate every candidate and return the candidate-day ledger.

    When `buffer`/`spread_frac` are None (default), they are derived per
    trade: the 21-session trailing median spread at the entry session and
    the R06 predeclared buffer. Pass explicit values for synthetic
    known-answer tests.
    """
    rows = []
    for cand in candidates:
        entry_session = panel.next_session(cand.signal_date)
        spec = BracketSpec(
            symbol=cand.symbol, signal_date=cand.signal_date,
            entry_session=entry_session,
            limit=cand.limit, stop=cand.stop, target=cand.target,
            shares=cand.shares, events=cand.events,
            blackouts=cand.blackouts, splits=cand.splits,
            exdiv_dates=cand.exdiv_dates)
        if buffer is None or spread_frac is None:
            sp = trailing_median_spread(panel, cand.symbol, entry_session)
            bf = estimate_buffer(sp, cand.limit, cost_model)
        else:
            sp, bf = spread_frac, buffer
        result = simulate_trade(panel, spec, bf, sp,
                                cost_model, commission_model)
        rows.append(summarize(panel, cand, result))
    return rows


def ambiguity_report(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """SCOPE §5 done-means: report ambiguity rates, not just compute them."""
    n = len(rows)
    filled = [r for r in rows if r["filled"]]
    return {
        "n_candidates": n,
        "n_filled": len(filled),
        "fill_rate": len(filled) / n if n else 0.0,
        "ambiguous_bar_rate": (sum(1 for r in filled if r["ambiguous_bar"])
                               / len(filled) if filled else 0.0),
        "touch_only_rate": (sum(1 for r in rows
                                if r["unfilled_reason"] == "touch_only")
                            / n if n else 0.0),
        "gap_entry_rate": (sum(1 for r in filled if r["entry_gap"])
                           / len(filled) if filled else 0.0),
        "gap_exit_rate": (sum(1 for r in filled if r["exit_gap"])
                          / len(filled) if filled else 0.0),
        "corporate_action_rate": (sum(1 for r in rows if r["corporate_action"])
                                  / n if n else 0.0),
        "late_time_exit_rate": (sum(1 for r in filled if r["late_time_exit"])
                                / len(filled) if filled else 0.0),
        "exdiv_stop_rate": (sum(1 for r in filled if r["exdiv_stop"])
                            / len(filled) if filled else 0.0),
        "split_adjusted_rate": (sum(1 for r in filled if r["split_adjusted"])
                                / len(filled) if filled else 0.0),
    }


def ledger_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """research/metrics.py over the ledger's per-trade return series.

    Returns Sharpe (per-trade, rf=0), max drawdown of the cumulative
    per-trade equity, hit rate, profit factor, and avg win/loss — all on
    filled trades only. Unfilled candidates contribute no return.
    """
    filled = [r for r in rows if r["filled"]]
    rets = [r["return_pct"] / 100.0 for r in filled]
    equity = []
    cum = 1.0
    for r in rets:
        cum *= 1.0 + r
        equity.append(cum)
    avg_win, avg_loss = m.avg_win_avg_loss(rets) if rets else (0.0, 0.0)
    # Fold-level series can be tiny; guard the metrics that need length.
    from collections.abc import Callable
    def _safe(fn: Callable[..., float],
              xs: list[float], default: float = 0.0) -> float:
        try:
            return fn(xs)
        except ValueError:
            return default
    return {
        "n_trades": len(filled),
        "sharpe_per_trade": _safe(m.sharpe_ratio, rets) if len(rets) > 1 else 0.0,
        "max_drawdown": _safe(m.max_drawdown, equity),
        "hit_rate": _safe(m.hit_rate, rets),
        "profit_factor": _safe(m.profit_factor, rets),
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "total_pnl_dollars": sum(r["pnl_dollars"] for r in filled),
    }
