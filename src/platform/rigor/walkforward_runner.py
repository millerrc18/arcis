"""Walk-forward validation main runner — orchestrates R1–R8.

Called by: scripts/backtest/run_walkforward.py, cloud_routes/walkforward.py.
Calls: src.platform.backtest_engine.run_backtest, src.platform.rigor.*.
Owns tables: walkforward_results, walkforward_trades (writes only).
Config keys: none.
Tests: tests/platform/rigor/test_walkforward_runner.py.

The runner is the orchestrator — it calls the specialized modules in
order and combines their outputs into a single persistent result. Any
refactoring of individual steps happens in the step modules; the runner
only wires and reduces.

Flow per run:
  1. R8(a) validate derived_from
  2. R8(b) assert no overlap with OOS windows
  3. R8(d) ensure bootcamp_override=False
  4. R8 heuristic (non-blocking WARNING)
  5. For each window:
     a. Call backtest engine for IS range
     b. Call backtest engine for OOS range (zero cost at engine level)
     c. Apply per-side cost uniformly (R4)
     d. Purge IS trades straddling OOS (R2)
     e. Embargo first N trading days of OOS (R2)
     f. Compute per-window metrics (R6)
     g. Evaluate power gate (R6)
  6. Pool OOS trades, compute pooled Sharpe + distinct VIX tiers (R6)
  7. Reduce to three-state outcome (R6 state machine)
  8. Persist to walkforward_results + walkforward_trades (R7)
"""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
from src.utils.db import connect_db, engine_aware_upsert
import subprocess
import uuid
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Any, Sequence

import numpy as np

from src.platform.rigor.walkforward_config import WalkForwardConfig, WalkForwardWindow
from src.platform.rigor.walkforward_costs import apply_per_side_cost_batch
from src.platform.rigor.walkforward_firewall import (
    Window as FirewallWindow,
    assert_no_overlap,
    check_provenance_heuristic,
    ensure_bootcamp_off,
    validate_derived_from,
)
from src.platform.rigor.walkforward_metrics import (
    WindowMetrics,
    compute_pooled_sharpe,
    compute_window_metrics,
    distinct_tier_count,
    vix_tier_of,
)
from src.platform.rigor.walkforward_outcome import (
    OutcomeResult,
    WINDOW_FAIL,
    WINDOW_PASS,
    reduce_outcome,
)
from src.platform.rigor.walkforward_power import (
    PowerResult,
    count_power_states,
    evaluate_window_power,
)
from src.platform.rigor.walkforward_purging import (
    embargo_oos_trades,
    purge_is_trades,
)

logger = logging.getLogger(__name__)


@dataclass
class WalkForwardRunResult:
    """Full in-memory result. Dashboard + promotion gate read this shape
    plus the persisted tables."""

    run_id: str
    strategy_id: str
    spec_hash: str
    code_git_sha: str | None
    outcome: OutcomeResult
    pooled_sharpe: float
    pooled_mde: float
    heavy_tail_window_count: int
    window_metrics: list[WindowMetrics]
    window_power: list[PowerResult]
    window_states: dict[int, str]
    vix_tier_coverage: int
    effective_universe_size: int
    config: WalkForwardConfig


def _git_sha(repo_root: str = ".") -> str | None:
    try:
        out = subprocess.check_output(
            ["git", "-C", repo_root, "rev-parse", "HEAD"],
            stderr=subprocess.DEVNULL, timeout=5,
        )
        return out.decode().strip()
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
        return None


def _spec_hash(spec_raw: dict) -> str:
    return hashlib.sha256(
        json.dumps(spec_raw, sort_keys=True, default=str).encode()
    ).hexdigest()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _assign_vix_tier(trade: Any) -> str | None:
    vix = getattr(trade, "vix_at_entry", None)
    if vix is None and isinstance(trade, dict):
        vix = trade.get("vix_at_entry")
    return vix_tier_of(vix)


def _pnl_array(trades: Sequence[Any]) -> np.ndarray:
    vals: list[float] = []
    for t in trades:
        p = getattr(t, "pnl_pct", None)
        if p is None and isinstance(t, dict):
            p = t.get("pnl_pct")
        if p is None:
            continue
        vals.append(float(p))
    return np.asarray(vals, dtype=float)


def process_window(
    window_index: int,
    window: WalkForwardWindow,
    is_trades_raw: Sequence[Any],
    oos_trades_raw: Sequence[Any],
    config: WalkForwardConfig,
    max_hold_days: int,
) -> tuple[WindowMetrics, PowerResult, list[Any]]:
    """Run R2 purge/embargo + R4 costs + R6 metrics/power for one window.

    Returns (WindowMetrics, PowerResult, oos_kept_trades_with_costs).
    """
    is_kept = purge_is_trades(
        is_trades_raw, window.test_start, window.test_end,
    )
    oos_kept = embargo_oos_trades(
        oos_trades_raw, window.test_start, window.test_end,
        embargo_days=config.embargo_days,
    )
    _ = is_kept  # IS trades are audited / persisted but not pooled into OOS
    oos_costed = apply_per_side_cost_batch(
        oos_kept, per_side_bps=config.per_side_cost_bps,
    )
    metrics = compute_window_metrics(
        oos_costed, window_index=window_index,
        heavy_tail_se_ratio=config.heavy_tail_se_ratio,
        bootstrap_resamples=config.bootstrap_resamples,
        random_seed=config.random_seed,
    )
    pnls = _pnl_array(oos_costed)
    power = evaluate_window_power(
        metrics, max_hold_days=max_hold_days, pnls=pnls,
        sharpe_min=config.sharpe_min, mde_max=config.mde_max,
        alpha=config.alpha, power=config.power,
    )
    return metrics, power, list(oos_costed)


def run_walkforward(
    strategy_spec_raw: dict,
    config: WalkForwardConfig,
    window_trades: dict[int, dict[str, Sequence[Any]]],
    *,
    spec_path: str | None = None,
    forensic_audits: Sequence[dict] = (),
    max_hold_days: int = 21,
    effective_universe_size: int = 0,
    repo_root: str = ".",
) -> WalkForwardRunResult:
    """Deterministic walk-forward run.

    window_trades is keyed by window_index and contains:
        {'is': list[BacktestTrade], 'oos': list[BacktestTrade]}
    This shape lets the runner be tested end-to-end with synthetic data
    without invoking the backtest engine, and lets the CLI wrapper hand
    in real engine output for production runs.

    Raises R8ViolationError on derived_from / overlap violations.
    """
    # R8(a) + (b) + (d) + runtime heuristic — up front before ANY cycles.
    validate_derived_from(strategy_spec_raw)
    firewall_windows = [
        FirewallWindow(test_start=w.test_start, test_end=w.test_end)
        for w in config.windows
    ]
    assert_no_overlap(strategy_spec_raw.get("derived_from"), firewall_windows)
    ensure_bootcamp_off(config.bootcamp_override)
    heuristic_warnings = check_provenance_heuristic(
        spec_path=spec_path, spec_raw=strategy_spec_raw,
        forensic_audits=list(forensic_audits), repo_root=repo_root,
    )
    for w in heuristic_warnings:
        logger.warning("[WF] %s", w)

    window_metrics: list[WindowMetrics] = []
    window_power: list[PowerResult] = []
    oos_trades_per_window: list[list[Any]] = []
    max_drawdowns: list[float] = []
    for i, window in enumerate(config.windows):
        trades = window_trades.get(i, {})
        metrics, power, oos_kept = process_window(
            window_index=i, window=window,
            is_trades_raw=trades.get("is", []),
            oos_trades_raw=trades.get("oos", []),
            config=config, max_hold_days=max_hold_days,
        )
        window_metrics.append(metrics)
        window_power.append(power)
        oos_trades_per_window.append(oos_kept)
        max_drawdowns.append(metrics.max_drawdown_pct)

    window_states = count_power_states(
        window_power,
        min_trades_per_window=config.min_trades_per_window,
        n_trades_per_window=[m.n_trades for m in window_metrics],
        windows=config.windows,
        min_window_duration_days=config.min_window_duration_days,
    )
    pooled_sharpe = compute_pooled_sharpe(oos_trades_per_window)
    pooled_n = sum(m.n_trades for m in window_metrics)
    # Pooled MDE uses concatenated pnls and the overall sharpe
    all_pnls = _pnl_array(sum(oos_trades_per_window, []))
    if all_pnls.size > 1:
        from src.platform.rigor.walkforward_metrics import (
            compute_parametric_se,
        )
        from src.platform.rigor.walkforward_power import compute_mde
        param_se = compute_parametric_se(pooled_sharpe, pooled_n)
        pooled_mde = compute_mde(
            pooled_sharpe, n_effective=pooled_n, se_used=param_se,
            alpha=config.alpha, power=config.power,
        )
    else:
        pooled_mde = float("inf")
    distinct_tiers = distinct_tier_count(window_metrics)
    outcome = reduce_outcome(
        window_states=window_states,
        max_drawdowns=max_drawdowns,
        pooled_sharpe=pooled_sharpe,
        distinct_vix_tiers=distinct_tiers,
        pooled_sharpe_min=config.pooled_sharpe_min,
        max_drawdown_cap_pct=config.max_drawdown_cap_pct,
        min_vix_tiers=config.min_vix_tiers,
        windows_passing_criterion_2=4,
        inconclusive_window_threshold=2,
    )
    return WalkForwardRunResult(
        run_id=str(uuid.uuid4()),
        strategy_id=config.strategy_id,
        spec_hash=_spec_hash(strategy_spec_raw),
        code_git_sha=_git_sha(repo_root),
        outcome=outcome,
        pooled_sharpe=pooled_sharpe,
        pooled_mde=pooled_mde,
        heavy_tail_window_count=sum(
            1 for m in window_metrics if m.heavy_tail_flag
        ),
        window_metrics=window_metrics,
        window_power=window_power,
        window_states=window_states,
        vix_tier_coverage=distinct_tiers,
        effective_universe_size=effective_universe_size,
        config=config,
    )


def persist_run_result(
    result: WalkForwardRunResult,
    strategy_spec_raw: dict,
    oos_trades_per_window: Sequence[Sequence[Any]] | None,
    db_path: str,
) -> None:
    """Write walkforward_results + walkforward_trades rows for a single run.
    Idempotent via primary key — re-persist overwrites. Split from the
    runner so tests can exercise the runner without touching a DB."""
    df = strategy_spec_raw.get("derived_from") or {}
    source_type = df.get("source_type") if isinstance(df, dict) else None
    source_run_id = df.get("source_run_id") if isinstance(df, dict) else None

    overall_max_dd = max(
        (m.max_drawdown_pct for m in result.window_metrics), default=0.0,
    )
    conn = connect_db(db_path)
    try:
        results_row = {
            "run_id": result.run_id,
            "strategy_id": result.strategy_id,
            "spec_hash": result.spec_hash,
            "code_git_sha": result.code_git_sha,
            "random_seed": result.config.random_seed,
            "config_json": json.dumps(result.config.as_json_dict()),
            "outcome_state": result.outcome.outcome_state,
            "reason": result.outcome.reason,
            "pooled_sharpe": result.pooled_sharpe,
            "pooled_mde": result.pooled_mde,
            "heavy_tail_flag": 1 if result.heavy_tail_window_count > 0 else 0,
            "heavy_tail_window_count": result.heavy_tail_window_count,
            "n_windows": len(result.config.windows),
            "n_windows_pass": result.outcome.n_windows_pass,
            "n_windows_fail": result.outcome.n_windows_fail,
            "n_windows_inconclusive_data": result.outcome.n_windows_inconclusive_data,
            "n_windows_inconclusive_power": result.outcome.n_windows_inconclusive_power,
            "n_windows_inconclusive_duration": result.outcome.n_windows_inconclusive_duration,
            "derived_from_source_type": source_type,
            "derived_from_source_run_id": source_run_id,
            "effective_universe_size": result.effective_universe_size,
            "max_drawdown_pct": overall_max_dd,
            "vix_tier_coverage": result.vix_tier_coverage,
            "created_at": _now_iso(),
        }
        engine_aware_upsert(conn, "walkforward_results", results_row, action="replace")
        if oos_trades_per_window is not None:
            for i, trades in enumerate(oos_trades_per_window):
                window_sharpe = (
                    result.window_metrics[i].sharpe
                    if i < len(result.window_metrics) else 0.0
                )
                window_mde = (
                    result.window_power[i].mde
                    if i < len(result.window_power) else float("inf")
                )
                window_bse = (
                    result.window_metrics[i].bootstrap_se
                    if i < len(result.window_metrics) else 0.0
                )
                for t in trades:
                    trade_row = {
                        "trade_id": (
                            getattr(t, "trade_id", None)
                            or (t.get("trade_id") if isinstance(t, dict) else None)
                            or str(uuid.uuid4())
                        ),
                        "run_id": result.run_id,
                        "window_index": i,
                        "is_in_is_window": 0,
                        "ticker": getattr(t, "ticker", None) or (t.get("ticker") if isinstance(t, dict) else None),
                        "entry_date": getattr(t, "entry_date", None) or (t.get("entry_date") if isinstance(t, dict) else None),
                        "exit_date": getattr(t, "exit_date", None) or (t.get("exit_date") if isinstance(t, dict) else None),
                        "entry_price": getattr(t, "entry_price", None) or (t.get("entry_price") if isinstance(t, dict) else None),
                        "exit_price": getattr(t, "exit_price", None) or (t.get("exit_price") if isinstance(t, dict) else None),
                        "pnl_pct": getattr(t, "pnl_pct", None) or (t.get("pnl_pct") if isinstance(t, dict) else None),
                        "excess_return": getattr(t, "excess_return", None) or (t.get("excess_return") if isinstance(t, dict) else None),
                        "exit_reason": getattr(t, "exit_reason", None) or (t.get("exit_reason") if isinstance(t, dict) else None),
                        "hold_days": getattr(t, "hold_days", None) or (t.get("hold_days") if isinstance(t, dict) else None),
                        "vix_at_entry": getattr(t, "vix_at_entry", None) or (t.get("vix_at_entry") if isinstance(t, dict) else None),
                        "vix_tier": _assign_vix_tier(t),
                        "purged": 0,
                        "embargoed": 0,
                        "sharpe_observed": window_sharpe,
                        "bootstrap_se": window_bse,
                        "mde_value": window_mde,
                    }
                    engine_aware_upsert(conn, "walkforward_trades", trade_row, action="replace")
        conn.commit()
    finally:
        conn.close()
