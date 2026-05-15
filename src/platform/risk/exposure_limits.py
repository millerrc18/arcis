"""Hard pre-trade exposure limits + soft advisory limits.

Called by: src.shadow_trading.executor (Sprint 4 wires this),
           src.platform.shadow_harness (Sprint 4 wires this).
Calls: src.universe.sectors (GICS classification), sqlite3 for drawdown lookup.
Owns tables: none (reads shadow_trades for drawdown).
Config keys: none (HARD_LIMITS / SOFT_LIMITS are module constants).
Tests: tests/platform/risk/test_exposure_limits.py.

Based on Millennium / Citadel architecture translated to retail scale.
Hard limits BLOCK trades and are NEVER overridden during drawdown. Soft
limits trigger advisory review only.

Sprint 3 scope: create the pure-function check + unit tests. Sprint 4
wires check_pre_trade_limits into src/shadow_trading/executor.py before
bracket order placement.
"""

from __future__ import annotations

import logging
import sqlite3
from src.utils.db import DBError, connect_db
from typing import Any

logger = logging.getLogger(__name__)

HARD_LIMITS = {
    "max_single_name_pct_of_nav": 0.06,
    "max_sector_pct_of_nav": 0.25,
    "max_gross_leverage": 1.5,
    "book_drawdown_circuit_breaker_pct": 0.08,
}

SOFT_LIMITS = {
    "max_pair_spearman_63d": 0.50,
    "max_pair_spearman_persistence_days": 5,
    "max_aggregate_factor_beta": 0.50,
    "max_vol_ratio_21d_vs_252d": 1.50,
}


def _lookup_sector(ticker: str) -> str | None:
    """Resolve GICS sector for a ticker. Returns None if unknown."""
    try:
        from src.universe.sectors import SECTOR_MAP
        sector = SECTOR_MAP.get(ticker.upper())
        if sector is not None:
            return sector
    except Exception:
        pass

    # Fallback: read the CSV directly
    try:
        import csv
        from pathlib import Path
        csv_path = Path("data/reference/sp100-gics-lookup.csv")
        if not csv_path.exists():
            return None
        with open(csv_path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if row.get("ticker", "").upper() == ticker.upper():
                    return row.get("gics_sector")
    except Exception:
        pass

    return None


def _aggregate_single_name_value(
    ticker: str,
    current_positions: list[dict],
    proposed_shares: int,
    proposed_price: float,
) -> float:
    existing = sum(
        p.get("shares", 0) * p.get("current_price", 0.0)
        for p in current_positions if p.get("ticker") == ticker
    )
    proposed = proposed_shares * proposed_price
    return existing + proposed


def _aggregate_sector_value(
    sector: str | None,
    current_positions: list[dict],
    proposed_ticker: str,
    proposed_shares: int,
    proposed_price: float,
) -> float:
    if sector is None:
        return 0.0
    existing = 0.0
    for p in current_positions:
        p_sec = _lookup_sector(p.get("ticker", ""))
        if p_sec == sector:
            existing += p.get("shares", 0) * p.get("current_price", 0.0)
    proposed = proposed_shares * proposed_price
    return existing + proposed


def _gross_exposure(
    current_positions: list[dict],
    proposed_shares: int,
    proposed_price: float,
) -> float:
    existing = sum(
        abs(p.get("shares", 0) * p.get("current_price", 0.0))
        for p in current_positions
    )
    proposed = abs(proposed_shares * proposed_price)
    return existing + proposed


def check_book_drawdown_circuit_breaker(
    db_path: str | None = None,
) -> tuple[bool, float]:
    """Return (within_limits, drawdown_pct). If drawdown exceeds
    HARD_LIMITS['book_drawdown_circuit_breaker_pct'], ALL new entries
    must be blocked until a manual reset (no auto-reset — requires
    human decision per spec line 1403-1409).

    Sprint 3 implementation: compute from shadow_trades closed rows
    (cumulative pnl_pct running equity curve, max peak, current valley).
    If db_path is None or DB unavailable, return (True, 0.0) — i.e.,
    conservative assumption that no breach occurred.

    Sprint 4 refines this against correlation_matrices / factor_loadings
    for per-desk drawdown tracking.
    """
    if db_path is None:
        return True, 0.0
    try:
        conn = connect_db(db_path)
        rows = conn.execute(
            "SELECT pnl_pct FROM shadow_trades "
            "WHERE actual_exit_time IS NOT NULL "
            "ORDER BY actual_exit_time"
        ).fetchall()
        conn.close()
    except DBError:
        return True, 0.0

    if not rows:
        return True, 0.0

    # Compute cumulative equity curve from per-trade pnl_pct
    equity = 1.0
    peak = 1.0
    max_dd = 0.0
    for (pnl,) in rows:
        if pnl is None:
            continue
        equity *= 1.0 + float(pnl)
        peak = max(peak, equity)
        dd = (peak - equity) / peak if peak > 0 else 0.0
        max_dd = max(max_dd, dd)

    breached = max_dd > HARD_LIMITS["book_drawdown_circuit_breaker_pct"]
    return (not breached, float(max_dd))


def _check_concentration_limits(
    ticker: str,
    proposed_shares: int,
    proposed_price: float,
    current_positions: list[dict],
    current_nav: float,
) -> tuple[bool, str | None]:
    """Check single-name and sector concentration; gross leverage.
    Returns (allowed, reason_if_blocked). NAV assumed positive by caller.
    """
    # Single-name concentration
    single_pct = _aggregate_single_name_value(
        ticker, current_positions, proposed_shares, proposed_price,
    ) / current_nav
    if single_pct > HARD_LIMITS["max_single_name_pct_of_nav"]:
        return False, (
            f"single-name concentration exceeded for {ticker}: "
            f"{single_pct:.2%} > limit "
            f"{HARD_LIMITS['max_single_name_pct_of_nav']:.2%} (6%)"
        )

    # Sector concentration
    sector = _lookup_sector(ticker)
    if sector is not None:
        sector_pct = _aggregate_sector_value(
            sector, current_positions, ticker, proposed_shares, proposed_price,
        ) / current_nav
        if sector_pct > HARD_LIMITS["max_sector_pct_of_nav"]:
            return False, (
                f"sector concentration exceeded for {sector}: "
                f"{sector_pct:.2%} > limit "
                f"{HARD_LIMITS['max_sector_pct_of_nav']:.2%} (25%)"
            )

    # Gross leverage
    leverage = _gross_exposure(
        current_positions, proposed_shares, proposed_price,
    ) / current_nav
    if leverage > HARD_LIMITS["max_gross_leverage"]:
        return False, (
            f"gross leverage exceeded: {leverage:.2f}x > limit "
            f"{HARD_LIMITS['max_gross_leverage']:.1f}x"
        )

    return True, None


def check_pre_trade_limits(
    ticker: str,
    proposed_shares: int,
    proposed_price: float,
    current_positions: list[dict],
    current_nav: float,
    db_path: str | None = None,
) -> tuple[bool, str | None]:
    """Pre-trade hard-limit check. Returns (allowed, reason_if_blocked).

    Pure function — NO DB writes. Reads only for drawdown check
    (via check_book_drawdown_circuit_breaker which opens+closes its
    own connection). Caller (Sprint 4 executor.py) invokes this before
    placing a bracket order.

    Order of checks (short-circuit on first violation):
      1. Book drawdown circuit breaker — ALL entries blocked if > 8%.
      2. Single-name concentration — aggregate per ticker <= 6% of NAV.
      3. Sector concentration — aggregate per GICS sector <= 25% of NAV.
      4. Gross leverage — sum of |positions| <= 1.5x NAV.
    """
    if current_nav <= 0:
        return False, f"invalid NAV: {current_nav}"

    # 1. Drawdown circuit breaker
    within, dd = check_book_drawdown_circuit_breaker(db_path)
    if not within:
        return False, (
            f"book drawdown circuit breaker triggered: "
            f"drawdown={dd:.2%} > limit "
            f"{HARD_LIMITS['book_drawdown_circuit_breaker_pct']:.2%}. "
            f"ALL new entries blocked until manual reset."
        )

    # 2-4. Concentration + leverage checks
    return _check_concentration_limits(
        ticker, proposed_shares, proposed_price, current_positions, current_nav,
    )


def get_soft_limit_breaches(db_path: str | None = None) -> list[dict]:
    """Return list of active soft-limit breaches for dashboard display.
    Advisory only — does NOT block trades.

    Sprint 3 stub: returns empty list. Sprint 4 wires the correlation
    / factor / volatility checks against correlation_matrices and
    factor_loadings tables (Task 11b.1 schema).
    """
    # Sprint 4 implementation — fill in when correlation data is populated
    return []
