"""Subgroup analysis harness for Stage 1 walk-forward results (#81).

Pre-registration §6 (`docs/research/pre-registration-stage1.md`) commits to
four EXPLORATORY subgroup analyses: regime, calendar year, GICS sector, and
LLM conviction tier. Per §8.1 these are diagnostics — they are reported but
do NOT enter the binary pass/fail decision and do NOT enter the multiple-
testing correction count.

Called by: Stage 1 results report writer (post #83).
Calls: src.analytics.canonical_sharpe (per-partition Sharpe).
Owns tables: none.
Tests: tests/evaluation/test_subgroup_analysis.py.

Trade dict contract — fields the partitioner reads:

- ``pnl_pct`` (float, required) — PnL percentage. All metrics derive from this.
- ``date`` (str ISO ``YYYY-MM-DD``) — used for the calendar-year partition.
  Falls back to ``actual_exit_time`` if ``date`` is absent.
- ``traffic_light`` (str: GREEN/YELLOW/RED, optional) — used for the regime
  partition when present. Pre-reg §6 specifies Traffic Light explicitly.
  Falls back to ``regime`` (regime_label like BULL_LOW_VOL) if absent. The
  partition reports whichever set of values exists in the data.
- ``sector`` (str, optional) — GICS sector. Top-5 are reported separately;
  others bucketed under "Other"; missing under "unknown".
- ``llm_conviction`` (str: low/medium/high, optional) — LLM tier. Missing
  values bucketed under "unknown".
"""
from __future__ import annotations

import logging
import statistics
from collections import defaultdict
from typing import Any, Iterable

logger = logging.getLogger(__name__)

# Pre-reg §6: top 5 GICS sectors are explicitly reported.
TOP_5_SECTORS = (
    "Technology",
    "Health Care",
    "Financials",
    "Communication Services",
    "Consumer Discretionary",
)

# Per-trade allocation % — mirrors backtester.py's allocation_pct=0.05.
# Used in max-drawdown computation so this harness's equity curve matches
# what the backtester itself produced.
_ALLOCATION_PCT = 0.05


def partition_by_subgroups(walkforward_result: dict) -> dict[str, dict]:
    """Partition trades from a walkforward result into pre-reg §6 subgroups.

    Args:
        walkforward_result: output dict from
            ``src.evaluation.walkforward.run_walkforward()``. Must have shape
            ``{"folds": [{"trades": [...]}, ...], ...}``.

    Returns:
        Dict mapping subgroup name to per-partition metrics:

        ::

            {
                "regime": {"GREEN": {...}, "YELLOW": {...}, "RED": {...}},
                "year": {2024: {...}, 2025: {...}, ...},
                "sector": {"Technology": {...}, ..., "Other": {...}},
                "llm_conviction": {"low": {...}, "medium": {...}, ...},
            }

        Per-partition metrics dict has keys ``trade_count``,
        ``mean_return``, ``win_rate``, ``sharpe``, ``max_drawdown_pct``.
        Empty partitions return ``trade_count=0`` with the rest as ``None``.
    """
    trades = _flatten_trades(walkforward_result)
    return {
        "regime": _summarize_partitions(_partition_by_regime(trades)),
        "year": _summarize_partitions(_partition_by_year(trades)),
        "sector": _summarize_partitions(_partition_by_sector(trades)),
        "llm_conviction": _summarize_partitions(_partition_by_llm_conviction(trades)),
    }


def _flatten_trades(walkforward_result: dict) -> list[dict]:
    """Collect all trades across folds into a flat list.

    Includes underpowered folds — the harness reports per-partition raw
    counts; downstream consumers can apply the §3.5 underpowered exclusion
    if they want to mirror primary-metric semantics.
    """
    trades: list[dict] = []
    for fold in walkforward_result.get("folds", []):
        trades.extend(fold.get("trades", []) or [])
    return trades


def _partition_by_regime(trades: Iterable[dict]) -> dict[str, list[dict]]:
    """Partition by Traffic Light (preferred) or regime_label (fallback)."""
    buckets: dict[str, list[dict]] = defaultdict(list)
    for t in trades:
        tl = t.get("traffic_light")
        if tl is not None:
            key = str(tl)
        else:
            key = str(t.get("regime", "unknown"))
        buckets[key].append(t)
    return dict(buckets)


def _partition_by_year(trades: Iterable[dict]) -> dict[int, list[dict]]:
    """Partition by calendar year of trade date."""
    buckets: dict[int, list[dict]] = defaultdict(list)
    for t in trades:
        date_str = t.get("date") or t.get("actual_exit_time") or ""
        try:
            year = int(str(date_str)[:4])
        except (ValueError, TypeError):
            year = -1  # sentinel for unknown
        buckets[year].append(t)
    return dict(buckets)


def _partition_by_sector(trades: Iterable[dict]) -> dict[str, list[dict]]:
    """Partition by GICS sector (top 5 named, others bucketed)."""
    buckets: dict[str, list[dict]] = defaultdict(list)
    for t in trades:
        sec = t.get("sector")
        if sec is None or sec == "":
            buckets["unknown"].append(t)
        elif sec in TOP_5_SECTORS:
            buckets[sec].append(t)
        else:
            buckets["Other"].append(t)
    return dict(buckets)


def _partition_by_llm_conviction(trades: Iterable[dict]) -> dict[str, list[dict]]:
    """Partition by LLM conviction tier: low / medium / high / unknown."""
    buckets: dict[str, list[dict]] = defaultdict(list)
    for t in trades:
        conv = t.get("llm_conviction")
        if conv in ("low", "medium", "high"):
            buckets[conv].append(t)
        else:
            buckets["unknown"].append(t)
    return dict(buckets)


def _summarize_partitions(buckets: dict[Any, list[dict]]) -> dict[Any, dict]:
    """Apply _compute_metrics to each partition. Returns dict[key, metrics]."""
    return {key: _compute_metrics(trades) for key, trades in buckets.items()}


def _compute_metrics(trades: list[dict]) -> dict:
    """Compute trade_count, mean_return, win_rate, sharpe, max_drawdown_pct."""
    if not trades:
        return {
            "trade_count": 0,
            "mean_return": None,
            "win_rate": None,
            "sharpe": None,
            "max_drawdown_pct": None,
        }
    pnls = [float(t.get("pnl_pct", 0) or 0) for t in trades]
    n = len(pnls)
    win_count = sum(1 for p in pnls if p > 0)
    return {
        "trade_count": n,
        "mean_return": round(statistics.fmean(pnls), 4),
        "win_rate": round(win_count / n, 4),
        "sharpe": _safe_sharpe(pnls),
        "max_drawdown_pct": _max_drawdown_pct(pnls),
    }


def _safe_sharpe(pnls: list[float]) -> float | None:
    """Wrap canonical raw_sharpe. Returns None when it cannot be computed."""
    if len(pnls) < 2:
        return None
    try:
        from src.analytics.canonical_sharpe import raw_sharpe
        decimal_pnls = [p / 100.0 for p in pnls]
        result = raw_sharpe(decimal_pnls)
        return round(result, 4) if result is not None else None
    except Exception as exc:
        logger.warning("subgroup_analysis: sharpe failed for %d trades: %s", len(pnls), exc)
        return None


def _max_drawdown_pct(pnls: list[float]) -> float | None:
    """Peak-to-trough drawdown on the equity curve implied by these PnLs.

    Returns a non-negative percentage (e.g. 15.0 = 15% drawdown from peak).
    Mirrors the backtester's 5% allocation per trade so the partition's
    drawdown reflects what the backtester itself produced for that subset.
    """
    if not pnls:
        return None
    equity = 100.0
    peak = equity
    max_dd = 0.0
    for p in pnls:
        equity *= 1.0 + _ALLOCATION_PCT * (p / 100.0)
        if equity > peak:
            peak = equity
        elif peak > 0:
            dd = (peak - equity) / peak * 100.0
            if dd > max_dd:
                max_dd = dd
    return round(max_dd, 4)
