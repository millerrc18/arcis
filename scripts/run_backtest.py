"""Backtest CLI runner.

Usage:
  python scripts/run_backtest.py --strategy lazy_prices_v1 \\
      --start 2020-01-01 --end 2024-12-31 --output-format json --persist
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import subprocess
import sys
import uuid
from datetime import datetime, timezone

from src.config import DB_PATH
from src.platform.backtest_engine import BacktestConfig, run_backtest
from src.platform.strategy_spec import load_spec


def _git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True
        ).strip()
    except Exception:
        return "unknown"


def _spec_hash(raw: dict) -> str:
    return hashlib.sha256(
        json.dumps(raw, sort_keys=True).encode()
    ).hexdigest()


def _persist(result, db_path: str = DB_PATH) -> str:
    result_id = str(uuid.uuid4())
    created_at = datetime.now(timezone.utc).isoformat()
    m = result.metrics
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """INSERT INTO backtest_results
               (result_id, strategy_id, spec_version, spec_hash, start_date,
                end_date, initial_capital, total_trades, total_return_pct,
                sharpe, excess_sharpe, deflated_sharpe, sortino, calmar,
                max_drawdown_pct, win_rate, profit_factor, code_git_sha,
                created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                result_id, result.strategy_id,
                result.config.strategy.raw.get("spec_version", 1),
                _spec_hash(result.config.strategy.raw),
                result.config.start_date, result.config.end_date,
                result.config.initial_capital, m.get("n_trades"),
                m.get("total_return_pct"), m.get("sharpe"),
                m.get("excess_sharpe"), None,  # deflated_sharpe — Sprint 2 wires this
                m.get("sortino"), m.get("calmar"),
                m.get("max_drawdown_pct"),
                m.get("win_rate"), m.get("profit_factor"),
                _git_sha(), created_at,
            ),
        )
        for t in result.trades:
            conn.execute(
                """INSERT INTO backtest_trades
                   (trade_id, result_id, ticker, entry_date, exit_date,
                    entry_price, exit_price, shares, pnl_dollars, pnl_pct,
                    exit_reason, hold_days, spy_return_over_hold,
                    excess_return, realized_sector, regime_at_entry)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    t.trade_id, result_id, t.ticker, t.entry_date,
                    t.exit_date, t.entry_price, t.exit_price, t.shares,
                    t.pnl_dollars, t.pnl_pct, t.exit_reason, t.hold_days,
                    t.spy_return_over_hold, t.excess_return,
                    t.realized_sector, t.regime_at_entry,
                ),
            )
        conn.commit()
    finally:
        conn.close()
    return result_id


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--strategy", required=True)
    p.add_argument("--start", required=True)
    p.add_argument("--end", required=True)
    p.add_argument("--output-format", choices=("json", "pretty"), default="pretty")
    p.add_argument("--persist", action="store_true")
    p.add_argument("--db-path", default=DB_PATH)
    args = p.parse_args()

    spec = load_spec(args.strategy)
    cfg = BacktestConfig(
        strategy=spec, start_date=args.start, end_date=args.end,
    )
    result = run_backtest(cfg)

    if args.persist:
        result_id = _persist(result, db_path=args.db_path)
        print(f"persisted as result_id={result_id}")

    if args.output_format == "json":
        print(json.dumps(result.metrics, default=str, indent=2))
    else:
        print(f"Strategy: {result.strategy_id}")
        n = result.metrics.get("n_trades") or 0
        print(f"  n_trades: {n}")
        tr = result.metrics.get("total_return_pct")
        print(f"  total_return: {tr:.2%}" if tr is not None else "  total_return: —")
        print(f"  sharpe: {result.metrics.get('sharpe')}")
        print(f"  max_dd: {result.metrics.get('max_drawdown_pct')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
