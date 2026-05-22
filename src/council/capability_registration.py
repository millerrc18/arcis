"""Capability registrations for the council and decision-packet family (T6 keep-set).

Keep-set entries hosted here:
  - council_engine        SYSTEM   — health = last council run freshness
  - build_decision_packet ACTION   — LLM trade-packet assembly (packet_writer.py)

llm_scorer SYSTEM is hosted in src/llm/capability_registration.py.

Deferred (seed into Convention E EXEMPT_MODULES in Task 10):
  candidate_ranking, build_watchlist, trade_postmortem,
  council_aggregation, eod_recap

Called by: src.platform.capability_registry.bootstrap (import-time side effect)
Calls: src.platform.capability_registry.register_*, lazy imports inside fns
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
# council_engine — SYSTEM
# Health: last council_sessions row freshness (lazy import; degrade-not-raise).
# ---------------------------------------------------------------------------

def _council_engine_health() -> dict:
    try:
        from src.config import DB_PATH
        from src.utils.db import DBOperationalError, connect_db
        try:
            conn = connect_db(DB_PATH)
        except Exception as exc:
            return {"status": "degraded", "detail": f"db unavailable: {exc}"}
        try:
            row = conn.execute(
                "SELECT MAX(created_at) FROM council_sessions"
            ).fetchone()
        except DBOperationalError as exc:
            return {"status": "degraded", "detail": f"council_sessions unavailable: {exc}"}
        finally:
            conn.close()
        last = (row or (None,))[0]
        if last is None:
            return {"status": "degraded", "detail": "no council run recorded"}
        return {"status": "ok", "detail": f"last council run at {last}"}
    except Exception as exc:
        return {"status": "degraded", "detail": f"no council run recorded: {exc}"}


register_system(
    name="council_engine",
    description=(
        "Modified Delphi council engine: runs 5-agent vote-first sessions "
        "to build consensus on trade decisions. Conditional Round 2 fires "
        "when Round 1 lacks 3/5 agreement. Health: last council_sessions row."
    ),
    category="council",
    version="1.0",
    maintainer="ai_session",
    introduced_in=_INTRODUCED,
    last_reviewed_date=_TODAY,
    expected_runtime="on-demand per scan cycle",
)(_council_engine_health)


# ---------------------------------------------------------------------------
# build_decision_packet — ACTION
# Kickoff: real route /api/scan/packet or CLI equivalent via scan_service.
# ---------------------------------------------------------------------------

@register_action(
    name="build_decision_packet",
    description=(
        "Build a LLM-enhanced trade decision packet for a candidate ticker: "
        "generates conviction score, why-now prose, and key-risk annotation "
        "via Ollama (packet_writer.py). Falls back to deterministic template "
        "when Ollama is unavailable."
    ),
    category="llm",
    version="1.0",
    maintainer="ai_session",
    introduced_in=_INTRODUCED,
    last_reviewed_date=_TODAY,
    kickoff_endpoint="/api/scan/packet",
    input_schema=simple_io_schema(
        properties={
            "ticker": {
                "type": "string",
                "description": "Equity ticker to build the decision packet for.",
            },
            "force_template": {
                "type": "boolean",
                "description": "Skip LLM and use deterministic template.",
            },
        },
        required=["ticker"],
    ),
    output_schema=simple_io_schema(
        properties={
            "ticker": {"type": "string"},
            "conviction": {"type": "number"},
            "why_now": {"type": "string"},
            "key_risk": {"type": "string"},
        },
        required=["ticker"],
    ),
    estimated_duration="5-30 seconds",
)
def build_decision_packet_capability() -> dict:
    return {
        "registered_at": _TODAY.isoformat(),
        "entry_module": "src.council.capability_registration",
    }
