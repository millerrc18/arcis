"""Capability registrations for the shadow_trading execution/exits family.

Keep-set (T5, 3 entries):
  - submit_shadow_trade  ACTION   — paper trade entry via open_shadow_trade
  - position_exit_manager SYSTEM  — health = MAX(updated_at) on active trades
  - trade_reconciler      SYSTEM  — reconcile-engine health (distinct from
                                    the reconcile_trades proxy in reconcile_state.py)

Deferred (seed into Convention E EXEMPT_MODULES in Task 10):
  exit_reason_classifier, decision_trade_alerts, bracket_monitor

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
# submit_shadow_trade — ACTION
# Kickoff: the paper-trade entry route in the shadow-trading API.
# Anchor near executor.open_shadow_trade (executor.py:557).
# ---------------------------------------------------------------------------

@register_action(
    name="submit_shadow_trade",
    description=(
        "Submit a paper trade for the shadow-trading ledger via "
        "open_shadow_trade(). Applies the full decision chain: "
        "risk-governor checks, position limits, duplicate guard, "
        "and bracket order placement."
    ),
    category="shadow-trading",
    version="1.0",
    maintainer="ai_session",
    introduced_in=_INTRODUCED,
    last_reviewed_date=_TODAY,
    kickoff_endpoint="/api/shadow/open",
    input_schema=simple_io_schema(
        properties={
            "recommendation_id": {
                "type": "string",
                "description": "UUID of the recommendation driving this trade.",
            },
            "ticker": {
                "type": "string",
                "description": "Equity ticker symbol (e.g. AAPL).",
            },
            "dry_run": {
                "type": "boolean",
                "description": "If true, validate only — do not persist.",
            },
        },
        required=["recommendation_id", "ticker"],
    ),
    output_schema=simple_io_schema(
        properties={
            "trade_id": {"type": "string"},
            "status": {"type": "string"},
            "rejected_reason": {"type": "string"},
        },
        required=["status"],
    ),
    estimated_duration="<1 second",
)
def submit_shadow_trade_capability() -> dict:
    return {
        "registered_at": _TODAY.isoformat(),
        "entry_module": "src.shadow_trading.capability_registration",
    }


# ---------------------------------------------------------------------------
# position_exit_manager — SYSTEM
# Health: MAX(updated_at) on active shadow_trades rows.
# ---------------------------------------------------------------------------

def _position_exit_manager_health() -> dict:
    from src.data_collection._capability_health import table_freshness_health
    return table_freshness_health(
        table="shadow_trades",
        ts_col="updated_at",
        stale_after_minutes=30,
        cadence_label="every 5 min during market hours",
    )


register_system(
    name="position_exit_manager",
    description=(
        "Monitors all open positions for exit conditions: stop-loss hits, "
        "take-profit targets, timeout, and bracket fills. Runs every 5 min "
        "during market hours. Health proxy: MAX(updated_at) on shadow_trades."
    ),
    category="shadow-trading",
    version="1.0",
    maintainer="ai_session",
    introduced_in=_INTRODUCED,
    last_reviewed_date=_TODAY,
    expected_runtime="every 5 min during market hours",
)(_position_exit_manager_health)


# ---------------------------------------------------------------------------
# trade_reconciler — SYSTEM
# Distinct from reconcile_trades proxy (reconcile_state.py).
# Health: reconcile-engine freshness via MAX(updated_at) on shadow_trades.
# ---------------------------------------------------------------------------

def _trade_reconciler_health() -> dict:
    from src.data_collection._capability_health import table_freshness_health
    return table_freshness_health(
        table="shadow_trades",
        ts_col="updated_at",
        stale_after_minutes=30,
        cadence_label="reconcile engine",
    )


register_system(
    name="trade_reconciler",
    description=(
        "Core reconciliation engine: syncs shadow-trade journal with "
        "Alpaca broker state, closes positions on fill confirmation, "
        "and resolves orphaned or drift-detected trades. Distinct from "
        "the reconcile_trades health proxy."
    ),
    category="shadow-trading",
    version="1.0",
    maintainer="ai_session",
    introduced_in=_INTRODUCED,
    last_reviewed_date=_TODAY,
    expected_runtime="every 5 min",
)(_trade_reconciler_health)
