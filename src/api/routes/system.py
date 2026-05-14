"""System API routes — the largest route file, serving the system dashboard.

Called by: api.app
Calls: config, evaluation.cto_report, evaluation.system_validator, journal.store, logging.activity, risk.governor, scheduler.metrics, services.system_service, training.versioning
Owns tables: none
Config keys: none
Tests: tests/test_local_api_routes.py, tests/test_tier_1_5_hygiene.py,
  tests/evaluation/test_sharpe_canonical_routing.py

Endpoints:
    GET  /status                    - System status (preflight-equivalent)
    GET  /preflight                 - Alias for /status
    GET  /config                    - Current config (secrets masked)
    PUT  /config                    - Update config YAML directly
    GET  /cto-report?days=7         - CTO performance report
    GET  /costs?days=30             - API cost breakdown
    POST /halt-trading              - Emergency halt all trading
    POST /resume-trading            - Resume after halt
    GET  /halt-status               - Check halt state
    GET  /audit/latest              - Most recent daily audit
    GET  /audit/history?days=7      - Audit history
    GET  /metric-history?days=90    - Rolling trade metrics (Sharpe, drawdown)
    GET  /data-collection-stats     - Per-table collection stats (#224)
    GET  /earnings?days=14          - Upcoming earnings calendar
    GET  /activity-log              - Recent activity entries
    GET  /schedule-metrics?days=30  - Compute schedule utilization
    GET  /system/validation         - Run/cached system validation
    GET  /system/table-counts       - Row counts for DB Schema page
    GET  /activity/feed             - Activity feed (matches cloud shape)
    GET  /settings                  - Settings with dashboard overrides
    POST /settings                  - Save a config override
    DELETE /settings/overrides      - Clear all overrides
    GET  /scan/metrics              - Scan metrics history
    GET  /training/history          - Model version list (cloud parity alias)
    GET  /attribution/stats         - Alpha attribution statistics
    GET  /stress-test/results       - Historical stress test results
    GET  /simulation/results        - Simulation engine results (heatmap data)
"""
import logging
from contextlib import closing

from fastapi import APIRouter, Depends, Query
from src.api.local_auth import verify_local_token
from src.config import DB_PATH, load_config
from src.services.system_service import get_system_status
from src.utils.db import connect_db, engine_aware_upsert

router = APIRouter(tags=["system"])
logger = logging.getLogger(__name__)

# These queries are validated by test_stats_queries_reference_valid_columns
# in test_schema.py to ensure column names match the schema registry.
# If a query references a non-existent column, the test will catch it (#224).
# #328: Use COALESCE(collected_at, collected_date) for tables that may have
# only one of the two time columns in the actual database.
_DATA_COLLECTION_QUERIES = {
    "options_chains": (
        "SELECT COUNT(*) AS total_records, MAX(collected_at) AS latest_collection, "
        "COUNT(DISTINCT ticker) AS coverage_count FROM options_chains"
    ),
    "options_metrics": (
        "SELECT COUNT(*) AS total_records, "
        "MAX(COALESCE(collected_at, collected_date)) AS latest_collection, "
        "COUNT(DISTINCT ticker) AS coverage_count FROM options_metrics"
    ),
    "vix_term_structure": (
        "SELECT COUNT(*) AS total_records, "
        "MAX(COALESCE(collected_at, collected_date)) AS latest_collection, "
        "COUNT(DISTINCT collected_date) AS coverage_count FROM vix_term_structure"
    ),
    "macro_snapshots": (
        "SELECT COUNT(*) AS total_records, "
        "MAX(COALESCE(collected_at, collected_date)) AS latest_collection, "
        "COUNT(DISTINCT series_id) AS coverage_count FROM macro_snapshots"
    ),
    "google_trends": (
        "SELECT COUNT(*) AS total_records, "
        "MAX(COALESCE(collected_at, collected_date)) AS latest_collection, "
        "COUNT(DISTINCT ticker) AS coverage_count FROM google_trends"
    ),
    "cboe_ratios": (
        "SELECT COUNT(*) AS total_records, "
        "MAX(COALESCE(collected_at, collected_date)) AS latest_collection, "
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


def _build_table_stats(row) -> dict:
    """Normalize a stats row into a stable response shape."""
    if not row:
        return {"total_records": 0, "latest_collection": None, "coverage_count": 0}
    row = dict(row)  # normalize sqlite3.Row to mapping (defensive — sqlite3.Row lacks .get())
    total_records = row.get("total_records", 0) or 0
    latest = row.get("latest_collection")
    return {
        "total_records": total_records,
        "latest_collection": str(latest)[:10] if (total_records and latest) else None,
        "coverage_count": row.get("coverage_count", 0) if total_records else 0,
    }


@router.get("/status")
def status():
    config = load_config()
    return get_system_status(config)


@router.get("/preflight")
def preflight():
    config = load_config()
    return get_system_status(config)


@router.get("/config")
def get_config():
    """Return current config with sensitive values masked.

    The dashboard needs config values to display settings, but we must never
    expose API keys or passwords. Each sensitive field is explicitly masked
    rather than using a generic approach so we don't accidentally miss one.
    """
    config = load_config()
    # Mask sensitive values
    safe = dict(config)
    if "email" in safe:
        email = dict(safe["email"])
        if "password" in email:
            email["password"] = "***"
        safe["email"] = email
    if "alpaca" in safe:
        alpaca = dict(safe["alpaca"])
        if "api_secret" in alpaca:
            alpaca["api_secret"] = "***"
        safe["alpaca"] = alpaca
    if "training" in safe:
        t = dict(safe["training"])
        if "anthropic_api_key" in t:
            t["anthropic_api_key"] = "***"
        safe["training"] = t
    return safe


@router.get("/cto-report")
def cto_report(days: int = 7):
    from src.evaluation.cto_report import generate_cto_report
    return generate_cto_report(days=days)


@router.get("/costs")
def api_costs(days: int = 30):
    from src.training.versioning import get_cost_summary
    return get_cost_summary(days=days)


@router.post("/halt-trading", dependencies=[Depends(verify_local_token)])
def halt_trading():
    """Emergency halt — stops all new trade entry immediately.

    The risk governor's _global_halt flag is checked before every trade entry.
    This is the "big red button" — use when something goes wrong and you need
    to stop immediately without killing the watch loop.
    """
    from src.risk.governor import _global_halt
    _global_halt(True, source="api", reason="manual halt via /halt-trading")
    return {"status": "halted", "message": "All trading halted. No new positions will be opened."}


@router.post("/resume-trading", dependencies=[Depends(verify_local_token)])
def resume_trading():
    """Resume trading after a halt."""
    from src.risk.governor import _global_halt
    _global_halt(False, source="api", reason="manual resume via /resume-trading")
    return {"status": "resumed", "message": "Trading resumed."}


@router.get("/halt-status")
def halt_status():
    """Check if trading is halted."""
    from src.risk.governor import _is_halted
    return {"halted": _is_halted()}


@router.get("/audit/latest")
def latest_audit():
    """Get the most recent daily audit report."""
    from src.training.versioning import init_training_tables
    import sqlite3
    init_training_tables()
    # PR #690 B4: `with connect_db(...) as conn:` triggers sqlite3.Connection
    # __exit__ which commits/rollbacks the transaction but does NOT close
    # the connection. Wrap in closing() so the file handle is released.
    with closing(connect_db(DB_PATH)) as conn:  # #258: 30s busy_timeout
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM audit_reports ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
    if not row:
        return {"audit": None}
    import json
    result = dict(row)
    for key in ("flags", "metrics_to_watch"):
        if result.get(key):
            try:
                result[key] = json.loads(result[key])
            except (json.JSONDecodeError, TypeError):
                pass
    return result


@router.get("/audit/history")
def audit_history(days: int = 7):
    """Get audit reports for the last N days."""
    from src.training.versioning import init_training_tables
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo
    import sqlite3, json
    init_training_tables()
    et = ZoneInfo("America/New_York")
    cutoff = (datetime.now(et) - timedelta(days=days)).isoformat()
    # PR #690 B4: closing() guarantees conn.close() — sqlite3 __exit__ only
    # commits/rolls back, it does not release the file handle.
    with closing(connect_db(DB_PATH)) as conn:  # #258: 30s busy_timeout
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM audit_reports WHERE created_at >= ? ORDER BY created_at DESC",
            (cutoff,),
        ).fetchall()
    results = []
    for row in rows:
        r = dict(row)
        for key in ("flags", "metrics_to_watch"):
            if r.get(key):
                try:
                    r[key] = json.loads(r[key])
                except (json.JSONDecodeError, TypeError):
                    pass
        results.append(r)
    return results


def _build_metric_snapshots(closed: list[dict]) -> list[dict]:
    """Pure helper: build rolling metric snapshots from a sorted closed-trade list.

    F-2 / Sprint-0 wave-4a: rolling Sharpe is computed via the canonical
    `compute_sharpe(periods_per_year=150)` (matches cto_report's trade-
    frequency convention of ~150 trades/year). Returns 0 (not None) on
    degenerate windows so the JSON snapshot always has a numeric Sharpe.

    Extracted from `metric_history` so the rolling logic is unit-testable
    without a DB fixture. The route handler is a thin wrapper that fetches
    closed trades and calls this helper.
    """
    from src.analytics.canonical_sharpe import compute_sharpe

    if not closed:
        return []

    snapshots: list[dict] = []
    cumulative_pnl = 0
    peak = 0
    all_pnl_pcts: list[float] = []
    wins = 0

    for i, t in enumerate(closed):
        pnl = t.get("pnl_dollars", 0) or 0
        pnl_pct = t.get("pnl_pct", 0) or 0
        cumulative_pnl += pnl
        all_pnl_pcts.append(pnl_pct)
        if pnl > 0:
            wins += 1

        if cumulative_pnl > peak:
            peak = cumulative_pnl
        drawdown = peak - cumulative_pnl

        trade_count = i + 1
        win_rate = wins / trade_count

        sharpe_val = compute_sharpe(all_pnl_pcts, periods_per_year=150)
        sharpe = 0 if sharpe_val is None else sharpe_val

        snapshots.append({
            "date": (t.get("created_at") or "")[:10],
            "trade_number": trade_count,
            "cumulative_pnl": round(cumulative_pnl, 2),
            "win_rate": round(win_rate, 3),
            "sharpe_ratio": round(sharpe, 2),
            "max_drawdown": round(drawdown, 2),
            "expectancy": round(cumulative_pnl / trade_count, 2),
        })

    return snapshots


@router.get("/metric-history")
def metric_history(days: int = 90):
    """Get rolling metric snapshots computed from closed trade history."""
    from src.journal.store import get_closed_shadow_trades

    closed = get_closed_shadow_trades(days=days)
    if not closed:
        return []

    # Sort by created_at ascending
    closed.sort(key=lambda t: t.get("created_at", ""))
    return _build_metric_snapshots(closed)


@router.get("/data-collection-stats")
def data_collection_stats():
    """Return summary stats for all data collection tables."""
    import sqlite3

    db_path = DB_PATH
    stats = {}

    # PR #690 B4: closing() guarantees conn.close() — sqlite3 __exit__ only
    # commits/rolls back, it does not release the file handle.
    with closing(connect_db(db_path)) as conn:  # #258: 30s busy_timeout
        for table_name, sql in _DATA_COLLECTION_QUERIES.items():
            try:
                row = conn.execute(sql).fetchone()
                stats[table_name] = _build_table_stats(row)
            except Exception as e:
                logger.warning("Stats query failed for %s: %s", table_name, e)
                stats[table_name] = {"error": str(e), "total_records": 0,
                                     "latest_collection": None, "coverage_count": 0}

    return stats


@router.get("/earnings")
def upcoming_earnings(days: int = 14):
    """Return upcoming earnings dates for the S&P 100 universe."""
    try:
        from scripts.fetch_earnings_calendar import get_all_upcoming_earnings
        earnings = get_all_upcoming_earnings(days=days)
        return {
            "days_ahead": days,
            "count": len(earnings),
            "earnings": earnings,
        }
    except Exception as e:
        return {
            "days_ahead": days,
            "count": 0,
            "earnings": [],
            "error": str(e),
        }


@router.get("/activity-log")
def activity_log(
    limit: int = Query(default=20, ge=1, le=200),
    category: str | None = Query(default=None),
):
    """Return recent activity log entries."""
    from src.logging.activity import get_recent_activity
    entries = get_recent_activity(limit=limit, category=category)
    return {"count": len(entries), "entries": entries}


@router.get("/schedule-metrics")
def schedule_metrics(days: int = 30):
    """Return compute schedule metrics for dashboard display."""
    from src.scheduler.metrics import get_metrics, get_todays_metrics
    return {
        "today": get_todays_metrics(),
        "history": get_metrics(days=days),
    }


@router.put("/config", dependencies=[Depends(verify_local_token)])
def update_config(updates: dict):
    import yaml
    from pathlib import Path
    from src.config import reload_config

    config_path = Path(__file__).resolve().parent.parent.parent.parent / "config" / "settings.local.yaml"
    if not config_path.exists():
        return {"success": False, "error": "settings.local.yaml not found"}

    with open(config_path, "r") as f:
        current = yaml.safe_load(f) or {}

    for section, values in updates.items():
        if isinstance(values, dict) and section in current:
            current[section].update(values)
        else:
            current[section] = values

    with open(config_path, "w") as f:
        yaml.dump(current, f, default_flow_style=False)

    reload_config()
    return {"success": True}


# ── System Validation ────────────────────────────────────────────────

# System validation is expensive (checks Ollama, Alpaca, DB, disk, etc.)
# so we cache for 5 minutes. Pass ?fresh=true to bypass the cache.
_validation_cache: dict | None = None
_validation_cache_ts: float = 0


@router.get("/system/validation")
def system_validation(fresh: bool = False):
    """Run system validation checks. Cached for 5 minutes unless fresh=True."""
    import time
    global _validation_cache, _validation_cache_ts

    if not fresh and _validation_cache and (time.time() - _validation_cache_ts < 300):
        return _validation_cache

    from src.evaluation.system_validator import run_full_validation, save_validation_result
    result = run_full_validation()
    save_validation_result(result)

    _validation_cache = result
    _validation_cache_ts = time.time()
    return result


# Whitelist prevents arbitrary table reads via the API. Only tables
# listed here can be queried for row counts on the DB Schema page.
_TABLE_WHITELIST = [
    "shadow_trades", "recommendations", "training_examples", "model_versions",
    "preference_pairs", "model_evaluations", "quality_drift_metrics",
    "options_chains", "options_metrics", "vix_term_structure", "cboe_ratios",
    "macro_snapshots", "google_trends", "earnings_calendar", "edgar_filings",
    "insider_transactions", "short_interest", "fed_communications", "analyst_estimates",
    "activity_log", "log_entries", "pending_commands", "command_results",
    "config_overrides", "scan_metrics", "metric_snapshots", "schedule_metrics",
    "council_sessions", "council_votes", "audit_reports", "build_score_history",
    "canary_evaluations", "validation_results", "api_costs",
    "bracket_health", "council_calibrations", "council_debug_log",
    "council_parameter_log", "council_parameter_state",
    "research_digests", "research_docs", "research_papers",
    "setup_signals", "simulation_results", "sync_state", "traffic_light_state",
    "user_notes",
    "system_metrics",
]


@router.get("/system/table-counts")
def table_counts():
    """Return row counts for whitelisted tables (for DB Schema page)."""
    # PR #690 B4: bare conn.close() at end leaks the connection if any
    # exception escapes the for-loop. The per-table try/except already
    # swallows OperationalError, but a pathological case (e.g. database
    # locked beyond the 30s busy_timeout) would surface here. Wrap in
    # closing() so the connection is always released.
    from src.schema.registry import TABLES
    counts = {}
    with closing(connect_db(DB_PATH)) as conn:  # #258: 30s busy_timeout
        for table in _TABLE_WHITELIST:
            try:
                row = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
                counts[table] = row[0] if row else 0
            except Exception:
                counts[table] = -1
    return {"counts": counts, "registry_total": len(TABLES)}


@router.get("/activity/feed")
def activity_feed(
    limit: int = Query(default=50, ge=1, le=200),
    event_type: str | None = Query(default=None),
):
    """Activity feed matching cloud /api/activity/feed response shape."""
    import sqlite3 as _sqlite3
    try:
        # PR #690 B4: closing() guarantees conn.close() — sqlite3 __exit__ only
        # commits/rolls back, it does not release the file handle.
        with closing(connect_db(DB_PATH)) as conn:
            conn.row_factory = _sqlite3.Row
            if event_type:
                rows = conn.execute(
                    "SELECT * FROM activity_log WHERE event_type = ? "
                    "ORDER BY created_at DESC LIMIT ?",
                    (event_type, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM activity_log ORDER BY created_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            return [dict(row) for row in rows]
    except Exception as e:
        logger.error("[API] activity/feed failed: %s", e)
        return []


@router.get("/settings")
def get_settings():
    """Return current settings including dashboard overrides."""
    import sqlite3 as _sqlite3
    config = load_config()
    overrides = {}
    try:
        # PR #690 B4: closing() guarantees conn.close() — sqlite3 __exit__ only
        # commits/rolls back, it does not release the file handle.
        with closing(connect_db(DB_PATH)) as conn:
            conn.row_factory = _sqlite3.Row
            rows = conn.execute(
                "SELECT setting_key, setting_value, updated_at FROM config_overrides"
            ).fetchall()
            for row in rows:
                import json as _json
                try:
                    overrides[row["setting_key"]] = {
                        "value": _json.loads(row["setting_value"]),
                        "updated_at": row["updated_at"],
                    }
                except (ValueError, TypeError):
                    overrides[row["setting_key"]] = {
                        "value": row["setting_value"],
                        "updated_at": row["updated_at"],
                    }
    except Exception:
        pass

    risk = config.get("risk", {})
    return {
        "overrides": overrides,
        "risk": {
            "max_position_pct": risk.get("max_position_pct", 0.25),
            "max_open_positions": risk.get("max_open_positions", 50),
            "max_sector_pct": risk.get("max_sector_pct", 0.22),
            "planned_risk_pct_min": risk.get("planned_risk_pct_min", 0.005),
            "planned_risk_pct_max": risk.get("planned_risk_pct_max", 0.01),
        },
        "shadow_trading": config.get("shadow_trading", {}),
        "llm": config.get("llm", {}),
        "scheduler": config.get("automation", {}),
    }


@router.post("/settings", dependencies=[Depends(verify_local_token)])
def update_settings(body: dict):
    """Save a config override to config_overrides table."""
    import sqlite3 as _sqlite3
    import json as _json
    from datetime import datetime
    from zoneinfo import ZoneInfo

    key = body.get("key")
    value = body.get("value")
    if not key:
        return {"error": "key is required"}

    now = datetime.now(ZoneInfo("America/New_York")).isoformat()
    try:
        # PR #690 B4: closing() guarantees conn.close() — sqlite3 __exit__ only
        # commits/rolls back, it does not release the file handle.
        # Sprint 5 §J5/§J6 Phase 1 T1.11: route through engine_aware_upsert so
        # the same call works on SQLite (native replace) and PG (ON CONFLICT
        # DO UPDATE). config_overrides is classified `in_place_update` in
        # `_REPLACE_SEMANTICS` (T0.12 audit §5.3).
        with closing(connect_db(DB_PATH)) as conn:
            with conn:  # transaction commit on context exit
                engine_aware_upsert(
                    conn,
                    "config_overrides",
                    {
                        "setting_key": key,
                        "setting_value": _json.dumps(value),
                        "updated_at": now,
                    },
                    action="replace",
                )
        return {"status": "saved", "key": key}
    except Exception as exc:
        logger.error("[API] settings update failed: %s", exc)
        return {"error": str(exc)}


@router.delete("/settings/overrides", dependencies=[Depends(verify_local_token)])
def clear_overrides():
    """Clear all dashboard overrides."""
    import sqlite3 as _sqlite3
    try:
        # PR #690 B4: closing() guarantees conn.close() — sqlite3 __exit__ only
        # commits/rolls back, it does not release the file handle.
        with closing(connect_db(DB_PATH)) as conn:
            with conn:  # transaction commit on context exit
                conn.execute("DELETE FROM config_overrides")
        return {"message": "All overrides cleared"}
    except Exception as exc:
        return {"error": str(exc)}


@router.get("/scan/metrics")
def scan_metrics(limit: int = Query(default=20, ge=1, le=200)):
    """Return scan metrics history."""
    import sqlite3 as _sqlite3
    try:
        # PR #690 B4: closing() guarantees conn.close() — sqlite3 __exit__ only
        # commits/rolls back, it does not release the file handle.
        with closing(connect_db(DB_PATH)) as conn:
            conn.row_factory = _sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM scan_metrics ORDER BY created_at DESC LIMIT ?",
                (min(limit, 100),),
            ).fetchall()
            return [dict(r) for r in rows]
    except Exception as exc:
        logger.error("[API] scan/metrics failed: %s", exc)
        return []


@router.get("/training/history")
def training_history():
    """Alias for training/versions (cloud parity)."""
    import sqlite3 as _sqlite3
    try:
        # PR #690 B4: closing() guarantees conn.close() — sqlite3 __exit__ only
        # commits/rolls back, it does not release the file handle.
        with closing(connect_db(DB_PATH)) as conn:
            conn.row_factory = _sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM model_versions ORDER BY created_at DESC"
            ).fetchall()
            return {"versions": [dict(r) for r in rows]}
    except Exception as exc:
        logger.error("[API] training/history failed: %s", exc)
        return {"versions": []}


@router.get("/attribution/stats")
def attribution_stats():
    """Get alpha attribution statistics."""
    try:
        from src.attribution.logger import get_attribution_stats
        return get_attribution_stats()
    except Exception as exc:
        logger.error("[API] attribution/stats failed: %s", exc)
        return {"total_pairs": 0, "error": str(exc)}


@router.get("/stress-test/results")
def stress_test_results():
    """Get historical stress test results."""
    import sqlite3 as _sqlite3
    import json
    try:
        # PR #690 B4: closing() guarantees conn.close() — sqlite3 __exit__ only
        # commits/rolls back, it does not release the file handle.
        with closing(connect_db(DB_PATH)) as conn:
            conn.row_factory = _sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM stress_test_results ORDER BY created_at DESC"
            ).fetchall()
            results = []
            for r in rows:
                d = dict(r)
                for jf in ("monthly_returns_json", "regime_breakdown_json",
                           "equity_curve_json"):
                    if d.get(jf):
                        try:
                            d[jf] = json.loads(d[jf])
                        except (json.JSONDecodeError, TypeError):
                            pass
                results.append(d)
            return {"results": results}
    except Exception as exc:
        logger.error("[API] stress-test/results failed: %s", exc)
        return {"results": [], "error": str(exc)}


@router.get("/monitoring/snapshot")
def monitoring_snapshot():
    """Capture and return a fresh system metrics snapshot."""
    from src.monitoring.system_metrics import collect_system_snapshot
    return collect_system_snapshot()


@router.get("/monitoring/history")
def monitoring_history(hours: int = 24):
    """Get system metrics history."""
    import sqlite3
    from datetime import datetime, timedelta, timezone
    try:
        # Sprint 5 §J5/§J6 Phase 2.5 T5: compute the cutoff in Python and
        # bind as `?` so the same SQL works on SQLite and Postgres post-
        # cutover. The previous SQLite-only time-modifier literal was
        # replaced by this Python-side computation.
        cutoff = (
            datetime.now(timezone.utc).replace(tzinfo=None)
            - timedelta(hours=hours)
        ).isoformat()
        # PR #690 B4: closing() guarantees conn.close() — sqlite3 __exit__ only
        # commits/rolls back, it does not release the file handle.
        with closing(connect_db(DB_PATH)) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM system_metrics "
                "WHERE timestamp >= ? "
                "ORDER BY timestamp ASC",
                (cutoff,),
            ).fetchall()
        return [dict(r) for r in rows]
    except Exception as exc:
        logger.error("[API] monitoring/history failed: %s", exc)
        return []


@router.get("/simulation/results")
def simulation_results():
    """Get simulation results for dashboard display."""
    import sqlite3 as _sqlite3
    import json
    try:
        # PR #690 B4: closing() guarantees conn.close() — sqlite3 __exit__ only
        # commits/rolls back, it does not release the file handle.
        with closing(connect_db(DB_PATH)) as conn:
            conn.row_factory = _sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM simulation_results ORDER BY created_at DESC"
            ).fetchall()
            results = []
            for r in rows:
                d = dict(r)
                for jf in ("monthly_returns_json", "equity_curve_json",
                           "regime_breakdown_json", "config_json"):
                    if d.get(jf):
                        try:
                            d[jf] = json.loads(d[jf])
                        except (json.JSONDecodeError, TypeError):
                            pass
                results.append(d)
            return {"results": results}
    except Exception as exc:
        logger.error("[API] simulation/results failed: %s", exc)
        return {"results": [], "error": str(exc)}
