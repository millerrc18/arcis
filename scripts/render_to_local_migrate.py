"""Copy live data from Render Postgres to local Postgres (post-cutover finalization).

Why this exists:
    The Phase-3-revised cutover (task #88) moved the canonical DB from Render to
    local. The schema-sync side completed but the data-copy side never landed —
    a prior recovery attempt (`sqlite_to_pg_migrate.py`) shipped data BACK to
    Render (DATABASE_URL env carryover). NSSM's ArcisWatchLoop points at local
    PG, which stayed empty, and startup crashes with UndefinedTable.

What this script does:
    1. Validates SOURCE_DATABASE_URL (Render) and DATABASE_URL (local). Both
       must start with "postgres". Source != destination check.
    2. Interactive confirmation prompt (operator types 'YES' to proceed). The
       prompt redacts both URLs and shows source/destination row counts so the
       operator can sanity-check direction before any writes happen.
    3. Runs create_all_tables on destination (schema sync from registry).
    4. For each table in TABLES with sync_to_postgres=True, copies rows from
       source -> destination in chunks of 1000 with execute_values, using
       INSERT ... ON CONFLICT (pk) DO NOTHING for PK-based dedup.
    5. Advances destination sequences for SERIAL/IDENTITY columns post-bulk so
       the next caller's INSERT (without explicit id) doesn't collide.

Usage:
    PowerShell:
        $env:SOURCE_DATABASE_URL = "postgresql://halcyon:***@dpg-...render.com/halcyon_zjdk"
        $env:DATABASE_URL        = "postgresql://halcyon_app:***@localhost:5433/halcyon"
        python scripts/render_to_local_migrate.py

    Skip the interactive prompt with --yes (scripted/CI use):
        python scripts/render_to_local_migrate.py --yes

    Filter to specific tables:
        python scripts/render_to_local_migrate.py --tables shadow_trades,recommendations

Tracker context:
    Residual content-dedup (different PK + same content from pre-cutover
    dual-writes era) is NOT handled by this script. Run the follow-up dedup
    pass after this lands and the watch loop is back online.
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    import psycopg2
    from psycopg2 import sql
    from psycopg2.extras import execute_values
except ImportError:
    print("ERROR: psycopg2 not installed. Run: pip install psycopg2-binary", file=sys.stderr)
    sys.exit(1)

from _shared_migration_utils import confirm as _shared_confirm
from _shared_migration_utils import redact_password as _redact_password
from _shared_migration_utils import topo_sort_tables
from src.schema.postgres import create_all_tables
from src.schema.registry import TABLES

_CHUNK_SIZE = 1000


def _validate_url(url: str, label: str) -> None:
    if not url:
        print(f"ERROR: {label} is empty or unset. Aborting.", file=sys.stderr)
        sys.exit(1)
    if not url.startswith("postgres"):
        print(
            f"ERROR: {label} must start with 'postgres', got: {url!r}. Aborting.",
            file=sys.stderr,
        )
        sys.exit(1)


def apply_ownership_reconciliation(dest_url: str) -> dict:
    """Transfer ownership of all public tables/sequences to halcyon_app + apply GRANT block.

    Idempotent. Discovers tables/sequences in the public schema NOT already owned
    by halcyon_app and ALTERs each. Then applies the load-bearing GRANT + ALTER
    DEFAULT PRIVILEGES block from memory `feedback_drop_schema_grant_pattern` so
    halcyon_app retains write access and halcyon_readonly retains SELECT, both
    surviving future table creations.

    Wire-up site for the 2026-05-14 restore-loop incident (v0.36.60 / #92): the
    public-schema DROP + restore-as-superuser pattern leaves tables owned by the
    restore user (`halcyon`) instead of the runtime app role (`halcyon_app`),
    which manifests as permission-denied restart loops. Calling this function
    after any schema-create step closes that drift.

    Privilege requirement
    ---------------------
    ALTER TABLE OWNER requires the connection role to be superuser OR have
    membership in halcyon_app. If neither holds, this function logs a clear
    actionable warning and returns without mutating -- the caller's script
    completes successfully and the operator can re-run with a privileged URL.

    Returns
    -------
    dict with keys: tables_altered (list[str]), sequences_altered (list[str]),
    grants_applied (bool), skipped (bool, True iff privilege check failed).
    """
    conn = psycopg2.connect(dest_url, connect_timeout=15)
    conn.autocommit = False
    result: dict = {
        "tables_altered": [],
        "sequences_altered": [],
        "grants_applied": False,
        "skipped": False,
    }
    try:
        with conn.cursor() as cur:
            # Upfront role/privilege checks -- single short-circuit + no in-txn surprises.
            cur.execute("SELECT 1 FROM pg_roles WHERE rolname='halcyon_app'")
            if not cur.fetchone():
                raise RuntimeError(
                    "halcyon_app role does not exist on this PG. "
                    "Cannot reconcile ownership to a non-existent role; "
                    "create the role first or run this against the correct DB."
                )

            cur.execute("SELECT current_user, current_setting('is_superuser')")
            user, is_super = cur.fetchone()
            cur.execute("SELECT pg_has_role(current_user, 'halcyon_app', 'MEMBER')")
            is_member = cur.fetchone()[0]
            if not (is_super == "on" or is_member):
                print(
                    f"  WARN: current_user={user!r} cannot ALTER OWNER "
                    f"(not superuser, not member of halcyon_app). "
                    f"Skipping ownership reconciliation. Re-run as halcyon "
                    f"(or another privileged role) to apply.",
                    file=sys.stderr,
                )
                result["skipped"] = True
                return result

            cur.execute("SELECT 1 FROM pg_roles WHERE rolname='halcyon_readonly'")
            has_readonly = cur.fetchone() is not None

            # Tables: only ALTER what's not already correct (cheaper + clearer log)
            cur.execute(
                "SELECT tablename FROM pg_tables "
                "WHERE schemaname='public' AND tableowner != 'halcyon_app' "
                "ORDER BY tablename"
            )
            for (tname,) in cur.fetchall():
                cur.execute(
                    sql.SQL("ALTER TABLE public.{} OWNER TO halcyon_app").format(
                        sql.Identifier(tname)
                    )
                )
                result["tables_altered"].append(tname)
                print(f"  ALTER TABLE public.{tname} OWNER TO halcyon_app")

            # Sequences: information_schema.sequences has no owner column, so
            # join pg_class -> pg_namespace -> pg_authid (the discovery query
            # documented in tests/test_table_ownership.py).
            cur.execute(
                "SELECT c.relname FROM pg_class c "
                "JOIN pg_namespace n ON n.oid=c.relnamespace "
                "JOIN pg_authid r ON r.oid=c.relowner "
                "WHERE c.relkind='S' AND n.nspname='public' "
                "AND r.rolname != 'halcyon_app' ORDER BY c.relname"
            )
            for (sname,) in cur.fetchall():
                cur.execute(
                    sql.SQL("ALTER SEQUENCE public.{} OWNER TO halcyon_app").format(
                        sql.Identifier(sname)
                    )
                )
                result["sequences_altered"].append(sname)
                print(f"  ALTER SEQUENCE public.{sname} OWNER TO halcyon_app")

            # GRANT block per feedback_drop_schema_grant_pattern -- idempotent;
            # locks the privileges in for halcyon_app across current AND future
            # tables (the ALTER DEFAULT PRIVILEGES part). halcyon_readonly GRANTs
            # are conditional on the role existing (ephemeral test PG without
            # the full role topology gracefully skips them).
            cur.execute("GRANT ALL ON ALL TABLES IN SCHEMA public TO halcyon_app")
            cur.execute("GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO halcyon_app")
            cur.execute(
                "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
                "GRANT ALL ON TABLES TO halcyon_app"
            )
            cur.execute(
                "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
                "GRANT ALL ON SEQUENCES TO halcyon_app"
            )
            if has_readonly:
                cur.execute(
                    "GRANT SELECT ON ALL TABLES IN SCHEMA public TO halcyon_readonly"
                )
                cur.execute(
                    "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
                    "GRANT SELECT ON TABLES TO halcyon_readonly"
                )
            else:
                print(
                    "  NOTE: halcyon_readonly role absent; skipped its GRANTs "
                    "(expected on ephemeral test PG; would be a flag on production)",
                    file=sys.stderr,
                )

            result["grants_applied"] = True
            print(
                f"  GRANTs + ALTER DEFAULT PRIVILEGES applied: "
                f"{len(result['tables_altered'])} table(s), "
                f"{len(result['sequences_altered'])} sequence(s) altered"
            )

        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return result


def _resolve_primary_key_columns(table) -> list[str]:
    pk = table.primary_key
    return [pk] if isinstance(pk, str) else list(pk)


def _get_sync_tables(table_filter: Optional[list[str]]):
    sync_tables = [t for t in TABLES.values() if t.sync_to_postgres]
    if table_filter:
        filter_set = set(table_filter)
        sync_tables = [t for t in sync_tables if t.name in filter_set]
    return sync_tables


def _topologically_sort_by_fk(sync_tables: list) -> list:
    """Sort tables so FK parents come before children.

    Delegates to topo_sort_tables from _shared_migration_utils (Sprint 6
    Wave A WA6). Raises graphlib.CycleError if a cyclic FK dependency is
    detected (not expected in the registry; surfaces violations loudly).

    PR #1067 review found that shadow_trades (registry idx 1) was being migrated
    before strategy_registry (idx 57) — and shadow_trades.strategy_id has
    initially_deferred=True FK. With per-table commits in the migration loop,
    `initially_deferred` does NOT defer past the commit, so a non-NULL
    strategy_id referencing an unmigrated strategy_registry row would FK-fail.
    Topological sort guarantees the parent is committed first.
    """
    fks = [
        (t.name, fk.references_table)
        for t in sync_tables
        for fk in t.foreign_keys
    ]
    return topo_sort_tables(sync_tables, fks)


def _source_table_exists(src_conn, table_name: str) -> bool:
    """Return True iff `table_name` exists in the source DB's public schema.

    Uses `to_regclass(...)` which returns NULL when the relation is missing
    rather than raising — avoids transaction abort. PR #1067 review fix: when
    a new table is added to the registry (e.g., platform_events in PR #1064)
    and the script is re-run for top-off, source PG may not have that table
    yet. Without this probe, the SELECT crashes with UndefinedTable and the
    table is reported as an error rather than a graceful skip.
    """
    with src_conn.cursor() as cur:
        cur.execute("SELECT to_regclass(%s)", (f'public."{table_name}"',))
        result = cur.fetchone()
        return result is not None and result[0] is not None


def _build_insert_template(table_name: str, col_names: list[str], pk_cols: list[str]) -> str:
    """Build an `INSERT ... ON CONFLICT (...) DO NOTHING` template for execute_values."""
    cols_sql = ", ".join(f'"{c}"' for c in col_names)
    pk_cols_sql = ", ".join(f'"{c}"' for c in pk_cols)
    return (
        f'INSERT INTO "{table_name}" ({cols_sql}) VALUES %s '
        f"ON CONFLICT ({pk_cols_sql}) DO NOTHING"
    )


def _advance_sequence_after_bulk(dst_conn, table_name: str, pk_col: str) -> None:
    """Advance the PG sequence for an integer SERIAL PK to MAX(id)+1 after bulk load.

    Bulk INSERTs that specify explicit id values don't advance the sequence.
    Subsequent INSERTs that omit id rely on the sequence and would collide.
    """
    with dst_conn.cursor() as cur:
        cur.execute("SELECT pg_get_serial_sequence(%s, %s)", (table_name, pk_col))
        seq_row = cur.fetchone()
        if not seq_row or not seq_row[0]:
            return  # UUID / composite / no sequence — nothing to advance
        seq_name = seq_row[0]
        cur.execute(
            sql.SQL(
                "SELECT setval(%s, COALESCE(MAX({pk_col}), 0) + 1, false) FROM {tbl}"
            ).format(
                pk_col=sql.Identifier(pk_col),
                tbl=sql.Identifier(table_name),
            ),
            (seq_name,),
        )
    dst_conn.commit()


def _migrate_table(src_conn, dst_conn, table) -> dict:
    table_name = table.name
    pk_cols = _resolve_primary_key_columns(table)
    col_names = [c.name for c in table.columns]
    pk_indexes = [col_names.index(c) for c in pk_cols]

    # PR #1067 review fix: probe source for table existence before SELECT.
    # When a table is in the registry but not yet on source (e.g., a newly
    # added table on a top-off run), to_regclass returns None and we skip
    # gracefully rather than crashing the per-table SELECT.
    if not _source_table_exists(src_conn, table_name):
        print(
            f"  {table_name:<45} SKIP (table not in source schema; registry-only)"
        )
        return {"source": 0, "inserted": 0, "null_pk_skipped": 0}

    # Row count via a regular cursor (named cursors don't pair well with
    # other statements on the same connection; keep them separate).
    with src_conn.cursor() as count_cur:
        count_cur.execute(f'SELECT COUNT(*) FROM "{table_name}"')
        source_count = count_cur.fetchone()[0]

    insert_sql = _build_insert_template(table_name, col_names, pk_cols)
    cols_sql_select = ", ".join(f'"{c}"' for c in col_names)

    # PR #1067 review fix: named (server-side) cursor streams rows from PG
    # without loading the full result set into client RAM. The default
    # cursor for a 1.5M-row table like options_chains buffers ~300MB
    # before the first fetchmany() returns. itersize aligns the wire-batch
    # size with our processing chunk size.
    src_cur = src_conn.cursor(name=f"render_to_local_migrate_{table_name}")
    src_cur.itersize = _CHUNK_SIZE
    src_cur.execute(f'SELECT {cols_sql_select} FROM "{table_name}"')

    dst_cur = dst_conn.cursor()
    total_inserted = 0
    null_pk_skipped = 0

    while True:
        chunk = src_cur.fetchmany(_CHUNK_SIZE)
        if not chunk:
            break
        valid_chunk = [r for r in chunk if all(r[i] is not None for i in pk_indexes)]
        null_pk_skipped += len(chunk) - len(valid_chunk)
        if not valid_chunk:
            continue
        execute_values(dst_cur, insert_sql, valid_chunk, page_size=_CHUNK_SIZE)
        total_inserted += len(valid_chunk)

    dst_cur.close()
    src_cur.close()

    print(
        f"  {table_name:<45} src={source_count:>8}  inserted={total_inserted:>8}  "
        f"null_pk_skip={null_pk_skipped:>4}"
    )
    return {
        "source": source_count,
        "inserted": total_inserted,
        "null_pk_skipped": null_pk_skipped,
    }


def _summarize_counts(url: str, sync_tables: list, label: str) -> tuple[int, int]:
    """Return (total_rows, tables_present) for the destination — used in confirmation prompt."""
    conn = psycopg2.connect(url, connect_timeout=15)
    cur = conn.cursor()
    total = 0
    present = 0
    for t in sync_tables:
        try:
            cur.execute(f'SELECT COUNT(*) FROM "{t.name}"')
            total += cur.fetchone()[0]
            present += 1
            conn.commit()
        except psycopg2.Error:
            conn.rollback()
    cur.close()
    conn.close()
    print(f"  {label}: {total:,} rows across {present}/{len(sync_tables)} tables present")
    return total, present


def _confirm(source_url: str, dest_url: str, sync_tables: list, *, auto_yes: bool) -> None:
    """Print direction + counts, require operator types 'YES' to proceed (unless --yes)."""
    print()
    print("=" * 72)
    print("RENDER -> LOCAL POSTGRES DATA MIGRATION — pre-flight summary")
    print("=" * 72)
    print(f"  SOURCE:      {_redact_password(source_url)}")
    print(f"  DESTINATION: {_redact_password(dest_url)}")
    print(f"  TABLES:      {len(sync_tables)} sync_to_postgres tables from registry")
    print()
    print("Connecting to both DBs to fetch row counts (read-only)...")
    _summarize_counts(source_url, sync_tables, "SOURCE     ")
    _summarize_counts(dest_url, sync_tables, "DESTINATION")
    print()
    print("Migration writes the source -> destination using INSERT ... ON CONFLICT")
    print("(pk) DO NOTHING per table. Existing destination rows with matching PKs")
    print("are preserved. Sequences advance to MAX(pk)+1 post-bulk.")
    print("=" * 72)

    _shared_confirm("RENDER -> LOCAL POSTGRES DATA MIGRATION", auto_yes=auto_yes)
    print()


def run_migration(
    source_url: str,
    dest_url: str,
    table_filter: Optional[list[str]],
    auto_yes: bool,
    create_schema: bool,
) -> None:
    _validate_url(source_url, "SOURCE_DATABASE_URL")
    _validate_url(dest_url, "DATABASE_URL")
    if source_url == dest_url:
        print("ERROR: SOURCE_DATABASE_URL == DATABASE_URL. Refusing to migrate.", file=sys.stderr)
        sys.exit(1)

    sync_tables = _get_sync_tables(table_filter)
    # PR #1067 review fix: sort by FK dependencies BEFORE migration so per-table
    # commits never reference an unmigrated parent. initially_deferred=True
    # FKs are NOT respected across commit boundaries — only within a single
    # transaction with SET CONSTRAINTS ALL DEFERRED.
    sync_tables = _topologically_sort_by_fk(sync_tables)
    _confirm(source_url, dest_url, sync_tables, auto_yes=auto_yes)

    if create_schema:
        print("Step 1/2: ensure destination schema (create_all_tables)...")
        # create_all_tables takes a DSN URL string, not a connection object.
        create_all_tables(dest_url)
        print("Schema sync complete.")
        # v0.36.60 / #92: reconcile ownership immediately after schema-create so
        # any tables created by a restore-as-superuser earlier (per the
        # 2026-05-14 incident) get handed back to halcyon_app before the data
        # copy starts. Idempotent: a no-op when ownership is already correct.
        print("Reconciling public-schema ownership to halcyon_app...")
        # SF1 from #92 review: fail-fast on unexpected reconciliation errors.
        # The function already handles the safe not-privileged case via
        # result["skipped"]=True (returns gracefully); any raised exception is
        # a genuine misconfiguration (missing halcyon_app role, conn drop, etc.)
        # and continuing with the data copy would leave the operator in the
        # exact 2026-05-14 failure mode this PR fixes -- halcyon_app with rows
        # but no DDL rights. Matches the --reconcile-only path's
        # propagate-exceptions semantics for a uniform contract.
        apply_ownership_reconciliation(dest_url)
        print()

    print("Step 2/2: copy data Render -> local, table by table...")
    print(f"  {'table':<45} {'src':>8} {'inserted':>15} {'null_pk_skip':>12}")
    print("-" * 84)

    # connect_timeout=30: PR #1067 review fix — without an explicit timeout the
    # connect call hangs forever if the peer becomes unreachable mid-migration.
    src_conn = psycopg2.connect(source_url, connect_timeout=30)
    dst_conn = psycopg2.connect(dest_url, connect_timeout=30)
    totals = {"source": 0, "inserted": 0, "null_pk_skipped": 0, "errors": 0}
    try:
        for table in sync_tables:
            try:
                result = _migrate_table(src_conn, dst_conn, table)
                dst_conn.commit()
                pk = table.primary_key
                if isinstance(pk, str):
                    _advance_sequence_after_bulk(dst_conn, table.name, pk)
                for k in ("source", "inserted", "null_pk_skipped"):
                    totals[k] += result[k]
            except Exception as exc:
                print(f"  ERROR migrating {table.name}: {exc}", file=sys.stderr)
                try:
                    dst_conn.rollback()
                except Exception:
                    pass
                totals["errors"] += 1
    finally:
        src_conn.close()
        dst_conn.close()

    print("-" * 84)
    print(
        f"MIGRATION COMPLETE: {len(sync_tables)} tables, "
        f"{totals['inserted']:,} rows inserted (source had {totals['source']:,}), "
        f"{totals['errors']} errors, {totals['null_pk_skipped']} null-PK rows skipped"
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="One-shot Render Postgres -> local Postgres data migration."
    )
    parser.add_argument(
        "--tables",
        type=str,
        default=None,
        help="Comma-separated list of tables to migrate (default: all sync_to_postgres tables).",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Skip the interactive confirmation prompt (scripted/CI use).",
    )
    parser.add_argument(
        "--no-schema",
        action="store_true",
        help="Skip the create_all_tables step (use when schema already in sync).",
    )
    parser.add_argument(
        "--reconcile-only",
        action="store_true",
        help=(
            "Skip Render->local data copy entirely and only run ownership "
            "reconciliation against DATABASE_URL. Use post-restore from a "
            "snapshot (v0.36.60 / #92) when the schema is already populated "
            "but tables are owned by the restore-user instead of halcyon_app. "
            "Requires DATABASE_URL to be a privileged role (superuser or "
            "member of halcyon_app); SOURCE_DATABASE_URL is not consulted."
        ),
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    dest_url = os.environ.get("DATABASE_URL", "")

    if args.reconcile_only:
        # Standalone reconciliation path -- no source URL, no data copy, no
        # interactive prompt. Invoked from scripts/recovery/restore_pg_from_snapshot.ps1
        # at step 7.5 (post-GRANT, pre-verification) and operator-runnable
        # anytime drift surfaces on a healthy DB.
        _validate_url(dest_url, "DATABASE_URL")
        print(f"Reconciling ownership on: {_redact_password(dest_url)}")
        result = apply_ownership_reconciliation(dest_url)
        if result["skipped"]:
            sys.exit(1)
        return

    source_url = os.environ.get("SOURCE_DATABASE_URL", "")
    table_filter = [t.strip() for t in args.tables.split(",")] if args.tables else None

    run_migration(
        source_url=source_url,
        dest_url=dest_url,
        table_filter=table_filter,
        auto_yes=args.yes,
        create_schema=not args.no_schema,
    )


if __name__ == "__main__":
    main()
