"""Cloud analytics routes and helpers for HSHS and CTO reporting.

Called by: api.cloud_app
Calls: evaluation.hshs_live
Owns tables: none
Config keys: none
Tests: none

Endpoints:
    GET /api/traffic-light/current  - Current regime and VIX
    GET /api/health/hshs            - Halcyon System Health Score
    GET /api/health/score           - Detailed health score with dimensions
    GET /api/cto-report?days=7      - Full CTO performance report
    GET /api/build-score            - Build Score from synced history (#80)
    GET /api/strategy-detail/{strategy_type} - Per-strategy analytics (Phase 5)
    GET /api/attribution/stats      - Alpha attribution stats (ranker vs LLM)
    GET /api/stress-test/results    - Historical stress test results per scenario

The HSHS dimension weights reflect our current priorities: data_asset (35%)
is highest because we're in the data accumulation phase. As we move past
the 50-trade gate into Phase 2, performance weight will increase. The
dimension computation functions are defined at module level (not inside
create_router) so they can be unit-tested independently.
"""

from fastapi import APIRouter, Depends, HTTPException

from src.shadow_trading.exit_reason import (
    EXCLUDED_FROM_OUTCOME_STATS,
    outcome_stats_filter_sql,
)
from src.evaluation.statistics import calmar_ratio as _canonical_calmar


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

    from src.analytics.canonical_sharpe import compute_sharpe
    pnls = [float(trade.get("pnl_pct", 0) or 0) for trade in closed_trades]
    pnl_dollars = [float(trade.get("pnl_dollars", 0) or 0) for trade in closed_trades]
    wins = [pnl for pnl in pnls if pnl > 0]
    losses = [pnl for pnl in pnls if pnl <= 0]
    win_rate = len(wins) / closed_count
    sharpe = compute_sharpe(pnls, periods_per_year=1, ddof=1) or 0.0
    profit_factor = (sum(wins) / abs(sum(losses))) if losses and sum(losses) != 0 else None

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
        "profit_factor": profit_factor if profit_factor is None else round(profit_factor, 2),
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


def _compute_max_consecutive(closed_trades: list[dict], direction: str = "loss") -> int:
    """Count max consecutive wins or losses in trade history.

    Fix for #254: This was hardcoded to 0. The real calculation exists in
    cto_report.py (lines 218-225) — replicated here to avoid import coupling
    with the heavyweight CTO report module.

    Args:
        closed_trades: list of trade dicts with pnl_dollars
        direction: "loss" counts consecutive losses, "win" counts consecutive wins
    """
    max_streak = 0
    current_streak = 0
    for trade in closed_trades:
        pnl = float(trade.get("pnl_dollars", 0) or 0)
        is_match = pnl <= 0 if direction == "loss" else pnl > 0
        if is_match:
            current_streak += 1
            max_streak = max(max_streak, current_streak)
        else:
            current_streak = 0
    return max_streak


def _compute_trade_summary(closed_recent: list[dict], open_count: int) -> dict:
    """Compute CTO trade-summary KPIs."""
    from src.analytics.canonical_sharpe import compute_sharpe
    pnls = [float(trade.get("pnl_pct", 0) or 0) for trade in closed_recent]
    wins = [pnl for pnl in pnls if pnl > 0]
    losses = [pnl for pnl in pnls if pnl <= 0]
    total_pnl = sum(float(trade.get("pnl_dollars", 0) or 0) for trade in closed_recent)
    sharpe = 0
    if len(pnls) >= 2:
        sharpe = round(compute_sharpe(pnls, periods_per_year=1, ddof=1) or 0.0, 3)

    gross_wins = sum(wins) if wins else 0
    gross_losses = abs(sum(losses)) if losses else 0
    profit_factor = round(gross_wins / gross_losses, 2) if gross_losses > 0 else (None if gross_wins > 0 else 0)

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
            # Fix for #254: was hardcoded to 0 — now computed from actual trade history
            "max_consecutive_losses": _compute_max_consecutive(closed_recent, "loss"),
        },
    }


def create_router(runtime, verify_auth):
    """Build the cloud analytics router."""
    router = APIRouter()

    @router.get("/api/traffic-light/current", dependencies=[Depends(verify_auth)])
    def get_traffic_light_current():
        """Current Traffic Light regime and VIX from live database."""
        try:
            row = runtime.query_one(
                "SELECT current_regime, last_total_score FROM traffic_light_state WHERE id = 1"
            )
            vix_row = runtime.query_one(
                "SELECT vix FROM vix_term_structure ORDER BY collected_date DESC LIMIT 1"
            )
            return {
                "regime": row["current_regime"] if row else "UNKNOWN",
                "score": row["last_total_score"] if row else 0,
                "vix": round(float(vix_row["vix"]), 2) if vix_row else 0,
            }
        except Exception:
            return {"regime": "UNKNOWN", "score": 0, "vix": 0}

    @router.get("/api/health/hshs", dependencies=[Depends(verify_auth)])
    def health_hshs():
        try:
            # Compute HSHS dimensions from Postgres (mirrors health/score logic)
            closed_trades = runtime.query(
                "SELECT pnl_dollars, pnl_pct FROM shadow_trades WHERE status = 'closed'"
                " AND COALESCE(quarantined, 0) = 0"
                f" {outcome_stats_filter_sql()}"
            )
            example_row = runtime.query_one("SELECT COUNT(*) as count FROM training_examples")
            scan = runtime.query_one(
                "SELECT llm_success, llm_total FROM scan_metrics ORDER BY created_at DESC LIMIT 1"
            )
            canary = runtime.query_one(
                "SELECT verdict, perplexity, distinct_2 FROM canary_evaluations ORDER BY created_at DESC LIMIT 1"
            )
            open_count_row = runtime.query_one(
                "SELECT COUNT(*) as c FROM shadow_trades WHERE status = 'open'"
                " AND COALESCE(quarantined, 0) = 0"
            )
            source_rows = runtime.query(
                "SELECT source, COUNT(*) as cnt FROM training_examples GROUP BY source"
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

            perf_score, _ = _compute_performance_score(closed_trades)
            mq_score, _ = _compute_model_quality_score(scan, canary)
            da_score, _ = _compute_data_asset_score(example_count)
            fw_score, _ = _compute_flywheel_score(closed_count, open_count)
            def_score, _ = _compute_defensibility_score(
                example_count, source_map,
                regime_row["cnt"] if regime_row else 0,
                ticker_row["cnt"] if ticker_row else 0,
            )

            dimensions = {
                "performance": round(perf_score, 2),
                "model_quality": round(mq_score, 2),
                "data_asset": round(da_score, 2),
                "flywheel_velocity": round(fw_score, 2),
                "defensibility": round(def_score, 2),
            }
            weights = {
                "performance": PERFORMANCE_WEIGHT,
                "model_quality": MODEL_QUALITY_WEIGHT,
                "data_asset": DATA_ASSET_WEIGHT,
                "flywheel_velocity": FLYWHEEL_WEIGHT,
                "defensibility": DEFENSIBILITY_WEIGHT,
            }
            overall = round(sum(dimensions[k] * weights[k] for k in dimensions), 1)

            return {
                "hshs": overall,
                "dimensions": dimensions,
                "weights": weights,
                "phase": "early",
            }
        except Exception as exc:
            runtime.logger.error("[API] HSHS computation failed: %s", exc)
            return {"hshs": 0, "dimensions": {}, "error": str(exc)}

    @router.get("/api/health/score", dependencies=[Depends(verify_auth)])
    def health_score():
        try:
            closed_trades = runtime.query(
                "SELECT pnl_dollars, pnl_pct FROM shadow_trades WHERE status = 'closed'"
                " AND COALESCE(quarantined, 0) = 0"
                f" {outcome_stats_filter_sql()}"
            )
            open_count_row = runtime.query_one(
                "SELECT COUNT(*) as c FROM shadow_trades WHERE status = 'open'"
                " AND COALESCE(quarantined, 0) = 0"
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
                " AND COALESCE(quarantined, 0) = 0"
            )
            closed_recent = runtime.query(
                "SELECT st.ticker, st.pnl_dollars, st.pnl_pct, st.exit_reason, "
                "st.duration_days, st.recommendation_id "
                "FROM shadow_trades st "
                "WHERE st.status = 'closed' AND st.actual_exit_time >= %s "
                "AND COALESCE(st.quarantined, 0) = 0 "
                "ORDER BY st.actual_exit_time DESC",
                (cutoff,),
            )
            # Filter for outcome statistics. The query above intentionally returns
            # synthetic-closure rows (e.g. exit_reason='reconciled_stale') so the
            # by_exit_reason histogram below can surface them as informational signal.
            # But all win-rate / profit-factor / band / sector / regime aggregations
            # must EXCLUDE them — they have pnl_dollars=0 with no real broker fill,
            # so counting them as losses corrupts every aggregate. #919 follow-up.
            closed_recent_for_stats = [
                t for t in closed_recent
                if not t.get("exit_reason")
                or t["exit_reason"] not in EXCLUDED_FROM_OUTCOME_STATS
            ]
            packet_count = runtime.query_one(
                "SELECT COUNT(*) as c FROM recommendations WHERE created_at >= %s",
                (cutoff,),
            )
            latest_audit = runtime.query_one(
                "SELECT overall_assessment, summary FROM audit_reports ORDER BY created_at DESC LIMIT 1"
            )
            example_row = runtime.query_one("SELECT COUNT(*) as c FROM training_examples")
            model_row = runtime.query_one(
                "SELECT version_name FROM model_versions WHERE status = 'active' "
                "ORDER BY created_at DESC LIMIT 1"
            )

            summary = _compute_trade_summary(closed_recent_for_stats, open_count["c"] if open_count else 0)

            # By exit reason
            by_exit_reason = {}
            for trade in closed_recent:
                reason = trade.get("exit_reason") or "unknown"
                if reason not in by_exit_reason:
                    by_exit_reason[reason] = {"count": 0, "pnls": []}
                by_exit_reason[reason]["count"] += 1
                by_exit_reason[reason]["pnls"].append(trade.get("pnl_pct", 0) or 0)
            for reason, data in by_exit_reason.items():
                pnls = data.pop("pnls")
                data["avg_pnl"] = round(sum(pnls) / len(pnls), 2) if pnls else 0

            # By sector/regime - join with recommendations.
            # Use closed_recent_for_stats so reconciled_stale rows don't pollute the bands.
            rec_ids = [t["recommendation_id"] for t in closed_recent_for_stats if t.get("recommendation_id")]
            rec_map = {}
            if rec_ids:
                placeholders = ", ".join(["%s"] * len(rec_ids))
                recs = runtime.query(
                    f"SELECT recommendation_id, priority_score, setup_type, market_regime "
                    f"FROM recommendations WHERE recommendation_id IN ({placeholders})",
                    tuple(rec_ids),
                )
                rec_map = {r["recommendation_id"]: r for r in recs}

            # By score band
            by_score_band = {}
            for trade in closed_recent_for_stats:
                rec = rec_map.get(trade.get("recommendation_id"), {})
                score = rec.get("priority_score", 0) or 0
                if score >= 80:
                    band = "80-100"
                elif score >= 60:
                    band = "60-79"
                elif score >= 40:
                    band = "40-59"
                else:
                    band = "0-39"
                if band not in by_score_band:
                    by_score_band[band] = {"trades": 0, "wins": 0, "pnls": []}
                by_score_band[band]["trades"] += 1
                pnl = trade.get("pnl_dollars", 0) or 0
                if pnl > 0:
                    by_score_band[band]["wins"] += 1
                by_score_band[band]["pnls"].append(trade.get("pnl_pct", 0) or 0)
            for band, data in by_score_band.items():
                pnls = data.pop("pnls")
                data["win_rate"] = round(data["wins"] / data["trades"], 3) if data["trades"] else 0
                data["avg_pnl"] = round(sum(pnls) / len(pnls), 2) if pnls else 0

            # By sector
            from src.universe.sectors import SECTOR_MAP
            by_sector = {}
            for trade in closed_recent_for_stats:
                sector = SECTOR_MAP.get(trade.get("ticker", ""), "Other")
                if sector not in by_sector:
                    by_sector[sector] = {"trades": 0, "wins": 0}
                by_sector[sector]["trades"] += 1
                if float(trade.get("pnl_dollars", 0) or 0) > 0:
                    by_sector[sector]["wins"] += 1
            for sector, data in by_sector.items():
                data["win_rate"] = round(data["wins"] / data["trades"], 3) if data["trades"] else 0

            # By regime
            by_regime = {}
            for trade in closed_recent_for_stats:
                rec = rec_map.get(trade.get("recommendation_id"), {})
                regime = rec.get("market_regime") or "unknown"
                if regime not in by_regime:
                    by_regime[regime] = {"trades": 0, "wins": 0}
                by_regime[regime]["trades"] += 1
                if float(trade.get("pnl_dollars", 0) or 0) > 0:
                    by_regime[regime]["wins"] += 1
            for regime, data in by_regime.items():
                data["win_rate"] = round(data["wins"] / data["trades"], 3) if data["trades"] else 0

            # Execution analysis. Uses closed_recent_for_stats — synthetic closures
            # have NULL/zero durations and meaningless exit_reasons, so they'd skew
            # avg_hold_period_days, targets_hit_pct, and timeout_pct.
            durations = [t.get("duration_days", 0) or 0 for t in closed_recent_for_stats]
            timeouts = [t for t in closed_recent_for_stats if t.get("exit_reason") == "timeout"]
            targets_hit = [t for t in closed_recent_for_stats if t.get("exit_reason") in ("target_1_hit", "target_2_hit", "target_1", "target_2")]
            execution_analysis = {
                "avg_hold_period_days": round(sum(durations) / len(durations), 1) if durations else 0,
                "targets_hit_pct": round(len(targets_hit) / len(closed_recent_for_stats) * 100, 1) if closed_recent_for_stats else 0,
                "timeout_pct": round(len(timeouts) / len(closed_recent_for_stats) * 100, 1) if closed_recent_for_stats else 0,
                "avg_mfe_winners": None,  # MFE requires intraday data not yet tracked
            }

            # Fund metrics — uses closed_recent_for_stats for the same reason
            pnls = [t.get("pnl_pct", 0) or 0 for t in closed_recent_for_stats]
            pnl_dollars = [t.get("pnl_dollars", 0) or 0 for t in closed_recent_for_stats]
            fund_metrics = {"sortino_ratio": None, "calmar_ratio": None, "var_95": None}
            if len(pnls) >= 2:
                mean_ret = sum(pnls) / len(pnls)
                downside = [p for p in pnls if p < 0]
                if downside:
                    downside_dev = (sum(d ** 2 for d in downside) / len(downside)) ** 0.5
                    fund_metrics["sortino_ratio"] = round(mean_ret / downside_dev, 3) if downside_dev else None
                sorted_pnls = sorted(pnls)
                idx_95 = max(0, int(len(sorted_pnls) * 0.05))
                fund_metrics["var_95"] = round(sorted_pnls[idx_95], 2)
                total_ret = sum(pnl_dollars)
                running = 0
                peak = 0
                max_dd = 0
                for p in pnl_dollars:
                    running += p
                    peak = max(peak, running)
                    max_dd = max(max_dd, peak - running)
                if max_dd > 0:
                    ann_ret = mean_ret * 252
                    fund_metrics["calmar_ratio"] = round(_canonical_calmar(annualized_return=ann_ret, max_drawdown_pct=max_dd), 3) if max_dd else None

            # --- Additional fund metrics (dashboard expects these) ---
            if pnls:
                fund_metrics["best_trade_pct"] = round(max(pnls), 2)
                fund_metrics["worst_trade_pct"] = round(min(pnls), 2)
                fund_metrics["total_return_pct"] = round(sum(pnls), 2)

                # Return skewness
                if len(pnls) >= 3:
                    n = len(pnls)
                    mean_p = sum(pnls) / n
                    std_p = (sum((p - mean_p) ** 2 for p in pnls) / (n - 1)) ** 0.5
                    if std_p > 0:
                        skew = (n / ((n - 1) * (n - 2))) * sum(((p - mean_p) / std_p) ** 3 for p in pnls)
                        fund_metrics["return_skewness"] = round(skew, 3)

                # Monthly batting avg: % of calendar months with positive total P&L.
                # Uses closed_recent_for_stats — synthetic closures contribute $0 to
                # their month, falsely flipping a winning month to break-even.
                monthly_pnl = {}
                for trade in closed_recent_for_stats:
                    exit_time = trade.get("actual_exit_time") or trade.get("updated_at") or ""
                    month_key = exit_time[:7]
                    if month_key:
                        monthly_pnl[month_key] = monthly_pnl.get(month_key, 0) + float(trade.get("pnl_dollars", 0) or 0)
                if monthly_pnl:
                    winning_months = sum(1 for v in monthly_pnl.values() if v > 0)
                    fund_metrics["monthly_batting_avg"] = round(winning_months / len(monthly_pnl) * 100, 1)

                # Avg hold period (duplicate in fund_metrics for the second card row)
                if durations:
                    fund_metrics["avg_hold_period_days"] = round(sum(durations) / len(durations), 1)

            # DB-2 Task 11: by-broker breakdown. Splits recent closed trades
            # by broker (alpaca vs ib) so the CTO report can show whether one
            # broker is dragging the overall numbers. Filters: quarantine applied
            # in the SQL query; reconciled_stale (synthetic closures) excluded
            # in-memory via closed_recent_for_stats.
            by_broker = {}
            for trade in closed_recent_for_stats:
                broker = (trade.get("broker") or "alpaca").lower()
                bucket = by_broker.setdefault(broker, {
                    "trades": 0, "wins": 0, "losses": 0,
                    "total_pnl": 0.0, "total_pnl_pct": 0.0,
                })
                pnl_d = float(trade.get("pnl_dollars") or 0)
                bucket["trades"] += 1
                bucket["total_pnl"] += pnl_d
                bucket["total_pnl_pct"] += float(trade.get("pnl_pct") or 0)
                if pnl_d > 0:
                    bucket["wins"] += 1
                else:
                    bucket["losses"] += 1
            for bucket in by_broker.values():
                bucket["total_pnl"] = round(bucket["total_pnl"], 2)
                bucket["total_pnl_pct"] = round(bucket["total_pnl_pct"], 2)
                bucket["win_rate"] = round(bucket["wins"] / bucket["trades"] * 100, 1) if bucket["trades"] else 0
                bucket["avg_pnl"] = round(bucket["total_pnl"] / bucket["trades"], 2) if bucket["trades"] else 0

            return {
                "report_period": {
                    "start": cutoff[:10],
                    "end": datetime.now(runtime.et).strftime("%Y-%m-%d"),
                },
                "headline_kpis": summary["headline_kpis"],
                "trade_summary": summary["trade_summary"],
                "by_exit_reason": by_exit_reason,
                "by_score_band": by_score_band,
                "by_sector": by_sector,
                "by_regime": by_regime,
                "by_broker": by_broker,
                "execution_analysis": execution_analysis,
                "fund_metrics": fund_metrics,
                "confidence_calibration": {},
                "system_status": {
                    "model_version": model_row["version_name"] if model_row else "cloud",
                    "dataset_size": example_row["c"] if example_row else 0,
                },
                "period_days": days,
                "packets_generated": packet_count["c"] if packet_count else 0,
                "latest_audit": latest_audit,
                "generated_at": datetime.now(runtime.et).isoformat(),
            }
        except Exception as exc:
            runtime.logger.error("[API] cto_report failed: %s", exc, exc_info=True)
            return {"error": str(exc)}

    @router.get("/api/build-score", dependencies=[Depends(verify_auth)])
    def build_score():
        try:
            # Read from synced build_score_history table instead of computing
            # from local SQLite
            latest = runtime.query_one(
                "SELECT build_score, gate_velocity, system_health, "
                "data_asset_value, model_quality, research_velocity, "
                "reliability, decay_applied, created_at "
                "FROM build_score_history ORDER BY created_at DESC LIMIT 1"
            )
            if not latest:
                return {"build_score": 0, "components": {}}

            components = {
                "gate_velocity": latest.get("gate_velocity", 0) or 0,
                "system_health": latest.get("system_health", 0) or 0,
                "data_asset_value": latest.get("data_asset_value", 0) or 0,
                "model_quality": latest.get("model_quality", 0) or 0,
                "research_velocity": latest.get("research_velocity", 0) or 0,
                "reliability": latest.get("reliability", 0) or 0,
            }

            # History: last 7 days of scores
            history_rows = runtime.query(
                "SELECT build_score FROM build_score_history "
                "ORDER BY created_at DESC LIMIT 7"
            )
            history_7d = [r["build_score"] for r in reversed(history_rows)] if history_rows else []

            # Delta 7d
            delta_7d = None
            if len(history_7d) >= 2:
                delta_7d = round(history_7d[-1] - history_7d[0], 1)

            # Phase progress from closed trades
            closed_row = runtime.query_one(
                "SELECT COUNT(*) as c FROM shadow_trades WHERE status = 'closed'"
                " AND COALESCE(quarantined, 0) = 0"
            )
            closed_count = closed_row["c"] if closed_row else 0
            phase_progress = {
                "current_phase": 1,
                "trades_required": 50,
                "trades_closed": closed_count,
                "pct_complete": round(min(100, (closed_count / 50) * 100), 1),
            }

            return {
                "build_score": latest.get("build_score", 0) or 0,
                "delta_7d": delta_7d,
                "components": components,
                "data_asset_detail": {},
                "phase_progress": phase_progress,
                "decay_today": bool(latest.get("decay_applied")),
                "history_7d": history_7d,
                "computed_at": latest.get("created_at", ""),
            }
        except Exception as exc:
            runtime.logger.error("[API] build-score failed: %s", exc, exc_info=True)
            return {"build_score": 0, "components": {}, "error": str(exc)}

    @router.get("/api/attribution/stats", dependencies=[Depends(verify_auth)])
    def attribution_stats():
        """Alpha attribution stats — ranker-only vs LLM-filtered portfolio comparison."""
        try:
            total = runtime.query_one("SELECT COUNT(*) as c FROM attribution_trades")
            total_pairs = total["c"] if total else 0

            by_action_rows = runtime.query(
                "SELECT llm_action, COUNT(*) as cnt FROM attribution_trades GROUP BY llm_action"
            )
            by_action = {r["llm_action"]: r["cnt"] for r in by_action_rows} if by_action_rows else {}

            by_pair_rows = runtime.query(
                "SELECT pair_type, COUNT(*) as cnt FROM attribution_trades GROUP BY pair_type"
            )
            by_pair = {r["pair_type"]: r["cnt"] for r in by_pair_rows} if by_pair_rows else {}

            ranker_resolved = runtime.query_one(
                "SELECT COUNT(*) as c FROM attribution_trades WHERE ranker_only_outcome != 'pending'"
            )
            ranker_wins = runtime.query_one(
                "SELECT COUNT(*) as c FROM attribution_trades WHERE ranker_only_outcome = 'win'"
            )
            llm_resolved = runtime.query_one(
                "SELECT COUNT(*) as c FROM attribution_trades WHERE llm_portfolio_outcome IS NOT NULL"
            )
            llm_wins = runtime.query_one(
                "SELECT COUNT(*) as c FROM attribution_trades WHERE llm_portfolio_outcome = 'win'"
            )
            paired_resolved = runtime.query_one(
                "SELECT COUNT(*) as c FROM attribution_trades "
                "WHERE ranker_only_outcome != 'pending' "
                "AND llm_portfolio_outcome IS NOT NULL"
            )

            def _win_rate(wins, resolved):
                return round(wins / resolved, 3) if resolved else None

            rr = ranker_resolved["c"] if ranker_resolved else 0
            rw = ranker_wins["c"] if ranker_wins else 0
            lr = llm_resolved["c"] if llm_resolved else 0
            lw = llm_wins["c"] if llm_wins else 0
            paired_n = paired_resolved["c"] if paired_resolved else 0

            return {
                "total_pairs": total_pairs,
                "by_action": by_action,
                "by_pair_type": by_pair,
                "ranker_only": {"resolved": rr, "wins": rw, "win_rate": _win_rate(rw, rr)},
                "llm_portfolio": {"resolved": lr, "wins": lw, "win_rate": _win_rate(lw, lr)},
                "statistical_power": "insufficient" if paired_n < 50 else (
                    "low" if paired_n < 200 else "adequate"),
                "paired_n": paired_n,
            }
        except Exception as exc:
            runtime.logger.error("[API] attribution_stats failed: %s", exc, exc_info=True)
            return {"total_pairs": 0, "error": str(exc)}

    @router.get("/api/strategy-detail/{strategy_type}", dependencies=[Depends(verify_auth)])
    def strategy_detail(strategy_type: str):
        """Detailed analytics for a single strategy (pullback or mean_reversion)."""
        try:
            trades = runtime.query(
                "SELECT st.ticker, st.actual_entry_time as entry_date, "
                "st.actual_exit_time as exit_date, "
                "st.pnl_pct, st.pnl_dollars, st.exit_reason, "
                "st.duration_days, r.priority_score as score, "
                "st.regime_at_entry as regime "
                "FROM shadow_trades st "
                "LEFT JOIN recommendations r ON st.recommendation_id = r.recommendation_id "
                "WHERE st.status = 'closed' AND st.strategy_type = %s "
                "AND COALESCE(st.quarantined, 0) = 0 "
                f"{outcome_stats_filter_sql()} "
                "ORDER BY st.actual_exit_time ASC",
                (strategy_type,),
            )

            if not trades:
                return {"trades": [], "by_score_band": {}, "by_regime": {},
                        "hold_distribution": [], "drawdown_series": []}

            trade_list = [dict(t) for t in trades]

            # Compute cumulative P&L
            cumulative = 0
            for t in trade_list:
                cumulative += float(t.get("pnl_dollars") or 0)
                t["cumulative_pnl"] = round(cumulative, 2)

            # Score band breakdown
            bands = {"0-39": [], "40-59": [], "60-79": [], "80-100": []}
            for t in trade_list:
                s = int(t.get("score") or 0)
                if s >= 80:
                    bands["80-100"].append(t)
                elif s >= 60:
                    bands["60-79"].append(t)
                elif s >= 40:
                    bands["40-59"].append(t)
                else:
                    bands["0-39"].append(t)

            by_score_band = {}
            for band, tlist in bands.items():
                if not tlist:
                    by_score_band[band] = {"trades": 0, "wins": 0, "win_rate": 0, "avg_pnl": 0}
                    continue
                wins = sum(1 for t in tlist if float(t.get("pnl_dollars") or 0) > 0)
                avg_pnl = sum(float(t.get("pnl_pct") or 0) for t in tlist) / len(tlist)
                by_score_band[band] = {
                    "trades": len(tlist), "wins": wins,
                    "win_rate": round(wins / len(tlist), 3),
                    "avg_pnl": round(avg_pnl, 2),
                }

            # Regime breakdown
            by_regime = {}
            for t in trade_list:
                regime = t.get("regime") or "unknown"
                if regime not in by_regime:
                    by_regime[regime] = []
                by_regime[regime].append(t)
            by_regime_out = {}
            for k, v in by_regime.items():
                wins = sum(1 for t in v if float(t.get("pnl_dollars") or 0) > 0)
                by_regime_out[k] = {
                    "trades": len(v),
                    "win_rate": round(wins / len(v), 3),
                    "avg_pnl": round(
                        sum(float(t.get("pnl_pct") or 0) for t in v) / len(v), 2
                    ),
                }

            # Hold distribution
            hold_counts: dict[int, int] = {}
            for t in trade_list:
                days = int(t.get("duration_days") or 0)
                hold_counts[days] = hold_counts.get(days, 0) + 1
            hold_distribution = [
                {"days": d, "count": c} for d, c in sorted(hold_counts.items())
            ]

            # Drawdown series
            peak = 0.0
            drawdown_series = []
            for i, t in enumerate(trade_list):
                cum = t["cumulative_pnl"]
                peak = max(peak, cum)
                dd_pct = (
                    round((peak - cum) / max(peak, 1) * 100, 1) if peak > 0 else 0
                )
                drawdown_series.append(
                    {"trade_num": i + 1, "cumulative_pnl": cum, "drawdown_pct": dd_pct}
                )

            return {
                "trades": trade_list,
                "by_score_band": by_score_band,
                "by_regime": by_regime_out,
                "hold_distribution": hold_distribution,
                "drawdown_series": drawdown_series,
            }
        except Exception as exc:
            runtime.logger.error(
                "[API] strategy_detail failed for %s: %s", strategy_type, exc,
                exc_info=True,
            )
            return {
                "trades": [], "by_score_band": {}, "by_regime": {},
                "hold_distribution": [], "drawdown_series": [],
                "error": str(exc),
            }

    # ── Stress Test Results ─────────────────────────────────────────
    @router.get("/api/stress-test/results", dependencies=[Depends(verify_auth)])
    def stress_test_results():
        """Historical stress test results from Postgres."""
        import json as _json
        try:
            rows = runtime.query(
                "SELECT * FROM stress_test_results ORDER BY created_at DESC"
            )
            results = []
            for r in rows:
                d = dict(r)
                for jf in ("monthly_returns_json", "regime_breakdown_json",
                           "equity_curve_json"):
                    if d.get(jf):
                        try:
                            d[jf] = _json.loads(d[jf])
                        except (_json.JSONDecodeError, TypeError):
                            pass
                results.append(d)
            return {"results": results}
        except Exception as exc:
            runtime.logger.error("[API] stress-test/results failed: %s", exc, exc_info=True)
            return {"results": [], "error": str(exc)}

    # ── Simulation Results ────────────────────────────────────────
    @router.get("/api/simulation/results", dependencies=[Depends(verify_auth)])
    def simulation_results():
        """Simulation engine results from Postgres."""
        import json as _json
        try:
            rows = runtime.query(
                "SELECT * FROM simulation_results ORDER BY created_at DESC"
            )
            results = []
            for r in rows:
                d = dict(r)
                for jf in ("monthly_returns_json", "equity_curve_json",
                           "regime_breakdown_json", "config_json"):
                    if d.get(jf):
                        try:
                            d[jf] = _json.loads(d[jf])
                        except (_json.JSONDecodeError, TypeError):
                            pass
                results.append(d)
            return {"results": results}
        except Exception as exc:
            runtime.logger.error("[API] simulation/results failed: %s", exc, exc_info=True)
            return {"results": [], "error": str(exc)}

    # ── Monitoring Endpoints ────────────────────────────────────────
    @router.get("/api/monitoring/history", dependencies=[Depends(verify_auth)])
    def monitoring_history(hours: int = 24):
        """System metrics history from Postgres."""
        try:
            from datetime import datetime, timedelta, timezone
            cutoff = (datetime.now(tz=timezone.utc) - timedelta(hours=hours)).isoformat()
            rows = runtime.query(
                "SELECT * FROM system_metrics WHERE timestamp > %s ORDER BY timestamp DESC LIMIT 500",
                (cutoff,),
            )
            return [dict(r) for r in rows]
        except HTTPException:
            raise
        except Exception as exc:
            # PR #690 O8: Don't swallow into [] — frontend can't distinguish
            # "no data" from "fetch failed". Raise 500 so the dashboard's
            # error boundary fires. C1 changed success shape from
            # {snapshots: [...]} to bare array; the failure-path silent []
            # introduced in that same commit was the regression we're fixing.
            runtime.logger.warning(
                "[API] monitoring/history failed: %s", exc, exc_info=True
            )
            raise HTTPException(status_code=500, detail=str(exc))

    @router.get("/api/monitoring/snapshot", dependencies=[Depends(verify_auth)])
    def monitoring_snapshot():
        """Latest system metrics snapshot (cloud mode — returns last synced data)."""
        try:
            row = runtime.query_one(
                "SELECT * FROM system_metrics ORDER BY timestamp DESC LIMIT 1"
            )
            return dict(row) if row else {"note": "No metrics synced yet"}
        except Exception as exc:
            runtime.logger.error("[API] monitoring/snapshot failed: %s", exc, exc_info=True)
            return {"note": "Monitoring not available in cloud mode", "error": str(exc)}

    return router
