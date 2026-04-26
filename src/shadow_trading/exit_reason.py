"""Controlled vocabulary for shadow_trades.exit_reason + coercion helper.

Called by: executor.py (all exit_reason writes)
Calls: logging
Owns tables: none
Config keys: none
Tests: tests/shadow_trading/test_exit_reason_taxonomy.py

Track 1.5 / B3 — writer-side validation for exit_reason column.
Forward-only enforcement: existing out-of-vocab rows are preserved as-is.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

CONTROLLED_VOCAB: frozenset[str] = frozenset({
    "target_1",
    "target_2",
    "stop_loss",
    "timeout",
    "manual",
    "reconciled",
    "reconciled_stale",
    "exit_overshoot_detected",
    "qty_mismatch_partial_fill",
    # Sprint 0 / Wave 2b — promoted to first-class so prefix info isn't lost
    # when the executor cancels an unfilled entry, accepts a partial exit
    # fill, or marks a row after a broker-side exception.
    "entry_unfilled",
    "partial_exit",
    "broker_exception",
    "error",
    "unknown",
})

LEGACY_COERCIONS: dict[str, str] = {
    "target_1_hit": "target_1",
    "target_2_hit": "target_2",
    "stop_hit": "stop_loss",
    "take_profit": "target_1",
    "mr_timeout": "timeout",
    "rsi_exit": "target_1",
    "atr_stop": "stop_loss",
    "late_fill_reconciled": "reconciled",
    "manual_alpaca_close_op_confirmed": "manual",
}


def coerce_exit_reason(value: str, ticker: str = "") -> str:
    """Return value if in vocab; coerce legacy synonyms; else log warning and return 'unknown'.

    Known synonym mappings from LEGACY_COERCIONS are applied silently (no warning).
    Unknown values that are not in the vocab and not in LEGACY_COERCIONS trigger a
    WARNING log with [EXIT_REASON_INVALID] prefix and return 'unknown'.
    """
    if value in CONTROLLED_VOCAB:
        return value
    if value in LEGACY_COERCIONS:
        return LEGACY_COERCIONS[value]
    logger.warning(
        "[EXIT_REASON_INVALID] received=%r ticker=%s fallback=unknown",
        value,
        ticker,
    )
    return "unknown"
