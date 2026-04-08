#!/usr/bin/env python3
"""CLI wrapper for the full-regime simulation engine.

Core logic lives in src/simulation/engine.py — this script provides
argparse CLI and console output formatting only.

Usage:
    python scripts/simulation_engine.py                          # All 13 scenarios
    python scripts/simulation_engine.py --regime strong_bull     # Single regime
    python scripts/simulation_engine.py --monte-carlo 1000       # With MC resampling
    python scripts/simulation_engine.py --transitions-only        # Just 3 transitions
    python scripts/simulation_engine.py --validate-traffic-light  # Check TL accuracy
    python scripts/simulation_engine.py --clear-cache             # Delete cached data
    python scripts/simulation_engine.py --dry-run                 # Print config only
"""

import argparse
import json
import logging
import sys
import uuid
import warnings
from pathlib import Path

warnings.filterwarnings("ignore", message=".*utcnow.*deprecated.*")
warnings.filterwarnings("ignore", message=".*Timestamp.utcnow.*")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.simulation.cache import CACHE_DIR, clear_cache, warm_cache
from src.simulation.engine import (
    SCENARIOS,
    TRANSACTION_COSTS,
    TRANSITION_SCENARIOS,
    print_heatmap,
    run_scenario,
    store_result,
    validate_traffic_light,
)
from src.simulation.monte_carlo import monte_carlo_resample
from src.universe.sp100 import get_sp100_universe


def main():
    parser = argparse.ArgumentParser(description="Full-regime simulation engine")
    parser.add_argument("--regime", type=str, help="Run single regime")
    parser.add_argument("--monte-carlo", type=int, default=0,
                        help="MC simulations (0=disabled)")
    parser.add_argument("--transitions-only", action="store_true")
    parser.add_argument("--validate-traffic-light", action="store_true")
    parser.add_argument("--clear-cache", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--model", type=str, default=None,
                        help="Model version tag for results")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")

    if args.clear_cache:
        clear_cache()
        print("Cache cleared.")
        return

    # Select scenarios
    if args.regime:
        if args.regime not in SCENARIOS:
            print(f"Unknown regime: {args.regime}")
            print(f"Available: {', '.join(SCENARIOS.keys())}")
            return
        scenarios = {args.regime: SCENARIOS[args.regime]}
    elif args.transitions_only:
        scenarios = {k: v for k, v in SCENARIOS.items() if k in TRANSITION_SCENARIOS}
    else:
        scenarios = SCENARIOS

    config = {
        "scan_interval_days": 5,
        "max_entries_per_scan": 3,
        "position_size": 2000,
        "starting_equity": 100000,
        "transaction_costs": TRANSACTION_COSTS,
        "seed": args.seed,
        "model": args.model,
    }

    print("\n" + "=" * 60)
    print("  ARCIS FULL-REGIME SIMULATION ENGINE")
    print(f"  Scenarios: {len(scenarios)}")
    print(f"  Monte Carlo: {args.monte_carlo or 'disabled'}")
    print(f"  Seed: {args.seed}")
    print(f"  Cache dir: {CACHE_DIR}")
    print("=" * 60)

    if args.dry_run:
        print("\n[DRY RUN] Config:")
        print(json.dumps(config, indent=2))
        print("\nScenarios:")
        for name, dates in scenarios.items():
            print(f"  {name}: {dates['start']} -> {dates['end']} ({dates.get('label', '')})")
        return

    # Warm cache
    universe = get_sp100_universe()
    print(f"\n[CACHE] Warming cache for {len(scenarios)} scenarios x {len(universe)} tickers...")
    cache_stats = warm_cache(scenarios, universe)
    print(f"[CACHE] Done: {cache_stats['cached']}/{cache_stats['total']} cached, "
          f"{cache_stats['failed']} failed")

    # Run scenarios
    run_id = str(uuid.uuid4())
    results = {}
    all_trades = []

    for name, dates in scenarios.items():
        result = run_scenario(name, dates["start"], dates["end"], config)
        if "error" not in result:
            results[name] = result
            if args.model:
                result["model_version"] = args.model
            store_result(result, run_id, args.seed, config)
            all_trades.extend(result.get("trades", []))
        else:
            print(f"  [SKIP] {name}: {result['error']}")

    # Print heatmap
    if results:
        print(f"\n{'='*60}")
        print("  REGIME HEATMAP")
        print(f"{'='*60}\n")
        print_heatmap(results)

    # Monte Carlo
    if args.monte_carlo > 0 and all_trades:
        print(f"\n[MC] Running {args.monte_carlo} Monte Carlo simulations...")
        mc_results = monte_carlo_resample(
            all_trades, n_simulations=args.monte_carlo, seed=args.seed)
        print(f"[MC] Results:")
        print(f"  Median equity: ${mc_results['median_equity']:,.0f}")
        print(f"  P5 equity:     ${mc_results['p5_equity']:,.0f}")
        print(f"  P95 equity:    ${mc_results['p95_equity']:,.0f}")
        print(f"  P95 drawdown:  {mc_results['p95_dd']:.1f}%")
        print(f"  P(ruin):       {mc_results['probability_of_ruin']:.4f}")

    # Traffic light validation
    if args.validate_traffic_light and results:
        print(f"\n{'='*60}")
        print("  TRAFFIC LIGHT VALIDATION")
        print(f"{'='*60}\n")
        correct = 0
        total = 0
        for name, r in results.items():
            tl_val = validate_traffic_light(name, r.get("tl_states", []))
            total += 1
            if tl_val["correct"]:
                correct += 1
            status = "[OK]" if tl_val["correct"] else "[XX]"
            print(f"  {status} {name}: expected={tl_val['expected']}, "
                  f"actual={tl_val['actual_majority']}, "
                  f"dist={tl_val['tl_distribution']}")
        print(f"\n  Accuracy: {correct}/{total} ({correct/total:.0%})" if total else "")

    print(f"\n[DONE] Run ID: {run_id}")
    print(f"  Scenarios: {len(results)}/{len(scenarios)}")
    print(f"  Total trades: {len(all_trades)}")


if __name__ == "__main__":
    main()
