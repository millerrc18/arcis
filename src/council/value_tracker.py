"""Council value tracking -- counterfactual P&L computation.

Called by: council/engine.py
Calls: council/constants.py
Owns tables: council_parameter_log, council_parameter_state
Config keys: none
Tests: none

Tracks whether council parameter adjustments create or destroy value
by comparing actual P&L to counterfactual P&L (default parameters).

Architecture: AI_Council_Redesign_v2__Architecture_and_Implementation.md

FIX #5: Counterfactual attribution limited to position_sizing_multiplier.
        cash_reserve_target_pct and scan_aggressiveness require replay
        simulation for proper counterfactual -- deferred to Phase 2.

Decisions:
- Both holistic + per-agent value tracking from day 1
- Alert at 8 weeks negative, auto-tighten at 12 weeks, restore at 4 weeks positive
"""

import logging
import sqlite3
import uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from src.config import DB_PATH
from src.council.constants import PARAMETER_DEFAULTS

logger = logging.getLogger(__name__)

ET = ZoneInfo("America/New_York")

# Parameters where counterfactual P&L can be computed
# FIX #5: Only position_sizing_multiplier has a clean counterfactual
ATTRIBUTABLE_PARAMETERS = {"position_sizing_multiplier"}


def init_value_tables(db_path: str = DB_PATH) -> None:
    """Create value tracking tables and run column migrations via the schema registry."""
    try:
        from src.schema.sqlite import create_all_tables, ensure_columns
        create_all_tables(db_path)
        ensure_columns(db_path)
    except Exception as e:
        logger.warning("[VALUE] Table creation failed: %s", e)


def get_current_parameters(db_path: str = DB_PATH) -> dict:
    """Get current active council parameter values.

    Falls back to defaults if no state stored.
    #122 — Auto-create tables on first access.
    """
    init_value_tables(db_path)
    params = PARAMETER_DEFAULTS.copy()
    try:
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT parameter_name, current_value FROM council_parameter_state"
            ).fetchall()
            for row in rows:
                params[row["parameter_name"]] = row["current_value"]
    except Exception:
        pass
    return params


def log_parameter_change(
    session_id: str,
    parameter_name: str,
    default_value: float,
    council_value: float,
    applied_value: float,
    rate_limited: bool = False,
    agent_name: str | None = None,
    db_path: str = DB_PATH,
) -> str:
    """Log a council parameter change for value tracking.

    Closes the previous attribution window for this parameter.
    Returns the log_id.
    """
    log_id = str(uuid.uuid4())
    now = datetime.now(ET).isoformat()

    try:
        init_value_tables(db_path)
        with sqlite3.connect(db_path) as conn:
            # Close previous attribution window
            conn.execute(
                "UPDATE council_parameter_log SET attribution_end = ? "
                "WHERE parameter_name = ? AND attribution_end IS NULL",
                (now, parameter_name),
            )

            # Insert new log entry
            conn.execute(
                "INSERT INTO council_parameter_log "
                "(log_id, session_id, agent_name, parameter_name, default_value, "
                "council_value, applied_value, rate_limited, attribution_start, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (log_id, session_id, agent_name, parameter_name,
                 default_value, council_value, applied_value,
                 1 if rate_limited else 0, now, now),
            )

            # Update current state
            conn.execute(
                "INSERT OR REPLACE INTO council_parameter_state "
                "(parameter_name, current_value, default_value, last_session_id, last_updated) "
                "VALUES (?, ?, ?, ?, ?)",
                (parameter_name, applied_value, default_value, session_id, now),
            )

    except Exception as e:
        logger.error("[VALUE] Failed to log parameter change: %s", e)

    return log_id


def _empty_value_summary(days: int | None = None) -> dict:
    """Return the standard council value summary shape."""
    summary = {
        "total_value_added": 0.0,
        "windows_computed": 0,
        "per_parameter": {},
        "per_agent": {},
    }
    if days is not None:
        summary.update(
            {
                "period_days": days,
                "total_trades_influenced": 0,
                "weeks_negative": 0,
                "authority_status": "full",
            }
        )
    return summary


def _record_value(summary: dict, parameter_name: str, agent_name: str | None, value_added: float, trades: int) -> None:
    """Accumulate a value-add contribution into the summary buckets."""
    summary["total_value_added"] += value_added
    if "total_trades_influenced" in summary:
        summary["total_trades_influenced"] += trades

    parameter_bucket = summary["per_parameter"].setdefault(
        parameter_name,
        {"value_added": 0.0, "trades": 0},
    )
    parameter_bucket["value_added"] += value_added
    parameter_bucket["trades"] += trades

    agent_bucket = summary["per_agent"].setdefault(
        agent_name or "consensus",
        {"value_added": 0.0, "recommendations": 0},
    )
    agent_bucket["value_added"] += value_added
    agent_bucket["recommendations"] += 1


def _compute_window_value(conn: sqlite3.Connection, window: sqlite3.Row) -> tuple[int, float, float, float] | None:
    """Compute actual, counterfactual, and value-add numbers for one attribution window."""
    if window["parameter_name"] != "position_sizing_multiplier":
        return None

    applied = window["applied_value"]
    default = window["default_value"]
    if applied <= 0 or default <= 0:
        return None

    trades = conn.execute(
        "SELECT pnl_dollars FROM shadow_trades "
        "WHERE status = 'closed' AND actual_entry_time >= ? "
        "AND actual_entry_time < ?",
        (window["attribution_start"], window["attribution_end"]),
    ).fetchall()
    if not trades:
        return 0, 0.0, 0.0, 0.0

    actual_pnl = sum(trade["pnl_dollars"] or 0 for trade in trades)
    sizing_ratio = default / applied
    counterfactual_pnl = sum((trade["pnl_dollars"] or 0) * sizing_ratio for trade in trades)
    value_added = actual_pnl - counterfactual_pnl
    return len(trades), actual_pnl, counterfactual_pnl, value_added


def _count_negative_weeks(conn: sqlite3.Connection, weeks: int = 12) -> int:
    """Count the most recent consecutive weekly value-add buckets that are negative."""
    streak = 0
    for week in range(weeks):
        week_start = (datetime.now(ET) - timedelta(weeks=week + 1)).isoformat()
        week_end = (datetime.now(ET) - timedelta(weeks=week)).isoformat()
        row = conn.execute(
            "SELECT COALESCE(SUM(value_added_dollars), 0) as va "
            "FROM council_parameter_log "
            "WHERE attribution_start >= ? AND attribution_start < ? "
            "AND value_added_dollars IS NOT NULL",
            (week_start, week_end),
        ).fetchone()
        if row and row["va"] < 0:
            streak += 1
        else:
            break
    return streak


def _determine_authority_status(weeks_negative: int) -> str:
    """Map recent value-add streaks onto the council authority state."""
    if weeks_negative >= 12:
        return "reduced"
    if weeks_negative >= 8:
        return "alert"
    return "full"


def compute_attribution(db_path: str = DB_PATH) -> dict:
    """Compute value attribution for closed attribution windows.

    FIX #5: Only computes counterfactual for position_sizing_multiplier.
    Other parameters (cash_reserve, scan_aggressiveness) are logged but
    attribution requires replay simulation — deferred to Phase 2.

    For position_sizing_multiplier:
    - Actual P&L = trade P&L at council-adjusted size
    - Counterfactual = trade P&L scaled by (default / applied) ratio
    - Value added = actual - counterfactual
      - If council reduced size and trade lost: value added is POSITIVE (saved money)
      - If council reduced size and trade won: value added is NEGATIVE (missed gains)

    Returns:
        {
            "total_value_added": float,
            "windows_computed": int,
            "per_parameter": {name: {"value_added": float, "trades": int}},
            "per_agent": {name: {"value_added": float, "recommendations": int}},
        }
    """
    result = _empty_value_summary()

    try:
        init_value_tables(db_path)
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row

            # Find closed windows without computed attribution
            windows = conn.execute(
                "SELECT * FROM council_parameter_log "
                "WHERE attribution_end IS NOT NULL AND value_added_dollars IS NULL "
                "AND parameter_name IN ({})".format(
                    ",".join(f"'{p}'" for p in ATTRIBUTABLE_PARAMETERS)
                )
            ).fetchall()

            for window in windows:
                value_tuple = _compute_window_value(conn, window)
                if value_tuple is None:
                    continue

                trade_count, actual_pnl, counterfactual_pnl, value_added = value_tuple
                conn.execute(
                    "UPDATE council_parameter_log SET "
                    "trades_during_window = ?, pnl_during_window = ?, "
                    "counterfactual_pnl = ?, value_added_dollars = ? "
                    "WHERE log_id = ?",
                    (
                        trade_count,
                        round(actual_pnl, 2),
                        round(counterfactual_pnl, 2),
                        round(value_added, 2),
                        window["log_id"],
                    ),
                )
                result["windows_computed"] += 1
                _record_value(
                    result,
                    window["parameter_name"],
                    window["agent_name"],
                    value_added,
                    trade_count,
                )

    except Exception as e:
        logger.error("[VALUE] Attribution computation failed: %s", e)

    return result


def get_rolling_value_summary(days: int = 30, db_path: str = DB_PATH) -> dict:
    """Get rolling N-day council value summary.

    Returns:
        {
            "period_days": int,
            "total_value_added": float,
            "total_trades_influenced": int,
            "per_parameter": {name: {"value_added": float, "trades": int}},
            "per_agent": {name: {"value_added": float, "recommendations": int}},
            "weeks_negative": int (consecutive, most recent),
            "authority_status": "full" | "alert" | "reduced",
        }
    """
    cutoff = (datetime.now(ET) - timedelta(days=days)).isoformat()
    summary = _empty_value_summary(days)

    try:
        init_value_tables(db_path)
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row

            # Aggregate computed windows
            rows = conn.execute(
                "SELECT parameter_name, agent_name, value_added_dollars, "
                "trades_during_window "
                "FROM council_parameter_log "
                "WHERE attribution_start >= ? AND value_added_dollars IS NOT NULL",
                (cutoff,),
            ).fetchall()

            for r in rows:
                _record_value(
                    summary,
                    r["parameter_name"],
                    r["agent_name"],
                    r["value_added_dollars"] or 0,
                    r["trades_during_window"] or 0,
                )

            summary["weeks_negative"] = _count_negative_weeks(conn)
            summary["authority_status"] = _determine_authority_status(summary["weeks_negative"])

    except Exception as e:
        logger.error("[VALUE] Rolling summary failed: %s", e)

    return summary
