"""Stage-1 instrumentation filter + Bailey-LdP MinTRL power assessment (T1.08).

Audit spec §F-1, §3.1, §9 item 9: before reporting Stage-1 Sharpe in a
baseline memo, callers must (a) drop any trade row missing one of the four
instrumentation columns and (b) declare whether the surviving N is large
enough to reject H0: SR <= 0 at alpha=0.05. Skipping either step lets the
desk publish numbers that look like signal but are actually small-sample
noise — see audit notes 9 and the underpowered phrase below.

Three exports:

  is_fully_instrumented(row)         -> bool predicate
  filter_fully_instrumented(rows)    -> list[dict] in input order
  assess_statistical_power(n, ...)   -> PowerAssessment dataclass

target_sharpe != 0.0 is intentionally unsupported here — that is the
T2.04 promotion-gate concern. T1.08 only owns the Stage-1 baseline
"can we even report this?" question, which simplifies to MinTRL =
1 + z_alpha**2 under the Gaussian / target=0 assumption.

Called by: src.platform.baseline_memo (T1.02).
Calls: math (z-quantile via Acklam / inverse Phi).
Owns tables: none.
Config keys: none.
Tests: tests/analytics/test_instrumentation_filter.py.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable, Literal

_INSTRUMENTATION_COLUMNS = (
    "pnl_pct",
    "actual_entry_time",
    "actual_exit_time",
    "excess_return",
)
_TIME_COLUMNS = ("actual_entry_time", "actual_exit_time")

UNDERPOWERED_MESSAGE = (
    "Stage-1 sample is underpowered; reported Sharpe is not "
    "statistically reliable. Consider deferring promotion until "
    "N >= MinTRL."
)


def is_fully_instrumented(row: dict) -> bool:
    """True iff all four instrumentation columns are populated.

    SQLite stores everything as raw bytes and does not enforce typing,
    so an empty string '' must be treated identically to NULL — that
    is how the writer signals "I tried to compute this but had no
    data". A bare-whitespace string is the same case (operator typo
    or upstream trim/strip artefact).
    """
    for col in _INSTRUMENTATION_COLUMNS:
        if col not in row:
            return False
        value = row[col]
        if value is None:
            return False
        if isinstance(value, str):
            if value.strip() == "":
                return False
        elif col in _TIME_COLUMNS:
            # Time fields are stored as ISO strings — anything else
            # is malformed and counts as missing.
            return False
    return True


def filter_fully_instrumented(rows: Iterable[dict]) -> list[dict]:
    """Return only rows passing is_fully_instrumented; preserves input order."""
    return [r for r in rows if is_fully_instrumented(r)]


@dataclass(frozen=True)
class PowerAssessment:
    """Result of Bailey-LdP MinTRL power check for a Stage-1 sample."""

    n: int
    mintrl_required: float
    status: Literal["powered", "underpowered", "marginal"]
    message: str


def _inverse_normal_cdf(p: float) -> float:
    """Acklam's rational approximation to the inverse standard-normal CDF.

    Inlined to keep this module dependency-free (canonical_sharpe.py is
    likewise pure-Python on purpose); accuracy is ~1e-9 over (0,1) which
    is fine for tabulating MinTRL.
    """
    if not 0.0 < p < 1.0:
        raise ValueError(f"_inverse_normal_cdf requires 0<p<1; got {p}")
    a = (
        -3.969683028665376e01,
        2.209460984245205e02,
        -2.759285104469687e02,
        1.383577518672690e02,
        -3.066479806614716e01,
        2.506628277459239e00,
    )
    b = (
        -5.447609879822406e01,
        1.615858368580409e02,
        -1.556989798598866e02,
        6.680131188771972e01,
        -1.328068155288572e01,
    )
    c = (
        -7.784894002430293e-03,
        -3.223964580411365e-01,
        -2.400758277161838e00,
        -2.549732539343734e00,
        4.374664141464968e00,
        2.938163982698783e00,
    )
    d = (
        7.784695709041462e-03,
        3.224671290700398e-01,
        2.445134137142996e00,
        3.754408661907416e00,
    )
    p_low, p_high = 0.02425, 1.0 - 0.02425
    if p < p_low:
        q = math.sqrt(-2.0 * math.log(p))
        return (
            ((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]
        ) / ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0)
    if p <= p_high:
        q = p - 0.5
        r = q * q
        return (
            (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q
        ) / (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1.0)
    q = math.sqrt(-2.0 * math.log(1.0 - p))
    return -(
        ((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]
    ) / ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0)


def assess_statistical_power(
    n: int,
    target_sharpe: float = 0.0,
    alpha: float = 0.05,
) -> PowerAssessment:
    """Bailey-Lopez de Prado MinTRL power assessment.

    Closed form (Bailey & López de Prado 2012 §3, Gaussian fallback,
    target_sharpe=0, no observed Sharpe estimate yet):
        MinTRL = 1 + z_(alpha/2)**2
    where z_(alpha/2) = Phi^-1(1 - alpha/2) is the two-sided critical
    value (alpha=0.05 -> 1.96 -> MinTRL ≈ 4.84) per audit spec §F-1.

    Status thresholds:
        n < MinTRL          -> 'underpowered' (operator MUST defer reporting)
        MinTRL <= n < 2*MinTRL -> 'marginal' (report with caveat)
        n >= 2*MinTRL       -> 'powered'
    """
    if target_sharpe != 0.0:
        raise NotImplementedError(
            "assess_statistical_power: non-zero target_sharpe is the "
            "T2.04 promotion-gate concern. T1.08 only supports "
            "target_sharpe=0.0 (Stage-1 baseline reportability)."
        )
    z_alpha = _inverse_normal_cdf(1.0 - alpha / 2.0)
    mintrl = 1.0 + z_alpha ** 2
    if n < mintrl:
        status = "underpowered"
        message = (
            f"{UNDERPOWERED_MESSAGE} "
            f"(n={n}, MinTRL={mintrl:.2f}, alpha={alpha})"
        )
    elif n < 2.0 * mintrl:
        status = "marginal"
        message = (
            f"Stage-1 sample is marginal (n={n}, MinTRL={mintrl:.2f}, "
            f"2*MinTRL={2.0 * mintrl:.2f}, alpha={alpha}). Report with "
            "caveat; rerun once N exceeds 2*MinTRL."
        )
    else:
        status = "powered"
        message = (
            f"Stage-1 sample is powered (n={n} >= 2*MinTRL="
            f"{2.0 * mintrl:.2f}, alpha={alpha})."
        )
    return PowerAssessment(
        n=n,
        mintrl_required=mintrl,
        status=status,
        message=message,
    )
