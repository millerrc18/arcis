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
# Gauss-Legendre quadrature (pure Python, computed once)
# ---------------------------------------------------------------------------

def _legendre(n: int, x: float) -> tuple[float, float]:
    """P_n(x) and P_n'(x) via the three-term recurrence."""
    p0, p1 = 1.0, x
    dp0, dp1 = 0.0, 1.0
    for k in range(1, n):
        p2 = ((2 * k + 1) * x * p1 - k * p0) / (k + 1)
        dp2 = ((2 * k + 1) * (x * dp1 + p1) - k * dp0) / (k + 1)
        p0, p1, dp0, dp1 = p1, p2, dp1, dp2
    return (p0, dp0) if n == 0 else (p1, dp1)


def _gauss_legendre(n: int) -> tuple[list[float], list[float]]:
    """Nodes and weights for n-point Gauss-Legendre on (-1, 1)."""
    xs, ws = [], []
    for i in range(1, n + 1):
        # Cosine initial guess for the i-th root.
        x = math.cos(math.pi * (i - 0.25) / (n + 0.5))
        for _ in range(20):
            p, dp = _legendre(n, x)
            dx = p / dp
            x -= dx
            if abs(dx) < 1e-14:
                break
        p, dp = _legendre(n, x)
        xs.append(x)
        ws.append(2.0 / ((1.0 - x * x) * dp * dp))
    return xs, ws


_GL_N = 96
_GL_X, _GL_W = _gauss_legendre(_GL_N)


def _gl_integral(f: Any, a: float, b: float) -> float:
    """∫_a^b f via 96-point Gauss-Legendre (exact for deg ≤ 191)."""
    mid = 0.5 * (a + b)
    half = 0.5 * (b - a)
    s = 0.0
    for x, w in zip(_GL_X, _GL_W, strict=True):
        s += w * f(mid + half * x)
    return s * half


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


def _interp_grid(zs: list[float], vals: list[float], z: float) -> float:
    """Linear interpolation of grid values (0 outside the grid)."""
    if z <= zs[0] or z >= zs[-1]:
        return 0.0
    i = bisect.bisect_left(zs, z)
    # zs[i-1] < z <= zs[i]
    z0, z1 = zs[i - 1], zs[i]
    v0, v1 = vals[i - 1], vals[i]
    frac = (z - z0) / (z1 - z0)
    return v0 + (v1 - v0) * frac


def _propagate(zs: list[float], dens: list[float], zmin: float,
               zmax: float, b_prev: float, r: float, sig: float,
               inv_sqrt_2pi: float) -> list[float]:
    """One recursion step: g_k from g_{k-1} via GL quadrature."""
    inv_sig = 1.0 / sig
    def make_dens(zj: float) -> float:
        def integrand(u: float) -> float:
            gu = _interp_grid(zs, dens, u)
            if gu == 0.0:
                return 0.0
            diff = (zj - r * u) * inv_sig
            return gu * math.exp(-0.5 * diff * diff)
        return _gl_integral(integrand, zmin, b_prev) * inv_sqrt_2pi * inv_sig
    return [make_dens(zj) for zj in zs]


def _find_bound(zs: list[float], dens: list[float], zmax: float,
                need: float) -> float:
    """Bisect b with P(Z_k > b) = need (GL quadrature for the tail)."""
    def tail_prob(b: float) -> float:
        return _gl_integral(lambda z: _interp_grid(zs, dens, z), b, zmax)
    lo, hi = 0.0, zmax
    for _ in range(60):
        mid = 0.5 * (lo + hi)
        if tail_prob(mid) > need:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def lan_demet_obf_bounds(n_looks: int, alpha: float = 0.025,
                         n_grid: int = 4001) -> list[float]:
    """One-sided Lan-DeMets O'Brien-Fleming z-boundaries.

    Forward recursion over the "still running" density, with all integrals
    via 96-point Gauss-Legendre quadrature (accurate to ~1e-9). The density
    is represented on a uniform grid and linearly interpolated at
    quadrature nodes.

    Raises ValueError on bad inputs. Pure Python; ~1s for 5 looks.
    """
    if n_looks < 1:
        raise ValueError(f"n_looks must be >= 1, got {n_looks}")
    if not 0.0 < alpha < 1.0:
        raise ValueError(f"alpha must be in (0, 1), got {alpha}")
    zmax, zmin = 12.0, -12.0
    dz = (zmax - zmin) / (n_grid - 1)
    zs = [zmin + i * dz for i in range(n_grid)]
    inv_sqrt_2pi = 1.0 / math.sqrt(2.0 * math.pi)
    dens = [math.exp(-0.5 * z * z) * inv_sqrt_2pi for z in zs]  # g_1
    ts = [(k + 1) / n_looks for k in range(n_looks)]
    out: list[float] = []
    spent = 0.0
    for k, tk in enumerate(ts):
        need = spending_ld_of(tk, alpha) - spent
        if k == 0:
            b = norm_ppf(1.0 - need)  # g_1 is exactly N(0,1)
        else:
            tp = ts[k - 1]
            r = math.sqrt(tp / tk)
            sig = math.sqrt(1.0 - tp / tk)
            dens = _propagate(zs, dens, zmin, zmax, out[-1], r, sig,
                              inv_sqrt_2pi)
            b = _find_bound(zs, dens, zmax, need)
        out.append(b)
        spent += need
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
