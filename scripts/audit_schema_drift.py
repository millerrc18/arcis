"""Schema NULL-constraint drift detector: registry vs SQLite vs PostgreSQL.

Sprint SP5 §J Cutover Rectification T3.

Compares per-column nullable semantics across three sources:
  1. Registry (src/schema/registry.py ColumnDef.nullable)
  2. Live SQLite (PRAGMA table_info — notnull field)
  3. Live PostgreSQL (information_schema.columns.is_nullable)

For each sync_to_postgres=True table, for each column, reports any mismatch.
A mismatch means the three sources disagree on whether the column is nullable.

Usage:
    python scripts/audit_schema_drift.py
    python scripts/audit_schema_drift.py --sqlite-path /path/to/db.sqlite3
    python scripts/audit_schema_drift.py --pg-dsn "host=... dbname=..."
    python scripts/audit_schema_drift.py --json-out drift_results.json

Exit codes:
    0 — No drift found (or only out-of-scope drift found)
    1 — Drift found in NOT NULL semantics
    2 — Both SQLite and PG were unreachable (static registry-only mode)
"""

import argparse
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src.schema.registry import TABLES


def _get_sqlite_nullability(db_path: str) -> dict[str, dict[str, bool]]:
    """Return {table_name: {col_name: nullable}} for all tables in the SQLite DB.

    nullable=True means the column allows NULL values (notnull=0 in PRAGMA).
    Returns an empty dict if the database is unreachable or empty.
    """
    result: dict[str, dict[str, bool]] = {}
    try:
        conn = sqlite3.connect(db_path)
        for tname in TABLES:
            cur = conn.execute(f"PRAGMA table_info({tname})")
            rows = cur.fetchall()
            if rows:
                result[tname] = {r[1]: not bool(r[3]) for r in rows}
        conn.close()
    except Exception as exc:
        print(f"[WARN] SQLite unreachable ({db_path}): {exc}", file=sys.stderr)
    return result


def _get_pg_nullability_via_docker(container: str = "halcyon-pg") -> dict[str, dict[str, bool]]:
    """Return {table_name: {col_name: nullable}} by querying PG via docker exec.

    Falls back gracefully if docker/container is unavailable.
    """
    result: dict[str, dict[str, bool]] = {}
    try:
        proc = subprocess.run(
            [
                "docker", "exec", container,
                "psql", "-U", "halcyon", "-d", "halcyon",
                "-t", "-A", "-F", "|",
                "-c",
                "SELECT table_name, column_name, is_nullable "
                "FROM information_schema.columns "
                "WHERE table_schema='public' "
                "ORDER BY table_name, ordinal_position;",
            ],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if proc.returncode != 0:
            print(f"[WARN] PG query failed: {proc.stderr.strip()}", file=sys.stderr)
            return result
        for line in proc.stdout.strip().split("\n"):
            parts = line.strip().split("|")
            if len(parts) == 3 and parts[0]:
                tname, cname, is_nullable = parts
                if tname not in result:
                    result[tname] = {}
                result[tname][cname] = (is_nullable.strip() == "YES")
    except FileNotFoundError:
        print("[WARN] docker not found — PG audit skipped", file=sys.stderr)
    except subprocess.TimeoutExpired:
        print("[WARN] PG query timed out — PG audit skipped", file=sys.stderr)
    except Exception as exc:
        print(f"[WARN] PG audit failed: {exc}", file=sys.stderr)
    return result


def _get_pg_nullability_via_dsn(dsn: str) -> dict[str, dict[str, bool]]:
    """Return PG nullability by connecting directly via psycopg2."""
    result: dict[str, dict[str, bool]] = {}
    try:
        import psycopg2
        conn = psycopg2.connect(dsn)
        cur = conn.cursor()
        cur.execute(
            "SELECT table_name, column_name, is_nullable "
            "FROM information_schema.columns "
            "WHERE table_schema='public' "
            "ORDER BY table_name, ordinal_position"
        )
        for tname, cname, is_nullable in cur.fetchall():
            if tname not in result:
                result[tname] = {}
            result[tname][cname] = (is_nullable == "YES")
        conn.close()
    except Exception as exc:
        print(f"[WARN] PG DSN connect failed: {exc}", file=sys.stderr)
    return result


def run_audit(
    sqlite_path: str | None = None,
    pg_dsn: str | None = None,
    pg_container: str = "halcyon-pg",
) -> dict:
    """Run the full three-way drift audit. Returns a result dict.

    Result structure:
    {
        "tables_audited": int,
        "columns_audited": int,
        "drifts": [
            {
                "table": str,
                "column": str,
                "registry_nullable": bool,
                "sqlite_nullable": bool | None,
                "pg_nullable": bool | None,
                "drift_type": "registry_vs_sqlite" | "registry_vs_pg" | "sqlite_vs_pg" | "all_three",
            },
            ...
        ],
        "sqlite_reachable": bool,
        "pg_reachable": bool,
        "pg_tables_in_db": int,
    }
    """
    if sqlite_path is None:
        sqlite_path = os.environ.get("ARCIS_DB_PATH", "")

    sqlite_data = {}
    if sqlite_path:
        sqlite_data = _get_sqlite_nullability(sqlite_path)

    pg_data = {}
    if pg_dsn:
        pg_data = _get_pg_nullability_via_dsn(pg_dsn)
    else:
        pg_data = _get_pg_nullability_via_docker(pg_container)

    sqlite_reachable = bool(sqlite_data)
    pg_reachable = bool(pg_data)
    pg_table_count = len(pg_data)

    tables_audited = 0
    columns_audited = 0
    drifts = []

    sync_tables = {k: v for k, v in TABLES.items() if v.sync_to_postgres}

    for tname, tdef in sync_tables.items():
        sq_table = sqlite_data.get(tname, {})
        pg_table = pg_data.get(tname, {})

        if not sq_table and not pg_table:
            continue

        tables_audited += 1

        for col in tdef.columns:
            cname = col.name
            reg_nullable = col.nullable
            sq_nullable = sq_table.get(cname) if sq_table else None
            pg_nullable = pg_table.get(cname) if pg_table else None

            reg_vs_sq = sq_nullable is not None and reg_nullable != sq_nullable
            reg_vs_pg = pg_nullable is not None and reg_nullable != pg_nullable
            sq_vs_pg = sq_nullable is not None and pg_nullable is not None and sq_nullable != pg_nullable

            if not (reg_vs_sq or reg_vs_pg or sq_vs_pg):
                columns_audited += 1
                continue

            if reg_vs_sq and reg_vs_pg and sq_vs_pg:
                dtype = "all_three"
            elif reg_vs_sq and reg_vs_pg:
                dtype = "registry_vs_both"
            elif reg_vs_sq:
                dtype = "registry_vs_sqlite"
            elif reg_vs_pg:
                dtype = "registry_vs_pg"
            else:
                dtype = "sqlite_vs_pg"

            drifts.append({
                "table": tname,
                "column": cname,
                "registry_nullable": reg_nullable,
                "sqlite_nullable": sq_nullable,
                "pg_nullable": pg_nullable,
                "drift_type": dtype,
            })
            columns_audited += 1

    return {
        "tables_audited": tables_audited,
        "columns_audited": columns_audited,
        "drifts": drifts,
        "sqlite_reachable": sqlite_reachable,
        "pg_reachable": pg_reachable,
        "pg_tables_in_db": pg_table_count,
    }


def _print_report(result: dict) -> None:
    drifts = result["drifts"]
    print("=" * 70)
    print("Schema NULL-Constraint Drift Audit — 2026-05-11")
    print("=" * 70)
    print(f"Tables audited:    {result['tables_audited']}")
    print(f"Columns audited:   {result['columns_audited']}")
    print(f"SQLite reachable:  {result['sqlite_reachable']}")
    print(f"PG reachable:      {result['pg_reachable']}")
    if result["pg_reachable"]:
        print(f"PG tables in DB:   {result['pg_tables_in_db']} (post-rollback: only ~9 tables remain)")
    print()

    if not drifts:
        print("No NOT-NULL drifts found.")
        return

    print(f"NOT-NULL drifts found: {len(drifts)}")
    print()
    header = f"{'Table.Column':<50} {'Registry':<10} {'SQLite':<10} {'PG':<10} {'Type'}"
    print(header)
    print("-" * len(header))
    for d in drifts:
        key = f"{d['table']}.{d['column']}"
        reg = "nullable" if d["registry_nullable"] else "NOT NULL"
        sq = ("nullable" if d["sqlite_nullable"] else "NOT NULL") if d["sqlite_nullable"] is not None else "N/A"
        pg = ("nullable" if d["pg_nullable"] else "NOT NULL") if d["pg_nullable"] is not None else "N/A"
        print(f"{key:<50} {reg:<10} {sq:<10} {pg:<10} {d['drift_type']}")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sqlite-path", default=None, help="Path to SQLite DB")
    parser.add_argument("--pg-dsn", default=None, help="PostgreSQL DSN string")
    parser.add_argument("--pg-container", default="halcyon-pg", help="Docker container name for PG")
    parser.add_argument("--json-out", default=None, help="Write JSON results to this file")
    parser.add_argument("--quiet", action="store_true", help="Suppress report output")
    args = parser.parse_args(argv)

    result = run_audit(
        sqlite_path=args.sqlite_path,
        pg_dsn=args.pg_dsn,
        pg_container=args.pg_container,
    )

    if not args.quiet:
        _print_report(result)

    if args.json_out:
        out_path = Path(args.json_out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(f"\nJSON results written to {out_path}")

    has_drifts = bool(result["drifts"])
    neither_reachable = not result["sqlite_reachable"] and not result["pg_reachable"]

    if neither_reachable:
        sys.exit(2)
    if has_drifts:
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
