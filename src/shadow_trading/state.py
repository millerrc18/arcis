"""State query: shadow trade cohort counts.

Thin wrapper that the capability registry exposes via /api/system/index.
The underlying data lives in the shadow_trades table; the query uses the
canonical TERMINAL_STATUSES / ACTIVE_STATUSES constants from models.py
rather than hardcoding status strings.

Called by: src.platform.capability_registry.bootstrap (import-time side effect)
Calls: src.config.DB_PATH, sqlite3, src.shadow_trading._status_sql
Owns tables: none (reads shadow_trades)
Config keys: none
Tests: tests/shadow_trading/test_state.py, tests/shadow_trading/test_status_in_clause_adoption.py

Sprint 0 / Wave 1b STATUS-CONST: pre-fix this query hardcoded `status='open'`
and `status='closed'` for the SUM CASE buckets, which undercounted any
non-`closed` terminal status (rejected, failed, exit_abandoned,
needs_manual_review) in `closed_n` and any non-`open` active status
(pending, exit_pending, exit_failed, submission_uncertain) in `open_n`.

Note on the public dict key `"closed"`: the bucket now counts ALL terminal
statuses (per the canonical TERMINAL_STATUSES set), not literally
`status='closed'`. The legacy public key is preserved to avoid breaking
the capability registry / dashboard consumers; readers MUST treat it as
"terminal trades" not "literally closed".
"""
from __future__ import annotations

import sqlite3
from datetime import date

from src.config import DB_PATH
from src.utils.db import DBOperationalError, connect_db
from src.platform.capability_registry import register_state
from src.shadow_trading._status_sql import active_in_clause, terminal_in_clause


def _shadow_cohort_counts() -> dict:
    """Return {open, closed, quarantined, total} counts as a single row.

    "open" counts trades with status in ACTIVE_STATUSES; "closed" counts
    trades with status in TERMINAL_STATUSES. The public dict keys are kept
    legacy-named for compatibility with /api/system/index consumers.
    """
    active_frag, active_params = active_in_clause()
    terminal_frag, terminal_params = terminal_in_clause()
    conn = connect_db(DB_PATH)
    try:
        row = conn.execute(
            "SELECT "
            f"  SUM(CASE WHEN status IN ({active_frag}) THEN 1 ELSE 0 END) AS open_n, "
            f"  SUM(CASE WHEN status IN ({terminal_frag}) THEN 1 ELSE 0 END) AS closed_n, "
            "  SUM(CASE WHEN COALESCE(quarantined, 0) = 1 THEN 1 ELSE 0 END) AS quarantined_n, "
            "  COUNT(*) AS total_n "
            "FROM shadow_trades",
            active_params + terminal_params,
        ).fetchone()
    except DBOperationalError as exc:
        return {"error": f"shadow_trades unavailable: {exc}"}
    finally:
        conn.close()
    open_n, closed_n, quarantined_n, total_n = (row or (0, 0, 0, 0))
    return {
        "value": {
            "open": int(open_n or 0),
            "closed": int(closed_n or 0),
            "quarantined": int(quarantined_n or 0),
            "total": int(total_n or 0),
        },
    }


@register_state(
    name="shadow_trade_cohort",
    description=(
        "Counts of shadow trades by status (open/closed/quarantined) "
        "and total cohort size. Powers promotion-gate decisions and "
        "diagnostic dashboards."
    ),
    category="shadow-trading",
    version="1.0",
    maintainer="ai_session",
    introduced_in="v0.22.0",
    last_reviewed_date=date(2026, 4, 18),
    refresh_hint="real-time",
)
def shadow_trade_cohort() -> dict:
    return _shadow_cohort_counts()
