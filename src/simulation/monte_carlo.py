"""Monte Carlo resampling for simulation confidence intervals.

Reshuffles trade sequences 1,000+ times to produce:
- 5th/95th percentile equity bounds
- 95th percentile worst-case drawdown
- Probability of ruin
"""

import numpy as np


def monte_carlo_resample(trades: list[dict], n_simulations: int = 1000,
                          starting_equity: float = 100000,
                          seed: int = 42) -> dict:
    """Bootstrap resample trades to produce confidence intervals."""
    if not trades:
        return {
            "n_simulations": n_simulations,
            "seed": seed,
            "median_equity": starting_equity,
            "p5_equity": starting_equity,
            "p95_equity": starting_equity,
            "median_dd": 0.0,
            "p95_dd": 0.0,
            "p99_dd": 0.0,
            "probability_of_ruin": 0.0,
        }

    rng = np.random.RandomState(seed)
    pnl_array = np.array([t["pnl_dollars"] for t in trades])

    final_equities = []
    max_drawdowns = []

    for _ in range(n_simulations):
        resampled = rng.choice(pnl_array, size=len(pnl_array), replace=True)
        equity = starting_equity
        peak = equity
        max_dd = 0.0

        for pnl in resampled:
            equity += pnl
            peak = max(peak, equity)
            dd = (peak - equity) / peak * 100 if peak > 0 else 0
            max_dd = max(max_dd, dd)

        final_equities.append(equity)
        max_drawdowns.append(max_dd)

    fe = np.array(final_equities)
    md = np.array(max_drawdowns)

    return {
        "n_simulations": n_simulations,
        "seed": seed,
        "median_equity": float(np.median(fe)),
        "p5_equity": float(np.percentile(fe, 5)),
        "p95_equity": float(np.percentile(fe, 95)),
        "median_dd": float(np.median(md)),
        "p95_dd": float(np.percentile(md, 95)),
        "p99_dd": float(np.percentile(md, 99)),
        "probability_of_ruin": float(np.sum(fe <= 0) / n_simulations),
    }
