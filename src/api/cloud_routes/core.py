"""Cloud core routes for auth, status, config, actions, and command queue.

Called by: api.cloud_app
Calls: sync.render_sync
Owns tables: none (reads Postgres)
Config keys: none
Tests: tests/test_cloud_app.py

Endpoints:
    GET  /healthz                          - Render health check (no auth)
    GET  /api/diagnostics                  - Postgres table health check
    GET  /api/auth                         - Auth token validation
    GET  /api/status                       - System status summary
    GET  /api/config                       - Static config (cloud has no YAML)
    GET  /api/halt-status                  - Always false in cloud mode
    GET  /api/costs?days=30                - API cost breakdown
    POST /api/commands/submit              - Submit command to queue
    GET  /api/commands/{id}/status         - Check command status
    GET  /api/commands/recent              - Recent command list
    GET  /api/logs/recent                  - Log entries from Postgres
    GET  /api/settings                     - Settings with overrides
    POST /api/settings                     - Submit config change via queue
    DELETE /api/settings/overrides         - Clear all overrides
    POST /api/actions/{action}             - All action endpoints (submit to queue)
    POST /api/shadow/close/{ticker}        - Close position via queue
    POST /api/training/{action}            - Training actions via queue
    POST /api/live/reconcile               - Cloud-blocked (local only)
    GET  /api/system/validation            - Latest validation result
    GET  /api/system/table-counts          - Row counts for DB Schema page

Action endpoints in cloud mode don't execute directly — they submit commands
to the pending_commands queue in Postgres. The local machine's sync thread
pulls these commands and executes them. This is why actions return a
command_id and status="pending" rather than actual results.
"""

import uuid
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel


class CommandSubmission(BaseModel):
    command_name: str
    command_type: str = "action"
    payload: dict = {}
    priority: int = 0


class SettingsUpdate(BaseModel):
    key: str
    value: object


def create_router(runtime, verify_auth):
    """Build the cloud core router."""
    router = APIRouter()

    # ── Helpers ─────────────────────────────────────────────────────

    def _submit_command(
        command_name: str,
        command_type: str = "action",
        payload: dict | None = None,
        priority: int = 0,
    ) -> dict:
        """Write a command to pending_commands in Render Postgres.

        Commands expire after 5 minutes to prevent stale actions from
        executing after the local machine reconnects from a long outage.
        The local sync thread picks these up via pull_commands() and
        executes them, writing results back to command_results.
        """
        command_id = str(uuid.uuid4())
        now = datetime.now(runtime.et)
        expires_at = (now + timedelta(minutes=5)).isoformat()

        import json
        payload_json = json.dumps(payload or {})

        try:
            with runtime.get_pg(readonly=False) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "INSERT INTO pending_commands "
                        "(command_id, command_type, command_name, payload_json, "
                        "status, priority, created_at, expires_at, created_by) "
                        "VALUES (%s, %s, %s, %s, 'pending', %s, %s, %s, 'dashboard')",
                        (
                            command_id, command_type, command_name,
                            payload_json, priority, now.isoformat(), expires_at,
                        ),
                    )
                    conn.commit()
        except Exception as exc:
            raise HTTPException(status_code=503, detail=f"Database unavailable: {exc}")

        return {
            "command_id": command_id,
            "status": "pending",
            "expires_at": expires_at,
        }

    # ── Health & auth ──────────────────────────────────────────────

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

    # ── Status & config ────────────────────────────────────────────

    @router.get("/api/status", dependencies=[Depends(verify_auth)])
    def status():
        try:
            open_trades = runtime.query(
                "SELECT COUNT(*) as count FROM shadow_trades WHERE status = 'open'"
                " AND COALESCE(quarantined, 0) = 0"
            )
            closed_trades = runtime.query(
                "SELECT COUNT(*) as count FROM shadow_trades WHERE status = 'closed'"
                " AND COALESCE(quarantined, 0) = 0"
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
                "SUM(output_tokens) as total_output, "
                "SUM(COALESCE(cost_dollars, estimated_cost, 0)) as total_cost, "
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

    # ── Command queue endpoints ────────────────────────────────────

    @router.post("/api/commands/submit", dependencies=[Depends(verify_auth)])
    def submit_command(body: CommandSubmission):
        """Submit a command to the queue for local execution."""
        try:
            result = _submit_command(
                command_name=body.command_name,
                command_type=body.command_type,
                payload=body.payload,
                priority=body.priority,
            )
            return result
        except Exception as exc:
            runtime.logger.error("Command submission failed: %s", exc)
            raise HTTPException(status_code=500, detail=str(exc))

    @router.get("/api/commands/{command_id}/status", dependencies=[Depends(verify_auth)])
    def command_status(command_id: str):
        """Check command + result status."""
        cmd = runtime.query_one(
            "SELECT * FROM pending_commands WHERE command_id = %s",
            (command_id,),
        )
        if not cmd:
            raise HTTPException(status_code=404, detail="Command not found")

        result = runtime.query_one(
            "SELECT * FROM command_results WHERE command_id = %s "
            "ORDER BY created_at DESC LIMIT 1",
            (command_id,),
        )
        return {"command": cmd, "result": result}

    @router.get("/api/commands/recent", dependencies=[Depends(verify_auth)])
    def recent_commands(limit: int = 20):
        """Last N commands with their results."""
        commands = runtime.query(
            "SELECT c.*, r.status as result_status, r.result_json, "
            "r.error_message, r.execution_ms "
            "FROM pending_commands c "
            "LEFT JOIN command_results r ON c.command_id = r.command_id "
            "ORDER BY c.created_at DESC LIMIT %s",
            (min(limit, 50),),
        )
        return {"commands": commands, "count": len(commands)}

    # ── Log entries ────────────────────────────────────────────────

    @router.get("/api/logs/recent", dependencies=[Depends(verify_auth)])
    def recent_logs(level: str = "INFO", limit: int = 100, source: str = None):
        """Query log_entries table."""
        params = []
        where_clauses = []

        if level and level != "ALL":
            level_order = {"DEBUG": 0, "INFO": 1, "WARNING": 2, "ERROR": 3, "CRITICAL": 4}
            min_level = level_order.get(level.upper(), 1)
            allowed = [k for k, v in level_order.items() if v >= min_level]
            placeholders = ", ".join(["%s"] * len(allowed))
            where_clauses.append(f"log_level IN ({placeholders})")
            params.extend(allowed)

        if source:
            where_clauses.append("source = %s")
            params.append(source)

        where = " AND ".join(where_clauses) if where_clauses else "1=1"
        params.append(min(limit, 500))

        logs = runtime.query(
            f"SELECT * FROM log_entries WHERE {where} "
            f"ORDER BY created_at DESC LIMIT %s",
            tuple(params),
        )
        return {"logs": logs, "count": len(logs)}

    # ── Settings (now writes to command queue) ─────────────────────

    @router.get("/api/settings", dependencies=[Depends(verify_auth)])
    def get_settings():
        """Return current settings including any dashboard overrides."""
        from src.config_overrides import WHITELISTED_KEYS

        # Read overrides from Postgres
        overrides = {}
        try:
            rows = runtime.query(
                "SELECT setting_key, setting_value, updated_at FROM config_overrides"
            )
            for row in rows:
                import json
                try:
                    overrides[row["setting_key"]] = {
                        "value": json.loads(row["setting_value"]),
                        "updated_at": row["updated_at"],
                    }
                except (json.JSONDecodeError, TypeError):
                    overrides[row["setting_key"]] = {
                        "value": row["setting_value"],
                        "updated_at": row["updated_at"],
                    }
        except Exception:
            pass

        return {
            "whitelisted_keys": sorted(WHITELISTED_KEYS),
            "overrides": overrides,
            "risk": {
                "max_position_pct": 0.25,
                "max_open_positions": 50,
                "max_sector_pct": 0.22,
                "planned_risk_pct_min": 0.005,
                "planned_risk_pct_max": 0.01,
            },
            "shadow_trading": {
                "enabled": True,
                "max_positions": 50,
                "timeout_days": {"default": 15, "pullback": 7},
            },
            "llm": {
                "enabled": True,
                "min_conviction_score": 0,
            },
            "scheduler": {
                "scan_interval_minutes": 30,
            },
        }

    @router.post("/api/settings", dependencies=[Depends(verify_auth)])
    def update_settings(body: SettingsUpdate):
        """Submit a config change command via the queue."""
        return _submit_command(
            command_name="update_setting",
            command_type="config_change",
            payload={"key": body.key, "value": body.value},
        )

    @router.delete("/api/settings/overrides", dependencies=[Depends(verify_auth)])
    def clear_overrides():
        """Clear all dashboard overrides (reset to YAML defaults)."""
        try:
            with runtime.get_pg(readonly=False) as conn:
                with conn.cursor() as cur:
                    cur.execute("DELETE FROM config_overrides")
                    conn.commit()
            return {"message": "All overrides cleared"}
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))

    # ── Action endpoints (now submit to command queue) ─────────────

    @router.post("/api/actions/scan", dependencies=[Depends(verify_auth)])
    def action_scan():
        return _submit_command("scan")

    @router.post("/api/actions/council", dependencies=[Depends(verify_auth)])
    def action_council(body: dict = None):
        payload = body or {}
        return _submit_command("council", payload=payload)

    @router.post("/api/actions/collect-data", dependencies=[Depends(verify_auth)])
    def action_collect_data():
        return _submit_command("collect-data")

    @router.post("/api/actions/collect-training", dependencies=[Depends(verify_auth)])
    def action_collect_training():
        return _submit_command("collect-training")

    @router.post("/api/actions/train-pipeline", dependencies=[Depends(verify_auth)])
    def action_train_pipeline():
        return _submit_command("train-pipeline")

    @router.post("/api/halt-trading", dependencies=[Depends(verify_auth)])
    def action_halt_trading():
        return _submit_command("halt-trading", priority=10)

    @router.post("/api/resume-trading", dependencies=[Depends(verify_auth)])
    def action_resume_trading():
        return _submit_command("resume-trading", priority=10)

    @router.post("/api/shadow/close/{ticker}", dependencies=[Depends(verify_auth)])
    def action_close_position(ticker: str):
        return _submit_command("close-position", payload={"ticker": ticker})

    @router.post("/api/actions/cto-report", dependencies=[Depends(verify_auth)])
    def action_cto_report():
        return _submit_command("cto-report")

    @router.post("/api/actions/score", dependencies=[Depends(verify_auth)])
    def action_score():
        return _submit_command("cto-report")

    @router.post("/api/training/train", dependencies=[Depends(verify_auth)])
    def training_train():
        return _submit_command("train-pipeline")

    @router.post("/api/training/bootstrap", dependencies=[Depends(verify_auth)])
    def training_bootstrap():
        return _submit_command("collect-training")

    @router.post("/api/training/rollback", dependencies=[Depends(verify_auth)])
    def training_rollback():
        return _submit_command("train-pipeline", payload={"rollback": True})

    @router.post("/api/live/reconcile", dependencies=[Depends(verify_auth)])
    def live_reconcile():
        return {
            "error": "cloud_mode",
            "message": "Reconciliation must be run locally via CLI: python -m src.main reconcile-live",
        }

    @router.get("/api/system/validation", dependencies=[Depends(verify_auth)])
    def system_validation(fresh: bool = False):
        """Return latest validation result from synced data."""
        if fresh:
            try:
                _submit_command("validate-system")
            except Exception:
                pass

        try:
            import json as _json

            row = runtime.query_one(
                "SELECT results_json FROM validation_results "
                "ORDER BY created_at DESC LIMIT 1"
            )
            if not row or not row.get("results_json"):
                return {
                    "overall_status": "unknown",
                    "categories": {},
                    "checks_passed": 0,
                    "checks_failed": 0,
                    "checks_warning": 0,
                    "checks_total": 0,
                }
            result = row["results_json"]
            if isinstance(result, str):
                result = _json.loads(result)
            return result
        except HTTPException:
            raise
        except Exception as exc:
            runtime.logger.error("[API] system_validation failed: %s", exc)
            return {
                "overall_status": "unknown",
                "categories": {},
                "checks_passed": 0,
                "checks_failed": 0,
                "checks_warning": 0,
                "checks_total": 0,
                "error": str(exc),
            }

    TABLE_WHITELIST = [
        "shadow_trades", "recommendations", "trade_exits", "bracket_orders",
        "trade_postmortems", "position_snapshots", "live_trades",
        "training_examples", "training_runs", "model_versions", "holdout_results",
        "preference_pairs", "contrastive_pairs", "quality_scores",
        "options_chains", "options_metrics", "vix_term_structure", "cboe_ratios",
        "macro_snapshots", "google_trends", "earnings_calendar", "edgar_filings",
        "insider_transactions", "short_interest", "fed_communications", "analyst_estimates",
        "activity_log", "log_entries", "pending_commands", "command_results",
        "config_overrides", "scan_metrics", "metric_snapshots",
        "council_sessions", "council_votes", "audit_reports", "build_score_history",
        "hshs_snapshots", "validation_checks",
        "feature_cache", "enrichment_cache", "news_cache", "regime_history",
        "sector_snapshots", "fundamental_snapshots",
    ]

    @router.get("/api/system/table-counts", dependencies=[Depends(verify_auth)])
    def table_counts():
        """Return row counts for whitelisted tables (for DB Schema page)."""
        counts = {}
        for table in TABLE_WHITELIST:
            try:
                row = runtime.query_one(f"SELECT COUNT(*) as c FROM {table}")
                counts[table] = row["c"] if row else 0
            except Exception:
                counts[table] = -1
        return counts

    return router
