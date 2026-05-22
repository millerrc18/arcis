"""Capability registration for the 17 ALL_HANDLERS watch-loop handlers.

Each handler is registered as a scheduler ACTION whose name is the
``maybe_``-stripped function name (Convention A oracle).  The real
kickoff endpoint is ``scripts/run_watch_handler.py``, which already
exists (Task 1) and accepts either the stripped or prefixed name.

Called by: src.platform.capability_registry.bootstrap (import-time side effect)
Calls: src.platform.capability_registry.register_action,
       src.platform.capability_registry._io_schemas.simple_io_schema,
       src.scheduler.watch_handlers.ALL_HANDLERS
Owns tables: none
Config keys: none
Tests: tests/test_capability_registry_coverage.py (Convention A)
"""
from __future__ import annotations

from datetime import date

from src.platform.capability_registry import register_action
from src.platform.capability_registry._io_schemas import simple_io_schema
from src.scheduler.watch_handlers import ALL_HANDLERS

_TODAY = date(2026, 5, 21)
_VERSION = "1.0"
_MAINTAINER = "ai_session"
_INTRODUCED = "v0.36.49"

# Per-handler metadata: name -> (description, estimated_duration)
# Name = maybe_-stripped handler __name__ (Convention A oracle).
_HANDLER_META: dict[str, tuple[str, str]] = {
    "morning_training_stop": (
        "Stop the overnight GPU0 training subprocess at 5:15 AM weekdays (bounded cooperative-then-hard stop).",
        "1-2 minutes",
    ),
    "post_close_capture": (
        "Capture post-close snapshots at 5:30 PM weekdays before overnight processing begins.",
        "2-5 minutes",
    ),
    "overnight_training_collection": (
        "Collect training examples at 6:00 PM weekdays before the overnight training launch.",
        "5-15 minutes",
    ),
    "evening_training_launch": (
        "Launch the overnight GPU0 training run in the 18:30-04:00 ET window when the market is closed.",
        "1-3 minutes",
    ),
    "market_open_training_stop": (
        "Hard-ceiling safety net at or after 09:25 ET that stops any GPU0 training still running before market open.",
        "1-2 minutes",
    ),
    "stress_test": (
        "Re-run the model stress test at 7 PM weekdays when the active model version has changed.",
        "10-30 minutes",
    ),
    "data_collection": (
        "Run comprehensive data collection at 9:30 PM nightly (7 days/week; CPU/network only).",
        "30-60 minutes",
    ),
    "news_ingestion": (
        "Full-universe news pull at 10 PM nightly (7 days/week; Monday uses weekend news).",
        "15-30 minutes",
    ),
    "enrichment_precache": (
        "Pre-fetch fundamentals, insider data, and macro data at 11 PM nightly (7 days/week).",
        "20-45 minutes",
    ),
    "1min_bar_collection": (
        "Collect 1-minute OHLCV bars for the S&P 100 at 11:30 PM (intraday foundation).",
        "5-15 minutes",
    ),
    "pre_market_refresh": (
        "Quick pre-market data check and brief generation at 6 AM weekdays.",
        "5-10 minutes",
    ),
    "premarket_rolling_features": (
        "Compute rolling features at 6:02 AM weekdays after the pre-market refresh.",
        "10-20 minutes",
    ),
    "premarket_training": (
        "Generate pre-market training data at 7 AM weekdays.",
        "10-20 minutes",
    ),
    "premarket_news_scoring": (
        "Score pre-market news relevance at 8:02 AM weekdays.",
        "5-15 minutes",
    ),
    "premarket_candidates": (
        "Build the pre-market candidate list and send the completion notification at 9:00-9:24 AM weekdays.",
        "5-10 minutes",
    ),
    "stats_pulse": (
        "Send trading-stats Telegram pulse at pre-market (7:45), midday (12:00), and post-close (16:05) on weekdays.",
        "1-2 minutes",
    ),
    "walkforward_reconciler": (
        "Find and auto-fire orphan backtests hourly during market hours (11-15 ET) on weekdays.",
        "2-5 minutes",
    ),
}

_INPUT_SCHEMA = simple_io_schema(
    properties={
        "at": {
            "type": "string",
            "format": "date-time",
            "description": "ISO timestamp override; defaults to now (ET)",
        },
        "force": {
            "type": "boolean",
            "description": "bypass the schedule-window gate",
        },
    },
    required=[],
)

_OUTPUT_SCHEMA = simple_io_schema()


def _stripped(name: str) -> str:
    return name[len("maybe_"):] if name.startswith("maybe_") else name


for _handler in ALL_HANDLERS:
    _action_name = _stripped(_handler.__name__)
    _desc, _duration = _HANDLER_META[_action_name]

    @register_action(
        name=_action_name,
        description=_desc,
        category="scheduler",
        version=_VERSION,
        maintainer=_MAINTAINER,
        introduced_in=_INTRODUCED,
        last_reviewed_date=_TODAY,
        kickoff_endpoint=f"python scripts/run_watch_handler.py --handler {_action_name}",
        history_endpoint=None,
        input_schema=_INPUT_SCHEMA,
        output_schema=_OUTPUT_SCHEMA,
        estimated_duration=_duration,
    )
    def _anchor(
        _name: str = _action_name,
        _date: date = _TODAY,
    ) -> dict:
        return {"registered_at": _date.isoformat(), "entry_module": "src.scheduler.handler_registration"}
