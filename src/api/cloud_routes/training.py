"""Cloud research, training, and data-surface routes.

Called by: api.cloud_app
Calls: none
Owns tables: none
Config keys: none
Tests: none

Endpoints:
    GET /api/training/status         - Active model + dataset stats
    GET /api/training/versions       - Model version history
    GET /api/training/history        - Alias for /training/versions
    GET /api/training/report         - Quality scoring report
    GET /api/training/quality        - Detailed dataset breakdown
    GET /api/metrics/history?days=90 - Metric snapshots over time
    GET /api/metric-history?days=90  - Alias for /metrics/history
    GET /api/schedule-metrics?days=30- Compute schedule metrics
    GET /api/earnings?days=14        - Upcoming earnings calendar
    GET /api/data-collection-stats   - Per-table collection freshness
    GET /api/audit/latest            - Most recent audit report
    GET /api/audit/history?days=30   - Audit report history
    GET /api/docs                    - Research doc list (from research_docs table)
    GET /api/docs/{id}               - Single research doc content
    GET /api/market/overview         - Latest VIX + macro snapshot
    GET /api/data-asset/growth       - Training example growth over time
    GET /api/macro/dashboard         - Latest value per macro series
    GET /api/research/papers         - Recent high-relevance papers
    GET /api/research/digest         - Latest weekly research digest
    GET /api/scan/metrics            - Scan metrics history

The _DATA_COLLECTION_QUERIES dict mirrors the one in local system.py routes.
Both must stay in sync — if a column is renamed in the registry, both
query dicts need updating. test_stats_queries_reference_valid_columns
validates both.
"""

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException

_DATA_COLLECTION_QUERIES = {
    "options_chains": (
        "SELECT COUNT(*) AS total_records, MAX(collected_at) AS latest_collection, "
        "COUNT(DISTINCT ticker) AS coverage_count FROM options_chains"
    ),
    "options_metrics": (
        "SELECT COUNT(*) AS total_records, MAX(collected_at) AS latest_collection, "
        "COUNT(DISTINCT ticker) AS coverage_count FROM options_metrics"
    ),
    "vix_term_structure": (
        "SELECT COUNT(*) AS total_records, MAX(collected_at) AS latest_collection, "
        "COUNT(DISTINCT collected_date) AS coverage_count FROM vix_term_structure"
    ),
    "macro_snapshots": (
        "SELECT COUNT(*) AS total_records, MAX(collected_at) AS latest_collection, "
        "COUNT(DISTINCT series_id) AS coverage_count FROM macro_snapshots"
    ),
    "google_trends": (
        "SELECT COUNT(*) AS total_records, MAX(collected_at) AS latest_collection, "
        "COUNT(DISTINCT ticker) AS coverage_count FROM google_trends"
    ),
    "cboe_ratios": (
        "SELECT COUNT(*) AS total_records, MAX(collected_at) AS latest_collection, "
        "COUNT(DISTINCT collected_date) AS coverage_count FROM cboe_ratios"
    ),
    "earnings_calendar": (
        "SELECT COUNT(*) AS total_records, MAX(collected_at) AS latest_collection, "
        "COUNT(DISTINCT ticker) AS coverage_count FROM earnings_calendar"
    ),
    "edgar_filings": (
        "SELECT COUNT(*) AS total_records, MAX(collected_at) AS latest_collection, "
        "COUNT(DISTINCT ticker) AS coverage_count FROM edgar_filings"
    ),
    "insider_transactions": (
        "SELECT COUNT(*) AS total_records, MAX(collected_at) AS latest_collection, "
        "COUNT(DISTINCT ticker) AS coverage_count FROM insider_transactions"
    ),
    "short_interest": (
        "SELECT COUNT(*) AS total_records, MAX(collected_at) AS latest_collection, "
        "COUNT(DISTINCT ticker) AS coverage_count FROM short_interest"
    ),
    "fed_communications": (
        "SELECT COUNT(*) AS total_records, MAX(collected_at) AS latest_collection, "
        "COUNT(DISTINCT comm_type) AS coverage_count FROM fed_communications"
    ),
    "analyst_estimates": (
        "SELECT COUNT(*) AS total_records, MAX(collected_at) AS latest_collection, "
        "COUNT(DISTINCT ticker) AS coverage_count FROM analyst_estimates"
    ),
}


def _zero_data_collection_shape() -> dict:
    return {"total_records": 0, "latest_collection": None, "coverage_count": 0}


def create_router(runtime, verify_auth):
    """Build the cloud training/data router."""
    router = APIRouter()

    @router.get("/api/training/status", dependencies=[Depends(verify_auth)])
    def training_status():
        try:
            active_model = runtime.query_one(
                "SELECT * FROM model_versions ORDER BY created_at DESC LIMIT 1"
            )
            total_versions = runtime.query("SELECT COUNT(*) as count FROM model_versions")
            total_examples = runtime.query_one("SELECT COUNT(*) as c FROM training_examples")
            win_examples = runtime.query_one(
                "SELECT COUNT(*) as c FROM training_examples WHERE outcome = 'win' OR source = 'blinded_win'"
            )
            loss_examples = runtime.query_one(
                "SELECT COUNT(*) as c FROM training_examples WHERE outcome = 'loss' OR source = 'blinded_loss'"
            )
            synthetic_examples = runtime.query_one(
                "SELECT COUNT(*) as c FROM training_examples WHERE source = 'synthetic_claude' OR source = 'synthetic'"
            )
            model_name = active_model["version_name"] if active_model else "base"

            # Avg quality score (COALESCE auto vs manual)
            avg_row = runtime.query_one(
                "SELECT AVG(COALESCE(quality_score_auto, quality_score)) as avg "
                "FROM training_examples "
                "WHERE COALESCE(quality_score_auto, quality_score) IS NOT NULL"
            )
            avg_quality = round(avg_row["avg"], 2) if avg_row and avg_row["avg"] else None

            # Outcome counts
            outcome_rows = runtime.query(
                "SELECT outcome, COUNT(*) as count FROM training_examples "
                "WHERE outcome IS NOT NULL GROUP BY outcome"
            )
            outcome_counts = {r["outcome"]: r["count"] for r in outcome_rows} if outcome_rows else None

            # Source counts
            source_rows = runtime.query(
                "SELECT source, COUNT(*) as count FROM training_examples GROUP BY source"
            )
            source_counts = {r["source"]: r["count"] for r in source_rows} if source_rows else None

            # Ticker coverage
            ticker_row = runtime.query_one(
                "SELECT COUNT(DISTINCT ticker) as covered FROM training_examples "
                "WHERE ticker IS NOT NULL"
            )
            ticker_coverage = {
                "covered": ticker_row["covered"] if ticker_row else 0,
                "total": 102,
            } if ticker_row and ticker_row["covered"] else None

            # Regime coverage (market regime: bull/bear/cautious)
            regime_rows = runtime.query(
                "SELECT regime, COUNT(*) as count FROM training_examples "
                "WHERE regime IS NOT NULL GROUP BY regime"
            )
            regime_coverage = {r["regime"]: r["count"] for r in regime_rows} if regime_rows else None

            # Curriculum stage coverage
            stage_rows = runtime.query(
                "SELECT curriculum_stage, COUNT(*) as count FROM training_examples "
                "WHERE curriculum_stage IS NOT NULL GROUP BY curriculum_stage"
            )
            curriculum_coverage = {r["curriculum_stage"]: r["count"] for r in stage_rows} if stage_rows else None

            # Examples this week
            week_ago = (datetime.now(runtime.et) - timedelta(days=7)).isoformat()
            week_row = runtime.query_one(
                "SELECT COUNT(*) as c FROM training_examples WHERE created_at >= %s",
                (week_ago,),
            )
            examples_this_week = week_row["c"] if week_row else 0

            # Recent examples
            recent_rows = runtime.query(
                "SELECT ticker, source, outcome_type, "
                "COALESCE(composite_score, quality_score_auto, quality_score) as quality_score, "
                "created_at FROM training_examples ORDER BY created_at DESC LIMIT 10"
            )

            return {
                "active_model": active_model,
                "total_versions": total_versions[0]["count"] if total_versions else 0,
                "model_name": model_name,
                "dataset_total": total_examples["c"] if total_examples else 0,
                "dataset_wins": win_examples["c"] if win_examples else 0,
                "dataset_losses": loss_examples["c"] if loss_examples else 0,
                "dataset_synthetic": synthetic_examples["c"] if synthetic_examples else 0,
                "new_since_last_train": 0,
                "train_queued": False,
                "train_reason": "Cloud mode — training runs locally",
                "rollback_status": "n/a (cloud mode)",
                "avg_quality_score": avg_quality,
                "outcome_counts": outcome_counts,
                "source_counts": source_counts,
                "ticker_coverage": ticker_coverage,
                "regime_coverage": regime_coverage,
                "curriculum_coverage": curriculum_coverage,
                "examples_this_week": examples_this_week,
                "recent_examples": recent_rows,
            }
        except HTTPException:
            raise
        except Exception as exc:
            runtime.logger.error("Training status error: %s", exc)
            return {
                "active_model": None,
                "model_name": "base",
                "dataset_total": 0,
                "dataset_wins": 0,
                "dataset_losses": 0,
                "dataset_synthetic": 0,
                "new_since_last_train": 0,
                "train_queued": False,
                "error": str(exc),
            }

    @router.get("/api/training/versions", dependencies=[Depends(verify_auth)])
    def training_versions():
        try:
            return {"versions": runtime.query("SELECT * FROM model_versions ORDER BY created_at DESC")}
        except HTTPException:
            raise
        except Exception as exc:
            runtime.logger.error("Training versions error: %s", exc)
            return {"versions": []}

    @router.get("/api/metrics/history", dependencies=[Depends(verify_auth)])
    def metrics_history(days: int = 90):
        try:
            cutoff = (datetime.now(runtime.et) - timedelta(days=days)).isoformat()
            rows = runtime.query(
                "SELECT * FROM metric_snapshots WHERE created_at >= %s "
                "ORDER BY snapshot_date ASC",
                (cutoff,),
            )
            for row in rows:
                runtime.parse_json_fields(row, ["metrics_json"])
            return rows
        except HTTPException:
            raise
        except Exception as exc:
            # PR #690 O8: Don't swallow into [] — surface 500 so the
            # dashboard error boundary can fire (frontend can't tell
            # "no metrics yet" from "fetch failed" if we return []).
            runtime.logger.warning(
                "[API] metrics/history failed: %s", exc, exc_info=True
            )
            raise HTTPException(status_code=500, detail=str(exc))

    @router.get("/api/schedule-metrics", dependencies=[Depends(verify_auth)])
    def schedule_metrics(days: int = 30):
        try:
            cutoff = (datetime.now(runtime.et) - timedelta(days=days)).strftime("%Y-%m-%d")
            return runtime.query(
                "SELECT * FROM schedule_metrics WHERE metric_date >= %s "
                "ORDER BY metric_date DESC",
                (cutoff,),
            )
        except HTTPException:
            raise
        except Exception as exc:
            # PR #690 O8: surface 500 instead of silent [] so frontend
            # error boundary fires.
            runtime.logger.warning(
                "[API] schedule-metrics failed: %s", exc, exc_info=True
            )
            raise HTTPException(status_code=500, detail=str(exc))

    @router.get("/api/earnings", dependencies=[Depends(verify_auth)])
    def earnings(days: int = 14):
        try:
            today = datetime.now(runtime.et).strftime("%Y-%m-%d")
            future = (datetime.now(runtime.et) + timedelta(days=days)).strftime("%Y-%m-%d")
            rows = runtime.query(
                "SELECT * FROM earnings_calendar "
                "WHERE earnings_date >= %s AND earnings_date <= %s "
                "ORDER BY earnings_date ASC",
                (today, future),
            )
            return {"days_ahead": days, "count": len(rows), "earnings": rows}
        except HTTPException:
            raise
        except Exception as exc:
            runtime.logger.error("Earnings error: %s", exc)
            return {"days_ahead": days, "count": 0, "earnings": [], "error": str(exc)}

    @router.get("/api/data-collection-stats", dependencies=[Depends(verify_auth)])
    def data_collection_stats():
        stats = {}
        for table_name, sql in _DATA_COLLECTION_QUERIES.items():
            try:
                row = runtime.query_one(sql) or {}
                total_records = row.get("total_records", 0) or 0
                stats[table_name] = {
                    "total_records": total_records,
                    "latest_collection": row.get("latest_collection") if total_records else None,
                    "coverage_count": row.get("coverage_count", 0) if total_records else 0,
                }
            except Exception as exc:
                runtime.logger.warning("[API] data_collection_stats %s failed: %s", table_name, exc)
                stats[table_name] = _zero_data_collection_shape()
        return stats

    @router.get("/api/audit/latest", dependencies=[Depends(verify_auth)])
    def audit_latest():
        try:
            row = runtime.query_one(
                "SELECT * FROM audit_reports ORDER BY created_at DESC LIMIT 1"
            )
            if not row:
                return {"audit": None}
            runtime.parse_json_fields(row, ["flags", "metrics_to_watch"])
            return row
        except HTTPException:
            raise
        except Exception as exc:
            runtime.logger.error("Audit latest error: %s", exc)
            return {"audit": None, "error": str(exc)}

    @router.get("/api/docs", dependencies=[Depends(verify_auth)])
    def docs_list():
        try:
            rows = runtime.query(
                "SELECT id, filename, title, category, size_kb, updated_at "
                "FROM research_docs ORDER BY category, title"
            )
            return [
                {
                    "id": row["id"],
                    "filename": row.get("filename", ""),
                    "title": row["title"],
                    "category": row.get("category", "Uncategorized"),
                    "size_kb": row.get("size_kb", 0),
                    "available": True,
                }
                for row in rows
            ]
        except HTTPException:
            raise
        except Exception as exc:
            # PR #690 O8: surface 500 instead of silent [] so frontend
            # error boundary can fire (frontend can't tell "no docs" from
            # "fetch failed" if we return []).
            runtime.logger.warning(
                "[API] docs list failed: %s", exc, exc_info=True
            )
            raise HTTPException(status_code=500, detail=str(exc))

    @router.get("/api/docs/{doc_id}", dependencies=[Depends(verify_auth)])
    def get_doc(doc_id: str):
        try:
            row = runtime.query_one(
                "SELECT id, title, category, content FROM research_docs WHERE id = %s",
                (doc_id,),
            )
            if row:
                return {
                    "id": row["id"],
                    "title": row["title"],
                    "category": row.get("category", ""),
                    "content": row["content"],
                }
            return {
                "id": doc_id,
                "title": doc_id,
                "content": f"# {doc_id}\n\nDocument not found. It may not have been synced yet.",
            }
        except Exception as exc:
            runtime.logger.error("Docs read error: %s", exc)
            return {
                "id": doc_id,
                "title": doc_id,
                "content": f"# Error\n\nFailed to load document: {exc}",
            }

    @router.get("/api/audit/history", dependencies=[Depends(verify_auth)])
    def audit_history(days: int = 30):
        try:
            cutoff = (datetime.now(runtime.et) - timedelta(days=days)).isoformat()
            return runtime.query(
                "SELECT * FROM audit_reports WHERE created_at >= %s ORDER BY created_at DESC",
                (cutoff,),
            )
        except HTTPException:
            raise
        except Exception as exc:
            # PR #690 O8: surface 500 instead of silent [].
            runtime.logger.warning(
                "[API] audit/history failed: %s", exc, exc_info=True
            )
            raise HTTPException(status_code=500, detail=str(exc))

    @router.get("/api/training/report", dependencies=[Depends(verify_auth)])
    def training_report():
        try:
            total = runtime.query_one("SELECT COUNT(*) as c FROM training_examples")
            scored = runtime.query_one(
                "SELECT COUNT(*) as c FROM training_examples "
                "WHERE COALESCE(quality_score_auto, quality_score) IS NOT NULL"
            )
            avg_score = runtime.query_one(
                "SELECT AVG(COALESCE(quality_score_auto, quality_score)) as avg "
                "FROM training_examples "
                "WHERE COALESCE(quality_score_auto, quality_score) IS NOT NULL"
            )
            return {
                "total_examples": total["c"] if total else 0,
                "scored": scored["c"] if scored else 0,
                "unscored": (total["c"] if total else 0) - (scored["c"] if scored else 0),
                "avg_quality_score": round(avg_score["avg"], 2)
                if avg_score and avg_score["avg"]
                else None,
            }
        except Exception as exc:
            runtime.logger.error("[API] training_report failed: %s", exc, exc_info=True)
            return {"total_examples": 0, "scored": 0, "unscored": 0, "error": str(exc)}

    @router.get("/api/metric-history", dependencies=[Depends(verify_auth)])
    def metric_history(days: int = 90):
        return metrics_history(days)

    @router.get("/api/market/overview", dependencies=[Depends(verify_auth)])
    def market_overview():
        try:
            vix = runtime.query_one(
                "SELECT * FROM vix_term_structure ORDER BY collected_date DESC LIMIT 1"
            )
            macro = runtime.query(
                "SELECT series_id, series_name, value, change_pct FROM macro_snapshots "
                "WHERE collected_date = (SELECT MAX(collected_date) FROM macro_snapshots)"
            )
            return {"vix": vix, "macro": macro}
        except Exception as exc:
            runtime.logger.error("[API] market_overview failed: %s", exc, exc_info=True)
            return {"vix": None, "macro": [], "error": str(exc)}

    @router.get("/api/data-asset/growth", dependencies=[Depends(verify_auth)])
    def data_asset_growth():
        try:
            rows = runtime.query(
                "SELECT DATE(created_at) as date, COUNT(*) as count "
                "FROM training_examples GROUP BY DATE(created_at) ORDER BY date"
            )
            return {"daily_counts": rows}
        except Exception as exc:
            runtime.logger.error("[API] data_asset_growth failed: %s", exc, exc_info=True)
            return {"daily_counts": [], "error": str(exc)}

    @router.get("/api/macro/dashboard", dependencies=[Depends(verify_auth)])
    def macro_dashboard():
        try:
            rows = runtime.query(
                "SELECT DISTINCT ON (series_id) series_id, series_name, value, "
                "previous_value, change_pct, collected_date "
                "FROM macro_snapshots ORDER BY series_id, collected_date DESC"
            )
            return {"series": rows}
        except Exception as exc:
            runtime.logger.error("[API] macro_dashboard failed: %s", exc, exc_info=True)
            return {"series": [], "error": str(exc)}

    @router.get("/api/research/papers", dependencies=[Depends(verify_auth)])
    def research_papers(days: int = 7, min_score: float = 0.4):
        try:
            cutoff = (datetime.now(runtime.et) - timedelta(days=days)).isoformat()
            rows = runtime.query(
                "SELECT id, source, title, authors, abstract, url, published_date, "
                "relevance_score, relevance_reason, actionable, collected_at "
                "FROM research_papers WHERE collected_at >= %s AND relevance_score >= %s "
                "ORDER BY relevance_score DESC",
                (cutoff, min_score),
            )
            return {"papers": rows, "count": len(rows)}
        except Exception as exc:
            runtime.logger.error("[API] research_papers failed: %s", exc, exc_info=True)
            return {"papers": [], "count": 0, "error": str(exc)}

    @router.get("/api/research/digest", dependencies=[Depends(verify_auth)])
    def research_digest():
        try:
            row = runtime.query_one(
                "SELECT * FROM research_digests ORDER BY created_at DESC LIMIT 1"
            )
            return row or {"digest": None}
        except Exception as exc:
            runtime.logger.error("[API] research_digest failed: %s", exc, exc_info=True)
            return {"digest": None, "error": str(exc)}

    @router.get("/api/training/quality", dependencies=[Depends(verify_auth)])
    def training_quality():
        try:
            total = runtime.query_one("SELECT COUNT(*) as c FROM training_examples")
            by_source = runtime.query(
                "SELECT source, COUNT(*) as count FROM training_examples GROUP BY source"
            )
            by_stage = runtime.query(
                "SELECT curriculum_stage, COUNT(*) as count FROM training_examples GROUP BY curriculum_stage"
            )
            by_outcome = runtime.query(
                "SELECT outcome_type, COUNT(*) as count FROM training_examples GROUP BY outcome_type"
            )
            return {
                "total": total["c"] if total else 0,
                "by_source": by_source,
                "by_stage": by_stage,
                "by_outcome": by_outcome,
            }
        except Exception as exc:
            runtime.logger.error("[API] training_quality failed: %s", exc, exc_info=True)
            return {
                "total": 0,
                "by_source": [],
                "by_stage": [],
                "by_outcome": [],
                "error": str(exc),
            }

    @router.get("/api/scan/metrics", dependencies=[Depends(verify_auth)])
    def scan_metrics_list(limit: int = 20):
        try:
            rows = runtime.query(
                "SELECT * FROM scan_metrics ORDER BY created_at DESC LIMIT %s",
                (min(limit, 100),),
            )
            return rows
        except HTTPException:
            raise
        except Exception as exc:
            # PR #690 O8: surface 500 instead of silent [].
            runtime.logger.warning(
                "[API] scan/metrics failed: %s", exc, exc_info=True
            )
            raise HTTPException(status_code=500, detail=str(exc))

    @router.get("/api/training/history", dependencies=[Depends(verify_auth)])
    def training_history():
        return training_versions()

    @router.get("/api/model-performance", dependencies=[Depends(verify_auth)])
    def model_performance():
        """Per-model-version live performance metrics."""
        try:
            from src.evaluation.model_monitor import _compute_metrics, _build_equity_curve

            # Model versions metadata
            model_rows = runtime.query(
                "SELECT version_id, version_name, created_at, "
                "training_examples_count, holdout_score, status "
                "FROM model_versions ORDER BY created_at DESC"
            ) or []
            versions_meta = {}
            for mv in model_rows:
                versions_meta[mv["version_name"]] = {
                    "version_id": mv["version_id"],
                    "created_at": (mv["created_at"] or "")[:10],
                    "training_examples": mv.get("training_examples_count") or 0,
                    "holdout_score": mv.get("holdout_score"),
                    "status": mv.get("status") or "unknown",
                }

            # Closed trades with model version
            trades = runtime.query(
                "SELECT st.trade_id, st.ticker, st.pnl_dollars, st.pnl_pct, "
                "st.exit_reason, st.duration_days, st.actual_exit_time, "
                "st.created_at, r.model_version "
                "FROM shadow_trades st "
                "LEFT JOIN recommendations r ON st.recommendation_id = r.recommendation_id "
                "WHERE st.status = 'closed' AND st.pnl_dollars IS NOT NULL "
                "AND COALESCE(st.quarantined, 0) = 0 "
                "ORDER BY st.actual_exit_time ASC"
            ) or []

            # Group by model version
            by_version = {}
            for t in trades:
                ver = t.get("model_version") or "unknown"
                by_version.setdefault(ver, []).append(t)

            models = []
            for ver, ver_trades in by_version.items():
                metrics = _compute_metrics(ver_trades)
                curve = _build_equity_curve(ver_trades)
                meta = versions_meta.get(ver, {})
                models.append({
                    "version": ver,
                    "meta": meta,
                    "live_metrics": metrics,
                    "equity_curve": curve,
                })

            # Overall metrics
            overall = _compute_metrics(trades) if trades else {}

            return {
                "models": models,
                "overall": overall,
                "total_closed_trades": len(trades),
            }
        except Exception as exc:
            runtime.logger.error("[API] model-performance failed: %s", exc, exc_info=True)
            return {"models": [], "overall": {}, "total_closed_trades": 0, "error": str(exc)}

    return router
