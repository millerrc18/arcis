#!/usr/bin/env python3
"""Audit SQLite <-> Postgres sync alignment against the schema registry.

Produces a markdown tri-diff across:
1. The schema registry (`src/schema/registry.py`)
2. The live local SQLite database
3. The live Render Postgres database

Optional `--sync-smoke` runs one real sync cycle after the read-only audit to
capture the current failure mode, per-table errors, and whether Postgres schema
auto-heal added any tables/columns during the run.
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from unittest.mock import patch
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.config import DB_PATH, load_config  # noqa: E402
from src.schema.registry import TABLES, TableDef  # noqa: E402
from src.schema.sync_config import generate_sync_tables  # noqa: E402
from src.sync.render_sync import run_sync_cycle  # noqa: E402
import src.schema.postgres as pg_schema  # noqa: E402
import src.sync.render_sync as render_sync_mod  # noqa: E402


@dataclass(frozen=True)
class ColumnSnapshot:
    name: str
    raw_type: str
    normalized_type: str
    nullable: bool
    default: str | None


@dataclass(frozen=True)
class TableSnapshot:
    columns: dict[str, ColumnSnapshot]
    primary_key: list[str]
    unique_indexes: list[list[str]]


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--output",
        type=Path,
        help="Optional markdown output path. Defaults to stdout only.",
    )
    parser.add_argument(
        "--sync-smoke",
        action="store_true",
        help=(
            "After the read-only tri-diff, run one real sync cycle to capture the "
            "current live failure mode. This updates sync_state and may sync rows "
            "to Postgres."
        ),
    )
    return parser.parse_args(argv)


def _normalize_sqlite_type(raw_type: str) -> str:
    value = (raw_type or "").upper()
    if "INT" in value:
        return "INTEGER"
    if any(token in value for token in ("REAL", "FLOA", "DOUB", "NUMERIC", "DECIMAL")):
        return "REAL"
    if "BLOB" in value:
        return "BLOB"
    return "TEXT"


def _normalize_pg_type(raw_type: str) -> str:
    value = (raw_type or "").lower()
    if value in {"smallint", "integer", "bigint"}:
        return "INTEGER"
    if value in {"real", "double precision", "numeric", "decimal"}:
        return "REAL"
    if value == "bytea":
        return "BLOB"
    return "TEXT"


def _sqlite_ro_uri(db_path: str) -> str:
    try:
        return f"{Path(db_path).as_uri()}?mode=ro"
    except ValueError:
        return f"file:{db_path}?mode=ro"


def _load_sqlite_snapshot(db_path: str) -> dict[str, TableSnapshot]:
    snapshot: dict[str, TableSnapshot] = {}
    with sqlite3.connect(_sqlite_ro_uri(db_path), uri=True) as conn:
        table_rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
        for (table_name,) in table_rows:
            col_rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
            index_rows = conn.execute(f"PRAGMA index_list({table_name})").fetchall()
            columns = {
                row[1]: ColumnSnapshot(
                    name=row[1],
                    raw_type=row[2] or "",
                    normalized_type=_normalize_sqlite_type(row[2] or ""),
                    nullable=not bool(row[3]),
                    default=row[4],
                )
                for row in col_rows
            }
            pk = [row[1] for row in sorted(col_rows, key=lambda item: item[5]) if row[5] > 0]
            unique_indexes: list[list[str]] = []
            for idx_row in index_rows:
                index_name = idx_row[1]
                is_unique = bool(idx_row[2])
                if not is_unique:
                    continue
                idx_info = conn.execute(f"PRAGMA index_info({index_name})").fetchall()
                unique_indexes.append([info[2] for info in sorted(idx_info, key=lambda item: item[0])])
            snapshot[table_name] = TableSnapshot(
                columns=columns,
                primary_key=pk,
                unique_indexes=unique_indexes,
            )
    return snapshot


def _load_postgres_snapshot(database_url: str) -> dict[str, TableSnapshot]:
    import psycopg2

    snapshot: dict[str, TableSnapshot] = {}
    conn = psycopg2.connect(database_url)
    cur = conn.cursor()
    try:
        cur.execute(
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'public'
            ORDER BY table_name
            """
        )
        table_names = [row[0] for row in cur.fetchall()]
        for table_name in table_names:
            cur.execute(
                """
                SELECT column_name, data_type, is_nullable, column_default
                FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = %s
                ORDER BY ordinal_position
                """,
                (table_name,),
            )
            columns = {
                row[0]: ColumnSnapshot(
                    name=row[0],
                    raw_type=row[1],
                    normalized_type=_normalize_pg_type(row[1]),
                    nullable=(row[2] == "YES"),
                    default=row[3],
                )
                for row in cur.fetchall()
            }

            cur.execute(
                """
                SELECT kcu.column_name
                FROM information_schema.table_constraints tc
                JOIN information_schema.key_column_usage kcu
                  ON tc.constraint_name = kcu.constraint_name
                 AND tc.table_schema = kcu.table_schema
                WHERE tc.table_schema = 'public'
                  AND tc.table_name = %s
                  AND tc.constraint_type = 'PRIMARY KEY'
                ORDER BY kcu.ordinal_position
                """,
                (table_name,),
            )
            pk = [row[0] for row in cur.fetchall()]

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
            unique_indexes = [
                list(row[3] or [])
                for row in cur.fetchall()
                if bool(row[2]) and not bool(row[1])
            ]

            snapshot[table_name] = TableSnapshot(
                columns=columns,
                primary_key=pk,
                unique_indexes=unique_indexes,
            )
    finally:
        cur.close()
        conn.close()
    return snapshot


def _registry_snapshot(table: TableDef) -> TableSnapshot:
    pk = table.primary_key if isinstance(table.primary_key, list) else [table.primary_key]
    unique_indexes = [idx.columns for idx in table.indexes if idx.unique]
    columns = {
        col.name: ColumnSnapshot(
            name=col.name,
            raw_type=col.type,
            normalized_type=col.type.upper(),
            nullable=col.nullable,
            default=col.default,
        )
        for col in table.columns
    }
    return TableSnapshot(columns=columns, primary_key=pk, unique_indexes=unique_indexes)


def _redact_database_url(database_url: str) -> str:
    parsed = urlparse(database_url)
    return f"{parsed.hostname}/{parsed.path.lstrip('/')}"


def _format_markdown_table(headers: list[str], rows: list[list[str]]) -> str:
    if not rows:
        return "_None._"
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


def _build_tri_diff(
    sqlite_snapshot: dict[str, TableSnapshot],
    pg_snapshot: dict[str, TableSnapshot],
) -> dict[str, Any]:
    registry_snapshots = {name: _registry_snapshot(table) for name, table in TABLES.items()}
    sync_config = generate_sync_tables()
    registry_names = set(registry_snapshots)
    synced_names = {name for name, table in TABLES.items() if table.sync_to_postgres}
    sqlite_names = set(sqlite_snapshot)
    pg_names = set(pg_snapshot)

    missing_tables = {
        "synced_registry_missing_in_sqlite": sorted(synced_names - sqlite_names),
        "synced_registry_missing_in_postgres": sorted(synced_names - pg_names),
        "sqlite_not_in_registry": sorted(sqlite_names - registry_names),
        "postgres_not_in_registry": sorted(pg_names - registry_names),
    }

    missing_columns: list[dict[str, Any]] = []
    type_mismatches: list[dict[str, Any]] = []
    pk_conflict_mismatches: list[dict[str, Any]] = []

    for table_name, registry_table in registry_snapshots.items():
        registry_cols = set(registry_table.columns)
        sqlite_table = sqlite_snapshot.get(table_name)
        pg_table = pg_snapshot.get(table_name)

        if sqlite_table is not None:
            sqlite_cols = set(sqlite_table.columns)
            if registry_cols - sqlite_cols:
                missing_columns.append({
                    "table": table_name,
                    "target": "sqlite",
                    "missing": sorted(registry_cols - sqlite_cols),
                })
            if registry_table.primary_key != sqlite_table.primary_key:
                pk_conflict_mismatches.append({
                    "table": table_name,
                    "kind": "sqlite_pk",
                    "expected": registry_table.primary_key,
                    "actual": sqlite_table.primary_key,
                })
            for col_name in sorted(registry_cols & sqlite_cols):
                registry_col = registry_table.columns[col_name]
                sqlite_col = sqlite_table.columns[col_name]
                if registry_col.normalized_type != sqlite_col.normalized_type:
                    type_mismatches.append({
                        "table": table_name,
                        "column": col_name,
                        "target": "sqlite",
                        "expected": registry_col.normalized_type,
                        "actual": sqlite_col.raw_type,
                    })

        if pg_table is not None and table_name in synced_names:
            pg_cols = set(pg_table.columns)
            if registry_cols - pg_cols:
                missing_columns.append({
                    "table": table_name,
                    "target": "postgres",
                    "missing": sorted(registry_cols - pg_cols),
                })
            if table_name in synced_names and registry_table.primary_key != pg_table.primary_key:
                pk_conflict_mismatches.append({
                    "table": table_name,
                    "kind": "postgres_pk",
                    "expected": registry_table.primary_key,
                    "actual": pg_table.primary_key,
                })
            for col_name in sorted(registry_cols & pg_cols):
                registry_col = registry_table.columns[col_name]
                pg_col = pg_table.columns[col_name]
                if registry_col.normalized_type != pg_col.normalized_type:
                    type_mismatches.append({
                        "table": table_name,
                        "column": col_name,
                        "target": "postgres",
                        "expected": registry_col.normalized_type,
                        "actual": pg_col.raw_type,
                    })
            if table_name in sync_config:
                conflict_target = sync_config[table_name].get("conflict_col")
                if conflict_target:
                    expected = [part.strip() for part in conflict_target.split(",") if part.strip()]
                    candidates = [pg_table.primary_key, *pg_table.unique_indexes]
                    if expected not in candidates:
                        pk_conflict_mismatches.append({
                            "table": table_name,
                            "kind": "postgres_conflict_target",
                            "expected": expected,
                            "actual": candidates,
                        })

    tables_with_natural_unique_but_no_conflict = []
    for table_name, table in TABLES.items():
        if not table.sync_to_postgres:
            continue
        unique_indexes = [idx.columns for idx in table.indexes if idx.unique]
        pk = table.primary_key if isinstance(table.primary_key, list) else [table.primary_key]
        if unique_indexes and not table.sync_conflict_col and not any(idx == pk for idx in unique_indexes):
            tables_with_natural_unique_but_no_conflict.append(table_name)
    if tables_with_natural_unique_but_no_conflict:
        pk_conflict_mismatches.append({
            "table": ", ".join(tables_with_natural_unique_but_no_conflict),
            "kind": "registry_missing_conflict_col",
            "expected": "explicit sync_conflict_col",
            "actual": "implicit pk/auto behavior",
        })

    local_only_tables = {
        "registry_local_only_present_in_sqlite": sorted(
            name
            for name, table in TABLES.items()
            if not table.sync_to_postgres and name in sqlite_names
        ),
        "registry_local_only_present_in_postgres": sorted(
            name
            for name, table in TABLES.items()
            if not table.sync_to_postgres and name in pg_names
        ),
        "registry_local_only_missing_in_sqlite": sorted(
            name
            for name, table in TABLES.items()
            if not table.sync_to_postgres and name not in sqlite_names
        ),
        "sqlite_only_unregistered": sorted(sqlite_names - registry_names),
    }

    return {
        "missing_tables": missing_tables,
        "missing_columns": missing_columns,
        "type_mismatches": type_mismatches,
        "pk_conflict_mismatches": pk_conflict_mismatches,
        "local_only_tables": local_only_tables,
    }


def _smoke_target_tables(tri_diff: dict[str, Any]) -> list[str]:
    sync_config = generate_sync_tables()
    risky_tables: set[str] = set(tri_diff["missing_tables"]["synced_registry_missing_in_postgres"])

    for collection_name in ("missing_columns", "type_mismatches", "pk_conflict_mismatches"):
        for entry in tri_diff[collection_name]:
            for name in str(entry["table"]).split(","):
                table_name = name.strip()
                if table_name in TABLES and TABLES[table_name].sync_to_postgres:
                    risky_tables.add(table_name)

    if not risky_tables:
        return list(sync_config)
    return [table_name for table_name in sync_config if table_name in risky_tables]


def _run_sync_smoke(database_url: str, db_path: str, tri_diff: dict[str, Any]) -> dict[str, Any]:
    auto_heal: dict[str, list[str]] = {
        "create_all_tables_added": [],
        "ensure_columns_added": [],
    }
    real_create_all_tables = pg_schema.create_all_tables
    real_ensure_columns = pg_schema.ensure_columns
    smoke_tables = _smoke_target_tables(tri_diff)
    full_sync_config = generate_sync_tables()
    targeted_sync_config = {
        table_name: full_sync_config[table_name]
        for table_name in smoke_tables
    }

    def wrapped_create_all_tables(*args, **kwargs):
        added = real_create_all_tables(*args, **kwargs)
        auto_heal["create_all_tables_added"] = list(added or [])
        return added

    def wrapped_ensure_columns(*args, **kwargs):
        added = real_ensure_columns(*args, **kwargs)
        auto_heal["ensure_columns_added"] = list(added or [])
        return added

    with patch("src.schema.postgres.create_all_tables", new=wrapped_create_all_tables), patch(
        "src.schema.postgres.ensure_columns", new=wrapped_ensure_columns
    ), patch.object(render_sync_mod, "SYNC_TABLES", new=targeted_sync_config):
        summary = run_sync_cycle(database_url, db_path)

    first_error = summary["errors"][0] if summary.get("errors") else None
    first_failing_table = None
    if first_error and ": " in first_error and not first_error.startswith("connection_failed"):
        first_failing_table = first_error.split(":", 1)[0]

    return {
        "summary": summary,
        "first_error": first_error,
        "first_failing_table": first_failing_table,
        "auto_heal": auto_heal,
        "scope": (
            "full sync table set"
            if len(targeted_sync_config) == len(full_sync_config)
            else "tri-diff risk tables"
        ),
        "tables": list(targeted_sync_config),
    }


def _render_report(
    *,
    sqlite_path: str,
    database_url: str,
    tri_diff: dict[str, Any],
    smoke: dict[str, Any] | None,
) -> str:
    generated_at = datetime.now().astimezone().isoformat(timespec="seconds")

    missing_tables = tri_diff["missing_tables"]
    missing_columns = tri_diff["missing_columns"]
    type_mismatches = tri_diff["type_mismatches"]
    pk_conflict_mismatches = tri_diff["pk_conflict_mismatches"]
    local_only_tables = tri_diff["local_only_tables"]

    lines = [
        "# SQLite <-> Postgres Sync Rebaseline Report",
        "",
        f"**Generated:** {generated_at}",
        f"**SQLite:** `{sqlite_path}`",
        f"**Postgres:** `{_redact_database_url(database_url)}`",
        f"**Registry tables:** {len(TABLES)} total / "
        f"{sum(1 for table in TABLES.values() if table.sync_to_postgres)} synced / "
        f"{sum(1 for table in TABLES.values() if not table.sync_to_postgres)} local-only",
        "",
        "## Missing Tables",
        "",
        _format_markdown_table(
            ["Category", "Tables"],
            [
                ["Synced registry missing in SQLite", ", ".join(missing_tables["synced_registry_missing_in_sqlite"]) or "None"],
                ["Synced registry missing in Postgres", ", ".join(missing_tables["synced_registry_missing_in_postgres"]) or "None"],
                ["SQLite tables not in registry", ", ".join(missing_tables["sqlite_not_in_registry"]) or "None"],
                ["Postgres tables not in registry", ", ".join(missing_tables["postgres_not_in_registry"]) or "None"],
            ],
        ),
        "",
        "## Missing Columns",
        "",
        _format_markdown_table(
            ["Table", "Target", "Missing Columns"],
            [
                [entry["table"], entry["target"], ", ".join(entry["missing"])]
                for entry in missing_columns
            ],
        ),
        "",
        "## Type Mismatches",
        "",
        _format_markdown_table(
            ["Table", "Column", "Target", "Registry", "Actual"],
            [
                [
                    entry["table"],
                    entry["column"],
                    entry["target"],
                    entry["expected"],
                    entry["actual"],
                ]
                for entry in type_mismatches
            ],
        ),
        "",
        "## PK / Conflict Target Mismatches",
        "",
        _format_markdown_table(
            ["Table", "Kind", "Expected", "Actual"],
            [
                [
                    entry["table"],
                    entry["kind"],
                    ", ".join(entry["expected"]) if isinstance(entry["expected"], list) else str(entry["expected"]),
                    (
                        "; ".join(", ".join(item) for item in entry["actual"])
                        if entry["kind"] == "postgres_conflict_target"
                        else ", ".join(entry["actual"]) if isinstance(entry["actual"], list)
                        else str(entry["actual"])
                    ),
                ]
                for entry in pk_conflict_mismatches
            ],
        ),
        "",
        "## Local-Only Tables",
        "",
        _format_markdown_table(
            ["Category", "Tables"],
            [
                ["Registry local-only present in SQLite", ", ".join(local_only_tables["registry_local_only_present_in_sqlite"]) or "None"],
                ["Registry local-only present in Postgres", ", ".join(local_only_tables["registry_local_only_present_in_postgres"]) or "None"],
                ["Registry local-only missing in SQLite", ", ".join(local_only_tables["registry_local_only_missing_in_sqlite"]) or "None"],
                ["SQLite-only unregistered", ", ".join(local_only_tables["sqlite_only_unregistered"]) or "None"],
            ],
        ),
    ]

    if smoke is not None:
        summary = smoke["summary"]
        auto_heal = smoke["auto_heal"]
        lines.extend([
            "",
            "## Sync Smoke",
            "",
            "This section comes from one live `run_sync_cycle()` invocation after the read-only tri-diff.",
            "",
            _format_markdown_table(
                ["Metric", "Value"],
                [
                    ["Smoke scope", smoke["scope"]],
                    ["Tables considered", ", ".join(smoke["tables"]) or "None"],
                    ["First failing table", smoke["first_failing_table"] or "None"],
                    ["First error", smoke["first_error"] or "None"],
                    ["Errors", str(len(summary.get("errors", [])))],
                    ["Tables synced", str(len(summary.get("synced", {})))],
                    [
                        "Tables with row activity",
                        ", ".join(
                            f"{table_name}={count}"
                            for table_name, count in summary.get("synced", {}).items()
                        ) or "None",
                    ],
                    ["create_all_tables added", ", ".join(auto_heal["create_all_tables_added"]) or "None"],
                    ["ensure_columns added", ", ".join(auto_heal["ensure_columns_added"]) or "None"],
                ],
            ),
            "",
            "### Per-Table Errors",
            "",
            _format_markdown_table(
                ["Error"],
                [[error] for error in summary.get("errors", [])],
            ),
        ])

    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    config = load_config()
    sqlite_path = DB_PATH
    database_url = os.environ.get("DATABASE_URL") or config.get("render", {}).get("database_url")

    if not sqlite_path:
        raise RuntimeError("ARCIS_DB_PATH / DB_PATH is required for the SQLite side of this audit")
    if not database_url:
        raise RuntimeError("DATABASE_URL or render.database_url is required for the Postgres side of this audit")

    sqlite_snapshot = _load_sqlite_snapshot(sqlite_path)
    pg_snapshot = _load_postgres_snapshot(database_url)
    tri_diff = _build_tri_diff(sqlite_snapshot, pg_snapshot)
    smoke = _run_sync_smoke(database_url, sqlite_path, tri_diff) if args.sync_smoke else None
    report = _render_report(
        sqlite_path=sqlite_path,
        database_url=database_url,
        tri_diff=tri_diff,
        smoke=smoke,
    )

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(report, encoding="utf-8")

    sys.stdout.write(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
