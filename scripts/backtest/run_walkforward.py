"""CLI wrapper for walk-forward validation v1.

Usage:
    python -m scripts.backtest.run_walkforward --strategy lazy_prices_v1
    python -m scripts.backtest.run_walkforward --strategy lazy_prices_v1 \\
           --embargo-days 5 --per-side-bps 0.5 --seed 42

Called by: operators / CI pipelines.
Calls: src.platform.strategy_spec.load_spec, src.platform.backtest_engine,
       src.platform.rigor.walkforward_runner.
Owns tables: writes to walkforward_results, walkforward_trades.
Config keys: reads ARCIS_DB_PATH env var via src.config.DB_PATH.
Tests: tests/scripts/test_run_walkforward_cli.py.

The runner itself is data-driven — it takes pre-computed IS/OOS trades
per window. This CLI populates that shape by calling the existing
src.platform.backtest_engine.run_backtest once per window (zero-cost
engine call; costs applied uniformly in the runner).
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from src.config import DB_PATH
from src.platform.backtest_engine import BacktestConfig, run_backtest
from src.platform.rigor.walkforward_config import (
    DEFAULT_PER_SIDE_COST_BPS,
    DEFAULT_EMBARGO_DAYS,
    DEFAULT_RANDOM_SEED,
    WalkForwardConfig,
)
from src.platform.rigor.walkforward_runner import (
    persist_run_result,
    run_walkforward,
)
from src.platform.rigor.walkforward_universe import (
    populate_constituents_table,
    resolve_universe_size,
)
from src.platform.strategy_spec import load_spec, load_spec_from_yaml

logger = logging.getLogger("walkforward.cli")


def _parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="run_walkforward",
        description="Walk-forward validation v1 — R1–R8 gate.",
    )
    p.add_argument("--strategy", required=True,
                   help="strategy_id (matches specs/<id>.yaml)")
    p.add_argument("--specs-dir", default=None,
                   help="directory containing <strategy>.yaml; defaults to "
                        "src/platform/specs")
    p.add_argument("--embargo-days", type=int, default=DEFAULT_EMBARGO_DAYS)
    p.add_argument("--per-side-bps", type=float,
                   default=DEFAULT_PER_SIDE_COST_BPS)
    p.add_argument("--seed", type=int, default=DEFAULT_RANDOM_SEED)
    p.add_argument("--db-path", default=DB_PATH)
    p.add_argument("--max-hold-days", type=int, default=21)
    p.add_argument("--skip-engine", action="store_true",
                   help="skip engine calls; run with empty trade inputs (dev)")
    p.add_argument("--dry-run", action="store_true",
                   help="print config and exit without running the framework")
    p.add_argument("--json", action="store_true",
                   help="print the outcome as a JSON object on stdout")
    return p.parse_args(argv)


def _gather_window_trades(
    spec, config: WalkForwardConfig, *, skip_engine: bool,
) -> dict:
    """Return the {window_index: {'is': [...], 'oos': [...]}} shape the
    runner needs. When skip_engine is True returns empty lists (dev mode)."""
    window_trades: dict[int, dict[str, list]] = {}
    for i, w in enumerate(config.windows):
        if skip_engine:
            window_trades[i] = {"is": [], "oos": []}
            continue
        is_cfg = BacktestConfig(
            strategy=spec, start_date=w.train_start, end_date=w.train_end,
            commission_bps=0.0, slippage_bps=0.0, spread_bps=0.0,
            random_seed=config.random_seed,
        )
        oos_cfg = BacktestConfig(
            strategy=spec, start_date=w.test_start, end_date=w.test_end,
            commission_bps=0.0, slippage_bps=0.0, spread_bps=0.0,
            random_seed=config.random_seed,
        )
        is_result = run_backtest(is_cfg)
        oos_result = run_backtest(oos_cfg)
        window_trades[i] = {
            "is": is_result.trades, "oos": oos_result.trades,
        }
    return window_trades


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv if argv is not None else sys.argv[1:])
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

    try:
        if args.specs_dir:
            spec_path = Path(args.specs_dir) / f"{args.strategy}.yaml"
            if not spec_path.exists():
                raise FileNotFoundError(
                    f"no spec found for strategy_id={args.strategy!r} at {spec_path}"
                )
            spec = load_spec_from_yaml(spec_path)
        else:
            spec = load_spec(args.strategy)
    except FileNotFoundError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2

    try:
        config = WalkForwardConfig(
            strategy_id=args.strategy,
            embargo_days=args.embargo_days,
            per_side_cost_bps=args.per_side_bps,
            random_seed=args.seed,
        )
    except ValueError as e:
        print(f"ERROR: invalid config: {e}", file=sys.stderr)
        return 2

    if args.dry_run:
        print(json.dumps(config.as_json_dict(), indent=2))
        return 0

    # Populate the SPDR table if schema is fresh. Idempotent.
    try:
        populate_constituents_table(args.db_path)
    except Exception as e:
        logger.warning("[WF CLI] constituents populate skipped: %s", e)

    window_trades = _gather_window_trades(
        spec, config, skip_engine=args.skip_engine,
    )

    # Try to estimate effective universe size as the mean of window starts
    try:
        sizes = [
            resolve_universe_size(w.test_start, args.db_path)
            for w in config.windows
        ]
        eff_univ = int(sum(sizes) / max(len(sizes), 1)) if sizes else 0
    except Exception:
        eff_univ = 0

    result = run_walkforward(
        strategy_spec_raw=spec.raw, config=config,
        window_trades=window_trades,
        spec_path=str(Path("src/platform/specs") / f"{args.strategy}.yaml"),
        max_hold_days=args.max_hold_days,
        effective_universe_size=eff_univ,
    )
    oos_per_window = []
    for i in range(len(config.windows)):
        oos_per_window.append(window_trades.get(i, {}).get("oos", []))
    persist_run_result(
        result=result, strategy_spec_raw=spec.raw,
        oos_trades_per_window=oos_per_window, db_path=args.db_path,
    )

    summary = {
        "run_id": result.run_id,
        "strategy_id": result.strategy_id,
        "outcome_state": result.outcome.outcome_state,
        "reason": result.outcome.reason,
        "pooled_sharpe": result.pooled_sharpe,
        "pooled_mde": result.pooled_mde,
        "n_windows_pass": result.outcome.n_windows_pass,
        "n_windows_fail": result.outcome.n_windows_fail,
        "n_windows_inconclusive_data": result.outcome.n_windows_inconclusive_data,
        "n_windows_inconclusive_power": result.outcome.n_windows_inconclusive_power,
        "heavy_tail_window_count": result.heavy_tail_window_count,
        "vix_tier_coverage": result.vix_tier_coverage,
    }
    if args.json:
        print(json.dumps(summary, indent=2))
    else:
        print(
            f"[WF] strategy={result.strategy_id} "
            f"outcome={result.outcome.outcome_state} "
            f"reason={result.outcome.reason} "
            f"pooled_sharpe={result.pooled_sharpe:.3f} "
            f"pass/fail/inc-d/inc-p={summary['n_windows_pass']}/"
            f"{summary['n_windows_fail']}/"
            f"{summary['n_windows_inconclusive_data']}/"
            f"{summary['n_windows_inconclusive_power']}"
        )

    # Exit code reflects the outcome — useful for CI wrappers.
    if result.outcome.outcome_state == "PASS":
        return 0
    if result.outcome.outcome_state == "INCONCLUSIVE":
        return 3
    return 1  # FAIL


if __name__ == "__main__":
    sys.exit(main())
