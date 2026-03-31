"""Cloud research, training, and data-surface routes.

Called by: api.cloud_app
Calls: none
Owns tables: none
Config keys: none
Tests: none
"""

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException

_DATA_COLLECTION_QUERIES = {
    "options_chains": (
        "SELECT COUNT(*) AS total_records, MAX(collected_at) AS latest_collection, "
        "COUNT(DISTINCT ticker) AS coverage_count FROM options_chains"
    ),
    "options_metrics": (
        "SELECT COUNT(*) AS total_records, MAX(collected_date) AS latest_collection, "
        "COUNT(DISTINCT ticker) AS coverage_count FROM options_metrics"
    ),
    "vix_term_structure": (
        "SELECT COUNT(*) AS total_records, MAX(collected_date) AS latest_collection, "
        "COUNT(DISTINCT collected_date) AS coverage_count FROM vix_term_structure"
    ),
    "macro_snapshots": (
        "SELECT COUNT(*) AS total_records, MAX(collected_date) AS latest_collection, "
        "COUNT(DISTINCT series_id) AS coverage_count FROM macro_snapshots"
    ),
    "google_trends": (
        "SELECT COUNT(*) AS total_records, MAX(collected_date) AS latest_collection, "
        "COUNT(DISTINCT ticker) AS coverage_count FROM google_trends"
    ),
    "cboe_ratios": (
        "SELECT COUNT(*) AS total_records, MAX(collected_date) AS latest_collection, "
        "COUNT(DISTINCT ratio_type) AS coverage_count FROM cboe_ratios"
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
                "SELECT * FROM model_versions WHERE status = 'active' "
                "ORDER BY created_at DESC LIMIT 1"
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
            runtime.logger.error("Metrics history error: %s", exc)
            return []

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
            runtime.logger.error("Schedule metrics error: %s", exc)
            return []

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
        except Exception as exc:
            runtime.logger.error("Docs list error: %s", exc)
            return []

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
        except Exception as exc:
            runtime.logger.error("[API] audit_history failed: %s", exc, exc_info=True)
            return []

    @router.get("/api/training/report", dependencies=[Depends(verify_auth)])
    def training_report():
        try:
            total = runtime.query_one("SELECT COUNT(*) as c FROM training_examples")
            scored = runtime.query_one(
                "SELECT COUNT(*) as c FROM training_examples WHERE quality_score IS NOT NULL"
            )
            avg_score = runtime.query_one(
                "SELECT AVG(quality_score) as avg FROM training_examples WHERE quality_score IS NOT NULL"
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
                "SELECT outcome, COUNT(*) as count FROM training_examples GROUP BY outcome"
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
    def scan_metrics_latest():
        try:
            row = runtime.query_one("SELECT * FROM scan_metrics ORDER BY created_at DESC LIMIT 1")
            return row or {}
        except Exception as exc:
            runtime.logger.error("[API] scan_metrics_latest failed: %s", exc, exc_info=True)
            return {"error": str(exc)}

    return router
