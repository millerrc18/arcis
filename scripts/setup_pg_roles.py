"""Idempotent PG role creation script.

Creates two application roles via the halcyon superuser connection:

- halcyon_app  : LOGIN, INSERT/SELECT/UPDATE/DELETE on all tables in public,
                 USAGE on sequences, ALTER DEFAULT PRIVILEGES for future tables.
- halcyon_readonly: LOGIN, SELECT only on all tables in public,
                    ALTER DEFAULT PRIVILEGES for future tables.

Password values are read from environment variables:
  DOCKER_PG_APP_PASSWORD  -- password for halcyon_app
  DOCKER_PG_RO_PASSWORD   -- password for halcyon_readonly

Each CREATE ROLE is wrapped in a DO $$ ... EXCEPTION WHEN duplicate_object
THEN NULL; END $$ block so the script is fully idempotent (safe to re-run).

Usage:
    python scripts/setup_pg_roles.py

Prerequisites:
  - DATABASE_URL points to the halcyon superuser connection
    (e.g. postgresql://halcyon:<pw>@localhost:5433/halcyon)
  - Both DOCKER_PG_APP_PASSWORD and DOCKER_PG_RO_PASSWORD are set in .env
    or the calling shell
"""

import os
import sys

import psycopg2
from psycopg2 import sql


def _get_required_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        print(f"ERROR: environment variable {name!r} is not set.", file=sys.stderr)
        sys.exit(1)
    return value


def main() -> None:
    app_password = _get_required_env("DOCKER_PG_APP_PASSWORD")
    ro_password = _get_required_env("DOCKER_PG_RO_PASSWORD")
    database_url = os.environ.get(
        "DATABASE_URL", "postgresql://halcyon:halcyon@localhost:5433/halcyon"
    )

    conn = psycopg2.connect(database_url)
    try:
        cur = conn.cursor()

        # --- CREATE ROLE halcyon_app (idempotent) ---
        # Named dollar-quote tag $halcyon$ is defensive against any future
        # Literal output containing $$ (industry standard for embedded
        # dollar-quoting). sql.Literal safely quotes the password value,
        # eliminating the SQL injection class present with f-string composition.
        cur.execute(
            sql.SQL("""
DO $halcyon$
BEGIN
  CREATE ROLE halcyon_app WITH LOGIN PASSWORD {pw};
EXCEPTION WHEN duplicate_object THEN NULL;
END
$halcyon$
""").format(pw=sql.Literal(app_password))
        )

        # --- CREATE ROLE halcyon_readonly (idempotent) ---
        cur.execute(
            sql.SQL("""
DO $halcyon$
BEGIN
  CREATE ROLE halcyon_readonly WITH LOGIN PASSWORD {pw};
EXCEPTION WHEN duplicate_object THEN NULL;
END
$halcyon$
""").format(pw=sql.Literal(ro_password))
        )

        # --- CONNECT on database ---
        cur.execute(
            "GRANT CONNECT ON DATABASE halcyon TO halcyon_app, halcyon_readonly"
        )

        # --- USAGE on schema ---
        cur.execute(
            "GRANT USAGE ON SCHEMA public TO halcyon_app, halcyon_readonly"
        )

        # --- Table-level grants for halcyon_app (write) ---
        cur.execute(
            "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO halcyon_app"
        )

        # --- Table-level grants for halcyon_readonly (read only) ---
        cur.execute(
            "GRANT SELECT ON ALL TABLES IN SCHEMA public TO halcyon_readonly"
        )

        # --- Sequence grants for halcyon_app (existing sequences) ---
        cur.execute(
            "GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO halcyon_app"
        )

        # --- Default privileges for future tables — halcyon_app ---
        cur.execute(
            "ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO halcyon_app"
        )

        # --- Default privileges for future sequences — halcyon_app ---
        # Without this, future SERIAL/IDENTITY columns added by migrations will
        # be inaccessible to halcyon_app — INSERT statements will fail with
        # "permission denied for sequence <name>_id_seq".
        cur.execute(
            "ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE ON SEQUENCES TO halcyon_app"
        )

        # --- Default privileges for future tables — halcyon_readonly ---
        cur.execute(
            "ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO halcyon_readonly"
        )

        conn.commit()
        print("setup_pg_roles: roles created and privileges granted.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
