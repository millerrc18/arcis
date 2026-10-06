"""Candidate-day ledger for the S07 bracket simulator.

Per PREREG §1.1, every signal produces a ledger row whether or not it
fills: next-open counterfactual return, filled/unfilled outcomes, MAE/MFE,
time to exit, and all ambiguity/gap/corporate-action flags. The ledger is
the raw material for the §2.4 historical check, the walk-forward harness,
and the ambiguity-rate report (SCOPE §5 done-means).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

from arcis.research import metrics as m
from arcis.research.panel import Panel
from arcis.research.simulator import BracketSpec, TradeResult, simulate_trade


@dataclass(frozen=True)
class Candidate:
    """One scored signal day awaiting simulation."""

    symbol: str
    signal_date: date
    limit: float
    stop: float
    target: float
    shares: int
    score: float | None = None
    events: dict[date, str] = field(default_factory=dict)


def _excursions(panel: Panel, symbol: str, start: date, end: date,
                ref_price: float) -> tuple[float, float]:
    """MAE/MFE in percent vs ref_price over [start, end] (inclusive)."""
    mae, mfe = 0.0, 0.0
    d = start
    while True:
        bar = panel.bar(symbol, d)
        if bar is not None:
            mae = min(mae, (bar.low / ref_price - 1) * 100)
            mfe = max(mfe, (bar.high / ref_price - 1) * 100)
        if d == end:
            break
        d = panel.next_session(d)
    return mae, mfe


def summarize(panel: Panel, candidate: Candidate,
              result: TradeResult) -> dict[str, Any]:
    """One ledger row for a simulated candidate day."""
    # Next-open counterfactual: signal close -> entry-session open.
    sig_bar = panel.bar(candidate.symbol, candidate.signal_date)
    entry_bar = panel.bar(candidate.symbol, result.spec.entry_session)
    next_open_ret = None
    if sig_bar is not None and entry_bar is not None and sig_bar.close:
        next_open_ret = (entry_bar.open / sig_bar.close - 1) * 100

    row: dict[str, Any] = {
        "symbol": candidate.symbol,
        "signal_date": candidate.signal_date.isoformat(),
        "entry_session": result.spec.entry_session.isoformat(),
        "limit": candidate.limit,
        "stop": candidate.stop,
        "target": candidate.target,
        "shares": candidate.shares,
        "score": candidate.score,
        "filled": result.entry is not None,
        "unfilled_reason": result.unfilled_reason,
        "ambiguous_bar": result.ambiguous_bar,
        "corporate_action": result.corporate_action,
        "next_open_return_pct": next_open_ret,
    }
    if result.entry is None or result.exit is None:
        row.update({
            "entry_price": None, "exit_price": None, "exit_kind": None,
            "exit_session": None, "holding_sessions": 0,
            "pnl_dollars": 0.0, "return_pct": 0.0,
            "mae_pct": None, "mfe_pct": None,
            "commission_dollars": 0.0, "sec_fee_dollars": 0.0,
            "taf_dollars": 0.0, "execution_addon_dollars": 0.0,
        })
        return row

    mae, mfe = _excursions(panel, candidate.symbol,
                           result.entry.session, result.exit.session,
                           result.entry.price)
    holding = (panel.session_index(result.exit.session)
               - panel.session_index(result.entry.session) + 1)
    row.update({
        "entry_price": result.entry.price,
        "entry_gap": result.entry.gap,
        "exit_price": result.exit.price,
        "exit_kind": result.exit.kind,
        "exit_gap": result.exit.gap,
        "exit_session": result.exit.session.isoformat(),
        "holding_sessions": holding,
        "pnl_dollars": result.pnl_dollars,
        "return_pct": result.return_pct,
        "mae_pct": mae,
        "mfe_pct": mfe,
        "commission_dollars": (result.entry_cost.get("commission", 0.0)
                               + result.exit_cost.get("commission", 0.0)),
        "sec_fee_dollars": result.exit_cost.get("sec_fee", 0.0),
        "taf_dollars": result.exit_cost.get("finra_taf", 0.0),
        "execution_addon_dollars": result.execution_addon_dollars,
    })
    return row


def build_ledger(panel: Panel, candidates: list[Candidate], buffer: float,
                 spread_frac: float, cost_model: str = "conservative",
                 commission_model: str = "modern") -> list[dict[str, Any]]:
    """Simulate every candidate day and return the ledger rows."""
    rows = []
    for cand in candidates:
        spec = BracketSpec(
            symbol=cand.symbol, signal_date=cand.signal_date,
            entry_session=panel.next_session(cand.signal_date),
            limit=cand.limit, stop=cand.stop, target=cand.target,
            shares=cand.shares, events=cand.events)
        result = simulate_trade(panel, spec, buffer, spread_frac,
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
        "unfilled_reasons": {reason: sum(1 for r in rows
                                         if r["unfilled_reason"] == reason)
                             for reason in {r["unfilled_reason"] for r in rows
                                             if not r["filled"]}},
        "ambiguous_bar_rate": (sum(1 for r in filled if r["ambiguous_bar"])
                               / len(filled) if filled else 0.0),
        "gap_entry_rate": (sum(1 for r in filled if r.get("entry_gap"))
                           / len(filled) if filled else 0.0),
        "gap_exit_rate": (sum(1 for r in filled if r.get("exit_gap"))
                          / len(filled) if filled else 0.0),
        "corporate_action_rate": (sum(1 for r in rows if r["corporate_action"])
                                  / n if n else 0.0),
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
    return {
        "n_trades": len(filled),
        "sharpe_per_trade": m.sharpe_ratio(rets) if len(rets) > 1 else 0.0,
        "max_drawdown": m.max_drawdown(equity) if equity else 0.0,
        "hit_rate": m.hit_rate(rets) if rets else 0.0,
        "profit_factor": m.profit_factor(rets) if rets else 0.0,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "total_pnl_dollars": sum(r["pnl_dollars"] for r in filled),
    }
