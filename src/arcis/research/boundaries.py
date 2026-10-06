"""Lan-DeMets O'Brien-Fleming sequential boundaries (PREREG §0 rule 6).

One-sided Type I error ``alpha`` (default 2.5%), via the Lan-DeMets
spending-function approximation to O'Brien-Fleming boundaries.

Spending function (gsDesign ``sfLDOF``, rho=1)::

    α(t) = 2 − 2·Φ( z_{1−α/2} / √t )

Boundaries are found by forward recursion over the joint distribution of
the sequential z-statistics: at look k, b_k solves
P(exit at k) = α(t_k) − α(t_{k−1}), where the "still running" density is
propagated with the exact Gaussian conditional
Z_k | Z_{k−1} = y ~ N(y·√(t_{k−1}/t_k), 1 − t_{k−1}/t_k).

Pure Python (stdlib only): no numpy/scipy, so the boundary generator and
its tests run in every environment, including the default CI install.

Reference values (one-sided α=2.5%): 2 looks → [2.963, 1.969],
3 looks → [3.710, 2.512, 1.993].
"""

from __future__ import annotations

import bisect
import json
import math
import sys
from datetime import date
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Normal distribution helpers (Acklam's approximation for the quantile)
# ---------------------------------------------------------------------------

_PPF_A = [-3.969683028665376e01, 2.209460984245205e02,
          -2.759285104469687e02, 1.383577518672690e02,
          -3.066479806614716e01, 2.506628277459239e00]
_PPF_B = [-5.447609879822406e01, 1.615858368580409e02,
          -1.556989798598866e02, 6.680131188771972e01,
          -1.328068155288572e01]
_PPF_C = [-7.784894002430293e-03, -3.223964580411365e-01,
          -2.400758277161838e00, -2.549732539343734e00,
          4.374664141464968e00, 2.938163982698783e00]
_PPF_D = [7.784695709041462e-03, 3.224671290700398e-01,
          2.445134137142996e00, 3.754408661907416e00]


def norm_cdf(x: float) -> float:
    """Standard normal CDF via erf (accurate to ~1e-15)."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def norm_ppf(p: float) -> float:
    """Standard normal quantile (Acklam's approximation, ~1e-9)."""
    if not 0.0 < p < 1.0:
        raise ValueError(f"p must be in (0, 1), got {p}")
    a, b, c, d = _PPF_A, _PPF_B, _PPF_C, _PPF_D
    if p < 0.02425:
        q = math.sqrt(-2.0 * math.log(p))
        num = ((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]
        den = (((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0
        return num / den
    if p <= 0.97575:
        q = p - 0.5
        r = q * q
        num = (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r
               + a[5]) * q
        den = (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1.0)
        return num / den
    q = math.sqrt(-2.0 * math.log(1.0 - p))
    num = ((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]
    den = (((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0
    return -num / den


def spending_ld_of(t: float, alpha: float = 0.025) -> float:
    """Lan-DeMets O'Brien-Fleming one-sided spending function.

    α(t) = 2 − 2·Φ(z_{1−α/2} / √t).  α(0) = 0, α(1) = α.
    """
    if not 0.0 < alpha < 1.0:
        raise ValueError(f"alpha must be in (0, 1), got {alpha}")
    if t <= 0.0:
        return 0.0
    if t >= 1.0:
        return alpha
    return 2.0 - 2.0 * norm_cdf(norm_ppf(1.0 - alpha / 2.0) / math.sqrt(t))


# ---------------------------------------------------------------------------
# Boundary computation
# ---------------------------------------------------------------------------

def _tail_prob(dens: list[float], zs: list[float], dz: float,
               b: float) -> float:
    """P(Z > b) for a piecewise-linear density on the grid (trapezoidal)."""
    n = len(zs)
    i = bisect.bisect_left(zs, b)
    if i >= n:
        return 0.0
    total = 0.0
    if i > 0:  # partial first cell: linear interpolation
        frac = (b - zs[i - 1]) / dz
        d0 = dens[i - 1] + (dens[i] - dens[i - 1]) * frac
        total += 0.5 * (d0 + dens[i]) * (zs[i] - b)
    s = 0.0
    for j in range(i, n - 1):
        s += dens[j] + dens[j + 1]
    return total + 0.5 * s * dz


def lan_demet_obf_bounds(n_looks: int, alpha: float = 0.025,
                         n_grid: int = 1501) -> list[float]:
    """One-sided Lan-DeMets O'Brien-Fleming z-boundaries.

    Raises ValueError on bad inputs. Pure Python; ~1s for 5 looks.
    """
    if n_looks < 1:
        raise ValueError(f"n_looks must be >= 1, got {n_looks}")
    if not 0.0 < alpha < 1.0:
        raise ValueError(f"alpha must be in (0, 1), got {alpha}")
    zmax = 12.0
    dz = 2.0 * zmax / (n_grid - 1)
    zs = [-zmax + i * dz for i in range(n_grid)]
    inv_sqrt_2pi = 1.0 / math.sqrt(2.0 * math.pi)
    dens = [math.exp(-0.5 * z * z) * inv_sqrt_2pi for z in zs]  # g_1
    ts = [(k + 1) / n_looks for k in range(n_looks)]
    out: list[float] = []
    spent = 0.0
    for k, tk in enumerate(ts):
        need = spending_ld_of(tk, alpha) - spent
        if k == 0:
            # g_1 is exactly standard normal: solve analytically.
            b = norm_ppf(1.0 - need)
        else:
            tp = ts[k - 1]
            r = math.sqrt(tp / tk)
            sig = math.sqrt(1.0 - tp / tk)
            inv = inv_sqrt_2pi / sig
            new = [0.0] * n_grid
            for j in range(n_grid):
                zj = zs[j]
                i_lo = max(0, int(((zj - 8.0 * sig) / r + zmax) / dz))
                i_hi = min(n_grid - 1, int(((zj + 8.0 * sig) / r + zmax) / dz))
                s = 0.0
                for i in range(i_lo, i_hi + 1):
                    d = dens[i]
                    if d:
                        diff = (zj - r * zs[i]) / sig
                        s += d * math.exp(-0.5 * diff * diff)
                new[j] = s * inv * dz
            dens = new
            lo, hi = 0.0, zmax
            for _ in range(60):  # bisection: tail mass is monotone in b
                mid = 0.5 * (lo + hi)
                if _tail_prob(dens, zs, dz, mid) > need:
                    lo = mid
                else:
                    hi = mid
            b = 0.5 * (lo + hi)
        out.append(b)
        spent += need
        # Truncate the "still running" density above b (fractional cell).
        f = (b + zmax) / dz
        i0, frac = int(f), f - int(f)
        for i in range(i0 + 1, n_grid):
            dens[i] = 0.0
        if 0 <= i0 < n_grid:
            dens[i0] *= 1.0 - frac
    return out


def archive(path: str | Path, n_looks: int, alpha: float = 0.025
            ) -> dict[str, Any]:
    """Generate the boundaries and archive inputs + outputs as JSON.

    Records the spending-function definition, the implementation
    (pure-Python stdlib: nothing to pin), and the Python version.
    """
    bounds = lan_demet_obf_bounds(n_looks, alpha)
    record = {
        "method": "lan_demet_obf",
        "spending_function": "2 - 2*Phi(z_{1-alpha/2} / sqrt(t))  (gsDesign sfLDOF)",
        "alpha_one_sided": alpha,
        "n_looks": n_looks,
        "bounds": bounds,
        "implementation": "pure-python stdlib (math.bisect)",
        "python_version": sys.version.split()[0],
        "archived_on": date.today().isoformat(),
    }
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(record, indent=2) + "\n")
    return record
