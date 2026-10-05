"""R06 transaction cost model.

Implements the dated-fee specification from docs/research/research-log.md.
All fees use exact effective dates. Spread proxies use Corwin-Schultz and
Abdi-Ranaldo estimators from OHLC data.

Central routine round-trip: 2-6 bp. Conservative: 6-15 bp.
These are model settings, not measured Alpaca averages.
"""

from __future__ import annotations

import math
from datetime import date

# --- Dated fee schedules ---

# SEC Section 31: (effective_date, rate per $1M of sale principal)
# Rate was zero from 2025-05-14 until the 2026 increase.
SEC_FEE_SCHEDULE: list[tuple[date, float]] = [
    (date(2026, 4, 4), 20.60),   # $20.60 per $1M = 0.206 bp
    # Prior rates would go here; zero from 2025-05-14 to 2026-04-03.
]

# FINRA TAF: (effective_date, rate per share, cap per trade)
FINRA_TAF_SCHEDULE: list[tuple[date, float, float]] = [
    (date(2024, 1, 1), 0.000166, 9.79),   # 2024-2025 rate (cap assumed)
    (date(2026, 1, 1), 0.000195, 9.79),   # 2026 rate
]
FINRA_TAF_INCEPTION = date(2002, 10, 1)
FINRA_TAF_2004_2011_RATE = 0.000075

# CAT fee per executed equivalent share (both sides)
CAT_FEE_PER_SHARE = 0.000003

# Tick floor for spread proxies
TICK_FLOOR = 0.01


def sec_fee_rate(as_of: date) -> float:
    """SEC Section 31 rate per $1M of sale principal on `as_of`."""
    # Zero from 2025-05-14 until 2026-04-04
    if date(2025, 5, 14) <= as_of < date(2026, 4, 4):
        return 0.0
    rate = 0.0
    for eff_date, r in sorted(SEC_FEE_SCHEDULE):
        if as_of >= eff_date:
            rate = r
    return rate


def sec_fee(sale_notional: float, as_of: date) -> float:
    """SEC fee in dollars: sale_notional * rate / 1,000,000."""
    return sale_notional * sec_fee_rate(as_of) / 1_000_000


def finra_taf_rate(as_of: date) -> tuple[float, float]:
    """FINRA TAF (rate per share, cap per trade) on `as_of`."""
    if as_of < FINRA_TAF_INCEPTION:
        return (0.0, 0.0)
    if date(2004, 1, 1) <= as_of < date(2012, 1, 1):
        return (FINRA_TAF_2004_2011_RATE, 9.79)
    rate, cap = 0.0, 0.0
    for eff_date, r, c in sorted(FINRA_TAF_SCHEDULE):
        if as_of >= eff_date:
            rate, cap = r, c
    return (rate, cap)


def finra_taf(shares_sold: float, as_of: date) -> float:
    """FINRA TAF in dollars: min(shares * rate, cap)."""
    rate, cap = finra_taf_rate(as_of)
    return min(shares_sold * rate, cap)


def cat_fee(shares: float) -> float:
    """CAT fee in dollars (both buys and sells)."""
    return shares * CAT_FEE_PER_SHARE


def commission(shares: int, model: str = "modern") -> float:
    """Commission in dollars.

    model="modern": zero (Alpaca zero-commission).
    model="hist_5": $5 per executed order (historical sensitivity).
    model="hist_10": $10 per executed order (historical sensitivity).
    """
    if model == "modern":
        return 0.0
    if model == "hist_5":
        return 5.0
    if model == "hist_10":
        return 10.0
    raise ValueError(f"unknown commission model: {model}")


# --- Spread proxies ---

def corwin_schultz_spread(highs: list[float], lows: list[float]) -> float:
    """Corwin-Schultz full spread proxy from adjacent high-low ranges.

    Uses the last 2 days. Returns 0 if inputs are invalid.
    Reference: Corwin & Schultz (2012), JF.
    """
    if len(highs) < 2 or len(lows) < 2:
        return 0.0
    h0, h1 = highs[-2], highs[-1]
    l0, l1 = lows[-2], lows[-1]
    if h0 <= 0 or h1 <= 0 or l0 <= 0 or l1 <= 0:
        return 0.0
    if h0 == l0 or h1 == l1:
        return 0.0

    beta = (math.log(h0 / l0) ** 2 + math.log(h1 / l1) ** 2)
    # Two-day high-low
    h_max = max(h0, h1)
    l_min = min(l0, l1)
    gamma = math.log(h_max / l_min) ** 2

    alpha = (math.sqrt(2 * beta) - math.sqrt(beta)) / (3 - 2 * math.sqrt(2))
    alpha -= math.sqrt(gamma / (3 - 2 * math.sqrt(2)))

    # Clamp alpha per CS (negative -> 0)
    alpha = max(alpha, 0.0)

    spread = 2 * (math.exp(alpha) - 1) / (1 + math.exp(alpha))
    return max(spread, 0.0)


def abdi_ranaldo_spread(highs: list[float], lows: list[float],
                        closes: list[float]) -> float:
    """Abdi-Ranaldo spread proxy from close, high, low.

    Uses the last 2 days. Returns 0 if inputs are invalid.
    Reference: Abdi & Ranaldo (2017), RFS.
    """
    if len(highs) < 2 or len(lows) < 2 or len(closes) < 3:
        return 0.0
    # AR uses: eta_t = (log H_t + log L_t)/2 ... simplified two-day version
    # Full AR: S = 2 * sqrt(E[(c_t - eta_t)(c_t - eta_{t+1})])
    # where eta_t = (log H_t + log L_t) / 2
    # We implement the two-day estimator.
    try:
        c1 = closes[-1]
        eta0 = (math.log(highs[-2]) + math.log(lows[-2])) / 2
        eta1 = (math.log(highs[-1]) + math.log(lows[-1])) / 2
        val = (math.log(c1) - eta1) * (math.log(c1) - eta0)
        # Note: AR uses c_t and c_{t+1}; we approximate with available data.
        # This is a proxy of a proxy — documented as such.
        if val < 0:
            return 0.0
        return 2 * math.sqrt(val)
    except (ValueError, ZeroDivisionError):
        return 0.0


def spread_proxy_central(highs: list[float], lows: list[float],
                         closes: list[float]) -> float:
    """Central full-spread proxy: max(tick floor, median(CS, AR))."""
    cs = corwin_schultz_spread(highs, lows)
    ar = abdi_ranaldo_spread(highs, lows, closes)
    # Median of two = mean
    median = (cs + ar) / 2
    return max(TICK_FLOOR / 100.0, median)  # tick floor as fraction


def spread_proxy_conservative(highs: list[float], lows: list[float],
                              closes: list[float]) -> float:
    """Conservative full-spread proxy: max(tick floor, larger(CS, AR))."""
    cs = corwin_schultz_spread(highs, lows)
    ar = abdi_ranaldo_spread(highs, lows, closes)
    return max(TICK_FLOOR / 100.0, cs, ar)


# --- Execution costs ---

def execution_marketable_exit(spread: float, model: str = "central") -> float:
    """Execution cost (fraction of notional) for a marketable exit.

    Central: 0.5 * spread + 0.25 bp
    Conservative: 0.5 * spread + 1.0 bp
    """
    buffer = 0.000025 if model == "central" else 0.00010
    if model not in ("central", "conservative"):
        raise ValueError(f"unknown model: {model}")
    return 0.5 * spread + buffer


def execution_stop_exit(spread: float, gap_shortfall: float = 0.0,
                        model: str = "central") -> float:
    """Execution cost (fraction) for a stop-market exit.

    Central non-gap: 0.5 * spread + 0.5 bp
    Conservative non-gap: 0.5 * spread + 2.0 bp
    Gap: add stop-to-open shortfall (as fraction).
    """
    buffer = 0.00005 if model == "central" else 0.00020
    if model not in ("central", "conservative"):
        raise ValueError(f"unknown model: {model}")
    return 0.5 * spread + buffer + gap_shortfall


def total_trade_cost(notional: float, shares: int, is_sell: bool,
                     as_of: date, spread: float,
                     exit_type: str = "marketable",
                     gap_shortfall: float = 0.0,
                     commission_model: str = "modern",
                     cost_model: str = "central") -> dict[str, float]:
    """Total trade cost in dollars and basis points.

    Returns dict with dollar amounts per component and total bp.
    """
    comm = commission(shares, commission_model)
    cat = cat_fee(shares)

    sec = sec_fee(notional, as_of) if is_sell else 0.0
    taf = finra_taf(shares, as_of) if is_sell else 0.0

    if exit_type == "marketable":
        exec_cost = execution_marketable_exit(spread, cost_model) * notional
    elif exit_type == "stop":
        exec_cost = execution_stop_exit(spread, gap_shortfall,
                                        cost_model) * notional
    elif exit_type == "passive":
        # Passive: strict trade-through, no separate execution cost added
        # (adverse selection is in the realized path, not double-counted)
        exec_cost = 0.0
    else:
        raise ValueError(f"unknown exit_type: {exit_type}")

    total_dollars = comm + cat + sec + taf + exec_cost
    total_bp = (total_dollars / notional * 10_000) if notional > 0 else 0.0

    return {
        "commission": comm,
        "cat_fee": cat,
        "sec_fee": sec,
        "finra_taf": taf,
        "execution": exec_cost,
        "total_dollars": total_dollars,
        "total_bp": total_bp,
    }
