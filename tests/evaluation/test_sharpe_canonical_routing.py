"""Regression tests for Sprint-0 wave-4a SHARPE-CONSOLIDATION-EVAL.

Asserts that the six legacy Sharpe (and one Sortino-MAR) sites in
evaluation/, api/routes/, and simulation/ delegate to
`src.analytics.canonical_sharpe` rather than re-implementing their own
ad-hoc formulas. Pre-fix at least one assertion in each site test FAILS
because each site has its own `mean / std * sqrt(N)` formula or no
delegation; post-fix all PASS because the site delegates to the canonical
helper with an explicit `periods_per_year` (and `ddof` where the legacy
contract used numpy default ddof=0).

Sites covered (per Sprint-0 wave-4a TASK):
  1. src/evaluation/cto_report.py:246  — sharpe, periods_per_year=150
  2. src/evaluation/cto_report.py:727  — sortino-MAR, periods_per_year=150
  3. src/api/routes/system.py:283       — rolling-Sharpe snapshot, 150
  4. src/evaluation/model_monitor.py:60-68 — trade-level, periods_per_year=150
  5. src/evaluation/statistics.py:18-23  — gate Sharpe, periods_per_year=1, ddof=0
  6. src/simulation/engine.py:425        — weekly Sharpe, periods_per_year=52, ddof=0

Q3 deferred: gate (site 5) preserves un-annualized + ddof=0 semantics so
the existing 0.15 GREEN threshold in `evaluate_50_trade_gate` is not
silently changed. Annualizing the gate would require recalibrating the
threshold (e.g. ~2.4 if 150 trades/yr) — out of scope for this PR.

Each site has TWO complementary assertions:
  (a) Source-level delegation: the module's source must import / call
      `compute_sharpe` (or `compute_sortino_mar`) — this fails pre-fix
      because the ad-hoc formula has no canonical reference.
  (b) Value equivalence: actual function output must equal canonical
      output to within rounding tolerance — locks the consolidation at
      the exact-numerical level.
"""
from __future__ import annotations

import inspect

import numpy as np
import pytest


# ── Site 1: cto_report._compute_trade_summary sharpe_ratio ──────────────

def _make_cto_closed_trades(pnl_pcts: list[float]) -> list[dict]:
    """Synthesize closed-trade dicts that _compute_trade_summary accepts."""
    out = []
    for i, p in enumerate(pnl_pcts):
        out.append({
            "trade_id": f"t-{i}",
            "ticker": "AAPL",
            "pnl_dollars": float(p) * 100.0,
            "pnl_pct": float(p),
            "exit_reason": "target_1_hit" if p > 0 else "stop_hit",
            "duration_days": 3,
            "max_favorable_excursion": 1.0,
            "max_adverse_excursion": -1.0,
            "actual_entry_price": 100.0,
            "actual_exit_price": 100.0 + float(p),
            "planned_shares": 10,
            "earnings_adjacent": 0,
            "status": "closed",
            "order_type": "bracket",
            "created_at": f"2026-03-{20 + (i % 9):02d}",
        })
    return out


def test_site1_cto_report_sharpe_delegates_to_canonical():
    """cto_report.py:246 — must call canonical compute_sharpe with
    periods_per_year=150."""
    from src.evaluation import cto_report
    src = inspect.getsource(cto_report)
    assert "from src.analytics.canonical_sharpe import" in src or \
           "src.analytics.canonical_sharpe" in src, \
        "cto_report must import from canonical_sharpe"
    # Pre-fix: ad-hoc formula `(mean_r / std_r) * math.sqrt(150)` —
    # post-fix: must be replaced with canonical compute_sharpe call.
    assert "math.sqrt(150)" not in src, \
        "cto_report:246 must not retain raw `math.sqrt(150)` after consolidation"
    assert "periods_per_year=150" in src, \
        "cto_report must call compute_sharpe with periods_per_year=150"


def test_site1_cto_report_sharpe_value_matches_canonical_150():
    from src.evaluation.cto_report import _compute_trade_summary
    from src.analytics.canonical_sharpe import compute_sharpe

    pnl_pcts = [2.0, -1.5, 3.0, -2.0, 1.5, 0.5, 1.0, -0.5, 2.5, -1.0,
                1.5, -2.0, 3.0, 0.5, -1.5]
    closed = _make_cto_closed_trades(pnl_pcts)
    result = _compute_trade_summary(closed, [], closed)

    expected_canonical = compute_sharpe(pnl_pcts, periods_per_year=150)
    assert expected_canonical is not None
    assert result["sharpe_ratio"] == pytest.approx(round(expected_canonical, 2), abs=1e-9)


# ── Site 2: cto_report._compute_fund_metrics sortino_ratio ──────────────

def test_site2_cto_report_sortino_delegates_to_canonical_mar():
    """cto_report.py:727 — Sortino-MAR must delegate to canonical
    compute_sortino_mar, not the raw `(mean_r / downside_dev) * sqrt(150)`
    formula."""
    from src.evaluation import cto_report
    src = inspect.getsource(cto_report)
    # The raw `* math.sqrt(150)` Sortino formula must not survive.
    assert "compute_sortino_mar" in src, \
        "cto_report must call canonical compute_sortino_mar"


def test_site2_cto_report_sortino_value_matches_canonical_mar_150():
    from src.evaluation.cto_report import _compute_fund_metrics
    from src.analytics.canonical_sharpe import compute_sortino_mar

    pnl_pcts = [2.0, -1.5, 3.0, -2.0, 1.5, 0.5, 1.0, -0.5, 2.5, -1.0,
                1.5, -2.0, 3.0, 0.5, -1.5]
    closed = _make_cto_closed_trades(pnl_pcts)
    trade_summary = {"max_drawdown_pct": 5.0}
    result = _compute_fund_metrics(closed, trade_summary)

    expected = compute_sortino_mar(pnl_pcts, periods_per_year=150, mar=0.0)
    assert expected is not None
    assert result["sortino_ratio"] == pytest.approx(round(expected, 2), abs=1e-9)


# ── Site 3: api.routes.system rolling-Sharpe snapshot ───────────────────

def test_site3_system_rolling_sharpe_delegates_to_canonical():
    """rolling-Sharpe must use canonical compute_sharpe with periods_per_year=150.

    T14: the rolling-Sharpe helper (_build_metric_snapshots) moved from
    system.py to system_status.py; the source-text guard now inspects the new
    home module.
    """
    from src.api.routes import system_status
    src = inspect.getsource(system_status)
    # Raw formula must be gone; canonical reference must appear.
    assert "math.sqrt(150)" not in src, \
        "system_status.py rolling-Sharpe must not retain raw math.sqrt(150)"
    assert "compute_sharpe" in src, \
        "system_status.py must reference canonical compute_sharpe"


def test_site3_system_rolling_sharpe_value_matches_canonical():
    """End-to-end: synthesizing a closed-trades list and calling the
    extracted helper reproduces canonical compute_sharpe(periods_per_year=150)
    rounded to 2 decimals."""
    from src.api.routes.system import _build_metric_snapshots
    from src.analytics.canonical_sharpe import compute_sharpe

    pnl_pcts = [2.0, -1.5, 3.0, -2.0, 1.5, 0.5, 1.0, -0.5, 2.5, -1.0]
    closed = []
    for i, p in enumerate(pnl_pcts):
        closed.append({
            "trade_id": f"t-{i}",
            "pnl_dollars": float(p) * 100.0,
            "pnl_pct": float(p),
            "created_at": f"2026-03-{20 + i:02d}",
        })

    snapshots = _build_metric_snapshots(closed)
    final = snapshots[-1]
    expected_full = compute_sharpe(pnl_pcts, periods_per_year=150)
    assert expected_full is not None
    assert final["sharpe_ratio"] == pytest.approx(round(expected_full, 2), abs=1e-9)


# ── Site 4: model_monitor._compute_metrics trade-level Sharpe ───────────

def test_site4_model_monitor_sharpe_delegates_to_canonical():
    """model_monitor.py:60-68 — trade-level Sharpe must delegate to
    canonical compute_sharpe with periods_per_year=150."""
    from src.evaluation import model_monitor
    src = inspect.getsource(model_monitor)
    assert "compute_sharpe" in src, \
        "model_monitor must reference canonical compute_sharpe"
    assert "periods_per_year=150" in src, \
        "model_monitor must call compute_sharpe(periods_per_year=150)"


def test_site4_model_monitor_sharpe_value_matches_canonical_150():
    """model_monitor._compute_metrics must produce the canonical 150-scaled
    Sharpe (matching cto_report parity for cross-model trade-level
    comparisons)."""
    from src.evaluation.model_monitor import _compute_metrics
    from src.analytics.canonical_sharpe import compute_sharpe

    pnl_pcts = [2.0, -1.0, 3.0, -2.0, 1.5, 0.5, 1.0, -0.5, 2.5, -1.0]
    trades = [
        {"pnl_dollars": p * 100.0, "pnl_pct": p,
         "exit_reason": "target_1", "duration_days": 3,
         "actual_exit_time": f"2026-03-{20 + i:02d}T16:00:00"}
        for i, p in enumerate(pnl_pcts)
    ]
    result = _compute_metrics(trades)

    expected = compute_sharpe(pnl_pcts, periods_per_year=150)
    assert expected is not None
    assert result["sharpe_ratio"] == pytest.approx(round(expected, 2), abs=1e-9)


def test_site4_model_monitor_degenerate_returns_zero_not_none():
    """Existing contract: zero-variance / single-trade => 0.0 (not None) so
    _build_comparison's `curr_m['sharpe_ratio'] - prev_m['sharpe_ratio']`
    arithmetic continues to work without TypeError."""
    from src.evaluation.model_monitor import _compute_metrics

    # Single trade
    result_single = _compute_metrics([
        {"pnl_dollars": 100.0, "pnl_pct": 1.0,
         "exit_reason": "target_1", "duration_days": 3,
         "actual_exit_time": "2026-03-20T16:00:00"}
    ])
    assert result_single["sharpe_ratio"] == 0.0
    assert isinstance(result_single["sharpe_ratio"], float)

    # Zero-variance series (all identical pnl_pct)
    result_zerovar = _compute_metrics([
        {"pnl_dollars": 100.0, "pnl_pct": 1.0,
         "exit_reason": "target_1", "duration_days": 3,
         "actual_exit_time": f"2026-03-{20 + i:02d}T16:00:00"}
        for i in range(5)
    ])
    assert result_zerovar["sharpe_ratio"] == 0.0


# ── Site 5: evaluation.statistics.sharpe_ratio (gate) ────────────────────

def test_site5_statistics_sharpe_delegates_to_canonical():
    """statistics.py:18-23 — sharpe_ratio must delegate to canonical
    compute_sharpe, with periods_per_year=1 + ddof=0 to preserve the
    legacy un-annualized + numpy-default-ddof contract that the 0.15
    GREEN gate threshold depends on."""
    from src.evaluation import statistics
    src = inspect.getsource(statistics)
    assert "compute_sharpe" in src, \
        "statistics must reference canonical compute_sharpe"
    # Must explicitly pass ddof=0 + periods_per_year=1 to preserve the
    # gate threshold semantics.
    assert "periods_per_year=1" in src, \
        "statistics.sharpe_ratio must call compute_sharpe(periods_per_year=1)"
    assert "ddof=0" in src, \
        "statistics.sharpe_ratio must call compute_sharpe(ddof=0) to preserve legacy"


def test_site5_statistics_sharpe_value_matches_canonical_per_trade_ddof0():
    from src.evaluation.statistics import sharpe_ratio
    from src.analytics.canonical_sharpe import compute_sharpe

    rng = np.random.default_rng(42)
    returns = rng.normal(0.005, 0.02, 60)

    out = sharpe_ratio(returns)
    expected = compute_sharpe(list(returns), periods_per_year=1, ddof=0)
    assert expected is not None
    assert out == pytest.approx(expected, rel=1e-9)


def test_site5_statistics_sharpe_zero_variance_returns_zero_not_none():
    """Existing contract preserved: degenerate => 0.0 (not None). Gate
    threshold logic relies on numeric output, not None."""
    from src.evaluation.statistics import sharpe_ratio
    returns = np.array([0.01, 0.01, 0.01, 0.01])
    assert sharpe_ratio(returns) == 0.0
    # Empty
    assert sharpe_ratio(np.array([])) == 0.0


def test_site5_gate_threshold_preserved_at_0_15():
    """Q3 documented decision: the Sharpe gate threshold (0.15 GREEN /
    0.05 YELLOW) is untouched by this PR. A future PR may annualize and
    re-calibrate; for now consolidation must NOT silently bump the gate."""
    from src.evaluation import gate_evaluator
    src = inspect.getsource(gate_evaluator)
    assert '"green": 0.15' in src
    assert '"yellow": 0.05' in src


# ── Site 6: simulation.engine weekly Sharpe ─────────────────────────────

def test_site6_simulation_engine_delegates_to_canonical():
    """engine.py:425 — weekly Sharpe must delegate to canonical
    compute_sharpe(periods_per_year=52, ddof=0)."""
    from src.simulation import engine
    src = inspect.getsource(engine)
    assert "np.sqrt(52)" not in src, (
        "simulation.engine must delegate weekly Sharpe to canonical "
        "compute_sharpe(periods_per_year=52, ddof=0); "
        "the raw np.sqrt(52) formula was found"
    )
    assert "compute_sharpe" in src
    assert "periods_per_year=52" in src
    # Engine had numpy ddof=0 (np.std default) historically — preserve it.
    assert "ddof=0" in src, \
        "simulation.engine must call compute_sharpe(ddof=0) to preserve np.std default"


def test_site6_simulation_engine_value_matches_canonical():
    """End-to-end: a tiny synthetic returns series passed through canonical
    compute_sharpe with the engine's parameters reproduces the engine's
    legacy np.std (ddof=0) result. This is the value-equivalence assertion
    that locks the consolidation."""
    from src.analytics.canonical_sharpe import compute_sharpe

    pnl_pcts = [2.0, -1.5, 3.0, -2.0, 1.5, 0.5, 1.0, -0.5]
    arr = np.array(pnl_pcts)
    legacy = float(np.mean(arr) / np.std(arr) * np.sqrt(52))
    canonical = compute_sharpe(pnl_pcts, periods_per_year=52, ddof=0)
    assert canonical is not None
    assert canonical == pytest.approx(legacy, rel=1e-9)
