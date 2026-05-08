"""Finnhub data ingestion adapter utilities.

Called by: scripts/fetch_earnings_calendar, notifications/telegram
Calls: none
Owns tables: none
Config keys: none
Tests: tests/notifications/test_t13c_earnings_time.py

Normalization helpers for data returned by the Finnhub API and compatible
sources (yfinance earnings calendar, etc.).
"""

from __future__ import annotations

_BMO_TOKENS = frozenset({"bmo", "pre", "before"})
_AMC_TOKENS = frozenset({"amc", "after"})


def normalize_earnings_time(raw: str | None) -> str:
    """Normalize raw earnings_time labels to canonical BMO / AMC / TBD.

    Handles the variety of strings returned by Finnhub, yfinance, and
    manual DB entries:
      "Pre-market", "PRE", "before market", "before market open" → "BMO"
      "After hours", "AMC", "after market", "After Market Close" → "AMC"
      None, "", "TBD", or unrecognised strings → "TBD"
    """
    if not raw:
        return "TBD"
    lower = raw.strip().lower()
    if not lower or lower == "tbd":
        return "TBD"
    for token in _BMO_TOKENS:
        if token in lower:
            return "BMO"
    for token in _AMC_TOKENS:
        if token in lower:
            return "AMC"
    return "TBD"
