"""Live-prod schema + FK reconciliation — the AUTHORITATIVE gate (#95, §3.7).

The registry completeness guard (classification.assert_partition_complete) is
necessary but NOT sufficient: the wipe runs against LIVE prod PG, which this
codebase repeatedly sees drift out of registry sync (notifications_* missing
2026-06-02; no PG schema auto-sync post-cutover). An unregistered live table is
invisible to the registry guard, the partition, AND the §3.5 FK proof — it could
silently survive the clean slate, or a CASCADE could reach it via an unmodeled
live FK.

`reconcile_live_schema(dsn)` and `reconcile_live_fk_edges(dsn)` run read-only
against the prod DSN in Phase 0 and ABORT on any drift, immediately before
anything irreversible. Uses pg_connect(dsn=...) ONLY (never connect_db, whose
cutover-gate could route to SQLite).

Tests: tests/scripts/test_clean_slate_live_schema.py
"""

from __future__ import annotations

import logging

from scripts._clean_slate._errors import CleanSlateAbort
from scripts._clean_slate.classification import EXPECTED_FK_EDGES, WIPE_TABLES
from src.schema import registry
from src.tools._db import pg_connect

logger = logging.getLogger(__name__)


def live_public_tables(dsn: str) -> set[str]:
    """Return the set of public BASE TABLE names in the live DB (read-only)."""
    with pg_connect(dsn, read_only=True) as (_conn, cur):
        cur.execute(
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'public'
              AND table_type = 'BASE TABLE'
            """
        )
        return {row["table_name"] for row in cur.fetchall()}


def live_wipe_touching_fk_edges(dsn: str) -> set[tuple[str, str, str]]:
    """Return live FK edges (child, child_col, parent) where child OR parent is
    in WIPE_TABLES — normalized for comparison against EXPECTED_FK_EDGES."""
    wipe_list = sorted(WIPE_TABLES)
    with pg_connect(dsn, read_only=True) as (_conn, cur):
        cur.execute(
            """
            SELECT
                tc.table_name        AS child_table,
                kcu.column_name      AS child_col,
                ccu.table_name       AS parent_table
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
              ON tc.constraint_name = kcu.constraint_name
             AND tc.table_schema = kcu.table_schema
            JOIN information_schema.constraint_column_usage ccu
              ON tc.constraint_name = ccu.constraint_name
             AND tc.table_schema = ccu.table_schema
            WHERE tc.constraint_type = 'FOREIGN KEY'
              AND tc.table_schema = 'public'
              AND (tc.table_name = ANY(%s) OR ccu.table_name = ANY(%s))
            """,
            (wipe_list, wipe_list),
        )
        return {
            (row["child_table"], row["child_col"], row["parent_table"])
            for row in cur.fetchall()
        }


def reconcile_live_schema(dsn: str) -> dict:
    """Assert the live public base-table set == set(registry.TABLES).

    Raises CleanSlateAbort('ABORT_LIVE_SCHEMA_DRIFT', ...) naming both the
    live-only and registered-only sets on any divergence. Returns a verdict dict
    on success.
    """
    live = live_public_tables(dsn)
    registered = set(registry.TABLES)
    live_only = sorted(live - registered)
    registered_only = sorted(registered - live)
    if live_only or registered_only:
        raise CleanSlateAbort(
            "ABORT_LIVE_SCHEMA_DRIFT",
            f"live public schema diverges from registry: "
            f"live_only={live_only} registered_only={registered_only}. "
            f"A human must reconcile (register+classify the live-only table, or "
            f"create_all_tables the registry-only one) before the wipe can run.",
        )
    logger.info("live-schema reconciliation PASSED (%d tables)", len(live))
    return {
        "result": "LIVE_SCHEMA_OK",
        "live_count": len(live),
        "registered_count": len(registered),
    }


def reconcile_live_fk_edges(dsn: str) -> dict:
    """Assert live FK edges touching WIPE tables introduce no UNEXPECTED edge (§3.5/§3.7).

    The CASCADE-safety hazard is an *unexpected* live FK — especially a live
    wipe->keep edge a multi-table TRUNCATE ... CASCADE would traverse to reach
    KEEP data — OR any modeled edge whose child/parent is unexpectedly OUTSIDE
    WIPE. The authoritative test is therefore that the live wipe-touching FK set
    is a SUBSET of EXPECTED_FK_EDGES (no unexpected edges).

    Implementation note (codebase reality, surfaced 2026-06-03): the registry's
    PG provisioning (src.schema.postgres.create_all_tables) creates tables +
    columns + indexes but NOT FK constraints, so a faithfully registry-built PG
    (the live prod path) has FEWER than the 6 modeled edges physically present —
    often zero. A MISSING expected edge is NOT a CASCADE hazard (fewer edges =>
    CASCADE reaches strictly less), so it is recorded informationally, not
    aborted. Only an UNEXPECTED edge aborts ABORT_FK_DRIFT.

    Returns a verdict dict on success (includes `missing_modeled_edges` for audit).
    """
    live_edges = live_wipe_touching_fk_edges(dsn)
    expected = set(EXPECTED_FK_EDGES)
    unexpected = sorted(live_edges - expected)
    missing = sorted(expected - live_edges)
    if unexpected:
        raise CleanSlateAbort(
            "ABORT_FK_DRIFT",
            f"unexpected live FK edge(s) touching WIPE tables: unexpected={unexpected}. "
            f"A single multi-table TRUNCATE ... CASCADE is only proven keep-safe for "
            f"the {len(expected)} modeled edges; an unmodeled edge could let a CASCADE "
            f"reach KEEP data.",
        )
    logger.info(
        "live-FK reconciliation PASSED (%d live edge(s), %d modeled edge(s) not "
        "physically enforced)", len(live_edges), len(missing),
    )
    return {
        "result": "LIVE_FK_OK",
        "edge_count": len(live_edges),
        "missing_modeled_edges": missing,
    }
