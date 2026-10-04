"""S03 T4: Power simulations via date-block bootstrap (CLI).

Clean-room measurement for preregistration power calibration. All effects
are SYNTHETIC and randomly assigned. Core logic in tools/s03_power_lib.py.

Family A (§2.1): label = b_Q·Qualified + ε, date FE, date-clustered SE,
  one-sided α=2.5%. Label proxy: beta-adjusted 15-session forward return
  (per S03 spec T4).
Family B (§3.2): r = α_i + δ_t + b·(N·F) + ε, Holm at family α=2.5%
  (per-test 1.25%). Outcome: 1-day beta-adjusted forward return.

Qualification rates: 0.5%, 1%, 2%, 5%, 10%, plus the 5% forward planning
rate (preregistered S&P 500 qualification parameter).

Output: <data_root>/s03/power_results.json (aggregate statistics only).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

from s03_power_lib import (  # noqa: E402
    BLOCK_LEN,
    check_forbidden,
    load_beta_adjusted_returns,
    simulate_family_a,
    simulate_family_b,
)

BASE_SEED = 304
N_REPS = 2000

# Family A: §2.1 qualification rates (fractions); 0.05 is the preregistered
# forward planning rate for the S&P 500 universe.
Q_RATES_A = [0.005, 0.01, 0.02, 0.05, 0.10]
WINDOWS_A = [12, 24]
# Family B: §3.2 windows (spec requires 12 and 24 months)
WINDOWS_B = [12, 24]
# News share: measured 0.0774 in T3 (second_moments.json)
NEWS_SHARE_B = 0.0774

# Effect grids (fractions; 0.0025 = 25 bp)
GRID_A = np.array([0.0005, 0.001, 0.002, 0.0025, 0.003, 0.005, 0.0075, 0.01])
GRID_B = np.array([0.0001, 0.0002, 0.0003, 0.0005, 0.0008, 0.001, 0.0015, 0.002])


def main() -> int:
    parser = argparse.ArgumentParser(description="S03 T4 power simulations")
    parser.add_argument("--data-root", default="/home/hatch/arcis-data")
    parser.add_argument("--config-dir", default="config")
    parser.add_argument("--quick", action="store_true",
                        help="smoke test: 20 reps, 1 cell")
    args = parser.parse_args()
    check_forbidden(args.config_dir)
    n_reps = 20 if args.quick else N_REPS
    out_dir = os.path.join(args.data_root, "s03")
    os.makedirs(out_dir, exist_ok=True)
    return _run(args.data_root, n_reps, args.quick, out_dir)


def _run(data_root: str, n_reps: int, quick: bool, out_dir: str) -> int:
    print("Loading beta-adjusted returns (h=15)...", flush=True)
    rets_15 = load_beta_adjusted_returns(data_root, h=15)
    print(f"  {len(rets_15):,} rows", flush=True)
    print("Loading beta-adjusted returns (h=1)...", flush=True)
    rets_1 = load_beta_adjusted_returns(data_root, h=1)
    print(f"  {len(rets_1):,} rows", flush=True)
    results = _init_results(n_reps)
    cell_idx = _run_family_a(results, rets_15, n_reps, quick)
    _run_family_b(results, rets_1, n_reps, quick, cell_idx)
    out_path = os.path.join(out_dir, "power_results.json")
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"Wrote {out_path}", flush=True)
    return 0


def _init_results(n_reps: int) -> dict:
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "base_seed": BASE_SEED,
        "block_len": BLOCK_LEN,
        "n_reps_per_cell": n_reps,
        "label_proxy_h": 15,
        "planning_rate": 0.05,
        "family_a": [],
        "family_b": [],
        "notes": [
            "All effects synthetic and randomly assigned.",
            "Family A outcome: 15-session beta-adjusted forward return "
            "(S03 spec T4 label proxy).",
            "Family B outcome: 1-day beta-adjusted forward return.",
            "Power SEs are binomial: sqrt(p(1-p)/n_reps).",
            "Unbracketed forward returns overstate dispersion vs bracketed "
            "labels (MDE biased up); current-constituent survivorship "
            "understates dispersion (MDE biased down).",
        ],
    }


def _run_family_a(results: dict, rets: object, n_reps: int, quick: bool) -> int:
    cell_idx = 0
    for n_months in WINDOWS_A:
        for q in Q_RATES_A:
            if quick and cell_idx > 0:
                continue
            seed = BASE_SEED + cell_idx
            print(f"Family A: {n_months}mo, q={q:.3f}, seed={seed}...", flush=True)
            cell = simulate_family_a(rets, q, n_months, seed, n_reps, GRID_A)
            results["family_a"].append(cell)
            print(f"  MDE80={cell['mde_80']*1e4:.1f}bp", flush=True)
            cell_idx += 1
    return cell_idx


def _run_family_b(
    results: dict, rets: object, n_reps: int, quick: bool, cell_idx: int
) -> None:
    for n_months in WINDOWS_B:
        if quick and cell_idx > 1:
            continue
        seed = BASE_SEED + 100 + cell_idx
        print(f"Family B: {n_months}mo, seed={seed}...", flush=True)
        cell = simulate_family_b(
            rets, n_months, seed, n_reps, GRID_B, NEWS_SHARE_B
        )
        results["family_b"].append(cell)
        print(f"  MDE80={cell['mde_80']*1e4:.1f}bp", flush=True)
        cell_idx += 1


if __name__ == "__main__":
    raise SystemExit(main())
