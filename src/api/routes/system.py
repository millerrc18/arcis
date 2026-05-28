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

from fastapi import APIRouter, Depends
from src.api.local_auth import verify_local_token
from src.config import DB_PATH, load_config
from src.services.system_service import get_system_status
from src.utils.db import connect_db, engine_aware_upsert

router = APIRouter(tags=["system"])
logger = logging.getLogger(__name__)


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


# T14: the read-only dashboard-data endpoints (metric-history,
# data-collection-stats, earnings, activity-log, schedule-metrics,
# table-counts, activity/feed, scan/metrics, training/history,
# attribution/stats, stress-test/results, monitoring/*, simulation/results)
# moved to ``system_status.py``. That module decorates THIS module's ``router``
# object, so the registered URLs are unchanged. Importing it here — after
# ``router`` and this module's own handlers are defined — triggers the
# decorator registration.
from src.api.routes import system_status  # noqa: E402,F401

# Backward-compatible re-exports for ``from src.api.routes.system import <symbol>``
# call sites whose targets moved to ``system_status``. Resolved lazily via
# PEP 562 ``__getattr__`` so neither module needs the other's symbols at import
# time — this is what keeps the system <-> system_status import cycle from
# dead-locking regardless of which module Python loads first.
_MOVED_TO_SYSTEM_STATUS = frozenset({
    "_DATA_COLLECTION_QUERIES",
    "_TABLE_WHITELIST",
    "_build_metric_snapshots",
    "_build_table_stats",
    "simulation_results",
})


def __getattr__(name: str):
    """Lazily resolve symbols that moved to ``system_status`` (T14)."""
    if name in _MOVED_TO_SYSTEM_STATUS:
        return getattr(system_status, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
