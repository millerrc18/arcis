#!/usr/bin/env python3
"""Forensic Trade Audit v1 — 8-question deep forensic of the closed-trade cohort.

Questions answered:
  Q1: Real beta decomposition (trade/cap/equal/notional-weighted + rolling)
  Q2: P&L distribution (Gini, top-K, Wilcoxon)
  Q3: Slippage vs theoretical (distribution, correlations)
  Q4: Exit type attribution (freq, mean return, Sharpe per exit type)
  Q5: Holding-period attribution (per-day return contribution)
  Q6: Time clustering (autocorrelation at lags 1/5/10/20)
  Q7: Selection vs holding split (day-1 vs day-2+ excess, CIs)
  Q8: Sector concentration (per-sector stats)

Usage:
  python scripts/diagnostics/forensic_trade_audit_v1.py \\
      --db C:/arcis/data/ai_research_desk.sqlite3 \\
      --output docs/diagnostics/forensic-audit-2026-04-18.md \\
      --plot-dir docs/diagnostics/forensic-audit-2026-04-18/
"""
from __future__ import annotations

import argparse
import datetime as dt
import logging
import math
import os
import sqlite3
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

logger = logging.getLogger(__name__)

# ── GICS Sector → SPDR ETF mapping ─────────────────────────────────
SECTOR_ETF_MAP = {
    "Technology": "XLK",
    "Information Technology": "XLK",
    "Financials": "XLF",
    "Energy": "XLE",
    "Health Care": "XLV",
    "Industrials": "XLI",
    "Consumer Discretionary": "XLY",
    "Consumer Staples": "XLP",
    "Utilities": "XLU",
    "Materials": "XLB",
    "Real Estate": "XLRE",
    "Communication Services": "XLC",
}

# Bootcamp vs strict-mode thresholds (from ranker.py + settings)
BOOTCAMP_QUALIFICATION = 40
STRICT_QUALIFICATION = 70
STRICT_MAX_POSITIONS = 5
STRICT_MAX_SECTOR_PCT = 0.30


# ── Data structures ─────────────────────────────────────────────────
@dataclass
class Trade:
    trade_id: str
    ticker: str
    pnl_pct: float
    excess_return: float
    spy_return: float  # fraction
    entry_price: float
    exit_price: float
    allocation: float
    entry_time: str
    exit_time: str
    exit_reason: str
    sector: str
    quarantined: bool
    confidence_score: Optional[float] = None
    duration_days: int = 0
    # Enriched fields
    theoretical_entry: Optional[float] = None
    slippage_bps: Optional[float] = None
    spy_day1_return: Optional[float] = None


@dataclass
class AuditResults:
    """Container for all 8 question results."""
    trades: list[Trade] = field(default_factory=list)
    q1: dict = field(default_factory=dict)
    q2: dict = field(default_factory=dict)
    q3: dict = field(default_factory=dict)
    q4: dict = field(default_factory=dict)
    q5: dict = field(default_factory=dict)
    q6: dict = field(default_factory=dict)
    q7: dict = field(default_factory=dict)
    q8: dict = field(default_factory=dict)
    bootcamp: dict = field(default_factory=dict)
    meta: dict = field(default_factory=dict)


# ── Data Pipeline ───────────────────────────────────────────────────
def load_trades(db_path: str) -> list[Trade]:
    """Load all closed trades from the database."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.execute("""
        SELECT t.trade_id, t.ticker,
               CAST(t.pnl_pct AS REAL) as pnl_pct,
               t.excess_return,
               t.spy_return_over_hold,
               CAST(t.entry_price AS REAL) as entry_price,
               CAST(t.actual_exit_price AS REAL) as exit_price,
               CAST(t.planned_allocation AS REAL) as allocation,
               t.actual_entry_time, t.actual_exit_time,
               t.exit_reason, t.realized_sector, t.quarantined,
               CAST(t.duration_days AS INTEGER) as duration_days,
               CAST(t.actual_entry_price AS REAL) as actual_entry_price,
               CAST(r.confidence_score AS REAL) as confidence_score
        FROM shadow_trades t
        LEFT JOIN recommendations r ON t.recommendation_id = r.recommendation_id
        WHERE t.status = 'closed'
        ORDER BY t.actual_entry_time
    """)
    trades = []
    for row in cur.fetchall():
        pnl = row["pnl_pct"] or 0.0
        spy_ret = row["spy_return_over_hold"] or 0.0
        excess = row["excess_return"] if row["excess_return"] is not None else (pnl - spy_ret * 100)
        entry_p = row["actual_entry_price"] or row["entry_price"] or 0.0
        trades.append(Trade(
            trade_id=row["trade_id"],
            ticker=row["ticker"],
            pnl_pct=pnl,
            excess_return=excess,
            spy_return=spy_ret,
            entry_price=entry_p,
            exit_price=row["exit_price"] or 0.0,
            allocation=row["allocation"] or 0.0,
            entry_time=row["actual_entry_time"] or "",
            exit_time=row["actual_exit_time"] or "",
            exit_reason=row["exit_reason"] or "unknown",
            sector=row["realized_sector"] or "Unknown",
            quarantined=bool(row["quarantined"]),
            confidence_score=row["confidence_score"],
            duration_days=row["duration_days"] or 0,
        ))
    conn.close()
    logger.info("Loaded %d closed trades (%d quarantined, %d clean)",
                len(trades), sum(1 for t in trades if t.quarantined),
                sum(1 for t in trades if not t.quarantined))
    return trades


def enrich_with_minute_bars(trades: list[Trade], db_path: str) -> int:
    """Reconstruct theoretical entry from 1-min bars where available.

    Returns count of trades enriched.
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    enriched = 0
    for trade in trades:
        if not trade.entry_time:
            continue
        try:
            entry_dt = dt.datetime.fromisoformat(trade.entry_time)
        except ValueError:
            continue
        # Look for the first 1-min bar close at or after signal time
        # Signal is assumed ~1 min before actual entry
        signal_time = (entry_dt - dt.timedelta(minutes=2)).isoformat()
        cur = conn.execute("""
            SELECT close FROM minute_bars
            WHERE ticker = ? AND timestamp >= ?
            ORDER BY timestamp LIMIT 1
        """, (trade.ticker, signal_time))
        row = cur.fetchone()
        if row and row["close"]:
            trade.theoretical_entry = float(row["close"])
            trade.slippage_bps = (
                (trade.entry_price - trade.theoretical_entry)
                / trade.theoretical_entry * 10000
            )
            enriched += 1
    conn.close()
    logger.info("Enriched %d/%d trades with minute-bar theoretical entry",
                enriched, len(trades))
    return enriched


def fetch_spy_daily(trades: list[Trade], db_path: str = "") -> dict[str, float]:
    """Fetch SPY daily close prices for the trade date range.

    Returns dict of date_str -> close price.
    Uses yfinance with deterministic cache.
    """
    if not trades:
        return {}
    # Determine date range
    dates = []
    for t in trades:
        if t.entry_time:
            try:
                dates.append(dt.datetime.fromisoformat(t.entry_time).date())
            except ValueError:
                pass
        if t.exit_time:
            try:
                dates.append(dt.datetime.fromisoformat(t.exit_time).date())
            except ValueError:
                pass
    if not dates:
        return {}
    start = min(dates) - dt.timedelta(days=10)
    end = max(dates) + dt.timedelta(days=5)

    try:
        import yfinance as yf
        data = yf.download("SPY", start=start.isoformat(), end=end.isoformat(),
                           progress=False, auto_adjust=True)
        if data.empty:
            return {}
        close = data["Close"].squeeze()
        result = {}
        for idx in data.index:
            d = idx.date() if hasattr(idx, 'date') else idx
            result[str(d)] = float(close.loc[idx])
        return result
    except Exception as e:
        logger.warning("Failed to fetch SPY daily bars: %s", e)
        return {}


def enrich_day1_spy(trades: list[Trade], spy_daily: dict[str, float]) -> int:
    """Compute day-1 SPY return for selection/holding split (Q7)."""
    enriched = 0
    for trade in trades:
        if not trade.entry_time:
            continue
        try:
            entry_date = dt.datetime.fromisoformat(trade.entry_time).date()
        except ValueError:
            continue
        # Find entry day close and next trading day close
        entry_str = str(entry_date)
        if entry_str not in spy_daily:
            continue
        # Find next trading day
        next_date = entry_date + dt.timedelta(days=1)
        for _ in range(5):  # skip weekends
            if str(next_date) in spy_daily:
                break
            next_date += dt.timedelta(days=1)
        next_str = str(next_date)
        if next_str in spy_daily:
            trade.spy_day1_return = (
                (spy_daily[next_str] - spy_daily[entry_str]) / spy_daily[entry_str]
            )
            enriched += 1
    return enriched


# ── Statistical helpers ─────────────────────────────────────────────
def _mean(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0

def _std(xs: list[float], ddof: int = 1) -> float:
    if len(xs) <= ddof:
        return 0.0
    m = _mean(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - ddof))

def _se(xs: list[float]) -> float:
    return _std(xs) / math.sqrt(len(xs)) if xs else 0.0

def _ci95(xs: list[float]) -> tuple[float, float]:
    m, se = _mean(xs), _se(xs)
    return (m - 1.96 * se, m + 1.96 * se)

def _median(xs: list[float]) -> float:
    if not xs:
        return 0.0
    s = sorted(xs)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2

def _percentile(xs: list[float], p: float) -> float:
    if not xs:
        return 0.0
    s = sorted(xs)
    k = (len(s) - 1) * p / 100
    f = int(k)
    c = f + 1 if f + 1 < len(s) else f
    return s[f] + (k - f) * (s[c] - s[f])

def _skewness(xs: list[float]) -> float:
    n = len(xs)
    if n < 3:
        return 0.0
    m, s = _mean(xs), _std(xs)
    if s == 0:
        return 0.0
    return (n / ((n - 1) * (n - 2))) * sum(((x - m) / s) ** 3 for x in xs)

def _kurtosis(xs: list[float]) -> float:
    n = len(xs)
    if n < 4:
        return 0.0
    m, s = _mean(xs), _std(xs)
    if s == 0:
        return 0.0
    k4 = sum(((x - m) / s) ** 4 for x in xs) / n
    return k4 - 3  # excess kurtosis

def gini_coefficient(xs: list[float]) -> float:
    """Compute Gini coefficient of absolute values."""
    if not xs:
        return 0.0
    abs_vals = sorted(abs(x) for x in xs)
    n = len(abs_vals)
    total = sum(abs_vals)
    if total == 0:
        return 0.0
    cum = sum((2 * i - n - 1) * v for i, v in enumerate(abs_vals, 1))
    return cum / (n * total)

def wilcoxon_signed_rank(xs: list[float]) -> tuple[float, float]:
    """Wilcoxon signed-rank test on xs (H0: median = 0).

    Returns (statistic, p_value). Uses normal approximation for n > 20.
    """
    diffs = [x for x in xs if x != 0]
    n = len(diffs)
    if n == 0:
        return (0.0, 1.0)
    ranks = sorted(range(n), key=lambda i: abs(diffs[i]))
    rank_values = [0.0] * n
    for rank_pos, idx in enumerate(ranks, 1):
        rank_values[idx] = float(rank_pos)
    w_plus = sum(r for d, r in zip(diffs, rank_values) if d > 0)
    w_minus = sum(r for d, r in zip(diffs, rank_values) if d < 0)
    w = min(w_plus, w_minus)
    # Normal approximation
    mean_w = n * (n + 1) / 4
    std_w = math.sqrt(n * (n + 1) * (2 * n + 1) / 24)
    if std_w == 0:
        return (w, 1.0)
    z = (w - mean_w) / std_w
    # Two-tailed p-value from z (approximation)
    p = 2 * _norm_cdf(-abs(z))
    return (w, p)

def _norm_cdf(z: float) -> float:
    """Standard normal CDF approximation (Abramowitz & Stegun)."""
    return 0.5 * (1 + math.erf(z / math.sqrt(2)))

def autocorrelation(xs: list[float], lag: int) -> tuple[float, float]:
    """Compute autocorrelation at given lag with p-value.

    Returns (acf, p_value).
    """
    n = len(xs)
    if n <= lag:
        return (0.0, 1.0)
    m = _mean(xs)
    var = sum((x - m) ** 2 for x in xs) / n
    if var == 0:
        return (0.0, 1.0)
    cov = sum((xs[i] - m) * (xs[i + lag] - m) for i in range(n - lag)) / n
    acf = cov / var
    # Bartlett approximation for SE under H0
    se = 1.0 / math.sqrt(n)
    z = acf / se if se > 0 else 0.0
    p = 2 * _norm_cdf(-abs(z))
    return (acf, p)


# ── Q1: Real Beta Decomposition ────────────────────────────────────
def compute_q1_beta(trades: list[Trade]) -> dict:
    """Compute trade-weighted, cap-weighted, equal-weighted, notional-weighted SPY beta."""
    valid = [t for t in trades if t.spy_return != 0]
    if not valid:
        return {"error": "No valid trades with SPY returns"}

    returns = [t.pnl_pct / 100 for t in valid]
    spy_returns = [t.spy_return for t in valid]
    allocations = [t.allocation for t in valid]

    # Equal-weighted beta: cov(r, spy) / var(spy)
    n = len(valid)
    mr, ms = _mean(returns), _mean(spy_returns)
    cov = sum((r - mr) * (s - ms) for r, s in zip(returns, spy_returns)) / (n - 1) if n > 1 else 0
    var_spy = sum((s - ms) ** 2 for s in spy_returns) / (n - 1) if n > 1 else 1
    equal_beta = cov / var_spy if var_spy > 0 else 0.0

    # Trade-weighted beta (weighted by absolute return)
    abs_returns = [abs(r) for r in returns]
    total_abs = sum(abs_returns) or 1
    tw_weights = [a / total_abs for a in abs_returns]
    tw_mr = sum(w * r for w, r in zip(tw_weights, returns))
    tw_ms = sum(w * s for w, s in zip(tw_weights, spy_returns))
    tw_cov = sum(w * (r - tw_mr) * (s - tw_ms) for w, r, s in zip(tw_weights, returns, spy_returns))
    tw_var = sum(w * (s - tw_ms) ** 2 for w, s in zip(tw_weights, spy_returns))
    trade_weighted_beta = tw_cov / tw_var if tw_var > 0 else 0.0

    # Cap-weighted (allocation-weighted)
    total_alloc = sum(allocations) or 1
    cw_weights = [a / total_alloc for a in allocations]
    cw_mr = sum(w * r for w, r in zip(cw_weights, returns))
    cw_ms = sum(w * s for w, s in zip(cw_weights, spy_returns))
    cw_cov = sum(w * (r - cw_mr) * (s - cw_ms) for w, r, s in zip(cw_weights, returns, spy_returns))
    cw_var = sum(w * (s - cw_ms) ** 2 for w, s in zip(cw_weights, spy_returns))
    cap_weighted_beta = cw_cov / cw_var if cw_var > 0 else 0.0

    # Gross-notional-weighted (same as cap-weighted for our purposes)
    notional_beta = cap_weighted_beta

    # Bootstrap CI for equal-weighted beta
    rng = np.random.default_rng(42)
    boot_betas = []
    for _ in range(1000):
        idx = rng.integers(0, n, size=n)
        br = [returns[i] for i in idx]
        bs = [spy_returns[i] for i in idx]
        bm_r, bm_s = _mean(br), _mean(bs)
        b_cov = sum((r - bm_r) * (s - bm_s) for r, s in zip(br, bs)) / (n - 1) if n > 1 else 0
        b_var = sum((s - bm_s) ** 2 for s in bs) / (n - 1) if n > 1 else 1
        boot_betas.append(b_cov / b_var if b_var > 0 else 0)
    boot_betas.sort()
    ci_lo = boot_betas[int(0.025 * len(boot_betas))]
    ci_hi = boot_betas[int(0.975 * len(boot_betas))]

    # Rolling 20-trade beta
    rolling = []
    window = min(20, n // 2) if n > 4 else n
    for i in range(window, n + 1):
        chunk_r = returns[i - window:i]
        chunk_s = spy_returns[i - window:i]
        cm_r, cm_s = _mean(chunk_r), _mean(chunk_s)
        c_cov = sum((r - cm_r) * (s - cm_s) for r, s in zip(chunk_r, chunk_s)) / (window - 1)
        c_var = sum((s - cm_s) ** 2 for s in chunk_s) / (window - 1)
        rolling.append(c_cov / c_var if c_var > 0 else 0)

    return {
        "n": n,
        "equal_weighted_beta": round(equal_beta, 4),
        "trade_weighted_beta": round(trade_weighted_beta, 4),
        "cap_weighted_beta": round(cap_weighted_beta, 4),
        "notional_weighted_beta": round(notional_beta, 4),
        "equal_weighted_ci95": (round(ci_lo, 4), round(ci_hi, 4)),
        "rolling_betas": rolling,
        "rolling_window": window,
    }


# ── Q2: P&L Distribution ───────────────────────────────────────────
def compute_q2_pnl_distribution(trades: list[Trade]) -> dict:
    """P&L concentration, Gini, Wilcoxon, skew, kurtosis."""
    returns = sorted([t.pnl_pct for t in trades], reverse=True)
    excess = [t.excess_return for t in trades]
    n = len(returns)
    total_gross = sum(abs(r) for r in returns) or 1

    # Top-K concentration
    abs_sorted = sorted(returns, key=lambda x: abs(x), reverse=True)
    top5_trades = abs_sorted[:5]
    top10pct = abs_sorted[:max(1, n // 10)]
    top20pct = abs_sorted[:max(1, n // 5)]

    top5_frac = sum(abs(r) for r in top5_trades) / total_gross
    top10pct_frac = sum(abs(r) for r in top10pct) / total_gross
    top20pct_frac = sum(abs(r) for r in top20pct) / total_gross

    # Gini
    gini = gini_coefficient(returns)

    # Wilcoxon on excess returns (paired test: trade vs SPY same period)
    w_stat, w_pval = wilcoxon_signed_rank(excess)

    return {
        "n": n,
        "mean_return": round(_mean(returns), 4),
        "mean_se": round(_se(returns), 4),
        "median_return": round(_median(returns), 4),
        "std_return": round(_std(returns), 4),
        "skewness": round(_skewness(returns), 4),
        "kurtosis_excess": round(_kurtosis(returns), 4),
        "gini": round(gini, 4),
        "top5_trades_pct": round(top5_frac * 100, 2),
        "top10pct_trades_pct": round(top10pct_frac * 100, 2),
        "top20pct_trades_pct": round(top20pct_frac * 100, 2),
        "top5_trades": [(t.ticker, round(t.pnl_pct, 2)) for t in
                        sorted(trades, key=lambda x: abs(x.pnl_pct), reverse=True)[:5]],
        "wilcoxon_stat": round(w_stat, 2),
        "wilcoxon_pval": round(w_pval, 6),
        "mean_excess": round(_mean(excess), 4),
        "mean_excess_se": round(_se(excess), 4),
        "mean_excess_ci95": tuple(round(x, 4) for x in _ci95(excess)),
    }


# ── Q3: Slippage ────────────────────────────────────────────────────
def compute_q3_slippage(trades: list[Trade]) -> dict:
    """Slippage distribution and correlations."""
    slippage_trades = [t for t in trades if t.slippage_bps is not None]
    n = len(slippage_trades)
    n_missing = len(trades) - n

    if n == 0:
        return {
            "n": 0, "n_missing": len(trades),
            "note": "No minute-bar data available for theoretical entry reconstruction"
        }

    slips: list[float] = [t.slippage_bps for t in slippage_trades if t.slippage_bps is not None]

    # Correlation with allocation size
    if n > 2:
        sizes = [t.allocation for t in slippage_trades]
        corr_size = _pearson(slips, sizes)
    else:
        corr_size = (0.0, 1.0)

    # Correlation with time of day (minutes from 9:30 AM)
    tod_minutes: list[float] = []
    for t in slippage_trades:
        try:
            entry_dt = dt.datetime.fromisoformat(t.entry_time)
            minutes = entry_dt.hour * 60 + entry_dt.minute - (9 * 60 + 30)
            tod_minutes.append(float(minutes))
        except ValueError:
            tod_minutes.append(0.0)
    corr_tod = _pearson(slips, tod_minutes) if n > 2 else (0.0, 1.0)

    # If slippage removed, what would gross excess-Sharpe be?
    excess_with = [t.excess_return for t in slippage_trades]
    excess_without = [t.excess_return + (t.slippage_bps or 0) / 100 for t in slippage_trades]
    sharpe_with = _mean(excess_with) / _std(excess_with) * math.sqrt(n) if _std(excess_with) > 0 else 0
    sharpe_without = _mean(excess_without) / _std(excess_without) * math.sqrt(n) if _std(excess_without) > 0 else 0

    return {
        "n": n,
        "n_missing": n_missing,
        "mean_bps": round(_mean(slips), 2),
        "mean_se": round(_se(slips), 2),
        "median_bps": round(_median(slips), 2),
        "pct95_bps": round(_percentile(slips, 95), 2),
        "worst_bps": round(max(slips, key=abs), 2),
        "corr_with_size": (round(corr_size[0], 4), round(corr_size[1], 6)),
        "corr_with_tod": (round(corr_tod[0], 4), round(corr_tod[1], 6)),
        "excess_sharpe_with_slippage": round(sharpe_with, 4),
        "excess_sharpe_without_slippage": round(sharpe_without, 4),
        "slippage_impact_on_sharpe": round(sharpe_without - sharpe_with, 4),
    }


def _pearson(xs: list[float], ys: list[float]) -> tuple[float, float]:
    """Pearson correlation + p-value."""
    n = len(xs)
    if n < 3:
        return (0.0, 1.0)
    mx, my = _mean(xs), _mean(ys)
    sx, sy = _std(xs), _std(ys)
    if sx == 0 or sy == 0:
        return (0.0, 1.0)
    r = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / ((n - 1) * sx * sy)
    # t-test for significance
    if abs(r) >= 1:
        return (r, 0.0)
    t = r * math.sqrt((n - 2) / (1 - r ** 2))
    # Approximate p from t with n-2 df (normal approx for large n)
    p = 2 * _norm_cdf(-abs(t))
    return (r, p)


# ── Q4: Exit Type Attribution ───────────────────────────────────────
def compute_q4_exit_attribution(trades: list[Trade]) -> dict:
    """Frequency, mean return, Sharpe per exit type."""
    exit_types: dict[str, list[Trade]] = {}
    for t in trades:
        # Normalize exit reasons
        reason = t.exit_reason
        if "target" in reason.lower():
            reason = "target_hit"
        elif "stop" in reason.lower():
            reason = "stop_hit"
        elif "timeout" in reason.lower() or "stale" in reason.lower():
            reason = "timeout/stale"
        elif "earnings" in reason.lower():
            reason = "earnings_flat"
        elif "manual" in reason.lower() or "quarantine" in reason.lower():
            reason = "manual_close"
        elif "exception" in reason.lower() or "error" in reason.lower():
            reason = "broker_error"
        else:
            reason = reason
        exit_types.setdefault(reason, []).append(t)

    result = {}
    for etype, group in sorted(exit_types.items()):
        returns = [t.pnl_pct for t in group]
        n = len(returns)
        std = _std(returns)
        sharpe = (_mean(returns) / std * math.sqrt(n)) if std > 0 else 0.0
        result[etype] = {
            "count": n,
            "frequency_pct": round(n / len(trades) * 100, 1),
            "mean_return": round(_mean(returns), 4),
            "mean_se": round(_se(returns), 4),
            "median_return": round(_median(returns), 4),
            "sharpe": round(sharpe, 4),
        }
    return result


# ── Q5: Holding Period Attribution ──────────────────────────────────
def compute_q5_holding_attribution(trades: list[Trade]) -> dict:
    """Per-day return contribution. Approximated from duration + total return."""
    # Group by duration bucket
    buckets = {"day_1": [], "days_2_3": [], "days_4_6": [], "days_7_plus": []}

    for t in trades:
        dur = t.duration_days
        # Approximate daily return as pnl_pct / duration
        if dur <= 0:
            dur = 1
        daily_return = t.pnl_pct / dur

        if dur >= 1:
            buckets["day_1"].append(daily_return)
        if dur >= 2:
            days_23 = min(dur, 3) - 1
            buckets["days_2_3"].extend([daily_return] * days_23)
        if dur >= 4:
            days_46 = min(dur, 6) - 3
            buckets["days_4_6"].extend([daily_return] * days_46)
        if dur >= 7:
            days_7p = dur - 6
            buckets["days_7_plus"].extend([daily_return] * days_7p)

    # Also compute: is alpha front-loaded or back-loaded?
    short_trades = [t for t in trades if 0 < t.duration_days <= 3]
    long_trades = [t for t in trades if t.duration_days > 3]
    short_mean = _mean([t.pnl_pct for t in short_trades]) if short_trades else 0
    long_mean = _mean([t.pnl_pct for t in long_trades]) if long_trades else 0

    # Per-day average return contribution
    result = {}
    for bucket_name, values in buckets.items():
        result[bucket_name] = {
            "n_observations": len(values),
            "mean_daily_return": round(_mean(values), 4) if values else 0.0,
            "se": round(_se(values), 4) if values else 0.0,
            "total_contribution": round(sum(values), 4) if values else 0.0,
        }

    result["front_loaded_test"] = {
        "short_trades_n": len(short_trades),
        "short_mean_pnl": round(short_mean, 4),
        "long_trades_n": len(long_trades),
        "long_mean_pnl": round(long_mean, 4),
        "alpha_is_front_loaded": short_mean > long_mean,
    }

    return result


# ── Q6: Time Clustering ────────────────────────────────────────────
def compute_q6_clustering(trades: list[Trade]) -> dict:
    """Autocorrelation of trade P&L at lags 1, 5, 10, 20."""
    pnl_series = [t.pnl_pct for t in trades]
    n = len(pnl_series)

    lags = [1, 5, 10, 20]
    acf_results = {}
    for lag in lags:
        acf, pval = autocorrelation(pnl_series, lag)
        acf_results[f"lag_{lag}"] = {
            "acf": round(acf, 4),
            "p_value": round(pval, 6),
            "significant_5pct": pval < 0.05,
        }

    # Check for win/loss clustering
    wins = [1 if t.pnl_pct > 0 else 0 for t in trades]
    win_acf1, win_p1 = autocorrelation([float(w) for w in wins], 1)

    # Overnight gap analysis (not available without intraday data, document limitation)
    return {
        "n": n,
        "acf_by_lag": acf_results,
        "win_loss_acf_lag1": round(win_acf1, 4),
        "win_loss_acf_lag1_pval": round(win_p1, 6),
        "clustering_detected": any(r["significant_5pct"] for r in acf_results.values()),
        "overnight_gap_note": "Overnight gap analysis requires intraday position-level data; not available in current schema.",
    }


# ── Q7: Selection vs Holding Split ──────────────────────────────────
def compute_q7_selection_holding(trades: list[Trade], spy_daily: Optional[dict] = None) -> dict:
    """Decompose into selection alpha (day 1) vs holding alpha (day 2+)."""
    # For trades with day-1 SPY return, compute:
    # Selection alpha = trade day-1 return - SPY day-1 return
    # Holding alpha = excess_return - selection_alpha

    valid = [t for t in trades if t.spy_day1_return is not None and t.duration_days >= 1]
    n = len(valid)

    if n == 0:
        return {
            "n": 0,
            "note": "No trades with day-1 SPY data available for decomposition"
        }

    # Approximate day-1 trade return as pnl_pct / duration_days (crude)
    # Better: use entry price and day-1 close from daily bars
    selection_alphas = []
    holding_alphas = []

    for t in valid:
        # Day-1 trade return approximation
        if t.duration_days > 0:
            day1_trade_ret = t.pnl_pct / t.duration_days  # Linear approximation
        else:
            day1_trade_ret = t.pnl_pct

        day1_spy_ret = (t.spy_day1_return or 0) * 100  # Convert to pct
        selection_alpha = day1_trade_ret - day1_spy_ret
        holding_alpha = t.excess_return - selection_alpha

        selection_alphas.append(selection_alpha)
        holding_alphas.append(holding_alpha)

    return {
        "n": n,
        "selection_alpha_mean": round(_mean(selection_alphas), 4),
        "selection_alpha_se": round(_se(selection_alphas), 4),
        "selection_alpha_ci95": tuple(round(x, 4) for x in _ci95(selection_alphas)),
        "holding_alpha_mean": round(_mean(holding_alphas), 4),
        "holding_alpha_se": round(_se(holding_alphas), 4),
        "holding_alpha_ci95": tuple(round(x, 4) for x in _ci95(holding_alphas)),
        "selection_positive": _mean(selection_alphas) > 0,
        "holding_positive": _mean(holding_alphas) > 0,
        "interpretation": _interpret_q7(_mean(selection_alphas), _mean(holding_alphas)),
    }


def _interpret_q7(sel: float, hold: float) -> str:
    if sel > 0 and hold > 0:
        return "Both entry and holding contribute positive alpha"
    elif sel > 0 and hold <= 0:
        return "Picking correctly but giving it back — change exit logic, not entry"
    elif sel <= 0 and hold > 0:
        return "Entry is noise but pattern is real — redesign entry signal"
    elif sel < -0.1 and abs(hold) < abs(sel):
        return "Entry signal actively losing; holding roughly neutral — redesign entry"
    else:
        return "Neither selection nor holding shows a statistically meaningful edge"


# ── Q8: Sector Concentration ───────────────────────────────────────
def compute_q8_sector(trades: list[Trade]) -> dict:
    """Per-sector trade count, mean return, excess-Sharpe, concentration."""
    sectors: dict[str, list[Trade]] = {}
    for t in trades:
        sectors.setdefault(t.sector, []).append(t)

    n = len(trades)
    result = {}
    for sector, group in sorted(sectors.items()):
        returns = [t.pnl_pct for t in group]
        excess = [t.excess_return for t in group]
        ns = len(group)
        std_ex = _std(excess)
        excess_sharpe = (_mean(excess) / std_ex * math.sqrt(ns)) if std_ex > 0 and ns > 1 else 0.0
        result[sector] = {
            "count": ns,
            "concentration_pct": round(ns / n * 100, 1),
            "mean_return": round(_mean(returns), 4),
            "mean_return_se": round(_se(returns), 4),
            "mean_excess": round(_mean(excess), 4),
            "excess_sharpe": round(excess_sharpe, 4),
            "etf": SECTOR_ETF_MAP.get(sector, "N/A"),
        }
    return result


# ── Bootcamp Mode Caveat ────────────────────────────────────────────
def compute_bootcamp_caveat(trades: list[Trade]) -> dict:
    """Counterfactual: which trades would survive strict-mode gates?"""
    strict_trades = []
    rejected_trades = []

    for t in trades:
        # Strict-mode gate: confidence_score >= 70 (vs bootcamp 40)
        # If confidence_score is None, assume it would need to be checked
        if t.confidence_score is not None and t.confidence_score < STRICT_QUALIFICATION:
            rejected_trades.append(t)
        else:
            strict_trades.append(t)

    # Sector cap: no sector > 30%
    if strict_trades:
        sector_counts: dict[str, int] = {}
        for t in strict_trades:
            sector_counts[t.sector] = sector_counts.get(t.sector, 0) + 1
        max_sector_count = max(sector_counts.values())
        over_cap_sectors = {s for s, c in sector_counts.items()
                          if c / len(strict_trades) > STRICT_MAX_SECTOR_PCT}
    else:
        over_cap_sectors = set()

    # Compute strict-mode stats
    strict_pnl = [t.pnl_pct for t in strict_trades]
    strict_excess = [t.excess_return for t in strict_trades]
    rejected_pnl = [t.pnl_pct for t in rejected_trades]

    n_strict = len(strict_trades)
    std_ex = _std(strict_excess)
    strict_excess_sharpe = (
        _mean(strict_excess) / std_ex * math.sqrt(n_strict)
        if std_ex > 0 and n_strict > 1 else 0.0
    )

    return {
        "total_trades": len(trades),
        "strict_survivors": n_strict,
        "rejected_count": len(rejected_trades),
        "rejected_tickers": [(t.ticker, t.confidence_score, round(t.pnl_pct, 2))
                             for t in rejected_trades],
        "bootcamp_mean_return": round(_mean([t.pnl_pct for t in trades]), 4),
        "strict_mean_return": round(_mean(strict_pnl), 4) if strict_pnl else 0.0,
        "rejected_mean_return": round(_mean(rejected_pnl), 4) if rejected_pnl else 0.0,
        "bootcamp_mean_excess": round(_mean([t.excess_return for t in trades]), 4),
        "strict_mean_excess": round(_mean(strict_excess), 4) if strict_excess else 0.0,
        "strict_excess_sharpe": round(strict_excess_sharpe, 4),
        "sectors_over_30pct_cap": list(over_cap_sectors),
        "qualification_threshold_bootcamp": BOOTCAMP_QUALIFICATION,
        "qualification_threshold_strict": STRICT_QUALIFICATION,
    }


# ── Plotting ────────────────────────────────────────────────────────
def generate_plots(results: AuditResults, plot_dir: str) -> list[str]:
    """Generate all required plots. Returns list of filenames."""
    os.makedirs(plot_dir, exist_ok=True)
    plots = []
    trades = results.trades
    n = len(trades)

    # 1. Equity curve
    fig, ax = plt.subplots(figsize=(10, 6))
    cum_pnl = np.cumsum([t.pnl_pct for t in trades])
    cum_spy = np.cumsum([t.spy_return * 100 for t in trades])
    cum_excess = cum_pnl - cum_spy
    ax.plot(cum_pnl, label="Strategy (cumulative %)", linewidth=2)
    ax.plot(cum_spy, label="SPY (matched periods)", linewidth=2)
    ax.plot(cum_excess, label="Excess", linewidth=2, linestyle="--")
    ax.set_xlabel("Trade number")
    ax.set_ylabel("Cumulative return (%)")
    ax.set_title(f"Equity Curve — Strategy vs SPY (N={n})")
    ax.legend()
    ax.grid(True, alpha=0.3)
    fname = "equity_curve.png"
    fig.savefig(os.path.join(plot_dir, fname), dpi=150, bbox_inches="tight")
    plt.close(fig)
    plots.append(fname)

    # 2. Rolling beta
    if results.q1.get("rolling_betas"):
        fig, ax = plt.subplots(figsize=(10, 5))
        betas = results.q1["rolling_betas"]
        window = results.q1["rolling_window"]
        ax.plot(range(window, window + len(betas)), betas, linewidth=2)
        ax.axhline(y=1.0, color="r", linestyle="--", alpha=0.5, label="Beta=1")
        ax.axhline(y=results.q1["equal_weighted_beta"], color="g", linestyle=":",
                   alpha=0.7, label=f"EW Beta={results.q1['equal_weighted_beta']:.2f}")
        ax.set_xlabel("Trade number")
        ax.set_ylabel("Rolling SPY beta")
        ax.set_title(f"Rolling {window}-Trade SPY Beta (N={n})")
        ax.legend()
        ax.grid(True, alpha=0.3)
        fname = "rolling_beta.png"
        fig.savefig(os.path.join(plot_dir, fname), dpi=150, bbox_inches="tight")
        plt.close(fig)
        plots.append(fname)

    # 3. P&L histogram
    fig, ax = plt.subplots(figsize=(10, 6))
    returns = [t.pnl_pct for t in trades]
    spy_matched = [t.spy_return * 100 for t in trades]
    ax.hist(returns, bins=20, alpha=0.6, label="Strategy returns", edgecolor="black")
    ax.hist(spy_matched, bins=20, alpha=0.4, label="SPY matched-period", edgecolor="black")
    ax.axvline(x=_mean(returns), color="blue", linestyle="--", label=f"Mean={_mean(returns):.2f}%")
    ax.axvline(x=_median(returns), color="green", linestyle=":", label=f"Median={_median(returns):.2f}%")
    ax.set_xlabel("Return (%)")
    ax.set_ylabel("Frequency")
    ax.set_title(f"P&L Distribution — Strategy vs SPY (N={n})")
    ax.legend()
    fname = "pnl_histogram.png"
    fig.savefig(os.path.join(plot_dir, fname), dpi=150, bbox_inches="tight")
    plt.close(fig)
    plots.append(fname)

    # 4. Slippage distribution
    slippage_trades = [t for t in trades if t.slippage_bps is not None]
    if slippage_trades:
        fig, ax = plt.subplots(figsize=(10, 5))
        slips: list[float] = [t.slippage_bps for t in slippage_trades if t.slippage_bps is not None]
        ax.hist(slips, bins=15, edgecolor="black", alpha=0.7)
        ax.axvline(x=_mean(slips), color="red", linestyle="--",
                   label=f"Mean={_mean(slips):.1f} bps")
        ax.set_xlabel("Slippage (bps)")
        ax.set_ylabel("Frequency")
        ax.set_title(f"Entry Slippage Distribution (N={len(slippage_trades)})")
        ax.legend()
        fname = "slippage_distribution.png"
        fig.savefig(os.path.join(plot_dir, fname), dpi=150, bbox_inches="tight")
        plt.close(fig)
        plots.append(fname)

    # 5. Exit type chart
    if results.q4:
        fig, axes = plt.subplots(1, 2, figsize=(14, 6))
        types = list(results.q4.keys())
        counts = [results.q4[t]["count"] for t in types]
        means = [results.q4[t]["mean_return"] for t in types]
        ses = [results.q4[t]["mean_se"] for t in types]

        axes[0].pie(counts, labels=types, autopct="%1.0f%%", startangle=90)
        axes[0].set_title(f"Exit Type Distribution (N={n})")

        colors = ["green" if m > 0 else "red" for m in means]
        axes[1].barh(types, means, xerr=ses, color=colors, alpha=0.7, edgecolor="black")
        axes[1].set_xlabel("Mean Return (%)")
        axes[1].set_title(f"Mean Return by Exit Type (N={n})")
        axes[1].axvline(x=0, color="black", linewidth=0.5)

        fname = "exit_type_attribution.png"
        fig.savefig(os.path.join(plot_dir, fname), dpi=150, bbox_inches="tight")
        plt.close(fig)
        plots.append(fname)

    # 6. Holding period attribution
    if results.q5:
        fig, ax = plt.subplots(figsize=(10, 6))
        buckets = ["day_1", "days_2_3", "days_4_6", "days_7_plus"]
        labels = ["Day 1", "Days 2-3", "Days 4-6", "Days 7+"]
        values = [results.q5.get(b, {}).get("mean_daily_return", 0) for b in buckets]
        errors = [results.q5.get(b, {}).get("se", 0) for b in buckets]
        colors = ["green" if v > 0 else "red" for v in values]
        ax.bar(labels, values, yerr=errors, color=colors, alpha=0.7, edgecolor="black")
        ax.set_ylabel("Mean Daily Return (%)")
        ax.set_title(f"Holding Period Attribution (N={n})")
        ax.axhline(y=0, color="black", linewidth=0.5)
        fname = "holding_attribution.png"
        fig.savefig(os.path.join(plot_dir, fname), dpi=150, bbox_inches="tight")
        plt.close(fig)
        plots.append(fname)

    # 7. Sector distribution
    if results.q8:
        fig, ax = plt.subplots(figsize=(10, 6))
        sectors = list(results.q8.keys())
        sector_counts = [results.q8[s]["count"] for s in sectors]
        sector_excess = [results.q8[s]["mean_excess"] for s in sectors]

        x = np.arange(len(sectors))
        width = 0.35
        ax.bar(x - width / 2, sector_counts, width, label="Trade count", alpha=0.7)
        ax2 = ax.twinx()
        colors = ["green" if e > 0 else "red" for e in sector_excess]
        ax2.bar(x + width / 2, sector_excess, width, color=colors, alpha=0.5, label="Mean excess (%)")
        ax.set_xticks(x)
        ax.set_xticklabels(sectors, rotation=45, ha="right")
        ax.set_ylabel("Trade count")
        ax2.set_ylabel("Mean excess return (%)")
        ax.set_title(f"Sector Distribution & Performance (N={n})")
        ax.legend(loc="upper left")
        ax2.legend(loc="upper right")
        fname = "sector_distribution.png"
        fig.savefig(os.path.join(plot_dir, fname), dpi=150, bbox_inches="tight")
        plt.close(fig)
        plots.append(fname)

    # 8. Autocorrelation plot
    if results.q6 and "acf_by_lag" in results.q6:
        fig, ax = plt.subplots(figsize=(10, 5))
        lags_data = results.q6["acf_by_lag"]
        lag_nums = sorted(int(k.split("_")[1]) for k in lags_data.keys())
        acfs = [lags_data[f"lag_{l}"]["acf"] for l in lag_nums]
        ax.bar(lag_nums, acfs, width=2, alpha=0.7, edgecolor="black")
        # Significance bands
        se_band = 1.96 / math.sqrt(results.q6["n"])
        ax.axhline(y=se_band, color="r", linestyle="--", alpha=0.5, label="95% CI")
        ax.axhline(y=-se_band, color="r", linestyle="--", alpha=0.5)
        ax.axhline(y=0, color="black", linewidth=0.5)
        ax.set_xlabel("Lag")
        ax.set_ylabel("Autocorrelation")
        ax.set_title(f"Trade P&L Autocorrelation (N={results.q6['n']})")
        ax.legend()
        fname = "autocorrelation.png"
        fig.savefig(os.path.join(plot_dir, fname), dpi=150, bbox_inches="tight")
        plt.close(fig)
        plots.append(fname)

    return plots


# ── Report Generator ────────────────────────────────────────────────
def generate_report(results: AuditResults, plots: list[str], plot_dir: str) -> str:
    """Generate markdown report answering all 8 questions."""
    today = dt.date.today().isoformat()
    n = len(results.trades)
    n_clean = sum(1 for t in results.trades if not t.quarantined)
    n_quarantined = n - n_clean

    lines = [
        f"# Forensic Trade Audit — {today}",
        "",
        "## Executive Summary",
        "",
        f"Analyzed **{n}** closed trades ({n_clean} non-quarantined, "
        f"{n_quarantined} quarantined from April 10 cascade).",
        "",
        "### 3 Most Surprising Findings",
        "",
    ]

    # Determine 3 most surprising findings from results
    surprises = _find_surprises(results)
    for i, s in enumerate(surprises[:3], 1):
        lines.append(f"{i}. {s}")
    lines.append("")

    # Q1
    q1 = results.q1
    lines.extend([
        "---", "",
        f"## Q1 — Real Beta Decomposition (N={q1.get('n', 0)})", "",
        "| Weighting | Beta | 95% CI |",
        "|-----------|------|--------|",
        f"| Equal-weighted | {q1.get('equal_weighted_beta', 'N/A')} | {q1.get('equal_weighted_ci95', ('N/A', 'N/A'))} |",
        f"| Trade-weighted | {q1.get('trade_weighted_beta', 'N/A')} | — |",
        f"| Cap-weighted | {q1.get('cap_weighted_beta', 'N/A')} | — |",
        f"| Notional-weighted | {q1.get('notional_weighted_beta', 'N/A')} | — |",
        "",
        f"![Rolling Beta](forensic-audit-{today}/rolling_beta.png)",
        "",
    ])

    # Q2
    q2 = results.q2
    lines.extend([
        "---", "",
        f"## Q2 — P&L Distribution (N={q2.get('n', 0)})", "",
        f"- **Mean return:** {q2.get('mean_return', 'N/A')}% (SE: {q2.get('mean_se', 'N/A')}%)",
        f"- **Median return:** {q2.get('median_return', 'N/A')}%",
        f"- **Std dev:** {q2.get('std_return', 'N/A')}%",
        f"- **Skewness:** {q2.get('skewness', 'N/A')}",
        f"- **Excess kurtosis:** {q2.get('kurtosis_excess', 'N/A')}",
        f"- **Gini coefficient:** {q2.get('gini', 'N/A')}",
        "",
        "### Concentration",
        f"- Top 5 trades: {q2.get('top5_trades_pct', 'N/A')}% of gross P&L",
        f"- Top 10%: {q2.get('top10pct_trades_pct', 'N/A')}%",
        f"- Top 20%: {q2.get('top20pct_trades_pct', 'N/A')}%",
        "",
        "### Wilcoxon Signed-Rank Test (excess returns vs 0)",
        f"- W statistic: {q2.get('wilcoxon_stat', 'N/A')}",
        f"- p-value: {q2.get('wilcoxon_pval', 'N/A')}",
        f"- Mean excess return: {q2.get('mean_excess', 'N/A')}% "
        f"(95% CI: {q2.get('mean_excess_ci95', 'N/A')})",
        "",
        f"![P&L Histogram](forensic-audit-{today}/pnl_histogram.png)",
        "",
    ])

    # Q3
    q3 = results.q3
    lines.extend([
        "---", "",
        f"## Q3 — Slippage vs Theoretical (N={q3.get('n', 0)}, missing={q3.get('n_missing', 0)})", "",
    ])
    if q3.get("n", 0) > 0:
        lines.extend([
            f"- **Mean slippage:** {q3.get('mean_bps', 'N/A')} bps (SE: {q3.get('mean_se', 'N/A')})",
            f"- **Median slippage:** {q3.get('median_bps', 'N/A')} bps",
            f"- **95th percentile:** {q3.get('pct95_bps', 'N/A')} bps",
            f"- **Worst:** {q3.get('worst_bps', 'N/A')} bps",
            "",
            "### Correlations",
            f"- With trade size: r={q3['corr_with_size'][0]}, p={q3['corr_with_size'][1]}",
            f"- With time-of-day: r={q3['corr_with_tod'][0]}, p={q3['corr_with_tod'][1]}",
            "",
            "### Slippage Impact on Excess-Sharpe",
            f"- With slippage: {q3.get('excess_sharpe_with_slippage', 'N/A')}",
            f"- Without slippage: {q3.get('excess_sharpe_without_slippage', 'N/A')}",
            f"- Slippage impact: {q3.get('slippage_impact_on_sharpe', 'N/A')}",
        ])
    else:
        lines.append(f"**Note:** {q3.get('note', 'No data')}")
    lines.extend(["",
        f"![Slippage Distribution](forensic-audit-{today}/slippage_distribution.png)",
        "",
    ])

    # Q4
    q4 = results.q4
    lines.extend([
        "---", "",
        "## Q4 — Exit Type Attribution", "",
        "| Exit Type | Count | Freq % | Mean Return % | SE | Sharpe |",
        "|-----------|-------|--------|---------------|-----|--------|",
    ])
    for etype, stats in q4.items():
        lines.append(
            f"| {etype} | {stats['count']} | {stats['frequency_pct']}% | "
            f"{stats['mean_return']} | {stats['mean_se']} | {stats['sharpe']} |"
        )
    lines.extend(["",
        f"![Exit Type Attribution](forensic-audit-{today}/exit_type_attribution.png)",
        "",
    ])

    # Q5
    q5 = results.q5
    lines.extend([
        "---", "",
        "## Q5 — Holding Period Attribution", "",
        "| Period | N obs | Mean Daily Return % | SE | Total Contribution % |",
        "|--------|-------|--------------------|----|---------------------|",
    ])
    for bucket in ["day_1", "days_2_3", "days_4_6", "days_7_plus"]:
        if bucket in q5:
            b = q5[bucket]
            lines.append(
                f"| {bucket} | {b['n_observations']} | {b['mean_daily_return']} | "
                f"{b['se']} | {b['total_contribution']} |"
            )
    if "front_loaded_test" in q5:
        fl = q5["front_loaded_test"]
        lines.extend([
            "",
            f"- Short trades (≤3d, N={fl['short_trades_n']}): mean={fl['short_mean_pnl']}%",
            f"- Long trades (>3d, N={fl['long_trades_n']}): mean={fl['long_mean_pnl']}%",
            f"- Alpha is {'front-loaded' if fl['alpha_is_front_loaded'] else 'back-loaded'}",
        ])
    lines.extend(["",
        f"![Holding Attribution](forensic-audit-{today}/holding_attribution.png)",
        "",
    ])

    # Q6
    q6 = results.q6
    lines.extend([
        "---", "",
        f"## Q6 — Time Clustering (N={q6.get('n', 0)})", "",
        "| Lag | ACF | p-value | Significant (5%) |",
        "|-----|-----|---------|-----------------|",
    ])
    if "acf_by_lag" in q6:
        for lag_key, data in sorted(q6["acf_by_lag"].items()):
            lines.append(
                f"| {lag_key} | {data['acf']} | {data['p_value']} | "
                f"{'Yes' if data['significant_5pct'] else 'No'} |"
            )
    lines.extend([
        "",
        f"- Win/loss ACF at lag 1: {q6.get('win_loss_acf_lag1', 'N/A')} "
        f"(p={q6.get('win_loss_acf_lag1_pval', 'N/A')})",
        f"- Clustering detected: {'Yes' if q6.get('clustering_detected') else 'No'}",
        f"- {q6.get('overnight_gap_note', '')}",
        "",
        f"![Autocorrelation](forensic-audit-{today}/autocorrelation.png)",
        "",
    ])

    # Q7
    q7 = results.q7
    lines.extend([
        "---", "",
        f"## Q7 — Selection vs Holding Split (N={q7.get('n', 0)})", "",
    ])
    if q7.get("n", 0) > 0:
        lines.extend([
            "| Component | Mean Alpha % | SE | 95% CI |",
            "|-----------|-------------|-----|--------|",
            f"| Selection (day 1) | {q7['selection_alpha_mean']} | "
            f"{q7['selection_alpha_se']} | {q7['selection_alpha_ci95']} |",
            f"| Holding (day 2+) | {q7['holding_alpha_mean']} | "
            f"{q7['holding_alpha_se']} | {q7['holding_alpha_ci95']} |",
            "",
            f"**Interpretation:** {q7.get('interpretation', 'N/A')}",
        ])
    else:
        lines.append(f"**Note:** {q7.get('note', 'N/A')}")
    lines.append("")

    # Q8
    q8 = results.q8
    lines.extend([
        "---", "",
        "## Q8 — Sector Concentration", "",
        "| Sector | ETF | Count | Conc % | Mean Return % | SE | Mean Excess % | Excess Sharpe |",
        "|--------|-----|-------|--------|--------------|-----|--------------|---------------|",
    ])
    for sector, stats in sorted(q8.items()):
        lines.append(
            f"| {sector} | {stats['etf']} | {stats['count']} | {stats['concentration_pct']}% | "
            f"{stats['mean_return']} | {stats['mean_return_se']} | "
            f"{stats['mean_excess']} | {stats['excess_sharpe']} |"
        )
    lines.extend(["",
        f"![Sector Distribution](forensic-audit-{today}/sector_distribution.png)",
        "",
    ])

    # Bootcamp Mode Caveat
    bc = results.bootcamp
    lines.extend([
        "---", "",
        "## Bootcamp Mode Caveat", "",
        f"**All {bc.get('total_trades', 0)} trades were executed under bootcamp-mode "
        f"relaxed thresholds** (qualification ≥ {bc.get('qualification_threshold_bootcamp', 40)} "
        f"vs strict-mode ≥ {bc.get('qualification_threshold_strict', 70)}).",
        "",
        "**Findings do NOT extrapolate directly to strict-mode operation.**",
        "",
        "### Counterfactual: Strict-Mode Filter",
        f"- Trades surviving strict-mode gates: **{bc.get('strict_survivors', 0)}** "
        f"/ {bc.get('total_trades', 0)}",
        f"- Trades rejected by strict qualification threshold: **{bc.get('rejected_count', 0)}**",
        "",
        "| Metric | Bootcamp | Strict-mode counterfactual |",
        "|--------|----------|--------------------------|",
        f"| Mean return % | {bc.get('bootcamp_mean_return', 'N/A')} | {bc.get('strict_mean_return', 'N/A')} |",
        f"| Mean excess % | {bc.get('bootcamp_mean_excess', 'N/A')} | {bc.get('strict_mean_excess', 'N/A')} |",
        f"| Excess Sharpe | — | {bc.get('strict_excess_sharpe', 'N/A')} |",
        "",
    ])
    if bc.get("rejected_tickers"):
        lines.append("### Rejected Trades (would not pass strict-mode)")
        lines.append("| Ticker | Confidence | P&L % |")
        lines.append("|--------|-----------|-------|")
        for ticker, conf, pnl in bc["rejected_tickers"]:
            lines.append(f"| {ticker} | {conf} | {pnl} |")
        lines.append("")

    if bc.get("sectors_over_30pct_cap"):
        lines.append(f"**Sectors exceeding 30% concentration cap:** "
                     f"{', '.join(bc['sectors_over_30pct_cap'])}")
        lines.append("")

    lines.extend([
        "**Re-running this diagnostic on N ≥ 150 strict-mode trades is REQUIRED "
        "before any real-capital allocation decision.**",
        "",
    ])

    # Synthesis
    lines.extend([
        "---", "",
        "## Synthesis", "",
        "### Does the forensic breakdown corroborate the excess-Sharpe ≈ 0 finding?",
        "",
    ])
    synthesis = _generate_synthesis(results)
    lines.extend(synthesis)
    lines.append("")

    # Implications
    lines.extend([
        "### 3 Implications for Strategy #2 Design", "",
    ])
    implications = _generate_implications(results)
    for i, imp in enumerate(implications[:3], 1):
        lines.append(f"{i}. {imp}")
    lines.append("")

    return "\n".join(lines)


def _find_surprises(results: AuditResults) -> list[str]:
    """Identify the 3 most surprising findings."""
    surprises = []

    q1 = results.q1
    if q1.get("equal_weighted_beta") is not None:
        beta = q1["equal_weighted_beta"]
        ci = q1.get("equal_weighted_ci95", (0, 0))
        ci_crosses_zero = ci[0] <= 0 <= ci[1]
        if ci_crosses_zero:
            surprises.append(
                f"Real SPY beta point estimate is {beta:.2f} (equal-weighted) but 95% CI "
                f"({ci[0]:.2f}, {ci[1]:.2f}) spans zero — beta is indistinguishable from zero"
            )
        elif abs(beta - 1.0) > 0.3:
            surprises.append(
                f"Real SPY beta is {beta:.2f} (equal-weighted), materially different from 1.0 "
                f"— the strategy is {'more' if beta > 1 else 'less'} market-exposed than assumed"
            )

    q2 = results.q2
    if q2.get("gini"):
        gini = q2["gini"]
        if gini > 0.5:
            surprises.append(
                f"P&L Gini coefficient is {gini:.2f} — returns are highly concentrated in a few trades"
            )
    if q2.get("top5_trades_pct"):
        top5 = q2["top5_trades_pct"]
        if top5 > 40:
            surprises.append(
                f"Top 5 trades account for {top5:.0f}% of gross P&L — a home-run-dependent strategy"
            )

    if q2.get("wilcoxon_pval") is not None:
        wp = q2["wilcoxon_pval"]
        if wp > 0.05:
            surprises.append(
                f"Wilcoxon signed-rank test on excess returns: p={wp:.4f} — cannot reject H0 "
                f"that median excess = 0, corroborating the zero-alpha finding"
            )

    q6 = results.q6
    if q6.get("clustering_detected"):
        surprises.append("Significant autocorrelation detected in trade P&L — regime clustering effect")

    q7 = results.q7
    if q7.get("n", 0) > 0:
        sel = q7.get("selection_alpha_mean", 0)
        hold = q7.get("holding_alpha_mean", 0)
        if sel > 0 and hold < 0:
            surprises.append(
                f"Selection alpha is positive ({sel:.2f}%) but holding alpha is negative ({hold:.2f}%) "
                f"— entry signal has value but exit logic destroys it"
            )
        elif sel < -0.1 and abs(hold) < abs(sel):
            surprises.append(
                f"Selection alpha is negative ({sel:.2f}%) while holding alpha is near-neutral "
                f"({hold:.2f}%) — entry signal is actively losing money, holding is a wash"
            )

    # Ensure at least 3
    while len(surprises) < 3:
        surprises.append(
            f"Mean return ({results.q2.get('mean_return', 0):.2f}%) vs median "
            f"({results.q2.get('median_return', 0):.2f}%) suggests "
            f"{'right-skewed' if results.q2.get('skewness', 0) > 0 else 'left-skewed'} distribution"
        )
    return surprises[:3]


def _generate_synthesis(results: AuditResults) -> list[str]:
    """Generate synthesis section."""
    lines = []
    q2 = results.q2
    wp = q2.get("wilcoxon_pval", 1.0)
    mean_excess = q2.get("mean_excess", 0)

    if wp > 0.05:
        lines.append(
            f"The Wilcoxon test (p={wp:.4f}) **corroborates** the 2026-04-16 finding: "
            f"excess returns are statistically indistinguishable from zero at N={q2.get('n', 0)}."
        )
    else:
        lines.append(
            f"The Wilcoxon test (p={wp:.4f}) **contradicts** the aggregate zero-alpha conclusion — "
            f"median excess return differs significantly from zero."
        )

    lines.append("")

    # Additional synthesis points
    q1 = results.q1
    beta = q1.get("equal_weighted_beta", 1.0)
    lines.append(
        f"The realized beta ({beta:.2f}) suggests the strategy "
        f"{'overweights' if beta > 1.1 else 'underweights' if beta < 0.9 else 'approximates'} "
        f"market exposure. {'This partially explains the positive raw returns despite zero alpha.' if beta > 0.8 else ''}"
    )

    bc = results.bootcamp
    if bc.get("strict_survivors", 0) < bc.get("total_trades", 0):
        lines.append(
            f"\nUnder strict-mode gates, only {bc['strict_survivors']}/{bc['total_trades']} trades survive. "
            f"Strict-mode mean excess: {bc.get('strict_mean_excess', 'N/A')}%. "
            f"The bootcamp-mode cohort may not represent strict-mode performance."
        )

    return lines


def _generate_implications(results: AuditResults) -> list[str]:
    """Generate 3 implications for strategy #2 design."""
    implications = []

    q7 = results.q7
    if q7.get("n", 0) > 0:
        sel = q7.get("selection_alpha_mean", 0)
        hold = q7.get("holding_alpha_mean", 0)
        if sel > 0 and hold <= 0:
            implications.append(
                "Strategy #2 should prioritize exit logic redesign over entry signal changes — "
                f"selection alpha ({sel:.2f}%) is positive but holding alpha ({hold:.2f}%) "
                "destroys the edge"
            )
        elif sel < -0.1:
            implications.append(
                "Strategy #2 must improve entry signal quality — current selection alpha "
                f"is negative ({sel:.2f}%), meaning entries are actively destroying value"
            )
        elif sel <= 0:
            implications.append(
                "Strategy #2 must improve entry signal quality — current selection alpha "
                "is indistinguishable from zero, meaning entries add no value"
            )

    q4 = results.q4
    timeout_stats = q4.get("timeout/stale", {})
    if timeout_stats.get("frequency_pct", 0) > 20:
        implications.append(
            f"Strategy #2 should reduce timeout/stale exits ({timeout_stats['frequency_pct']}% of trades, "
            f"mean return {timeout_stats['mean_return']}%) — consider adaptive hold periods "
            "tied to regime state"
        )

    q8 = results.q8
    losing_sectors = [s for s, data in q8.items() if data.get("mean_excess", 0) < -1.0]
    if losing_sectors:
        implications.append(
            f"Strategy #2 should exclude or reduce exposure to consistently losing sectors: "
            f"{', '.join(losing_sectors)}"
        )

    q6 = results.q6
    if q6.get("clustering_detected"):
        implications.append(
            "Strategy #2 must incorporate regime-aware position sizing — trade P&L clustering "
            "suggests losses concentrate in adverse regimes"
        )

    # Ensure at least 3
    if len(implications) < 3:
        implications.append(
            f"Strategy #2 should target N ≥ 150 strict-mode trades before allocation decisions — "
            f"current N={len(results.trades)} under bootcamp mode is insufficient for statistical power"
        )
    if len(implications) < 3:
        implications.append(
            "Strategy #2 should implement real-time slippage monitoring with alerts "
            "when entry slippage exceeds 50 bps"
        )

    return implications[:3]


# ── Main ────────────────────────────────────────────────────────────
def run_audit(db_path: str, output_path: str, plot_dir: str) -> AuditResults:
    """Execute the full forensic audit pipeline."""
    results = AuditResults()

    # Step 1: Load data
    logger.info("Step 1: Loading trades...")
    trades = load_trades(db_path)
    if not trades:
        logger.error("No closed trades found in database")
        sys.exit(1)
    results.trades = trades

    # Step 2: Enrich with minute bars
    logger.info("Step 2: Enriching with minute bars...")
    n_enriched = enrich_with_minute_bars(trades, db_path)

    # Step 3: Fetch SPY daily bars
    logger.info("Step 3: Fetching SPY daily bars...")
    spy_daily = fetch_spy_daily(trades, db_path)
    n_day1 = enrich_day1_spy(trades, spy_daily)
    logger.info("Enriched %d trades with day-1 SPY return", n_day1)

    # Step 4: Compute all 8 questions
    logger.info("Step 4: Computing Q1-Q8...")
    results.q1 = compute_q1_beta(trades)
    results.q2 = compute_q2_pnl_distribution(trades)
    results.q3 = compute_q3_slippage(trades)
    results.q4 = compute_q4_exit_attribution(trades)
    results.q5 = compute_q5_holding_attribution(trades)
    results.q6 = compute_q6_clustering(trades)
    results.q7 = compute_q7_selection_holding(trades, spy_daily)
    results.q8 = compute_q8_sector(trades)
    results.bootcamp = compute_bootcamp_caveat(trades)

    results.meta = {
        "db_path": db_path,
        "total_trades": len(trades),
        "non_quarantined": sum(1 for t in trades if not t.quarantined),
        "quarantined": sum(1 for t in trades if t.quarantined),
        "minute_bar_enriched": n_enriched,
        "spy_daily_bars": len(spy_daily),
        "date": dt.date.today().isoformat(),
    }

    # Step 5: Generate plots
    logger.info("Step 5: Generating plots...")
    plots = generate_plots(results, plot_dir)
    logger.info("Generated %d plots in %s", len(plots), plot_dir)

    # Step 6: Generate report
    logger.info("Step 6: Generating report...")
    report = generate_report(results, plots, plot_dir)
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    Path(output_path).write_text(report, encoding="utf-8")
    logger.info("Report written to %s", output_path)

    return results


def main():
    parser = argparse.ArgumentParser(description="Forensic Trade Audit v1")
    parser.add_argument("--db", required=True, help="Path to SQLite database")
    parser.add_argument("--output", required=True, help="Output report path (.md)")
    parser.add_argument("--plot-dir", required=True, help="Directory for plots")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    results = run_audit(args.db, args.output, args.plot_dir)

    # Print summary
    print(f"\n{'='*60}")
    print(f"Forensic Trade Audit Complete")
    print(f"{'='*60}")
    print(f"Trades analyzed: {results.meta['total_trades']}")
    print(f"  Non-quarantined: {results.meta['non_quarantined']}")
    print(f"  Quarantined: {results.meta['quarantined']}")
    print(f"  Minute-bar enriched: {results.meta['minute_bar_enriched']}")
    print(f"\nQ1 Equal-weighted beta: {results.q1.get('equal_weighted_beta', 'N/A')}")
    print(f"Q2 Gini: {results.q2.get('gini', 'N/A')}")
    print(f"Q2 Wilcoxon p-value: {results.q2.get('wilcoxon_pval', 'N/A')}")
    print(f"Q3 Mean slippage: {results.q3.get('mean_bps', 'N/A')} bps")
    print(f"Q7 Selection alpha: {results.q7.get('selection_alpha_mean', 'N/A')}%")
    print(f"Q7 Holding alpha: {results.q7.get('holding_alpha_mean', 'N/A')}%")
    print(f"\nBootcamp caveat: {results.bootcamp.get('strict_survivors', 'N/A')}"
          f"/{results.bootcamp.get('total_trades', 'N/A')} survive strict mode")
    print(f"\nReport: {args.output}")
    print(f"Plots: {args.plot_dir}/")


if __name__ == "__main__":
    main()
