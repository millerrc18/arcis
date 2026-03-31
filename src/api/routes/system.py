"""System API routes.

Called by: api.app
Calls: config, evaluation.cto_report, evaluation.system_validator, journal.store, logging.activity, risk.governor, scheduler.metrics, services.system_service, training.versioning
Owns tables: none
Config keys: none
Tests: none
"""
import logging

from fastapi import APIRouter, Query
from src.config import load_config
from src.services.system_service import get_system_status

router = APIRouter(tags=["system"])
logger = logging.getLogger(__name__)

_DATA_COLLECTION_QUERIES = {
    "options_chains": (
        "SELECT COUNT(*), MAX(collected_at), COUNT(DISTINCT ticker) FROM options_chains"
    ),
    "options_metrics": (
        "SELECT COUNT(*), MAX(collected_date), COUNT(DISTINCT ticker) FROM options_metrics"
    ),
    "vix_term_structure": (
        "SELECT COUNT(*), MAX(collected_date), COUNT(DISTINCT collected_date) FROM vix_term_structure"
    ),
    "macro_snapshots": (
        "SELECT COUNT(*), MAX(collected_date), COUNT(DISTINCT series_id) FROM macro_snapshots"
    ),
    "google_trends": (
        "SELECT COUNT(*), MAX(collected_date), COUNT(DISTINCT ticker) FROM google_trends"
    ),
    "cboe_ratios": (
        "SELECT COUNT(*), MAX(collected_date), COUNT(DISTINCT ratio_type) FROM cboe_ratios"
    ),
    "earnings_calendar": (
        "SELECT COUNT(*), MAX(collected_at), COUNT(DISTINCT ticker) FROM earnings_calendar"
    ),
    "edgar_filings": (
        "SELECT COUNT(*), MAX(collected_at), COUNT(DISTINCT ticker) FROM edgar_filings"
    ),
    "insider_transactions": (
        "SELECT COUNT(*), MAX(collected_at), COUNT(DISTINCT ticker) FROM insider_transactions"
    ),
    "short_interest": (
        "SELECT COUNT(*), MAX(collected_at), COUNT(DISTINCT ticker) FROM short_interest"
    ),
    "fed_communications": (
        "SELECT COUNT(*), MAX(collected_at), COUNT(DISTINCT comm_type) FROM fed_communications"
    ),
    "analyst_estimates": (
        "SELECT COUNT(*), MAX(collected_at), COUNT(DISTINCT ticker) FROM analyst_estimates"
    ),
}


def _build_table_stats(row: tuple | None) -> dict:
    """Normalize a stats row into a stable response shape."""
    if not row:
        return {"total_records": 0, "latest_collection": None, "coverage_count": 0}

    total_records = row[0] or 0
    return {
        "total_records": total_records,
        "latest_collection": row[1] if total_records else None,
        "coverage_count": row[2] if total_records else 0,
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


@router.post("/halt-trading")
def halt_trading():
    """Emergency halt — stops all new trade entry immediately."""
    from src.risk.governor import _global_halt
    _global_halt(True)
    return {"status": "halted", "message": "All trading halted. No new positions will be opened."}


@router.post("/resume-trading")
def resume_trading():
    """Resume trading after a halt."""
    from src.risk.governor import _global_halt
    _global_halt(False)
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
    with sqlite3.connect("ai_research_desk.sqlite3") as conn:
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
    with sqlite3.connect("ai_research_desk.sqlite3") as conn:
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


@router.get("/metric-history")
def metric_history(days: int = 90):
    """Get rolling metric snapshots computed from closed trade history."""
    from src.journal.store import get_closed_shadow_trades
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo
    import math

    et = ZoneInfo("America/New_York")
    closed = get_closed_shadow_trades(days=days)

    if not closed:
        return []

    # Sort by created_at ascending
    closed.sort(key=lambda t: t.get("created_at", ""))

    # Build rolling snapshots: for each trade, compute metrics up to that point
    snapshots = []
    cumulative_pnl = 0
    peak = 0
    all_pnl_pcts = []
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

        # Rolling Sharpe
        if len(all_pnl_pcts) >= 2:
            mean_r = sum(all_pnl_pcts) / len(all_pnl_pcts)
            std_r = (sum((r - mean_r) ** 2 for r in all_pnl_pcts) / (len(all_pnl_pcts) - 1)) ** 0.5
            sharpe = (mean_r / std_r) * math.sqrt(150) if std_r > 0 else 0
        else:
            sharpe = 0

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


@router.get("/data-collection-stats")
def data_collection_stats():
    """Return summary stats for all data collection tables."""
    import sqlite3

    db_path = "ai_research_desk.sqlite3"
    stats = {}

    try:
        with sqlite3.connect(db_path) as conn:
            for table_name, sql in _DATA_COLLECTION_QUERIES.items():
                row = conn.execute(sql).fetchone()
                stats[table_name] = _build_table_stats(row)

    except Exception as e:
        logger.warning("data_collection_stats error: %s", e)

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


@router.put("/config")
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
