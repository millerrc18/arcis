"""Bootstrap confidence interval engine.

Computes 95% CIs via percentile bootstrap with 10,000 resamples.
Statistic: mean of the input array (used for excess-Sharpe estimation).

Called by: diagnostics.analyses
Calls: numpy
Owns tables: none
Config keys: none
Tests: tests/diagnostics/test_regime_diagnostic.py
"""

from __future__ import annotations

import numpy as np


def bootstrap_ci(
    data: np.ndarray,
    n_resamples: int = 10_000,
    ci: float = 0.95,
    seed: int | None = 42,
) -> dict:
    """Compute bootstrap CI for the mean of data.

    Returns dict with keys: point_estimate, ci_lower, ci_upper, p_value.
    p_value is two-sided for H0: mean = 0.
    """
    data = np.asarray(data, dtype=float)
    n = len(data)
    rng = np.random.default_rng(seed)

    point_estimate = float(np.mean(data))

    boot_means = np.empty(n_resamples)
    for i in range(n_resamples):
        sample = rng.choice(data, size=n, replace=True)
        boot_means[i] = np.mean(sample)

    alpha = 1.0 - ci
    ci_lower = float(np.percentile(boot_means, 100 * alpha / 2))
    ci_upper = float(np.percentile(boot_means, 100 * (1 - alpha / 2)))

    # Two-sided p-value: proportion of bootstrap means on the opposite
    # side of zero from the point estimate, times 2 (capped at 1.0)
    if point_estimate >= 0:
        p_value = float(np.mean(boot_means <= 0)) * 2
    else:
        p_value = float(np.mean(boot_means >= 0)) * 2
    p_value = min(p_value, 1.0)

    return {
        "point_estimate": point_estimate,
        "ci_lower": ci_lower,
        "ci_upper": ci_upper,
        "p_value": p_value,
    }
