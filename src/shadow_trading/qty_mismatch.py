"""Qty-mismatch detection helpers for the executor exit-retry path.

Called by: shadow_trading.executor (_retry_exit)
Calls: re (stdlib only)
Owns tables: none
Config keys: none
Tests: tests/shadow_trading/test_qty_mismatch.py

Track 1.5 / B2.C — CVS regression (trade 00330e8d, 2026-04-21).

A2's forensic memo surfaced that CVS hit 25+ consecutive APIError(40310000)
exit attempts in a single day because local state believed 130 shares were
held but the broker had only 4. The executor blindly retried all day with no
detection and no abort. This module provides the two primitives that fix it:

  parse_qty_mismatch — extracts (requested, available) from Alpaca's
      "insufficient qty available: requested N, available M (code: 40310000)"
      message. Returns None for any other message, including other API codes.

  should_abort_retry — returns True when the consecutive-error count reaches
      or exceeds the threshold (default 3), signalling the executor must stop
      retrying and mark the trade for manual reconciliation.
"""
from __future__ import annotations

import re


# Regex: anchored on the literal API error code 40310000 AND the
# "requested N ... available M" pattern. Both anchors must be present
# for the match to succeed — a message with the right digits but the
# wrong code (e.g., 40310001) will NOT match.
_QTY_CODE_RE = re.compile(r"40310000")
_QTY_DIGITS_RE = re.compile(r"requested\s+(\d+).*?available\s+(\d+)", re.DOTALL)


def parse_qty_mismatch(message: str | None) -> tuple[int, int] | None:
    """Parse Alpaca's insufficient-qty error message.

    Returns (requested, available) as integers if both anchors match:
      1. The literal code '40310000' is present in the message.
      2. The pattern 'requested N ... available M' is present.

    Returns None for any other input, including None, empty strings,
    messages with different API codes, or messages missing the digit
    pattern (e.g., a buying-power error that happens to carry 40310000).
    """
    if not message:
        return None
    if not _QTY_CODE_RE.search(message):
        return None
    m = _QTY_DIGITS_RE.search(message)
    if not m:
        return None
    return int(m.group(1)), int(m.group(2))


def should_abort_retry(consecutive_count: int, threshold: int = 3) -> bool:
    """Return True when consecutive qty-mismatch errors reach the threshold.

    Args:
        consecutive_count: Number of consecutive 40310000 errors seen for
            the same ticker in this scan cycle.
        threshold: How many consecutive errors before the executor stops.
            Default 3 matches _MAX_EXIT_RETRIES in executor.py.

    Returns:
        True  when consecutive_count >= threshold (abort, mark exit_failed).
        False when consecutive_count < threshold (may still retry).
    """
    return consecutive_count >= threshold
