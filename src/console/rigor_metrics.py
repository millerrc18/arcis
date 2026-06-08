"""Rigor cohort metrics — Probability of Backtest Overfitting (PBO) plumbing.

Called by: src.api.cloud_routes.console_know (F4 — KNOW rigor panel).
Calls: src.methods.pbo.pbo (the CSCV math — wrapped, NEVER reimplemented),
       src.utils.db.connect_db (read-only).
Owns tables: none (pure read-only consumer).
Config keys: none.
Tests: tests/test_rigor_metrics.py.

Design law #1: this module does NOT reimplement the CSCV/PBO math — it builds
the (T, N) returns matrix that src.methods.pbo.pbo() requires and calls that
function verbatim. Design law #4: on insufficient data it degrades to an
explicit `insufficient_configs` state and NEVER fabricates a PBO.

────────────────────────────────────────────────────────────────────────────
DATA-SOURCE INVESTIGATION (F5) — is PBO computable today?
────────────────────────────────────────────────────────────────────────────
PBO via CSCV (Bailey, Borwein, López de Prado & Zhu 2014) is *meaningless on a
single configuration*. src.methods.pbo.pbo(returns, S) requires an
N-config (N >= 2) × T-period (T >= 8) returns matrix and an even S in [2, T].
A "config" is one distinct backtested strategy variant — in the schema a
distinct (backtest_results.strategy_id, spec_hash) pair, equivalently one
backtest_results.result_id, equivalently one group of backtest_trades rows
sharing a result_id.

Distinct-config count found in the DB on 2026-06-08 (queried via connect_db
against both the canonical SQLite store and the live PG store at :5433):

    backtest_results rows ............ 0
    distinct (strategy_id, spec_hash)  0
    backtest_trades rows ............. 0   (distinct result_id: 0)
    walkforward_trades rows .......... 0

There are therefore **0 distinct backtested configs in the DB today**, so PBO
is **NOT computable now** — build_pbo_envelope() honestly returns
state='insufficient_configs' (value=None, n=0). The plumbing is correct and
ready: the moment a parameter-sweep campaign persists >= 2 configs with >= 8
aligned trades each, the same code path produces a real PBO with state='ok'.

────────────────────────────────────────────────────────────────────────────
ALIGNMENT APPROACH
────────────────────────────────────────────────────────────────────────────
Each config's return series is the ordered sequence of its per-trade returns
(backtest_trades.pnl_pct, as a fraction), ordered by exit_date then trade_id
for determinism. Configs are aligned onto a common period index by
TRADE-SEQUENCE INDEX (row t = each config's t-th completed trade), truncated to
the common minimum trade count across configs, yielding a dense (T, N) matrix.

Trade-sequence alignment (not exit_date bucketing) is the honest choice here:
distinct configs trade different tickers on different calendar days, so an
exit_date-bucketed matrix would be almost entirely disjoint rows (one config
non-null per row) — which carries no cross-sectional ranking information and
which CSCV cannot consume. Trade-sequence alignment produces the dense float
matrix pbo() expects. The cost (documented, accepted): row t does not
correspond to a shared wall-clock instant across configs; PBO here measures
overfitting of the *ranking of configs by their trade-return streams*, which is
the quantity of interest for a config sweep.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import numpy as np

from src.methods.pbo import pbo
from src.utils.db import connect_db

_log = logging.getLogger(__name__)

# Mirror src.methods.pbo guards so we degrade BEFORE ever calling pbo().
_MIN_CONFIGS = 2
_MIN_PERIODS = 8

# Preferred CSCV partition count; clamped down to an even value <= n_periods.
_PREFERRED_S = 16


def _now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _largest_even_le(n: int) -> int:
    """Largest even integer <= n (n - (n % 2)). 0 if n < 2."""
    if n < 2:
        return 0
    return n - (n % 2)


def _load_config_series() -> dict[str, list[float]]:
    """Return {result_id: ordered per-trade returns (fraction)}. Read-only.

    One config per backtest_trades.result_id; its series is pnl_pct/100 in
    exit_date-then-trade_id order. Rows missing result_id or pnl_pct are
    skipped.
    """
    conn = connect_db()
    try:
        rows = conn.execute(
            "SELECT result_id, pnl_pct, exit_date, trade_id "
            "FROM backtest_trades "
            "ORDER BY result_id, exit_date, trade_id"
        ).fetchall()
    finally:
        conn.close()

    series: dict[str, list[float]] = {}
    for row in rows:
        result_id = row["result_id"]
        pnl_pct = row["pnl_pct"]
        if result_id is None or pnl_pct is None:
            continue
        series.setdefault(result_id, []).append(float(pnl_pct) / 100.0)
    return series


def build_config_returns_matrix() -> tuple[np.ndarray | None, dict]:
    """Load per-config return series and align them into a (T, N) matrix.

    Each distinct backtest_trades.result_id is one config (column). Its return
    series is the ordered pnl_pct (as a fraction) of its trades, ordered by
    exit_date then trade_id. Columns are aligned by trade-sequence index and
    truncated to the common minimum length.

    Returns:
        (matrix, meta) where matrix is a (T, N) float ndarray, or None when a
        usable matrix cannot be assembled (n_configs < 2 or n_periods < 8).
        meta is {n_configs, n_periods, reason}. Read-only via connect_db.
    """
    series = _load_config_series()

    n_configs = len(series)
    if n_configs < _MIN_CONFIGS:
        return None, {
            "n_configs": n_configs,
            "n_periods": 0,
            "reason": (
                f"need >= {_MIN_CONFIGS} backtested configs for CSCV; "
                f"found {n_configs}"
            ),
        }

    n_periods = min(len(v) for v in series.values())
    if n_periods < _MIN_PERIODS:
        return None, {
            "n_configs": n_configs,
            "n_periods": n_periods,
            "reason": (
                f"need >= {_MIN_PERIODS} aligned periods per config; "
                f"common minimum is {n_periods}"
            ),
        }

    # Deterministic column order; truncate each series to the common length.
    columns = [series[k][:n_periods] for k in sorted(series)]
    matrix = np.asarray(columns, dtype=float).T  # (n_periods, n_configs)
    return matrix, {
        "n_configs": n_configs,
        "n_periods": n_periods,
        "reason": "ok",
    }


def build_pbo_envelope() -> dict:
    """Canonical rigor envelope for PBO: degrade honestly or report state='ok'.

    Envelope keys: {value, n, as_of, cohort:'rigor', unit:'probability', state}.
    When no usable matrix exists (matrix is None, or no even S in [2, T] is
    available) the state is 'insufficient_configs' with value=None and
    n=n_configs — NEVER a fabricated PBO. Otherwise pbo() is called with an
    even S clamped to [2, n_periods] so its guards never raise, and value is
    the PBO rounded to 4 dp with state='ok'.
    """
    as_of = _now_utc_iso()
    matrix, meta = build_config_returns_matrix()
    n_configs = meta["n_configs"]

    base = {
        "value": None,
        "n": n_configs,
        "as_of": as_of,
        "cohort": "rigor",
        "unit": "probability",
    }

    if matrix is None:
        return {**base, "state": "insufficient_configs"}

    n_periods = meta["n_periods"]
    # Clamp S to an even integer in [2, n_periods]. n_periods >= 8 is already
    # guaranteed by build_config_returns_matrix, so a valid S always exists
    # here; the guard stays for defence-in-depth (NEVER let pbo() raise).
    s = min(_PREFERRED_S, _largest_even_le(n_periods))
    if s < 2:
        return {**base, "state": "insufficient_configs"}

    value = pbo(matrix, S=s)
    return {**base, "value": round(float(value), 4), "state": "ok"}
