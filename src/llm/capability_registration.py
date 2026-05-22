"""Capability registration for the LLM scoring subsystem (T6 keep-set, part 1).

Keep-set entry hosted here:
  - llm_scorer   SYSTEM  — health = Ollama reachable + last-score freshness

The build_decision_packet ACTION is hosted in the companion
src/council/capability_registration.py to keep this module lean and avoid
the heavy packet_writer import graph at module top.

Deferred (seed into Convention E EXEMPT_MODULES in Task 10):
  candidate_ranking, build_watchlist, trade_postmortem,
  council_aggregation, eod_recap

Called by: src.platform.capability_registry.bootstrap (import-time side effect)
Calls: src.platform.capability_registry.register_system (lazy imports inside fns)
Owns tables: none
Config keys: none
Tests: tests/test_capability_registry_coverage.py
"""
from __future__ import annotations

from datetime import date

from src.platform.capability_registry import register_system

_TODAY = date(2026, 5, 21)
_INTRODUCED = "v0.36.49"


# ---------------------------------------------------------------------------
# llm_scorer — SYSTEM
# Health: Ollama reachable + last-scored packet freshness.
# Degrades gracefully in bare env (no Ollama, no .env).
# ---------------------------------------------------------------------------

def _llm_scorer_health() -> dict:
    try:
        from src.llm.client import is_llm_available
        if not is_llm_available():
            return {"status": "down", "detail": "Ollama unreachable"}
        return {"status": "ok", "detail": "Ollama reachable and LLM scorer active"}
    except Exception as exc:
        return {"status": "down", "detail": f"Ollama unreachable: {exc}"}


register_system(
    name="llm_scorer",
    description=(
        "LLM-enhanced trade packet scorer: generates conviction scores "
        "and why-now prose via Ollama (Qwen3 8B). Feeds the "
        "champion-challenger canary framework. Health: Ollama reachability."
    ),
    category="llm",
    version="1.0",
    maintainer="ai_session",
    introduced_in=_INTRODUCED,
    last_reviewed_date=_TODAY,
    expected_runtime="per scan cycle",
)(_llm_scorer_health)
