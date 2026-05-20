"""Regression-lock for v0.36.32 — F-3: phantom-close drift anomaly alarm.

Background (W21 lifecycle audit, finding F-3, CRITICAL)
======================================================

`exit_reconciliation._check_trade` checked timeout exits only for
`duration_days < timeout_days`. A phantom-close (v0.36.28) where exit_price
was set to the entry-order fill passes that check silently — the position
exits at ~entry price on a multi-day hold and looks like a normal flat day.

This is the alarm that would have caught v0.36.28 in week 1 instead of
week 36. The reconciliation pass is the natural detection point but had no
drift check.

Threshold calibration note
==========================

The audit recommended 5 bps. But the canonical AMD case (`dcd090be`) had
entry=$439.80, exit=$440.72 → drift = 0.92/439.80 = **21 bps**, ABOVE the
5 bps floor. The audit's own threshold would have MISSED the bug it's
named for. We use **50 bps (0.5%)** instead: catches AMD with margin, and
genuine multi-day (>= 1 trading day) holds essentially never move < 0.5%.
A flag here is an anomaly-log entry (not a halt), so modest false-positive
tolerance is acceptable.

The fix
=======

`_is_phantom_drift_anomaly(row)` flags timeout/target_1/target_2/stop_loss
exits where `duration_days >= 1` AND the exit/entry price drift is below
`_PHANTOM_DRIFT_TOLERANCE` (50 bps). Wired into `_check_trade` as an
additional anomaly condition (OR with the existing per-reason checks).
"""
from __future__ import annotations

import pytest


def _row(**kw):
    """Build a dict row that supports both [] and .get (dicts do both)."""
    base = {
        "trade_id": "test-1",
        "ticker": "AMD",
        "exit_reason": "timeout",
        "actual_exit_price": None,
        "actual_entry_price": None,
        "entry_price": None,
        "stop_price": None,
        "target_1": None,
        "target_2": None,
        "duration_days": None,
        "timeout_days": 10,
        "actual_entry_time": None,
        "direction": "long",
    }
    base.update(kw)
    return base


def test_amd_phantom_close_is_flagged():
    """The canonical AMD dcd090be phantom: entry $439.80 → exit $440.72,
    10-day timeout. Drift = 21 bps. Must be flagged (< 50 bps tolerance)."""
    from src.shadow_trading.exit_reconciliation import _is_phantom_drift_anomaly

    row = _row(
        exit_reason="timeout",
        actual_entry_price=439.80,
        actual_exit_price=440.72,
        duration_days=10,
        timeout_days=10,
    )
    assert _is_phantom_drift_anomaly(row) is True, (
        "AMD phantom-close (21 bps drift on 10-day hold) was NOT flagged. "
        "This is the exact v0.36.28 case F-3 is meant to catch."
    )


def test_genuine_multiday_move_not_flagged():
    """A real 5% move over 10 days is normal — not a phantom."""
    from src.shadow_trading.exit_reconciliation import _is_phantom_drift_anomaly

    row = _row(
        exit_reason="timeout",
        actual_entry_price=100.0,
        actual_exit_price=105.0,  # 500 bps
        duration_days=10,
    )
    assert _is_phantom_drift_anomaly(row) is False


def test_exact_zero_drift_multiday_flagged():
    """exit == entry on a 5-day hold → definitely phantom."""
    from src.shadow_trading.exit_reconciliation import _is_phantom_drift_anomaly

    row = _row(
        exit_reason="timeout",
        actual_entry_price=100.0,
        actual_exit_price=100.0,  # 0 bps
        duration_days=5,
    )
    assert _is_phantom_drift_anomaly(row) is True


def test_intraday_flat_not_flagged():
    """duration_days < 1 (intraday) flat exit is normal — not flagged."""
    from src.shadow_trading.exit_reconciliation import _is_phantom_drift_anomaly

    row = _row(
        exit_reason="timeout",
        actual_entry_price=100.0,
        actual_exit_price=100.0,
        duration_days=0,
    )
    assert _is_phantom_drift_anomaly(row) is False


def test_null_exit_price_not_flagged():
    """Can't compute drift without exit price → not flagged (fail-safe)."""
    from src.shadow_trading.exit_reconciliation import _is_phantom_drift_anomaly

    row = _row(
        exit_reason="timeout",
        actual_entry_price=100.0,
        actual_exit_price=None,
        duration_days=5,
    )
    assert _is_phantom_drift_anomaly(row) is False


def test_non_price_exit_reason_not_flagged():
    """reconciled_stale / unknown exits aren't price-based — skip drift check."""
    from src.shadow_trading.exit_reconciliation import _is_phantom_drift_anomaly

    row = _row(
        exit_reason="reconciled_stale",
        actual_entry_price=100.0,
        actual_exit_price=100.0,
        duration_days=5,
    )
    assert _is_phantom_drift_anomaly(row) is False


def test_stop_loss_phantom_flagged():
    """A stop_loss exit at ~entry price on a multi-day hold is also a phantom."""
    from src.shadow_trading.exit_reconciliation import _is_phantom_drift_anomaly

    row = _row(
        exit_reason="stop_loss",
        actual_entry_price=200.0,
        actual_exit_price=200.05,  # 2.5 bps
        duration_days=3,
        stop_price=190.0,
    )
    assert _is_phantom_drift_anomaly(row) is True


def test_check_trade_flags_phantom_timeout():
    """End-to-end: _check_trade returns True (anomalous) for the AMD phantom,
    even though it passes the duration_days < timeout_days check."""
    from src.shadow_trading.exit_reconciliation import _check_trade

    # duration_days(10) < timeout_days(15) → passes the legacy timeout check
    # (would return False/clean), but zero-drift makes it anomalous.
    row = _row(
        exit_reason="timeout",
        actual_entry_price=439.80,
        actual_exit_price=440.72,
        duration_days=10,
        timeout_days=15,
    )
    assert _check_trade(row) is True, (
        "_check_trade should flag the phantom timeout via the drift check "
        "even though duration_days(10) < timeout_days(15) passes the legacy check."
    )
