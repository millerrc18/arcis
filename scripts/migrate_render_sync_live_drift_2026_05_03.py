#!/usr/bin/env python3
"""One-time Render Postgres migration for the remaining live sync drift.

Background:
The 2026-05-03 tri-diff in docs/audit/arcis-db-sync-rebaseline_2026-05-03.md
reduced the live SQLite -> Postgres drift to:

1. shadow_trades.planned_shares / actual_shares typed as INTEGER in Postgres
   while the registry expects REAL
2. Legacy Postgres primary keys on:
   - api_costs.id         -> registry expects cost_id
   - canary_evaluations.id -> registry expects eval_id
   - quality_drift_metrics.id -> registry expects metric_id
   - setup_signals.id     -> registry expects signal_id
   - training_examples.id -> registry expects example_id
3. macro_snapshots missing the registry-expected natural-key uniqueness on
   (series_id, collected_date) for retained-history sync semantics

This script converts those live Postgres tables toward the current registry
shape. It is intentionally conservative:

- dry-run by default
- fails fast if key columns contain NULLs or duplicates
- fails fast if inbound foreign keys still point at the legacy id PKs
- preserves legacy id uniqueness where possible, even after swapping the PK
- defaults to the current registry policy for macro_snapshots: preserve all
  historical dates and dedupe re-runs on (series_id, collected_date)

Usage:
    cmd.exe /C py -3 scripts/migrate_render_sync_live_drift_2026_05_03.py
    cmd.exe /C py -3 scripts/migrate_render_sync_live_drift_2026_05_03.py --apply

Operational guardrails:
    1. Stop the watch loop before running with --apply.
    2. Take a Postgres backup / Render snapshot first.
    3. macro_snapshots history is preserved. This script does not delete prior
       dates; it only adds the historical natural-key uniqueness that sync
       expects.
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from src.config import load_config

SHADOW_REAL_COLUMNS = ("planned_shares", "actual_shares")
REALISH_POSTGRES_TYPES = {"real", "double precision", "numeric", "decimal"}
LEGACY_PK_SWAPS = {
    "api_costs": "cost_id",
    "canary_evaluations": "eval_id",
    "quality_drift_metrics": "metric_id",
    "setup_signals": "signal_id",
    "training_examples": "example_id",
}


@dataclass(frozen=True)
class UniqueIndexState:
    name: str
    columns: tuple[str, ...]


@dataclass(frozen=True)
class TableCatalog:
    columns: dict[str, str]
    primary_key_name: str | None
    primary_key_columns: tuple[str, ...]
    unique_indexes: tuple[UniqueIndexState, ...]


@dataclass(frozen=True)
class KeyHealth:
    null_count: int
    duplicate_examples: tuple[str, ...]


@dataclass(frozen=True)
class InboundForeignKey:
    parent_table: str
    child_table: str
    constraint_name: str


@dataclass(frozen=True)
class MacroState:
    duplicate_surplus_rows: int
    duplicate_series_date_examples: tuple[str, ...]


@dataclass(frozen=True)
class MigrationState:
    tables: dict[str, TableCatalog]
    key_health: dict[str, KeyHealth]
    inbound_foreign_keys: tuple[InboundForeignKey, ...]
    macro_state: MacroState


@dataclass(frozen=True)
class MigrationPlan:
    statements: tuple[str, ...]
    notes: tuple[str, ...]


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Execute the migration. Default is dry-run / plan only.",
    )
    parser.add_argument(
        "--connect-timeout",
        type=int,
        default=15,
        help="Postgres connect timeout in seconds (default: 15).",
    )
    parser.add_argument(
        "--lock-timeout-ms",
        type=int,
        default=15000,
        help="DDL lock timeout in milliseconds (default: 15000).",
    )
    parser.add_argument(
        "--statement-timeout-ms",
        type=int,
        default=120000,
        help="Statement timeout in milliseconds (default: 120000).",
    )
    return parser.parse_args()


def _resolve_database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if url:
        return url
    cfg = load_config()
    url = (cfg.get("render") or {}).get("database_url")
    if url:
        return url
    raise RuntimeError(
        "DATABASE_URL not set and render.database_url missing from config/settings.local.yaml"
    )


def _qident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _qtable(name: str) -> str:
    return f"public.{_qident(name)}"


def _tupleize_columns(value) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, tuple):
        return value
    if isinstance(value, list):
        return tuple(value)
    if isinstance(value, str):
        text = value.strip()
        if text.startswith("{") and text.endswith("}"):
            text = text[1:-1]
        if not text:
            return ()
        return tuple(part.strip().strip('"') for part in text.split(",") if part.strip())
    return tuple(value)


def _is_realish(pg_type: str | None) -> bool:
    return (pg_type or "").lower() in REALISH_POSTGRES_TYPES


def _has_non_primary_unique(table: TableCatalog, columns: tuple[str, ...]) -> bool:
    return any(index.columns == columns for index in table.unique_indexes)


def _load_table_catalog(cur, table_name: str) -> TableCatalog:
    cur.execute(
        """
        SELECT column_name, data_type
        FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = %s
        ORDER BY ordinal_position
        """,
        (table_name,),
    )
    columns = {row[0]: row[1] for row in cur.fetchall()}
    if not columns:
        raise RuntimeError(f"Postgres table not found: {table_name}")

    cur.execute(
        """
        SELECT tc.constraint_name, array_agg(kcu.column_name ORDER BY kcu.ordinal_position)
        FROM information_schema.table_constraints tc
        JOIN information_schema.key_column_usage kcu
          ON tc.constraint_name = kcu.constraint_name
         AND tc.table_schema = kcu.table_schema
         AND tc.table_name = kcu.table_name
        WHERE tc.table_schema = 'public'
          AND tc.table_name = %s
          AND tc.constraint_type = 'PRIMARY KEY'
        GROUP BY tc.constraint_name
        """,
        (table_name,),
    )
    pk_row = cur.fetchone()
    pk_name = pk_row[0] if pk_row else None
    pk_columns = _tupleize_columns(pk_row[1]) if pk_row else ()

    cur.execute(
        """
        SELECT ix.relname AS index_name,
               i.indisprimary,
               i.indisunique,
               array_agg(a.attname ORDER BY ord.ord) AS cols
        FROM pg_class t
        JOIN pg_index i ON t.oid = i.indrelid
        JOIN pg_class ix ON ix.oid = i.indexrelid
        JOIN unnest(i.indkey) WITH ORDINALITY AS ord(attnum, ord) ON TRUE
        JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = ord.attnum
        WHERE t.relname = %s
        GROUP BY ix.relname, i.indisprimary, i.indisunique
        ORDER BY ix.relname
        """,
        (table_name,),
    )
    unique_indexes = tuple(
        UniqueIndexState(name=row[0], columns=_tupleize_columns(row[3]))
        for row in cur.fetchall()
        if bool(row[2]) and not bool(row[1])
    )

    return TableCatalog(
        columns=columns,
        primary_key_name=pk_name,
        primary_key_columns=pk_columns,
        unique_indexes=unique_indexes,
    )


def _load_inbound_foreign_keys(cur) -> tuple[InboundForeignKey, ...]:
    target_names = ", ".join(f"'{name}'" for name in sorted(LEGACY_PK_SWAPS))
    cur.execute(
        f"""
        SELECT ccu.table_name AS parent_table,
               tc.table_name AS child_table,
               tc.constraint_name
        FROM information_schema.table_constraints tc
        JOIN information_schema.constraint_column_usage ccu
          ON tc.constraint_name = ccu.constraint_name
         AND tc.table_schema = ccu.table_schema
        WHERE tc.table_schema = 'public'
          AND tc.constraint_type = 'FOREIGN KEY'
          AND ccu.table_schema = 'public'
          AND ccu.table_name IN ({target_names})
        ORDER BY ccu.table_name, tc.table_name, tc.constraint_name
        """
    )
    return tuple(
        InboundForeignKey(
            parent_table=row[0],
            child_table=row[1],
            constraint_name=row[2],
        )
        for row in cur.fetchall()
    )


def _load_key_health(cur, table_name: str, key_column: str) -> KeyHealth:
    cur.execute(
        f"SELECT COUNT(*) FROM {_qtable(table_name)} WHERE {_qident(key_column)} IS NULL"
    )
    null_count = int(cur.fetchone()[0] or 0)

    cur.execute(
        f"""
        SELECT {_qident(key_column)}::text AS key_text, COUNT(*) AS n
        FROM {_qtable(table_name)}
        GROUP BY 1
        HAVING COUNT(*) > 1
        ORDER BY n DESC, key_text
        LIMIT 5
        """
    )
    duplicates = tuple(f"{row[0]} x{row[1]}" for row in cur.fetchall())
    return KeyHealth(null_count=null_count, duplicate_examples=duplicates)


def _load_macro_state(cur) -> MacroState:
    cur.execute(
        f"""
        SELECT COALESCE(SUM(dup_rows), 0)
        FROM (
            SELECT COUNT(*) - 1 AS dup_rows
            FROM {_qtable('macro_snapshots')}
            GROUP BY {_qident('series_id')}, {_qident('collected_date')}
            HAVING COUNT(*) > 1
        ) d
        """
    )
    duplicate_surplus_rows = int(cur.fetchone()[0] or 0)

    cur.execute(
        f"""
        SELECT {_qident('series_id')}::text,
               {_qident('collected_date')}::text,
               COUNT(*) AS n
        FROM {_qtable('macro_snapshots')}
        GROUP BY 1, 2
        HAVING COUNT(*) > 1
        ORDER BY n DESC, {_qident('series_id')}::text, {_qident('collected_date')}::text
        LIMIT 5
        """
    )
    duplicates = tuple(f"{row[0]} @ {row[1]} x{row[2]}" for row in cur.fetchall())

    return MacroState(
        duplicate_surplus_rows=duplicate_surplus_rows,
        duplicate_series_date_examples=duplicates,
    )


def load_migration_state(cur) -> MigrationState:
    table_names = {"shadow_trades", "macro_snapshots", *LEGACY_PK_SWAPS.keys()}
    tables = {name: _load_table_catalog(cur, name) for name in sorted(table_names)}
    key_health = {
        table_name: _load_key_health(cur, table_name, expected_pk)
        for table_name, expected_pk in LEGACY_PK_SWAPS.items()
    }
    inbound_fks = _load_inbound_foreign_keys(cur)
    macro_state = _load_macro_state(cur)
    return MigrationState(
        tables=tables,
        key_health=key_health,
        inbound_foreign_keys=inbound_fks,
        macro_state=macro_state,
    )


def build_migration_plan(state: MigrationState, preserve_legacy_id: bool = True) -> MigrationPlan:
    statements: list[str] = []
    notes: list[str] = []

    shadow = state.tables["shadow_trades"]
    for column_name in SHADOW_REAL_COLUMNS:
        current_type = shadow.columns.get(column_name)
        if current_type is None:
            raise RuntimeError(f"shadow_trades.{column_name} not found in Postgres")
        if not _is_realish(current_type):
            statements.append(
                f"ALTER TABLE {_qtable('shadow_trades')} "
                f"ALTER COLUMN {_qident(column_name)} TYPE REAL "
                f"USING {_qident(column_name)}::real"
            )
            notes.append(
                f"shadow_trades.{column_name}: {current_type} -> REAL"
            )

    inbound_by_parent: dict[str, list[InboundForeignKey]] = {}
    for fk in state.inbound_foreign_keys:
        inbound_by_parent.setdefault(fk.parent_table, []).append(fk)

    for table_name, expected_pk in LEGACY_PK_SWAPS.items():
        table = state.tables[table_name]
        health = state.key_health[table_name]
        current_pk = table.primary_key_columns
        target_pk = (expected_pk,)
        needs_legacy_id_unique = (
            preserve_legacy_id
            and "id" in table.columns
            and expected_pk != "id"
            and not _has_non_primary_unique(table, ("id",))
        )

        if current_pk == target_pk:
            if needs_legacy_id_unique:
                statements.append(
                    f"ALTER TABLE {_qtable(table_name)} "
                    f"ADD CONSTRAINT {_qident(f'{table_name}_legacy_id_key')} UNIQUE (id)"
                )
                notes.append(f"{table_name}: preserve legacy id uniqueness")
            continue

        if current_pk != ("id",):
            raise RuntimeError(
                f"{table_name} has unexpected current PK {current_pk!r}; expected ('id',) "
                f"or {target_pk!r}"
            )

        if health.null_count:
            raise RuntimeError(
                f"{table_name}.{expected_pk} has {health.null_count} NULL rows; "
                "backfill before swapping the PK"
            )
        if health.duplicate_examples:
            raise RuntimeError(
                f"{table_name}.{expected_pk} has duplicates: {', '.join(health.duplicate_examples)}"
            )

        inbound_fks = inbound_by_parent.get(table_name, [])
        if inbound_fks:
            details = ", ".join(
                f"{fk.child_table}.{fk.constraint_name}" for fk in inbound_fks
            )
            raise RuntimeError(
                f"{table_name} still has inbound foreign keys on the legacy id PK: {details}"
            )

        if not table.primary_key_name:
            raise RuntimeError(f"{table_name} has no primary-key constraint name to drop")

        statements.append(
            f"ALTER TABLE {_qtable(table_name)} "
            f"DROP CONSTRAINT {_qident(table.primary_key_name)}"
        )
        if needs_legacy_id_unique:
            statements.append(
                f"ALTER TABLE {_qtable(table_name)} "
                f"ADD CONSTRAINT {_qident(f'{table_name}_legacy_id_key')} UNIQUE (id)"
            )
        statements.append(
            f"ALTER TABLE {_qtable(table_name)} "
            f"ADD CONSTRAINT {_qident(f'{table_name}_pkey')} PRIMARY KEY ({_qident(expected_pk)})"
        )
        notes.append(f"{table_name}: swap PK id -> {expected_pk}")

    macro = state.macro_state
    macro_table = state.tables["macro_snapshots"]
    if macro.duplicate_surplus_rows > 0:
        statements.append(
            """
WITH ranked AS (
    SELECT ctid,
           ROW_NUMBER() OVER (
               PARTITION BY series_id, collected_date
               ORDER BY collected_at DESC NULLS LAST, id DESC
           ) AS rn
    FROM public."macro_snapshots"
)
DELETE FROM public."macro_snapshots" target
USING ranked
WHERE target.ctid = ranked.ctid
  AND ranked.rn > 1
""".strip()
        )
        note = (
            "macro_snapshots: dedupe "
            f"{macro.duplicate_surplus_rows} repeated same-day rows before adding "
            "historical UNIQUE(series_id, collected_date)"
        )
        if macro.duplicate_series_date_examples:
            note += " [" + "; ".join(macro.duplicate_series_date_examples) + "]"
        notes.append(note)
    if not _has_non_primary_unique(macro_table, ("series_id", "collected_date")):
        statements.append(
            f"ALTER TABLE {_qtable('macro_snapshots')} "
            f"ADD CONSTRAINT {_qident('macro_snapshots_series_id_collected_date_key')} "
            f"UNIQUE ({_qident('series_id')}, {_qident('collected_date')})"
        )
        notes.append(
            "macro_snapshots: enforce UNIQUE(series_id, collected_date) for retained-history sync"
        )

    return MigrationPlan(statements=tuple(statements), notes=tuple(notes))


def _print_plan(plan: MigrationPlan) -> None:
    print("Planned migration steps:")
    if not plan.notes:
        print("  None. The target tables already match the current drift-fix plan.")
    else:
        for note in plan.notes:
            print(f"  - {note}")
    print("\nSQL statements:")
    if not plan.statements:
        print("  None.")
    else:
        for statement in plan.statements:
            print(f"  {statement};")


def _apply_plan(cur, plan: MigrationPlan, lock_timeout_ms: int, statement_timeout_ms: int) -> None:
    cur.execute(f"SET LOCAL lock_timeout = '{int(lock_timeout_ms)}ms'")
    cur.execute(f"SET LOCAL statement_timeout = '{int(statement_timeout_ms)}ms'")
    for statement in plan.statements:
        print(f"EXEC: {statement}")
        cur.execute(statement)


def main() -> int:
    args = _parse_args()
    database_url = _resolve_database_url()

    try:
        import psycopg2
    except ImportError:
        print("Run: pip install psycopg2-binary", file=sys.stderr)
        return 1

    print(
        "Connecting to Render Postgres "
        f"(connect_timeout={args.connect_timeout}s, lock_timeout={args.lock_timeout_ms}ms)..."
    )
    with psycopg2.connect(database_url, connect_timeout=args.connect_timeout) as conn:
        with conn.cursor() as cur:
            state = load_migration_state(cur)
            plan = build_migration_plan(state)
            _print_plan(plan)

            if not args.apply:
                print(
                    "\nDry-run only. Stop the watch loop, take a backup, then rerun with --apply."
                )
                return 0

            if not plan.statements:
                print("\nNo live drift statements remain. Nothing to apply.")
                return 0

            print("\nApplying migration in one transaction...")
            _apply_plan(cur, plan, args.lock_timeout_ms, args.statement_timeout_ms)

        conn.commit()

        with conn.cursor() as cur:
            post_state = load_migration_state(cur)
            post_plan = build_migration_plan(post_state)
        if post_plan.statements:
            raise RuntimeError(
                "Migration committed but drift statements still remain: "
                + "; ".join(post_plan.statements)
            )

    print("\nMigration complete.")
    print(
        "Next step: rerun "
        "`cmd.exe /C py -3 scripts/audit_db_sync.py --sync-smoke "
        "--output docs/audit/arcis-db-sync-rebaseline_2026-05-03.md`"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
