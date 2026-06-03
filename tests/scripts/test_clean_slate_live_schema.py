"""Live-schema + live-FK reconciliation tests (#95, T6) — drift -> abort, by-mutation.

Provisions a FRESH EPHEMERAL scratch DB on the 5434 test server from the
registry, then mutates it and asserts the reconcilers ABORT only on the injected
drift (and PASS on the faithful registry-built schema). NEVER prod 5433; NEVER
ARCIS_ALLOW_PROD_PG_IN_TESTS=1. The ephemeral DB is always dropped.

Requires the 'test' role on 5434 to have CREATEDB (verified 2026-06-03).
"""

from __future__ import annotations

import os
import uuid

import psycopg2
import pytest

from scripts._clean_slate import live_schema as ls
from scripts._clean_slate._errors import CleanSlateAbort
from src.schema import registry
from src.schema.postgres import create_all_tables

pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"),
    reason="integration(authoritative-coverage:pg-tests): needs TEST_DATABASE_URL 5434 server",
)


def _maintenance_dsn() -> str:
    """A /postgres maintenance DSN on the same server as TEST_DATABASE_URL."""
    base = os.environ["TEST_DATABASE_URL"]
    head, _, _db = base.rpartition("/")
    return f"{head}/postgres"


def _dsn_for(db: str) -> str:
    head, _, _db = os.environ["TEST_DATABASE_URL"].rpartition("/")
    return f"{head}/{db}"


@pytest.fixture
def ephemeral_db():
    """Create a fresh registry-provisioned ephemeral DB; drop it on teardown."""
    db_name = f"cs_ls_{uuid.uuid4().hex[:12]}"
    admin = psycopg2.connect(_maintenance_dsn(), connect_timeout=10)
    admin.autocommit = True
    with admin.cursor() as cur:
        cur.execute(f'CREATE DATABASE "{db_name}"')
    dsn = _dsn_for(db_name)
    try:
        create_all_tables(dsn)
        yield dsn
    finally:
        with admin.cursor() as cur:
            cur.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = %s AND pid <> pg_backend_pid()",
                (db_name,),
            )
            cur.execute(f'DROP DATABASE IF EXISTS "{db_name}"')
        admin.close()


def test_faithful_schema_passes_both_reconcilers(ephemeral_db):
    schema = ls.reconcile_live_schema(ephemeral_db)
    fk = ls.reconcile_live_fk_edges(ephemeral_db)
    assert schema["result"] == "LIVE_SCHEMA_OK"
    assert schema["live_count"] == len(registry.TABLES) == 80
    # PG provisioning (create_all_tables) omits FK constraints, so a faithfully
    # registry-built DB has zero live wipe-touching edges — that is keep-safe
    # (CASCADE reaches strictly less). The 6 modeled edges are recorded as
    # informationally-missing, NOT a hazard.
    assert fk["result"] == "LIVE_FK_OK"
    assert fk["edge_count"] == 0
    assert len(fk["missing_modeled_edges"]) == 6


def test_reconcile_fk_passes_when_modeled_edges_physically_present(ephemeral_db):
    # If the live DB DID enforce the 6 modeled FK edges, reconcile still PASSES
    # (they are the expected set). Add the two shadow_trades edges physically.
    conn = psycopg2.connect(ephemeral_db)
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute(
            "ALTER TABLE shadow_trades "
            "ADD CONSTRAINT __cs_fk_rec FOREIGN KEY (recommendation_id) "
            "REFERENCES recommendations(recommendation_id)"
        )
    conn.close()
    fk = ls.reconcile_live_fk_edges(ephemeral_db)
    assert fk["result"] == "LIVE_FK_OK"
    # The now-physically-present edge is no longer in missing_modeled_edges.
    assert (
        "shadow_trades",
        "recommendation_id",
        "recommendations",
    ) not in fk["missing_modeled_edges"]


def test_extra_unregistered_table_aborts_schema(ephemeral_db):
    conn = psycopg2.connect(ephemeral_db)
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute("CREATE TABLE __cs_unregistered_live__ (id INT PRIMARY KEY)")
    conn.close()
    with pytest.raises(CleanSlateAbort) as exc:
        ls.reconcile_live_schema(ephemeral_db)
    assert exc.value.code == "ABORT_LIVE_SCHEMA_DRIFT"
    assert "__cs_unregistered_live__" in str(exc.value)
    assert "live_only" in str(exc.value)


def test_dropped_registered_table_aborts_schema(ephemeral_db):
    conn = psycopg2.connect(ephemeral_db)
    conn.autocommit = True
    with conn.cursor() as cur:
        # Drop a KEEP table with no inbound FKs so the DROP is clean.
        cur.execute("DROP TABLE IF EXISTS macro_snapshots CASCADE")
    conn.close()
    with pytest.raises(CleanSlateAbort) as exc:
        ls.reconcile_live_schema(ephemeral_db)
    assert exc.value.code == "ABORT_LIVE_SCHEMA_DRIFT"
    assert "macro_snapshots" in str(exc.value)
    assert "registered_only" in str(exc.value)


def test_unexpected_fk_edge_touching_wipe_aborts_fk(ephemeral_db):
    # Add a NEW FK edge from a WIPE table (system_metrics) to a KEEP table
    # (config_overrides) — exactly the live wipe->keep edge a CASCADE would
    # traverse. config_overrides.setting_key is its PK (a valid FK target).
    conn = psycopg2.connect(ephemeral_db)
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute(
            "ALTER TABLE system_metrics "
            "ADD COLUMN __cs_fk_col TEXT "
            "REFERENCES config_overrides(setting_key)"
        )
    conn.close()
    with pytest.raises(CleanSlateAbort) as exc:
        ls.reconcile_live_fk_edges(ephemeral_db)
    assert exc.value.code == "ABORT_FK_DRIFT"
    assert "system_metrics" in str(exc.value)
    # The faithful-schema reconcile_live_schema still passes (only FK drifted).
    assert ls.reconcile_live_schema(ephemeral_db)["result"] == "LIVE_SCHEMA_OK"
