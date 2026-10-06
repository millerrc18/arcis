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

from arcis.research.fee_schedules import (
    sec_section31_rate,
    taf_cap,
    taf_rate,
)

# --- Dated fee schedules ---
#
# Full verified schedules live in arcis.research.fee_schedules
# (33 SEC Section 31 periods, 1934–2026; 8 FINRA TAF periods, 2002–2026),
# reconstructed 2026-10-06 from SEC/FINRA primary sources.
# Research notes: ~/workspace/research_notes/sec-taf-fee-schedules-20261006-0046/
#
# Date conventions: SEC Section 31 is looked up by CHARGE date (≈ settlement
# date); FINRA TAF by TRADE date. total_trade_cost takes the trade date as
# `as_of` and an optional `charge_date` (defaults to `as_of`: a documented
# 1-day approximation; pass the settlement date for exactness).

# CAT fee per executed equivalent share (both sides)
# R06: "Set zero until a verified Alpaca or executing-broker CAT
# pass-through schedule applies." No verified schedule exists, so
# CAT is zero. This is per-spec, not a guess.
CAT_FEE_PER_SHARE = 0.0

# Tick size for spread floor (Reg NMS minimum for stocks >= $1)
TICK_SIZE = 0.01


def sec_fee_rate(charge_date: date) -> float:
    """SEC Section 31 rate per $1M of sale principal for `charge_date`.

    Charge date generally means settlement date (not trade date).
    Delegates to the verified schedule in fee_schedules; raises
    UnresolvedFeeError outside the verified window.
    """
    return sec_section31_rate(charge_date)


def sec_fee(sale_notional: float, charge_date: date) -> float:
    """SEC fee in dollars: sale_notional * rate / 1,000,000.

    `charge_date` is the charge date (≈ settlement date).
    """
    return sale_notional * sec_fee_rate(charge_date) / 1_000_000


def finra_taf_rate(trade_date: date) -> float:
    """FINRA TAF rate per share for `trade_date` (cap applied separately).

    Trade date, not settlement date. Zero before TAF inception
    (2002-10-01); raises UnresolvedFeeError after 2026-12-31.
    """
    return taf_rate(trade_date)


def finra_taf_cap(trade_date: date) -> float:
    """FINRA TAF cap in dollars per trade for `trade_date`.

    Raises UnresolvedFeeError during the $0 assessment holiday and
    outside the verified window.
    """
    return taf_cap(trade_date)


def finra_taf(shares_sold: float, trade_date: date) -> float:
    """FINRA TAF in dollars: min(shares * rate, dated cap) per R06.

    `trade_date` is the trade date. Zero before TAF inception
    (2002-10-01) and during the $0 assessment holiday (2026-10-01
    through 2026-12-31); no cap lookup needed when the rate is zero.
    """
    rate = finra_taf_rate(trade_date)  # 0.0 pre-inception/holiday
    if rate == 0.0:
        return 0.0
    return min(shares_sold * rate, finra_taf_cap(trade_date))


def cat_fee(shares: float) -> float:
    """CAT fee in dollars. Currently zero per R06 (no verified schedule)."""
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
#
# UNRESOLVED: The 21-session trailing median smoothing from R06
# ("Smooth daily estimators with a trailing 21-session median for
# production cost inputs") is not implemented. The functions below
# return unsmoothed single-day estimates. Smoothing is deferred to
# the caller or a future sprint.


def corwin_schultz_spread(highs: list[float], lows: list[float]) -> float:
    """Corwin-Schultz full spread proxy from adjacent high-low ranges.

    Uses the last 2 days. Raises ValueError on invalid input
    (fail-closed; do not silently return 0).
    Reference: Corwin & Schultz (2012), JF.
    """
    if len(highs) < 2 or len(lows) < 2:
        raise ValueError("need 2 days of highs and lows")
    h0, h1 = highs[-2], highs[-1]
    l0, l1 = lows[-2], lows[-1]
    if h0 <= 0 or h1 <= 0 or l0 <= 0 or l1 <= 0:
        raise ValueError("prices must be positive")
    if h0 < l0 or h1 < l1:
        raise ValueError("high must be >= low")

    beta = (math.log(h0 / l0) ** 2 + math.log(h1 / l1) ** 2)
    h_max = max(h0, h1)
    l_min = min(l0, l1)
    gamma = math.log(h_max / l_min) ** 2

    alpha = (math.sqrt(2 * beta) - math.sqrt(beta)) / (3 - 2 * math.sqrt(2))
    alpha -= math.sqrt(gamma / (3 - 2 * math.sqrt(2)))
    alpha = max(alpha, 0.0)  # Clamp per CS

    spread = 2 * (math.exp(alpha) - 1) / (1 + math.exp(alpha))
    return max(spread, 0.0)


def abdi_ranaldo_spread(highs: list[float], lows: list[float],
                        closes: list[float]) -> float:
    """Abdi-Ranaldo spread proxy.

    Implements the two-day estimator from Abdi & Ranaldo (2017), RFS:
      S = 2 * sqrt((c_t - eta_t) * (c_t - eta_{t+1}))
    where c_t = log(C_t), eta_t = (log H_t + log L_t) / 2.

    Uses days t-1 and t (the last two days). Raises ValueError on
    invalid input (fail-closed).
    """
    if len(highs) < 2 or len(lows) < 2 or len(closes) < 2:
        raise ValueError("need 2 days of highs, lows, closes")
    h0, h1 = highs[-2], highs[-1]
    l0, l1 = lows[-2], lows[-1]
    c0 = closes[-2]
    if h0 <= 0 or h1 <= 0 or l0 <= 0 or l1 <= 0 or c0 <= 0:
        raise ValueError("prices must be positive")
    if h0 < l0 or h1 < l1:
        raise ValueError("high must be >= low")

    eta0 = (math.log(h0) + math.log(l0)) / 2
    eta1 = (math.log(h1) + math.log(l1)) / 2
    log_c0 = math.log(c0)
    val = (log_c0 - eta0) * (log_c0 - eta1)
    if val < 0:
        # Negative covariance estimate -> no measurable spread
        return 0.0
    return 2 * math.sqrt(val)


def tick_floor_fraction(price: float) -> float:
    """Minimum spread as a fraction of price: $0.01 / price.

    A $10 stock has a 10bp tick floor; a $100 stock has 1bp.
    Raises ValueError if price <= 0.
    """
    if price <= 0:
        raise ValueError("price must be positive")
    return TICK_SIZE / price


def spread_proxy_central(highs: list[float], lows: list[float],
                         closes: list[float], price: float) -> float:
    """Central full-spread proxy: max(tick floor, median(CS, AR)).

    Tick floor is price-aware: TICK_SIZE / price.
    """
    cs = corwin_schultz_spread(highs, lows)
    ar = abdi_ranaldo_spread(highs, lows, closes)
    median = (cs + ar) / 2  # median of two = mean
    return max(tick_floor_fraction(price), median)


def spread_proxy_conservative(highs: list[float], lows: list[float],
                              closes: list[float],
                              price: float) -> float:
    """Conservative full-spread proxy: max(tick floor, larger(CS, AR))."""
    cs = corwin_schultz_spread(highs, lows)
    ar = abdi_ranaldo_spread(highs, lows, closes)
    return max(tick_floor_fraction(price), cs, ar)


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
                     cost_model: str = "central",
                     charge_date: date | None = None) -> dict[str, float]:
    """Total trade cost in dollars and basis points.

    Returns dict with dollar amounts per component and total bp.

    Date conventions: `as_of` is the trade date (drives the FINRA TAF
    lookup). `charge_date` is the SEC Section 31 charge date (≈ settlement
    date); when None it defaults to `as_of`, a documented 1-day
    approximation — pass the settlement date for exactness around
    Section 31 rate changes.

    Raises ValueError on non-positive notional (fail-closed: a cost in
    basis points is undefined without a notional base).
    """
    if notional <= 0:
        raise ValueError(f"total_trade_cost: notional must be positive, "
                         f"got {notional}")
    comm = commission(shares, commission_model)
    cat = cat_fee(shares)

    sec = sec_fee(notional,
                  charge_date if charge_date is not None else as_of
                  ) if is_sell else 0.0
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
    total_bp = total_dollars / notional * 10_000

    return {
        "commission": comm,
        "cat_fee": cat,
        "sec_fee": sec,
        "finra_taf": taf,
        "execution": exec_cost,
        "total_dollars": total_dollars,
        "total_bp": total_bp,
    }
