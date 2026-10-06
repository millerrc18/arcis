"""Sequential monitoring boundaries (PREREG §0 rule 6, §2.5).

The §2.5 exposure-matched monitor uses Lan-DeMets O'Brien-Fleming
boundaries at one-sided 2.5%. Rule 6 requires boundaries from a named,
version-pinned calculation with inputs and outputs archived before the
first look — no hand-calculated critical values. This module is that
calculation; archive() writes the dated artifact.

Numerics use scipy (research extra) via a lazy import.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any


def _spending(t: float, z_alpha: float, norm: Any) -> float:
    """One-sided OBF-like spending: 1 - Phi(z_{1-alpha} / sqrt(t))."""
    if t <= 0:
        return 0.0
    return float(1.0 - norm.cdf(z_alpha / (t ** 0.5)))


def lan_demet_obf_bounds(n_looks: int, alpha: float = 0.025) -> list[float]:
    """One-sided Lan-DeMets OBF z-boundaries at equal information fractions.

    Recursive Armitage-McPherson-Rowe integration over the joint normal of
    the sequential z-statistics, on a fixed grid (fast and stable).
    Returns the upper boundary per look; reject H0 at look k when
    z_k >= bounds[k].
    """
    try:
        import numpy as np  # lazy: research extra
        from scipy import stats  # type: ignore[import-untyped]
    except ImportError as exc:
        raise ImportError(
            "lan_demet_obf_bounds needs numpy/scipy (research extras)"
        ) from exc
    if n_looks < 1:
        raise ValueError(f"n_looks must be >= 1, got {n_looks}")
    if not 0 < alpha < 0.5:
        raise ValueError(f"alpha must be in (0, 0.5), got {alpha}")
    norm = stats.norm
    z_alpha = norm.ppf(1 - alpha)
    times = [(k + 1) / n_looks for k in range(n_looks)]
    spend = [_spending(t, z_alpha, norm) for t in times]

    xs = np.linspace(-8.0, 8.0, 4001)
    dx = xs[1] - xs[0]
    g = norm.pdf(xs)  # sub-density of Z_1 given no earlier crossing
    bounds: list[float] = []
    for k, t in enumerate(times):
        target = spend[k] - (spend[k - 1] if k else 0.0)
        # Upper-tail of the sub-density: find b with P(Z_k >= b) = target.
        tail = np.cumsum(g[::-1])[::-1] * dx
        # tail decreases as x increases; invert by interpolation.
        b_k = float(np.interp(target, tail[::-1], xs[::-1]))
        bounds.append(b_k)
        if k + 1 >= n_looks:
            break
        t_next = times[k + 1]
        rho = (t / t_next) ** 0.5
        sd = max(1e-9, (1 - t / t_next) ** 0.5)
        # Truncate the sub-density at the boundary (crossed paths removed).
        g_tr = np.where(xs < b_k, g, 0.0)
        # Transition: Z_{k+1} | Z_k = u ~ N(rho*u, sd^2).
        z = (xs[:, None] - rho * xs[None, :]) / sd
        trans = norm.pdf(z) / sd * dx
        g = trans @ g_tr
    return bounds


def archive(path: str | Path, n_looks: int, alpha: float = 0.025
            ) -> dict[str, Any]:
    """Generate the boundaries and archive inputs + outputs as JSON."""
    import scipy  # noqa: F401  (pins the implementation version)
    bounds = lan_demet_obf_bounds(n_looks, alpha)
    record = {
        "method": "Lan-DeMets O'Brien-Fleming, one-sided",
        "alpha": alpha,
        "n_looks": n_looks,
        "information_fractions": [(k + 1) / n_looks for k in range(n_looks)],
        "z_boundaries": bounds,
        "implementation": f"arcis.research.boundaries scipy={scipy.__version__}",
        "generated": date.today().isoformat(),
    }
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return record
