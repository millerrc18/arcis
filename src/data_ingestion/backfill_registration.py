"""Capability registration for EDGAR historical backfill (CLI-only action).

The backfill itself lives at scripts/backfill_edgar_historical.py — a
standalone script that isn't imported at runtime. This module exists so
the bootstrap can register the capability; the UI shows it as a known
action with ui_kickoff_available=False so the button is disabled and the
detail view documents the CLI invocation.

Sprint 1B registration:
- edgar_historical_backfill (Action, CLI-only)

Called by: src.platform.capability_registry.bootstrap (import-time side effect)
Calls: src.platform.capability_registry.register_action
Owns tables: none
Config keys: none
Tests: tests/data_ingestion/test_backfill_registration.py
"""
from __future__ import annotations

from datetime import date

from src.platform.capability_registry import register_action


@register_action(
    name="edgar_historical_backfill",
    description=(
        "Backfill EDGAR 10-K/10-Q filings for historical periods "
        "(2019-2023) to enable Lazy Prices cosine-similarity features. "
        "CLI-only in v1; see scripts/backfill_edgar_historical.py."
    ),
    category="data-ingestion",
    version="1.0",
    maintainer="operator",
    introduced_in="v0.24.0",
    last_reviewed_date=date(2026, 4, 18),
    kickoff_endpoint="scripts/backfill_edgar_historical.py",
    history_endpoint=None,
    input_schema={
        "type": "object",
        "properties": {
            "year_start": {"type": "integer", "minimum": 2000},
            "year_end": {"type": "integer", "maximum": 2030},
        },
        "additionalProperties": False,
    },
    output_schema={
        "type": "object",
        "properties": {
            "filings_ingested": {"type": "integer"},
            "tickers_covered": {"type": "integer"},
        },
    },
    estimated_duration="hours (large backfills)",
    ui_kickoff_available=False,
)
def edgar_backfill_capability() -> dict:
    """Registration anchor — kickoff is a CLI command, not a UI button."""
    return {"entry_module": "src.data_ingestion.backfill_registration"}
