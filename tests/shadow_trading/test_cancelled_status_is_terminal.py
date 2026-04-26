"""Sprint 0 / Wave 2b — 'cancelled' must be in TERMINAL_STATUSES.

Before this fix, status='cancelled' (set when an entry order is cancelled
because exit triggered before the order filled — executor.py line 1884) was
in NEITHER TERMINAL_STATUSES nor ACTIVE_STATUSES. Cohort and dashboard queries
that filter on terminal-vs-active silently dropped these rows entirely.

Operator decision Q5 (2026-04-26): Option A — preserve the distinction;
do NOT collapse 'cancelled' to 'rejected'. Add it to TERMINAL_STATUSES.

This test locks the constant and verifies that all consumers that go through
terminal_in_clause() automatically pick up 'cancelled' (the centralized
SQL helper is the canonical pattern per CLAUDE.md).
"""
from __future__ import annotations


def test_cancelled_in_terminal_statuses():
    from src.shadow_trading.models import TERMINAL_STATUSES
    assert "cancelled" in TERMINAL_STATUSES, (
        "'cancelled' must be in TERMINAL_STATUSES — see executor.py line 1884 "
        "where status='cancelled' is written when an entry is cancelled "
        "before fill due to an exit signal."
    )


def test_cancelled_visible_in_terminal_in_clause():
    """The centralized terminal_in_clause helper auto-expands TERMINAL_STATUSES."""
    from src.shadow_trading._status_sql import terminal_in_clause

    placeholders, params = terminal_in_clause()
    assert "cancelled" in params, (
        f"terminal_in_clause params {params!r} must include 'cancelled' "
        "so SQL queries against shadow_trades.status see cancelled rows."
    )
    # Sanity: placeholder count matches param count
    assert placeholders.count("?") == len(params)


def test_cancelled_not_in_active_statuses():
    """'cancelled' is terminal, not active — exclusivity check."""
    from src.shadow_trading.models import ACTIVE_STATUSES
    assert "cancelled" not in ACTIVE_STATUSES, (
        "'cancelled' is a terminal status; must not also be in ACTIVE_STATUSES "
        "(otherwise the active vs. terminal partition would overlap)."
    )


def test_terminal_and_active_remain_disjoint():
    """Defensive: TERMINAL_STATUSES and ACTIVE_STATUSES must remain disjoint."""
    from src.shadow_trading.models import ACTIVE_STATUSES, TERMINAL_STATUSES
    overlap = TERMINAL_STATUSES & ACTIVE_STATUSES
    assert not overlap, f"TERMINAL_STATUSES and ACTIVE_STATUSES overlap: {overlap}"
