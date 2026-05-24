"""v0.36.48 — startup must auto-migrate the LOCAL cutover Postgres, not dead Render.

The 2026-05-18 PG cutover repointed runtime WRITES to the local PG
(ARCIS_PG_CUTOVER_ENABLED=1 + DATABASE_URL=localhost:5433), but startup SCHEMA
management (_check_render_postgres) still targeted config.render.database_url —
the decommissioned Render PG. So the local PG schema was never auto-migrated:
on 2026-05-21 notifications_sent + notifications_digest_queue silently went
missing and were never recreated (160 'relation does not exist' errors), while
startup logged 'Postgres auto-migrate failed: ...render.com' against a server
that no longer exists.

Fix: _check_cutover_postgres auto-migrates DATABASE_URL (the local PG the
runtime actually writes to) when the cutover is on — idempotent create_all_tables
+ ensure_columns, the same self-heal the SQLite path already does. And the dead
Render migrate is skipped when the cutover is active.
"""

from unittest.mock import patch

import src.startup  # noqa: F401 — import first to resolve startup<->startup_checks cycle
from src.startup_checks import _check_cutover_postgres, _check_render_postgres


def test_cutover_migrate_targets_local_database_url(monkeypatch):
    monkeypatch.setenv("ARCIS_PG_CUTOVER_ENABLED", "1")
    monkeypatch.setenv("DATABASE_URL", "postgresql://app:pw@localhost:5433/halcyon")
    with patch("src.schema.postgres.create_all_tables") as create:
        results = _check_cutover_postgres({})
    # migrates the LOCAL cutover URL, never the Render URL (create_all_tables is the
    # single idempotent entrypoint — it does tables + columns + indexes internally)
    assert create.call_count == 1
    assert create.call_args[0][0] == "postgresql://app:pw@localhost:5433/halcyon"
    assert any(r.name == "cutover_pg_schema" and r.status == "ok" for r in results)


def test_cutover_migrate_noop_when_gate_off(monkeypatch):
    monkeypatch.delenv("ARCIS_PG_CUTOVER_ENABLED", raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql://app:pw@localhost:5433/halcyon")
    with patch("src.schema.postgres.create_all_tables") as create:
        results = _check_cutover_postgres({})
    assert create.call_count == 0
    assert results == []


def test_cutover_migrate_noop_when_database_url_not_postgres(monkeypatch):
    monkeypatch.setenv("ARCIS_PG_CUTOVER_ENABLED", "1")
    monkeypatch.setenv("DATABASE_URL", "")
    with patch("src.schema.postgres.create_all_tables") as create:
        results = _check_cutover_postgres({})
    assert create.call_count == 0


def test_cutover_migrate_warns_on_ddl_failure_not_raises(monkeypatch):
    # A non-connection (DDL) failure against a REACHABLE db → warn, never raises.
    monkeypatch.setenv("ARCIS_PG_CUTOVER_ENABLED", "1")
    monkeypatch.setenv("DATABASE_URL", "postgresql://app:pw@localhost:5433/halcyon")
    with patch("src.schema.postgres.create_all_tables", side_effect=RuntimeError("ddl hiccup")):
        results = _check_cutover_postgres({})  # must not raise
    assert any(r.name == "cutover_pg_schema" and r.status == "warn" for r in results)


def test_cutover_migrate_critical_when_unreachable(monkeypatch):
    # The cutover PG is the SOLE runtime write target — unreachable must be CRITICAL
    # (not a benign warn), so the preflight surfaces red rather than yellow.
    import psycopg2
    monkeypatch.setenv("ARCIS_PG_CUTOVER_ENABLED", "1")
    monkeypatch.setenv("DATABASE_URL", "postgresql://app:pw@localhost:5433/halcyon")
    with patch("src.schema.postgres.create_all_tables",
               side_effect=psycopg2.OperationalError("could not connect to server")):
        results = _check_cutover_postgres({})
    assert any(r.name == "cutover_pg_schema" and r.status == "critical" for r in results)


def test_cutover_migrate_ok_not_yellow_on_ownership(monkeypatch):
    # Some tables are owned by a different role (e.g. recommendations by 'halcyon',
    # not 'halcyon_app'), so the runtime user can't reconcile them — but the
    # table-level self-heal already committed in the first phase. This is EXPECTED +
    # non-actionable, so it must emit OK-with-note (NOT a permanent yellow preflight,
    # which is the persistent-false-positive anti-pattern). Never critical.
    #
    # v0.36.60 / #92 update: the original five misowned tables (recommendations,
    # shadow_trades, sync_state, traffic_light_state, vix_term_structure) were
    # transferred to halcyon_app via schema/migrations/2026-05-24_table_ownership_fix.sql
    # and the wire-up in scripts/render_to_local_migrate.py:apply_ownership_reconciliation.
    # This test is kept as DEFENSE-IN-DEPTH for any FUTURE ownership drift (e.g., a
    # post-restore scenario where the migration wasn't yet re-run) -- the OK-with-note
    # behavior remains the correct response even after the historical cases are fixed.
    # See tests/test_table_ownership.py for the steady-state policy assertion.
    import psycopg2
    monkeypatch.setenv("ARCIS_PG_CUTOVER_ENABLED", "1")
    monkeypatch.setenv("DATABASE_URL", "postgresql://app:pw@localhost:5433/halcyon")
    with patch("src.schema.postgres.create_all_tables",
               side_effect=psycopg2.errors.InsufficientPrivilege("must be owner of table recommendations")):
        results = _check_cutover_postgres({})
    matches = [r for r in results if r.name == "cutover_pg_schema"]
    assert matches and matches[0].status == "ok"
    assert "owned by another role" in matches[0].detail


def test_index_reconcile_no_drop_on_ordering_only(monkeypatch):
    """Finding-1 guard: _reconcile_pg_index must NOT DROP an index whose only
    difference from the live index is an ASC/DESC ordering qualifier. Postgres
    reports bare attnames (ordering lives in indoption), so 'sent_at DESC' must
    normalize to 'sent_at' for the drift comparison — else the index is dropped +
    recreated on EVERY startup (observed thrash on idx_notifications_sent_event_recent).
    """
    from unittest.mock import MagicMock
    from src.schema import postgres as pg
    from src.schema.registry import TABLES

    assert pg._bare_index_cols(["event_type", "sent_at DESC"]) == ["event_type", "sent_at"]

    tdef = TABLES["notifications_sent"]
    cur = MagicMock()
    # Simulate a HEALTHY db: every index already matches its bare-normalized spec.
    def fake_sig(_c, _t, iname):
        idx = next(i for i in tdef.indexes if i.name == iname)
        return (idx.unique, pg._bare_index_cols(idx.columns))
    monkeypatch.setattr(pg, "_pg_index_signature", fake_sig)
    pg._reconcile_pg_index(cur, tdef)
    drops = [str(c) for c in cur.execute.call_args_list if "DROP INDEX" in str(c)]
    assert drops == [], f"ordering-only diff must not trigger DROP INDEX: {drops}"


def test_render_migrate_skipped_when_cutover_active(monkeypatch):
    # The dead Render PG must not be migrated once the local cutover owns the schema.
    monkeypatch.setenv("ARCIS_PG_CUTOVER_ENABLED", "1")
    cfg = {"render": {"enabled": True, "database_url": "postgresql://x@dpg-dead.render.com/db"}}
    with patch("src.schema.postgres.create_all_tables") as create:
        results = _check_render_postgres(cfg)
    assert create.call_count == 0  # no migrate against the dead Render server
    assert results == []
