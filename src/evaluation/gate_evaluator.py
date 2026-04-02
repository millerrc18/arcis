"""50-trade gate evaluation for Phase 1 -> Phase 2 decision.

Called by: cli.commands
Calls: evaluation.statistics
Owns tables: none
Config keys: none
Tests: tests/test_gate_evaluator.py

Decision rules:
- 4+ GREEN with 0 RED -> PROCEED to Phase 2
- Mixed GREEN/YELLOW with 0 RED -> EXTEND to 75 trades
- Any RED -> ROOT CAUSE ANALYSIS
- 2+ RED -> FUNDAMENTAL REVISION needed
"""

import logging
import sqlite3

import numpy as np

from src.config import DB_PATH

logger = logging.getLogger(__name__)


def evaluate_50_trade_gate(db_path: str = DB_PATH) -> dict:
    """Run the full 50-trade gate evaluation."""
    from src.evaluation.statistics import (
        sharpe_ratio, probabilistic_sharpe_ratio, bootstrap_sharpe_ci,
        profit_factor, max_drawdown, sortino_ratio,
    )

    try:
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT pnl_dollars, pnl_pct FROM shadow_trades "
                "WHERE status = 'closed' AND pnl_pct IS NOT NULL "
                "ORDER BY actual_exit_time ASC"
            ).fetchall()
    except Exception as e:
        return {"error": str(e), "trade_count": 0}

    if not rows:
        return {"error": "No closed trades", "trade_count": 0}

    pnl_dollars = np.array([float(r["pnl_dollars"] or 0) for r in rows])
    pnl_pct = np.array([float(r["pnl_pct"] or 0) for r in rows])
    n_trades = len(rows)

    wins = pnl_dollars[pnl_dollars > 0]
    losses = pnl_dollars[pnl_dollars <= 0]
    win_rate = len(wins) / n_trades if n_trades > 0 else 0

    pf = profit_factor(float(wins.sum()), float(abs(losses.sum()))) if len(losses) > 0 else 0
    net_pnl = float(pnl_dollars.sum())
    per_trade_sr = sharpe_ratio(pnl_pct / 100)

    # Drawdown from equity curve
    equity = np.cumsum(pnl_dollars) + 100000
    max_dd, _, _ = max_drawdown(equity)
    max_dd_pct = max_dd * 100

    # Expectancy in R-multiples
    avg_risk = float(np.abs(pnl_pct[pnl_pct < 0]).mean()) if len(pnl_pct[pnl_pct < 0]) > 0 else 1
    exp_r = float(pnl_pct.mean() / avg_risk) if avg_risk > 0 else 0

    # PSR
    std = pnl_pct.std()
    skew = float(((pnl_pct - pnl_pct.mean()) ** 3).mean() / std ** 3) if std > 0 else 0
    kurt = float(((pnl_pct - pnl_pct.mean()) ** 4).mean() / std ** 4) if std > 0 else 3
    skew = float(np.clip(skew, -10, 10))
    kurt = float(np.clip(kurt, 1, 50))
    psr = probabilistic_sharpe_ratio(per_trade_sr, 0.0, n_trades, skew, kurt)
    ci_lower, ci_obs, ci_upper = bootstrap_sharpe_ci(pnl_pct / 100, n_bootstrap=5000)

    gates = {
        "win_rate": {"value": round(win_rate, 3), "green": 0.45, "yellow": 0.38, "label": "Win rate"},
        "profit_factor": {"value": round(pf, 2), "green": 1.3, "yellow": 1.1, "label": "Profit factor"},
        "expectancy_r": {"value": round(exp_r, 3), "green": 0.20, "yellow": 0.05, "label": "Expectancy (R)"},
        "max_drawdown": {"value": round(max_dd_pct, 1), "green": 12, "yellow": 18, "label": "Max drawdown %", "invert": True},
        "sharpe": {"value": round(per_trade_sr, 3), "green": 0.15, "yellow": 0.05, "label": "Per-trade Sharpe"},
        "net_pnl": {"value": round(net_pnl, 2), "green": 0, "yellow": 0, "label": "Net P&L $", "binary": True},
    }

    for key, g in gates.items():
        if g.get("invert"):
            g["status"] = "green" if g["value"] <= g["green"] else ("yellow" if g["value"] <= g["yellow"] else "red")
        elif g.get("binary"):
            g["status"] = "green" if g["value"] > 0 else "red"
        else:
            g["status"] = "green" if g["value"] >= g["green"] else ("yellow" if g["value"] >= g["yellow"] else "red")

    greens = sum(1 for g in gates.values() if g["status"] == "green")
    reds = sum(1 for g in gates.values() if g["status"] == "red")

    if greens >= 4 and reds == 0:
        decision = "PROCEED to Phase 2"
    elif reds == 0:
        decision = "EXTEND to 75 trades, reassess"
    elif reds >= 2:
        decision = "FUNDAMENTAL REVISION needed"
    else:
        decision = "ROOT CAUSE ANALYSIS — investigate RED metrics"

    return {
        "gates": gates,
        "decision": decision,
        "greens": greens,
        "reds": reds,
        "trade_count": n_trades,
        "psr_0": round(psr, 3),
        "bootstrap_ci": {"lower": round(ci_lower, 4), "observed": round(ci_obs, 4), "upper": round(ci_upper, 4)},
        "sortino": round(sortino_ratio(pnl_pct / 100), 3),
    }


def format_gate_report(result: dict) -> str:
    """Format gate evaluation as a readable report."""
    if "error" in result:
        return f"Gate evaluation error: {result['error']}"

    lines = [f"50-TRADE GATE EVALUATION ({result['trade_count']} trades)\n"]
    status_emoji = {"green": "🟢", "yellow": "🟡", "red": "🔴"}

    for key, g in result.get("gates", {}).items():
        emoji = status_emoji.get(g["status"], "⚪")
        lines.append(f"{emoji} {g['label']}: {g['value']} (green: {g['green']})")

    lines.append(f"\nPSR(0): {result.get('psr_0', 'N/A')}")
    ci = result.get("bootstrap_ci", {})
    lines.append(f"Bootstrap Sharpe CI: [{ci.get('lower', 'N/A')}, {ci.get('upper', 'N/A')}]")
    lines.append(f"\nDECISION: {result['decision']} ({result['greens']} GREEN, {result['reds']} RED)")

    return "\n".join(lines)
