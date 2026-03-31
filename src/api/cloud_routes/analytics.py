"""Cloud analytics routes and helpers for HSHS and CTO reporting.

Called by: api.cloud_app
Calls: evaluation.hshs_live
Owns tables: none
Config keys: none
Tests: none
"""

import statistics

from fastapi import APIRouter, Depends


PERFORMANCE_WEIGHT = 0.10
MODEL_QUALITY_WEIGHT = 0.25
DATA_ASSET_WEIGHT = 0.35
FLYWHEEL_WEIGHT = 0.20
DEFENSIBILITY_WEIGHT = 0.10


def _compute_performance_score(closed_trades: list[dict]) -> tuple[float, dict]:
    """Compute performance dimension score and metrics."""
    closed_count = len(closed_trades)
    if closed_count < 2:
        return 0, {"status": "Insufficient data", "trade_count": closed_count, "target": 50}

    pnls = [trade.get("pnl_pct", 0) or 0 for trade in closed_trades]
    pnl_dollars = [trade.get("pnl_dollars", 0) or 0 for trade in closed_trades]
    wins = [pnl for pnl in pnls if pnl > 0]
    losses = [pnl for pnl in pnls if pnl <= 0]
    win_rate = len(wins) / closed_count
    mean_pnl = sum(pnls) / len(pnls)
    std_pnl = max((sum((pnl - mean_pnl) ** 2 for pnl in pnls) / len(pnls)) ** 0.5, 0.001)
    sharpe = mean_pnl / std_pnl
    profit_factor = (sum(wins) / abs(sum(losses))) if losses and sum(losses) != 0 else 99

    running = 0
    peak = 0
    max_dd = 0
    for pnl in pnl_dollars:
        running += pnl
        if running > peak:
            peak = running
        max_dd = max(max_dd, peak - running)

    max_dd_pct = (max_dd / 100000) * 100 if max_dd > 0 else 0
    wr_score = min(100, win_rate * 200)
    sharpe_score = min(100, max(0, sharpe * 50))
    dd_score = max(0, 100 - max_dd_pct * 5)
    perf_score = round(wr_score * 0.35 + sharpe_score * 0.35 + dd_score * 0.30, 1)
    return perf_score, {
        "win_rate": round(win_rate, 3),
        "sharpe": round(sharpe, 2),
        "profit_factor": round(min(profit_factor, 99), 2),
        "max_drawdown_pct": round(max_dd_pct, 2),
        "net_pnl": round(sum(pnl_dollars), 2),
        "trade_count": closed_count,
    }


def _compute_model_quality_score(scan: dict | None, canary: dict | None) -> tuple[float, dict]:
    """Compute model-quality dimension score and metrics."""
    fallback_rate = 0
    if scan and scan.get("llm_total") and scan["llm_total"] > 0:
        success = scan.get("llm_success", 0) or 0
        fallback_rate = round(1 - success / scan["llm_total"], 3)

    metrics = {"template_fallback_rate": fallback_rate}
    if canary:
        metrics["canary_verdict"] = canary.get("verdict", "unknown")
        if canary.get("perplexity"):
            metrics["perplexity"] = round(canary["perplexity"], 2)
        if canary.get("distinct_2"):
            metrics["distinct_2"] = round(canary["distinct_2"], 4)
    else:
        metrics["status"] = "Awaiting first retrain"

    fallback_score = max(0, 100 - fallback_rate * 200)
    canary_score = 80 if (canary and canary.get("verdict") == "pass") else 40 if canary else 0
    return round(fallback_score * 0.5 + canary_score * 0.5, 1), metrics


def _compute_data_asset_score(example_count: int) -> tuple[float, dict]:
    """Compute data-asset dimension score and metrics."""
    score = min(100, (example_count / 2800) * 100) if example_count else 0
    return score, {
        "example_count": example_count,
        "target": 2800,
        "progress_pct": round(score, 1),
    }


def _compute_flywheel_score(closed_count: int, open_count: int) -> tuple[float, dict]:
    """Compute flywheel dimension score and metrics."""
    score = min(100, (closed_count / 50) * 100) if closed_count else 0
    return score, {
        "closed_trades": closed_count,
        "target": 50,
        "open_trades": open_count,
    }


def _compute_defensibility_score(
    example_count: int,
    source_map: dict,
    regime_count: int,
    ticker_count: int,
) -> tuple[float, dict]:
    """Compute defensibility dimension score and metrics."""
    source_diversity = len(source_map)
    score = round(
        min(100, (example_count / 2800) * 100) * 0.30
        + min(100, source_diversity * 25) * 0.20
        + min(100, (regime_count / 33) * 100) * 0.25
        + min(100, (ticker_count / 50) * 100) * 0.25,
        1,
    )
    metrics = {
        "example_count": example_count,
        "source_diversity": source_map,
        "regime_coverage": regime_count,
        "regime_target": 33,
        "ticker_coverage": ticker_count,
    }
    if example_count < 100:
        metrics["status"] = "Building data asset"
    return score, metrics


def _compute_trade_summary(closed_recent: list[dict], open_count: int) -> dict:
    """Compute CTO trade-summary KPIs."""
    pnls = [trade.get("pnl_pct", 0) or 0 for trade in closed_recent]
    wins = [pnl for pnl in pnls if pnl > 0]
    losses = [pnl for pnl in pnls if pnl <= 0]
    total_pnl = sum(trade.get("pnl_dollars", 0) or 0 for trade in closed_recent)
    sharpe = 0
    if len(pnls) >= 2:
        avg_return = statistics.mean(pnls)
        std_return = statistics.stdev(pnls)
        sharpe = round(avg_return / std_return, 3) if std_return > 0 else 0

    gross_wins = sum(wins) if wins else 0
    gross_losses = abs(sum(losses)) if losses else 0
    profit_factor = round(gross_wins / gross_losses, 2) if gross_losses > 0 else (999 if gross_wins > 0 else 0)

    cumulative = 0
    peak = 0
    max_dd = 0
    for pnl in pnls:
        cumulative += pnl
        peak = max(peak, cumulative)
        max_dd = max(max_dd, peak - cumulative)

    win_rate = len(wins) / len(pnls) if pnls else 0
    return {
        "headline_kpis": {
            "sharpe_ratio": sharpe,
            "win_rate": win_rate,
            "max_drawdown_pct": round(max_dd, 2),
            "confidence_calibration": 0,
            "avg_rubric_score": None,
        },
        "trade_summary": {
            "trades_closed": len(closed_recent),
            "trades_open": open_count,
            "win_rate": win_rate,
            "sharpe_ratio": sharpe,
            "profit_factor": profit_factor,
            "expectancy_dollars": round(total_pnl / len(closed_recent), 2) if closed_recent else 0,
            "max_drawdown_pct": round(max_dd, 2),
            "total_pnl": round(total_pnl, 2),
            "avg_winner_pct": round(sum(wins) / len(wins), 1) if wins else None,
            "avg_loser_pct": round(sum(losses) / len(losses), 1) if losses else None,
            "max_consecutive_losses": 0,
        },
    }


def create_router(runtime, verify_auth):
    """Build the cloud analytics router."""
    router = APIRouter()

    @router.get("/api/health/hshs", dependencies=[Depends(verify_auth)])
    def health_hshs():
        try:
            from src.evaluation.hshs_live import compute_hshs

            return compute_hshs()
        except Exception as exc:
            runtime.logger.error("[API] HSHS computation failed: %s", exc)
            return {"hshs": 0, "dimensions": {}, "error": str(exc)}

    @router.get("/api/health/score", dependencies=[Depends(verify_auth)])
    def health_score():
        try:
            closed_trades = runtime.query(
                "SELECT pnl_dollars, pnl_pct FROM shadow_trades WHERE status = 'closed'"
            )
            open_count_row = runtime.query_one(
                "SELECT COUNT(*) as c FROM shadow_trades WHERE status = 'open'"
            )
            example_row = runtime.query_one("SELECT COUNT(*) as count FROM training_examples")
            model = runtime.query_one(
                "SELECT version_name, status FROM model_versions ORDER BY created_at DESC LIMIT 1"
            )
            canary = runtime.query_one(
                "SELECT verdict, perplexity, distinct_2 FROM canary_evaluations ORDER BY created_at DESC LIMIT 1"
            )
            source_rows = runtime.query(
                "SELECT source, COUNT(*) as cnt FROM training_examples GROUP BY source"
            )
            scan = runtime.query_one(
                "SELECT llm_success, llm_total FROM scan_metrics ORDER BY created_at DESC LIMIT 1"
            )
            regime_row = runtime.query_one(
                "SELECT COUNT(DISTINCT regime_label) as cnt FROM training_examples WHERE regime_label IS NOT NULL"
            )
            ticker_row = runtime.query_one(
                "SELECT COUNT(DISTINCT ticker) as cnt FROM training_examples WHERE ticker IS NOT NULL"
            )

            closed_count = len(closed_trades)
            open_count = open_count_row["c"] if open_count_row else 0
            example_count = example_row["count"] if example_row else 0
            source_map = {row["source"]: row["cnt"] for row in source_rows}
            perf_score, perf_metrics = _compute_performance_score(closed_trades)
            mq_score, mq_metrics = _compute_model_quality_score(scan, canary)
            data_asset_score, da_metrics = _compute_data_asset_score(example_count)
            flywheel_score, fw_metrics = _compute_flywheel_score(closed_count, open_count)
            def_score, def_metrics = _compute_defensibility_score(
                example_count,
                source_map,
                regime_row["cnt"] if regime_row else 0,
                ticker_row["cnt"] if ticker_row else 0,
            )

            weights = {
                "performance": PERFORMANCE_WEIGHT,
                "model_quality": MODEL_QUALITY_WEIGHT,
                "data_asset": DATA_ASSET_WEIGHT,
                "flywheel_velocity": FLYWHEEL_WEIGHT,
                "defensibility": DEFENSIBILITY_WEIGHT,
            }
            overall = round(
                perf_score * PERFORMANCE_WEIGHT
                + mq_score * MODEL_QUALITY_WEIGHT
                + data_asset_score * DATA_ASSET_WEIGHT
                + flywheel_score * FLYWHEEL_WEIGHT
                + def_score * DEFENSIBILITY_WEIGHT,
                1,
            )
            return {
                "score": {
                    "overall": overall,
                    "dimensions": {
                        "performance": round(perf_score, 1),
                        "model_quality": round(mq_score, 1),
                        "data_asset": round(data_asset_score, 1),
                        "flywheel_velocity": round(flywheel_score, 1),
                        "defensibility": round(def_score, 1),
                    },
                    "dimension_metrics": {
                        "performance": perf_metrics,
                        "model_quality": mq_metrics,
                        "data_asset": da_metrics,
                        "flywheel_velocity": fw_metrics,
                        "defensibility": def_metrics,
                    },
                    "weights": weights,
                    "phase": "early",
                },
                "closed_trades": closed_count,
                "training_examples": example_count,
                "model": model,
                "canary": canary,
                "history": [],
            }
        except Exception as exc:
            runtime.logger.error("[API] health_score failed: %s", exc, exc_info=True)
            return {
                "score": {"overall": 0, "dimensions": {}, "weights": {}, "phase": "early"},
                "history": [],
                "error": str(exc),
            }

    @router.get("/api/cto-report", dependencies=[Depends(verify_auth)])
    def cto_report(days: int = 7):
        try:
            from datetime import datetime, timedelta

            cutoff = (datetime.now(runtime.et) - timedelta(days=days)).isoformat()
            open_count = runtime.query_one(
                "SELECT COUNT(*) as c FROM shadow_trades WHERE status = 'open'"
            )
            closed_recent = runtime.query(
                "SELECT ticker, pnl_dollars, pnl_pct, exit_reason FROM shadow_trades "
                "WHERE status = 'closed' AND actual_exit_time >= %s ORDER BY actual_exit_time DESC",
                (cutoff,),
            )
            packet_count = runtime.query_one(
                "SELECT COUNT(*) as c FROM recommendations WHERE created_at >= %s",
                (cutoff,),
            )
            latest_audit = runtime.query_one(
                "SELECT overall_assessment, summary FROM audit_reports ORDER BY created_at DESC LIMIT 1"
            )
            summary = _compute_trade_summary(closed_recent, open_count["c"] if open_count else 0)
            return {
                "report_period": {
                    "start": cutoff[:10],
                    "end": datetime.now(runtime.et).strftime("%Y-%m-%d"),
                },
                "headline_kpis": summary["headline_kpis"],
                "trade_summary": summary["trade_summary"],
                "fund_metrics": {
                    "psr": None,
                    "calmar_ratio": None,
                    "dsr": None,
                    "information_ratio": None,
                },
                "system_status": {
                    "model_version": "cloud",
                    "dataset_size": 0,
                },
                "period_days": days,
                "packets_generated": packet_count["c"] if packet_count else 0,
                "latest_audit": latest_audit,
                "generated_at": datetime.now(runtime.et).isoformat(),
            }
        except Exception as exc:
            runtime.logger.error("[API] cto_report failed: %s", exc, exc_info=True)
            return {"error": str(exc)}

    return router
