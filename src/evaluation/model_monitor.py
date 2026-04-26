"""Model performance monitoring and regression detection.

Called by: api.routes.training, scheduler.watch
Calls: config
Owns tables: none (reads shadow_trades, recommendations, model_versions)
Config keys: none
Tests: tests/test_model_monitor.py

Provides two main functions:
  1. get_model_performance() — per-model-version live metrics for the dashboard
  2. check_model_regression() — automated alert when the active model underperforms

The Sharpe ratio here is trade-level (not daily): mean(pnl_pct) / std(pnl_pct).
With <50 trades this is noisy, but it's the best signal from live data.
Profit factor (gross wins / |gross losses|) is more stable at small N.
"""

import logging
import math
import sqlite3
from contextlib import closing

from src.config import DB_PATH

logger = logging.getLogger(__name__)


def _compute_metrics(trades: list[dict]) -> dict:
    """Compute performance metrics from a list of closed trade dicts.

    Each trade must have: pnl_dollars, pnl_pct, exit_reason, duration_days,
    actual_exit_time.
    """
    if not trades:
        return {
            "trades": 0, "wins": 0, "losses": 0, "timeouts": 0,
            "win_rate": 0.0, "profit_factor": 0.0,
            "expectancy_dollars": 0.0, "sharpe_ratio": 0.0,
            "max_drawdown_pct": 0.0, "avg_holding_days": 0.0,
            "total_pnl_pct": 0.0, "total_pnl_dollars": 0.0,
            "avg_win_dollars": 0.0, "avg_loss_dollars": 0.0,
        }

    pnl_dollars = [float(t.get("pnl_dollars") or 0) for t in trades]
    pnl_pcts = [float(t.get("pnl_pct") or 0) for t in trades]
    durations = [float(t.get("duration_days") or 0) for t in trades]

    wins = [p for p in pnl_dollars if p > 0]
    losses = [p for p in pnl_dollars if p < 0]
    timeouts = sum(1 for t in trades if (t.get("exit_reason") or "") == "timeout")

    n = len(trades)
    win_rate = len(wins) / n if n else 0
    gross_wins = sum(wins)
    gross_losses = abs(sum(losses))
    profit_factor = gross_wins / gross_losses if gross_losses > 0 else (
        float("inf") if gross_wins > 0 else 0.0
    )
    expectancy = sum(pnl_dollars) / n if n else 0

    # Trade-level Sharpe (annualized).
    # F-2 / Sprint-0 wave-4a: route through canonical compute_sharpe with
    # periods_per_year=150 (matches cto_report's "150 trades/year" trade-
    # frequency convention so cross-model deltas are comparable). Coerce
    # None → 0.0 because `_build_comparison` and `check_model_regression`
    # do arithmetic on `sharpe_ratio` (None - 0.5 would TypeError).
    from src.analytics.canonical_sharpe import compute_sharpe
    sharpe_canonical = compute_sharpe(pnl_pcts, periods_per_year=150)
    sharpe = 0.0 if sharpe_canonical is None else sharpe_canonical

    # Max drawdown from cumulative PnL%
    cumulative = 0.0
    peak = 0.0
    max_dd = 0.0
    for pct in pnl_pcts:
        cumulative += pct
        if cumulative > peak:
            peak = cumulative
        dd = peak - cumulative
        if dd > max_dd:
            max_dd = dd

    avg_hold = sum(durations) / n if n else 0
    total_pnl_pct = sum(pnl_pcts)
    total_pnl_dollars = sum(pnl_dollars)
    avg_win = sum(wins) / len(wins) if wins else 0
    avg_loss = sum(losses) / len(losses) if losses else 0

    return {
        "trades": n,
        "wins": len(wins),
        "losses": len(losses),
        "timeouts": timeouts,
        "win_rate": round(win_rate, 3),
        "profit_factor": round(min(profit_factor, 999.0), 2),
        "expectancy_dollars": round(expectancy, 2),
        "sharpe_ratio": round(sharpe, 2),
        "max_drawdown_pct": round(max_dd, 2),
        "avg_holding_days": round(avg_hold, 1),
        "total_pnl_pct": round(total_pnl_pct, 2),
        "total_pnl_dollars": round(total_pnl_dollars, 2),
        "avg_win_dollars": round(avg_win, 2),
        "avg_loss_dollars": round(avg_loss, 2),
    }


def _build_equity_curve(trades: list[dict]) -> list[dict]:
    """Build cumulative P&L equity curve from sorted trades."""
    if not trades:
        return []

    curve = []
    cumulative = 0.0
    for t in trades:
        exit_time = t.get("actual_exit_time") or t.get("created_at") or ""
        date = exit_time[:10] if exit_time else ""
        pnl = float(t.get("pnl_dollars") or 0)
        cumulative += pnl
        curve.append({"date": date, "cumulative_pnl": round(cumulative, 2)})
    return curve


def get_model_performance(db_path: str = DB_PATH) -> dict:
    """Get per-model-version live performance metrics.

    Joins shadow_trades → recommendations (for model_version) and
    model_versions table for training metadata.

    Returns dict with models[], comparison, canary_comparison.
    """
    with closing(sqlite3.connect(db_path)) as conn:
        conn.row_factory = sqlite3.Row

        # Get all model versions metadata
        try:
            model_rows = conn.execute(
                "SELECT version_id, version_name, created_at, "
                "training_examples_count, holdout_score, status "
                "FROM model_versions ORDER BY created_at DESC"
            ).fetchall()
        except Exception:
            model_rows = []

        versions_meta = {}
        for mv in model_rows:
            versions_meta[mv["version_name"]] = {
                "version_id": mv["version_id"],
                "created_at": (mv["created_at"] or "")[:10],
                "training_examples": mv["training_examples_count"] or 0,
                "holdout_score": mv["holdout_score"],
                "status": mv["status"] or "unknown",
            }

        # Get closed trades joined with recommendation model_version
        trade_rows = conn.execute(
            """
            SELECT st.trade_id, st.ticker, st.pnl_dollars, st.pnl_pct,
                   st.exit_reason, st.duration_days, st.actual_exit_time,
                   st.created_at,
                   r.model_version
            FROM shadow_trades st
            LEFT JOIN recommendations r ON st.recommendation_id = r.recommendation_id
            WHERE st.status = 'closed' AND st.pnl_dollars IS NOT NULL
            AND COALESCE(st.quarantined, 0) = 0
            ORDER BY st.actual_exit_time ASC
"""
        ).fetchall()
        trades = [dict(row) for row in trade_rows]

        # Check if canary_score column exists in recommendations
        has_canary = False
        try:
            cols = [r[1] for r in conn.execute("PRAGMA table_info(recommendations)").fetchall()]
            has_canary = "canary_score" in cols
        except Exception:
            pass

        # Get canary data if available
        canary_data = []
        if has_canary:
            canary_rows = conn.execute(
                """
                SELECT r.recommendation_id, r.llm_conviction, r.canary_score,
                       st.pnl_dollars
                FROM recommendations r
                JOIN shadow_trades st ON r.recommendation_id = st.recommendation_id
                WHERE st.status = 'closed' AND st.pnl_dollars IS NOT NULL
                  AND r.llm_conviction IS NOT NULL AND r.canary_score IS NOT NULL
                """
            ).fetchall()
            canary_data = [dict(row) for row in canary_rows]

    # Group trades by model version
    by_model: dict[str, list[dict]] = {}
    for t in trades:
        version = t.get("model_version") or "base"
        by_model.setdefault(version, []).append(t)

    # Build per-model results
    models = []
    ordered_versions = []  # For comparison (newest first)
    for version, version_trades in sorted(by_model.items(),
                                           key=lambda x: (x[1][0].get("actual_exit_time") or "") if x[1] else "",
                                           reverse=True):
        meta = versions_meta.get(version, {})
        metrics = _compute_metrics(version_trades)
        equity = _build_equity_curve(version_trades)

        model_entry = {
            "version": version,
            "status": meta.get("status", "unknown"),
            "created_at": meta.get("created_at", ""),
            "training_examples": meta.get("training_examples", 0),
            "holdout_score": meta.get("holdout_score"),
            "live_metrics": metrics,
            "equity_curve": equity,
        }
        models.append(model_entry)
        ordered_versions.append((version, metrics))

    # Also include model versions with zero trades
    for vname, vmeta in versions_meta.items():
        if vname not in by_model:
            models.append({
                "version": vname,
                "status": vmeta.get("status", "unknown"),
                "created_at": vmeta.get("created_at", ""),
                "training_examples": vmeta.get("training_examples", 0),
                "holdout_score": vmeta.get("holdout_score"),
                "live_metrics": _compute_metrics([]),
                "equity_curve": [],
            })

    # Cross-version comparison (current vs previous)
    comparison = _build_comparison(ordered_versions)

    # Canary comparison
    canary_comparison = _build_canary_comparison(canary_data)

    return {
        "models": models,
        "comparison": comparison,
        "canary_comparison": canary_comparison,
    }


def _build_comparison(ordered_versions: list[tuple[str, dict]]) -> dict:
    """Compare current (first) vs previous (second) model version."""
    if len(ordered_versions) < 2:
        current = ordered_versions[0][0] if ordered_versions else None
        return {
            "current_vs_previous": {
                "current": current,
                "previous": None,
                "sharpe_delta": None,
                "wr_delta": None,
                "pf_delta": None,
                "verdict": "insufficient_data",
            }
        }

    curr_name, curr_m = ordered_versions[0]
    prev_name, prev_m = ordered_versions[1]

    sharpe_delta = None
    wr_delta = None
    pf_delta = None
    verdict = "insufficient_data"

    if curr_m["trades"] >= 5 and prev_m["trades"] >= 5:
        sharpe_delta = round(curr_m["sharpe_ratio"] - prev_m["sharpe_ratio"], 2)
        wr_delta = round(curr_m["win_rate"] - prev_m["win_rate"], 3)
        pf_delta = round(curr_m["profit_factor"] - prev_m["profit_factor"], 2)

        if sharpe_delta > 0.1 and wr_delta >= 0:
            verdict = "current_improved"
        elif sharpe_delta < -0.1 or wr_delta < -0.05:
            verdict = "current_regressed"
        else:
            verdict = "no_significant_difference"

    return {
        "current_vs_previous": {
            "current": curr_name,
            "previous": prev_name,
            "sharpe_delta": sharpe_delta,
            "wr_delta": wr_delta,
            "pf_delta": pf_delta,
            "verdict": verdict,
        }
    }


def _build_canary_comparison(canary_data: list[dict]) -> dict:
    """Compare LLM conviction vs canary score on paired trades."""
    n = len(canary_data)
    if n == 0:
        return {
            "llm_win_rate": None,
            "canary_win_rate": None,
            "paired_trades": 0,
            "mcnemar_pvalue": None,
            "verdict": "insufficient_data",
        }

    llm_correct = sum(1 for d in canary_data
                       if (d["llm_conviction"] or 0) >= 5 and float(d["pnl_dollars"] or 0) > 0)
    canary_correct = sum(1 for d in canary_data
                          if (d["canary_score"] or 0) >= 5 and float(d["pnl_dollars"] or 0) > 0)

    llm_wr = llm_correct / n if n else 0
    canary_wr = canary_correct / n if n else 0

    # McNemar test requires n >= 50 paired trades for meaningful results
    mcnemar_p = None
    if n >= 50:
        try:
            # McNemar: count discordant pairs
            b = sum(1 for d in canary_data
                    if (d["llm_conviction"] or 0) >= 5 and float(d["pnl_dollars"] or 0) > 0
                    and not ((d["canary_score"] or 0) >= 5 and float(d["pnl_dollars"] or 0) > 0))
            c = sum(1 for d in canary_data
                    if not ((d["llm_conviction"] or 0) >= 5 and float(d["pnl_dollars"] or 0) > 0)
                    and (d["canary_score"] or 0) >= 5 and float(d["pnl_dollars"] or 0) > 0)
            if b + c > 0:
                chi2 = (abs(b - c) - 1) ** 2 / (b + c)
                # Approximate p-value from chi-squared with 1 df
                mcnemar_p = round(math.exp(-chi2 / 2), 4)
        except Exception:
            pass

    if n < 10:
        verdict = f"insufficient_data ({n} paired trades)"
    elif llm_wr > canary_wr + 0.05:
        verdict = "LLM adds value"
    elif canary_wr > llm_wr + 0.05:
        verdict = "Canary outperforms"
    else:
        verdict = "No statistical difference"

    return {
        "llm_win_rate": round(llm_wr, 3),
        "canary_win_rate": round(canary_wr, 3),
        "paired_trades": n,
        "mcnemar_pvalue": mcnemar_p,
        "verdict": verdict,
    }


# ── Regression Alert ────────────────────────────────────────────────────

def check_model_regression(db_path: str = DB_PATH,
                            min_trades_per_model: int = 10) -> dict:
    """Compare current active model against previous on live trade metrics.

    Returns regression alert if current model underperforms previous by
    a meaningful margin (>10% relative decline in Sharpe or win rate).

    Returns:
        {
            "status": "ok" | "warning" | "critical",
            "current_model": str,
            "previous_model": str | None,
            "details": {...metrics comparison...},
            "message": str,
        }
    """
    result = get_model_performance(db_path)
    models_with_trades = [m for m in result["models"] if m["live_metrics"]["trades"] > 0]

    if len(models_with_trades) < 2:
        msg = (f"Only {len(models_with_trades)} model(s) with trades — "
               "need at least 2 for comparison")
        logger.info("[MODEL_MONITOR] %s", msg)
        return {
            "status": "ok",
            "current_model": models_with_trades[0]["version"] if models_with_trades else None,
            "previous_model": None,
            "details": {},
            "message": msg,
        }

    current = models_with_trades[0]
    previous = models_with_trades[1]
    curr_m = current["live_metrics"]
    prev_m = previous["live_metrics"]

    if curr_m["trades"] < min_trades_per_model or prev_m["trades"] < min_trades_per_model:
        msg = (f"Insufficient trades: {current['version']}={curr_m['trades']}, "
               f"{previous['version']}={prev_m['trades']} (need {min_trades_per_model})")
        logger.info("[MODEL_MONITOR] %s", msg)
        return {
            "status": "ok",
            "current_model": current["version"],
            "previous_model": previous["version"],
            "details": {
                "current_trades": curr_m["trades"],
                "previous_trades": prev_m["trades"],
            },
            "message": msg,
        }

    # Compute deltas
    sharpe_delta = curr_m["sharpe_ratio"] - prev_m["sharpe_ratio"]
    wr_delta = curr_m["win_rate"] - prev_m["win_rate"]
    pf_delta = curr_m["profit_factor"] - prev_m["profit_factor"]

    # Relative decline thresholds
    sharpe_decline_pct = (
        abs(sharpe_delta / prev_m["sharpe_ratio"]) * 100
        if prev_m["sharpe_ratio"] != 0 else 0
    )
    wr_decline_pct = (
        abs(wr_delta / prev_m["win_rate"]) * 100
        if prev_m["win_rate"] != 0 else 0
    )

    details = {
        "current_sharpe": curr_m["sharpe_ratio"],
        "previous_sharpe": prev_m["sharpe_ratio"],
        "sharpe_delta": round(sharpe_delta, 2),
        "sharpe_decline_pct": round(sharpe_decline_pct, 1),
        "current_wr": curr_m["win_rate"],
        "previous_wr": prev_m["win_rate"],
        "wr_delta": round(wr_delta, 3),
        "wr_decline_pct": round(wr_decline_pct, 1),
        "current_pf": curr_m["profit_factor"],
        "previous_pf": prev_m["profit_factor"],
        "pf_delta": round(pf_delta, 2),
        "current_trades": curr_m["trades"],
        "previous_trades": prev_m["trades"],
    }

    # Determine status
    status = "ok"
    message = (f"{current['version']} vs {previous['version']}: "
               f"Sharpe {sharpe_delta:+.2f}, WR {wr_delta:+.3f}, PF {pf_delta:+.2f}")

    if curr_m["sharpe_ratio"] < 0 and prev_m["sharpe_ratio"] > 0:
        status = "critical"
        message = (f"CRITICAL: {current['version']} Sharpe went negative "
                   f"({curr_m['sharpe_ratio']}) vs {previous['version']} "
                   f"({prev_m['sharpe_ratio']})")
        logger.critical("[MODEL_MONITOR] %s", message)
    elif sharpe_delta < 0 and sharpe_decline_pct > 10:
        status = "warning"
        message = (f"WARNING: {current['version']} Sharpe declined {sharpe_decline_pct:.1f}% "
                   f"vs {previous['version']}")
        logger.warning("[MODEL_MONITOR] %s", message)
    elif wr_delta < 0 and wr_decline_pct > 10:
        status = "warning"
        message = (f"WARNING: {current['version']} win rate declined {wr_decline_pct:.1f}% "
                   f"vs {previous['version']}")
        logger.warning("[MODEL_MONITOR] %s", message)
    else:
        logger.info("[MODEL_MONITOR] %s", message)

    return {
        "status": status,
        "current_model": current["version"],
        "previous_model": previous["version"],
        "details": details,
        "message": message,
    }
