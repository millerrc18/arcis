"""Strategy research platform — backtest engine, promotion, shadow harness.

Sprint 1B registers two capabilities here:
- strategy_backtest (Action) — kicks off a backtest via POST /api/platform/backtests
- strategy_registry_state (State) — current status counts in strategy_registry
"""
from __future__ import annotations

from datetime import date

from src.platform.capability_registry import register_action, register_state

_INTRODUCED = "v0.24.0"
_LAST_REVIEWED = date(2026, 4, 18)


@register_action(
    name="strategy_backtest",
    description=(
        "Run a backtest for a registered strategy over a date range. "
        "Writes results to backtest_results; long-running strategies can "
        "be followed up with --with-walkforward for OOS efficiency."
    ),
    category="backtest",
    version="1.0",
    maintainer="ai_session",
    introduced_in=_INTRODUCED,
    last_reviewed_date=_LAST_REVIEWED,
    kickoff_endpoint="/api/platform/backtests",
    history_endpoint="/api/platform/strategies",
    input_schema={
        "type": "object",
        "properties": {
            "strategy_id": {"type": "string", "minLength": 1},
            "start_date": {"type": "string", "format": "date"},
            "end_date": {"type": "string", "format": "date"},
        },
        "required": ["strategy_id"],
        "additionalProperties": True,
    },
    output_schema={
        "type": "object",
        "properties": {
            "backtest_id": {"type": "string"},
            "status": {"type": "string"},
        },
        "required": ["status"],
    },
    estimated_duration="30s-10min (strategy-dependent)",
)
def strategy_backtest_capability() -> dict:
    """Registration anchor for the backtest Action."""
    return {"entry_module": "src.platform"}


def _query_strategy_registry_state() -> dict:
    """Aggregate strategy_registry counts by current_status."""
    import sqlite3

    from src.config import DB_PATH

    conn = sqlite3.connect(DB_PATH)
    try:
        rows = conn.execute(
            "SELECT current_status, COUNT(*) AS n "
            "FROM strategy_registry GROUP BY current_status",
        ).fetchall()
    except sqlite3.OperationalError as exc:
        return {"error": f"table missing or locked: {exc}"}
    finally:
        conn.close()
    by_status = {status: n for status, n in rows}
    total = sum(by_status.values())
    return {"value": {"total": total, "by_status": by_status}}


@register_state(
    name="strategy_registry_state",
    description=(
        "Counts of strategies in each lifecycle state "
        "(proposed, backtest_ready, shadow_live, promoted, demoted, etc.)."
    ),
    category="backtest",
    version="1.0",
    maintainer="ai_session",
    introduced_in=_INTRODUCED,
    last_reviewed_date=_LAST_REVIEWED,
    refresh_hint="real-time",
)
def strategy_registry_state() -> dict:
    return _query_strategy_registry_state()
