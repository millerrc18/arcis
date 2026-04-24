"""SQL helpers for shadow_trades.status filtering — uses canonical constants.

Called by: shadow_trading.executor, shadow_trading.reconcile, risk.governor, scheduler.reports
Calls: shadow_trading.models
Owns tables: none
Config keys: none
Tests: tests/test_tier_1_hardening.py

Centralizes the IN-clause expansion of TERMINAL_STATUSES / ACTIVE_STATUSES so
that future status additions automatically propagate to all consumer queries
without each call site needing to enumerate them. Closes #437 and #482.

CLAUDE.md rule: "use TERMINAL_STATUSES and ACTIVE_STATUSES from
src/shadow_trading/models.py in queries. Never hardcode status != 'closed'."

Usage:
    from src.shadow_trading._status_sql import terminal_in_clause

    frag, params = terminal_in_clause()  # frag = "?, ?, ?, ?, ?"
    cur.execute(
        f"SELECT pnl_dollars FROM shadow_trades WHERE status IN ({frag})",
        params,
    )

The fragments use parameterized placeholders, never inline string
interpolation, so SQL injection remains impossible even though the values
flow through an f-string for the placeholder count.

Both helpers return a sorted tuple so query plans / cache keys are stable
across runs (frozenset iteration order is implementation-defined).
"""

from __future__ import annotations

from src.shadow_trading.models import ACTIVE_STATUSES, TERMINAL_STATUSES


def terminal_in_clause() -> tuple[str, tuple[str, ...]]:
    """Return (sql_fragment, params) for `status IN (...)` matching any
    terminal status. Caller embeds the fragment into the SQL string and
    passes the params tuple to execute().

    Example fragment: ``"?, ?, ?, ?, ?"`` (one placeholder per status).
    """
    values = tuple(sorted(TERMINAL_STATUSES))
    placeholders = ", ".join("?" * len(values))
    return placeholders, values


def active_in_clause() -> tuple[str, tuple[str, ...]]:
    """Return (sql_fragment, params) for `status IN (...)` matching any
    active (non-terminal) status."""
    values = tuple(sorted(ACTIVE_STATUSES))
    placeholders = ", ".join("?" * len(values))
    return placeholders, values
