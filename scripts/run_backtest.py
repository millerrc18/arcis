"""Backtest CLI runner.

Usage:
  python scripts/run_backtest.py --strategy lazy_prices_v1 \\
      --start 2020-01-01 --end 2024-12-31 --output-format json --persist
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import subprocess
import sys

from src.config import DB_PATH
from src.platform.backtest_engine import BacktestConfig, run_backtest
from src.platform.backtest_persist import persist_backtest_result
from src.platform.strategy_spec import load_spec


def _get_survivorship_haircut_bps(
    strategy_id: str, db_path: str = DB_PATH,
) -> int:
    """Return survivorship_haircut_bps for `strategy_id` from strategy_registry.

    Falls back to 75 when the strategy has not been registered yet (e.g.,
    first-time backtest before registration).
    """
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "SELECT survivorship_haircut_bps FROM strategy_registry "
            "WHERE strategy_id = ?",
            (strategy_id,),
        ).fetchone()
    finally:
        conn.close()
    if row is None or row[0] is None:
        return 75
    return int(row[0])


def _git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True
        ).strip()
    except Exception:
        return "unknown"




def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--strategy", required=True)
    p.add_argument("--start", required=True)
    p.add_argument("--end", required=True)
    p.add_argument("--output-format", choices=("json", "pretty"), default="pretty")
    p.add_argument("--persist", action="store_true")
    p.add_argument("--db-path", default=DB_PATH)
    p.add_argument(
        "--with-walkforward", action="store_true",
        help=(
            "Run a rolling walk-forward analysis (Pardo 2008) against the same "
            "strategy spec + date range and persist oos_efficiency into the "
            "backtest_results row. Required for the shadow_trading promotion gate. "
            "Adds significant runtime (one extra IS+OOS backtest per fold)."
        ),
    )
    args = p.parse_args()

    spec = load_spec(args.strategy)
    haircut_bps = _get_survivorship_haircut_bps(args.strategy, db_path=args.db_path)
    cfg = BacktestConfig(
        strategy=spec, start_date=args.start, end_date=args.end,
        survivorship_haircut_bps=haircut_bps,
    )
    result = run_backtest(cfg)

    if args.with_walkforward:
        from src.platform.rigor.walkforward import run_walkforward
        wf = run_walkforward(spec, args.start, args.end)
        result.metrics["oos_efficiency"] = wf["oos_efficiency"]
        print(
            f"walk-forward: oos_efficiency={wf['oos_efficiency']:.4f} "
            f"(overfit={'yes' if wf['overfit_flag'] else 'no'})"
        )

    if args.persist:
        result_id = persist_backtest_result(
            result, db_path=args.db_path, git_sha=_git_sha(),
        )
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
