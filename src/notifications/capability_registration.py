"""Capability registrations for the notifications/attribution family (T9 keep-set).

Keep-set (2 entries):
  - telegram_notifier   SYSTEM  — health = token configured + last-send freshness
  - spy_benchmark_state STATE   — query = current SPY benchmark data; degrade to
                                  {value: None} on missing source

Deferred (seed into Convention E EXEMPT_MODULES in Task 10):
  telegram_command_handler, notification_policy, platform_event_bus,
  attribution_backtest

Called by: src.platform.capability_registry.bootstrap (import-time side effect)
Calls: src.platform.capability_registry.register_system, register_state
       (lazy imports inside fns — degrade-not-raise in bare env)
Owns tables: none
Config keys: telegram.bot_token, telegram.chat_id, telegram.enabled
Tests: tests/test_capability_registry_coverage.py
"""
from __future__ import annotations

from datetime import date

from src.platform.capability_registry import register_state, register_system

_TODAY = date(2026, 5, 21)
_INTRODUCED = "v0.36.49"


# ---------------------------------------------------------------------------
# telegram_notifier — SYSTEM
# Health: token configured + last-send attempt freshness.
# Degrades gracefully when no token in config (no .env, bare CI env).
# ---------------------------------------------------------------------------

def _telegram_notifier_health() -> dict:
    try:
        from src.config import load_config
        cfg = load_config()
        tg = cfg.get("telegram", {}) if isinstance(cfg, dict) else {}
        token = tg.get("bot_token") or ""
        enabled = tg.get("enabled", False)
        if not token:
            return {"status": "degraded", "detail": "not configured: no bot_token"}
        if not enabled:
            return {"status": "degraded", "detail": "telegram disabled in config"}
        return {"status": "ok", "detail": "telegram notifier configured and enabled"}
    except Exception as exc:
        return {"status": "degraded", "detail": f"not configured: {exc}"}


register_system(
    name="telegram_notifier",
    description=(
        "Real-time Telegram alert client: fires notifications for trade "
        "opens/closes, scan results, system events, overnight pipeline "
        "status, and model milestones. Health: bot_token present and "
        "telegram.enabled=true in config. Degrades (not raises) when "
        "unconfigured."
    ),
    category="notifications",
    version="1.0",
    maintainer="ai_session",
    introduced_in=_INTRODUCED,
    last_reviewed_date=_TODAY,
    expected_runtime="event-driven",
)(_telegram_notifier_health)


# ---------------------------------------------------------------------------
# spy_benchmark_state — STATE
# Query: SPY benchmark data for excess-return attribution.
# Degrades to {value: None} when yfinance or sector lookup is unavailable.
# ---------------------------------------------------------------------------

def _spy_benchmark_query() -> dict:
    try:
        from src.analytics.spy_benchmark import _load_sector_lookup
        sectors = _load_sector_lookup()
        return {
            "value": {
                "sector_count": len(sectors),
                "source": "data/reference/sp100-gics-lookup.csv",
            }
        }
    except Exception:
        return {"value": None}


register_state(
    name="spy_benchmark_state",
    description=(
        "SPY excess-return benchmark state: GICS sector lookup and SPY "
        "return-over-range calculations used to separate alpha from "
        "bull-market beta drift in closed-trade attribution. "
        "Source: data/reference/sp100-gics-lookup.csv + yfinance."
    ),
    category="analytics",
    version="1.0",
    maintainer="ai_session",
    introduced_in=_INTRODUCED,
    last_reviewed_date=_TODAY,
    refresh_hint="refreshes on demand via journal.store close_shadow_trade hook",
)(_spy_benchmark_query)
