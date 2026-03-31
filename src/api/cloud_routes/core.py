"""Cloud core routes for auth, status, config, and actions.

Called by: api.cloud_app
Calls: none
Owns tables: none
Config keys: none
Tests: none
"""

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException


def create_router(runtime, verify_auth):
    """Build the cloud core router."""
    router = APIRouter()

    @router.get("/healthz")
    def healthz():
        return {"status": "ok"}

    @router.get("/api/diagnostics", dependencies=[Depends(verify_auth)])
    def diagnostics():
        results = {}
        for table in runtime.diagnostic_tables:
            try:
                row = runtime.query_one(f"SELECT COUNT(*) as c FROM {table}")  # noqa: S608
                results[table] = {"status": "ok", "rows": row["c"] if row else 0}
            except Exception as exc:
                results[table] = {"status": "error", "error": str(exc)}

        failed = [table for table, result in results.items() if result["status"] == "error"]
        return {
            "status": "healthy" if not failed else "degraded",
            "tables": results,
            "failed_count": len(failed),
            "failed_tables": failed,
        }

    @router.get("/api/auth", dependencies=[Depends(verify_auth)])
    def auth_check():
        return {"authenticated": True}

    @router.get("/api/status", dependencies=[Depends(verify_auth)])
    def status():
        try:
            open_trades = runtime.query(
                "SELECT COUNT(*) as count FROM shadow_trades WHERE status = 'open'"
            )
            closed_trades = runtime.query(
                "SELECT COUNT(*) as count FROM shadow_trades WHERE status = 'closed'"
            )
            latest_model = runtime.query_one(
                "SELECT version_name, created_at, status FROM model_versions "
                "ORDER BY created_at DESC LIMIT 1"
            )
            latest_audit = runtime.query_one(
                "SELECT overall_assessment, created_at FROM audit_reports "
                "ORDER BY created_at DESC LIMIT 1"
            )

            try:
                training_examples = runtime.query_one(
                    "SELECT COUNT(*) as c FROM training_examples"
                )
                example_count = training_examples["c"] if training_examples else 0
            except Exception as exc:
                runtime.logger.warning("[API] training_examples count failed: %s", exc)
                example_count = 0

            model_name = latest_model["version_name"] if latest_model else "base"
            return {
                "environment": "cloud",
                "open_positions": open_trades[0]["count"] if open_trades else 0,
                "closed_trades": closed_trades[0]["count"] if closed_trades else 0,
                "latest_model": latest_model,
                "latest_audit": latest_audit,
                "llm_available": False,
                "model_version": model_name,
                "training_examples": example_count,
                "alpaca_equity": 0,
                "timestamp": datetime.now(runtime.et).isoformat(),
            }
        except HTTPException:
            raise
        except Exception as exc:
            runtime.logger.error("Status endpoint error: %s", exc)
            return {
                "environment": "cloud",
                "error": str(exc),
                "timestamp": datetime.now(runtime.et).isoformat(),
            }

    @router.get("/api/config", dependencies=[Depends(verify_auth)])
    def get_config():
        return {
            "risk": {
                "starting_capital": 100000,
                "planned_risk_pct_min": 0.005,
                "planned_risk_pct_max": 0.01,
                "max_open_positions": 50,
            },
            "shadow_trading": {"enabled": True, "max_positions": 50, "timeout_days": 15},
            "llm": {"enabled": True, "model": "halcyonlatest", "temperature": 0.7},
            "bootcamp": {
                "enabled": True,
                "phase": 1,
                "qualification_threshold": 40,
                "email_mode": "daily_summary",
            },
            "automation": {
                "morning_watchlist_hour_et": 8,
                "eod_recap_hour_et": 16,
                "scan_interval_minutes": 30,
            },
            "training": {
                "enabled": True,
                "claude_model": "claude-sonnet-4-20250514",
                "auto_train_threshold": 50,
            },
            "environment": "cloud",
        }

    @router.get("/api/halt-status", dependencies=[Depends(verify_auth)])
    def halt_status():
        return {"halted": False, "reason": None, "halted_at": None}

    @router.get("/api/costs", dependencies=[Depends(verify_auth)])
    def costs(days: int = 30):
        try:
            cutoff = (datetime.now(runtime.et) - timedelta(days=days)).isoformat()
            rows = runtime.query(
                "SELECT model, purpose, SUM(input_tokens) as total_input, "
                "SUM(output_tokens) as total_output, SUM(estimated_cost) as total_cost, "
                "COUNT(*) as call_count "
                "FROM api_costs WHERE created_at >= %s "
                "GROUP BY model, purpose ORDER BY total_cost DESC",
                (cutoff,),
            )
            total = sum(row.get("total_cost", 0) or 0 for row in rows)
            return {"days": days, "total_cost": round(total, 4), "breakdown": rows}
        except Exception as exc:
            runtime.logger.error("[API] costs failed: %s", exc, exc_info=True)
            return {"days": days, "total_cost": 0, "breakdown": [], "error": str(exc)}

    @router.get("/api/settings", dependencies=[Depends(verify_auth)])
    def get_settings():
        return {
            "risk": {
                "max_position_pct": 0.25,
                "max_open_positions": 50,
                "max_sector_pct": 0.22,
            },
            "bootcamp": {
                "max_packets_per_scan": 20,
                "min_score": 40,
            },
            "trading": {
                "email_mode": "daily_summary",
            },
            "schedule": {
                "between_scan_scoring": True,
                "overnight_schedule": True,
            },
            "system": {
                "model_version": "halcyonlatest",
                "python_version": "3.12",
                "environment": "cloud",
            },
        }

    @router.post("/api/settings", dependencies=[Depends(verify_auth)])
    def update_settings():
        return {
            "error": "cloud_mode",
            "message": "Settings can only be changed on the local machine.",
        }

    @router.post("/api/live/reconcile", dependencies=[Depends(verify_auth)])
    def live_reconcile():
        return {
            "error": "cloud_mode",
            "message": "Reconciliation must be run locally via CLI: python -m src.main reconcile-live",
        }

    def _cloud_only_action():
        return runtime.cloud_action_msg

    def _cloud_only_close_action(ticker: str):
        _ = ticker
        return runtime.cloud_action_msg

    for path in (
        "/api/actions/scan",
        "/api/actions/cto-report",
        "/api/actions/collect-data",
        "/api/actions/collect-training",
        "/api/actions/train-pipeline",
        "/api/actions/score",
        "/api/actions/council",
        "/api/halt-trading",
        "/api/resume-trading",
        "/api/training/train",
        "/api/training/bootstrap",
        "/api/training/rollback",
    ):
        router.add_api_route(
            path,
            _cloud_only_action,
            methods=["POST"],
            dependencies=[Depends(verify_auth)],
        )

    router.add_api_route(
        "/api/shadow/close/{ticker}",
        _cloud_only_close_action,
        methods=["POST"],
        dependencies=[Depends(verify_auth)],
    )

    return router
