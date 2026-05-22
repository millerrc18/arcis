"""Capability registrations for the evaluation/audit family (T8 keep-set).

Keep-set (3 entries):
  - system_auditor  SYSTEM  — health = last audit_reports freshness
  - model_monitor   SYSTEM  — health = last drift-check freshness
  - run_backtest    ACTION  — backtest engine (distinct from strategy_backtest wrapper)

Deferred (seed into Convention E EXEMPT_MODULES in Task 10):
  system_validator, walkforward_validation, build_scorecard,
  change_detector, monte_carlo_sim

Called by: src.platform.capability_registry.bootstrap (import-time side effect)
Calls: src.platform.capability_registry.register_*, src.data_collection._capability_health
Owns tables: none
Config keys: none
Tests: tests/test_capability_registry_coverage.py
"""
from __future__ import annotations

from datetime import date

from src.platform.capability_registry import register_action, register_system
from src.platform.capability_registry._io_schemas import simple_io_schema

_TODAY = date(2026, 5, 21)
_INTRODUCED = "v0.36.49"


# ---------------------------------------------------------------------------
# system_auditor — SYSTEM
# Health: last audit_reports row freshness via table_freshness_health.
# NOTE: two-layer staleness — audit verdict is only live once BOTH the process
# has restarted AND the stale audit_reports row has been regenerated (the
# governor trusts its last verdict for up to 36 h). See feedback note
# hotfix_deploy_two_layer_staleness in MEMORY.md.
# ---------------------------------------------------------------------------

def _system_auditor_health() -> dict:
    from src.data_collection._capability_health import table_freshness_health
    return table_freshness_health(
        table="audit_reports",
        ts_col="created_at",
        stale_after_minutes=1500,
        cadence_label="daily overnight",
    )


register_system(
    name="system_auditor",
    description=(
        "Daily and weekly auditor agent: analyzes trading activity for "
        "strategy drift, concentration risk, execution quality issues, "
        "model behaviour problems, and regime awareness gaps. Writes "
        "audit_reports rows consumed by the governor. WARNING: two-layer "
        "staleness — a new verdict only takes effect once the process "
        "restarts AND the stale audit_reports row regenerates (governor "
        "trusts last verdict up to 36 h)."
    ),
    category="evaluation",
    version="1.0",
    maintainer="ai_session",
    introduced_in=_INTRODUCED,
    last_reviewed_date=_TODAY,
    expected_runtime="daily overnight",
)(_system_auditor_health)


# ---------------------------------------------------------------------------
# model_monitor — SYSTEM
# Health: last drift-check freshness via MAX(actual_exit_time) on shadow_trades.
# ---------------------------------------------------------------------------

def _model_monitor_health() -> dict:
    from src.data_collection._capability_health import table_freshness_health
    return table_freshness_health(
        table="shadow_trades",
        ts_col="actual_exit_time",
        stale_after_minutes=2880,
        cadence_label="per closed trade",
    )


register_system(
    name="model_monitor",
    description=(
        "Model performance monitoring and regression detection: computes "
        "per-model-version live metrics (win rate, profit factor, Sharpe) "
        "and fires an automated alert when the active model underperforms "
        "the champion baseline. Health proxy: last closed trade timestamp."
    ),
    category="evaluation",
    version="1.0",
    maintainer="ai_session",
    introduced_in=_INTRODUCED,
    last_reviewed_date=_TODAY,
    expected_runtime="per closed trade",
)(_model_monitor_health)


# ---------------------------------------------------------------------------
# run_backtest — ACTION
# Backtest engine — distinct from the existing strategy_backtest wrapper.
# Kickoff: POST /api/training/backtest (backtester.py core engine).
# ---------------------------------------------------------------------------

@register_action(
    name="run_backtest",
    description=(
        "Run a full strategy backtest via the backtester engine "
        "(src/evaluation/backtester.py): applies entry signals, bracket "
        "exits, and risk-governor filters over historical data to produce "
        "equity-curve and performance-metric outputs. Distinct from the "
        "strategy_backtest wrapper used by the LLM council."
    ),
    category="evaluation",
    version="1.0",
    maintainer="ai_session",
    introduced_in=_INTRODUCED,
    last_reviewed_date=_TODAY,
    kickoff_endpoint="/api/training/backtest",
    input_schema=simple_io_schema(
        properties={
            "start_date": {
                "type": "string",
                "format": "date",
                "description": "Backtest start date (ISO 8601, e.g. 2025-01-01).",
            },
            "end_date": {
                "type": "string",
                "format": "date",
                "description": "Backtest end date (ISO 8601, e.g. 2025-12-31).",
            },
            "model_version": {
                "type": "string",
                "description": "Model version tag to evaluate; defaults to champion.",
            },
        },
        required=["start_date", "end_date"],
    ),
    output_schema=simple_io_schema(
        properties={
            "total_return": {"type": "number"},
            "sharpe_ratio": {"type": "number"},
            "win_rate": {"type": "number"},
            "trade_count": {"type": "integer"},
        },
        required=["total_return"],
    ),
    estimated_duration="2-10 minutes",
)
def run_backtest_capability() -> dict:
    return {
        "registered_at": _TODAY.isoformat(),
        "entry_module": "src.evaluation.capability_registration",
    }
