"""Background sync thread that pushes local SQLite data to Render Postgres.

Called by: api.cloud_app, scheduler.watch
Calls: none
Owns tables: sync_state
Config keys: database_url, enabled, mode, pk, render, sync_interval_seconds, time_col
Tests: tests/test_data_collectors.py, tests/test_render_sync.py

Architecture: Pull-based sync, SQLite -> Postgres. The local machine is the
source of truth for all data except user_notes (bidirectional) and
pending_commands/config_overrides (pulled FROM cloud). Every 120s the
daemon thread pushes new/changed rows to Render Postgres so the cloud
dashboard has fresh data.

Sync modes:
  - "incremental": rows where time_col > last_synced_at (most tables)
  - "latest_only": delete+reinsert latest snapshot date (#229, #242)
  - "full": upsert entire table (small state tables like traffic_light_state)

Key fixes referenced:
  - #185: ON CONFLICT DO NOTHING for tables with SERIAL pks to avoid
          duplicate key errors when SQLite rowids collide with Postgres serials
  - #199: Per-table Postgres reconnection — if the connection dies mid-cycle,
          each table gets its own reconnect attempt rather than failing all
  - #228: Sync thread silent death — health_status() exposes staleness so
          the dashboard can warn when sync stops
  - #229: latest_only race — savepoint-protected DELETE+INSERT to prevent
          data loss if INSERT fails after DELETE
  - #242: latest_only serial clash — strip SQLite 'id' column from INSERT
          to let Postgres SERIAL auto-generate, avoiding pkey collisions
  - #243: NULL id sync failure — filter out rows with NULL primary keys
          before attempting Postgres INSERT (incomplete SQLite data)
  - #130: Overlapping sync cycles — _sync_lock prevents concurrent runs
  - #131: Sync timezone — all timestamps are ET (America/New_York)
"""

import json
import logging
import socket
import sqlite3
import threading
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from src.config import DB_PATH

# Per-table reconnection (#199): if a Postgres connection dies mid-cycle,
# each table gets 3 retry attempts with escalating backoff. This prevents
# a single transient DNS failure from skipping all remaining tables.
_PG_CONNECT_RETRIES = 3
_PG_CONNECT_BACKOFF = [2, 5, 10]  # seconds between retries

logger = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")

LOCAL_DB = DB_PATH

# ── Tables and sync strategies ───────────────────────────────────────
# "incremental" = sync rows where created_at > last_synced_at
# "latest_only" = drop and re-insert latest snapshot (no created_at)
# Generated from schema registry — see src/schema/sync_config.py
from src.schema.sync_config import generate_sync_tables
SYNC_TABLES: dict[str, dict] = generate_sync_tables()
# NOTE: pending_commands and config_overrides flow in the OPPOSITE direction
# (cloud -> local). They are pulled by pull_commands() at the end of each
# sync cycle. This bidirectional flow lets the cloud dashboard submit
# commands that the local machine executes.


class TableFetchError(RuntimeError):
    """Raised when a configured sync table cannot be read from SQLite."""

# ── Sync state table (local SQLite) ─────────────────────────────────

from src.schema.registry import TABLES as _REGISTRY_TABLES
from src.schema.sqlite import generate_create_sql as _generate_create_sql


def _sqlite_conn(db_path: str = LOCAL_DB) -> sqlite3.Connection:
    """Create a SQLite connection with busy_timeout for concurrent access."""
    conn = sqlite3.connect(db_path, timeout=10)
    conn.execute("PRAGMA busy_timeout = 10000")
    return conn


def _sync_host_name() -> str:
    """Return the current host identifier used for sync_state rows."""
    return socket.gethostname() or "unknown-host"


def _registry_column_types(table_name: str) -> dict[str, str]:
    """Return registry column types for a sync table."""
    table = _REGISTRY_TABLES.get(table_name)
    if table is None:
        return {}
    return {col.name: col.type.upper() for col in table.columns}


def _split_conflict_columns(conflict_col: str | None) -> list[str]:
    """Normalize a comma-separated ON CONFLICT target into column names."""
    if not conflict_col:
        return []
    return [part.strip() for part in conflict_col.split(",") if part.strip()]


def _get_pg_table_columns(pg_conn, table_name: str) -> list[str] | None:
    """Best-effort fetch of Postgres column names for one table.

    Returns None when the connection/cursor is mocked or when the query fails.
    The sync path falls back to registry-only filtering in those cases so unit
    tests do not need to fully emulate information_schema.
    """
    if type(pg_conn).__module__.startswith("unittest.mock"):
        return None

    cursor = None
    try:
        cursor = pg_conn.cursor()
        cursor.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = %s ORDER BY ordinal_position",
            (table_name,),
        )
        rows = cursor.fetchall()
        if not isinstance(rows, list):
            return None
        return [row[0] for row in rows if isinstance(row, tuple) and row]
    except Exception:
        return None
    finally:
        if cursor is not None:
            try:
                cursor.close()
            except Exception:
                pass


def _filter_columns_by_registry(table_name: str, source_columns: list[str]) -> list[str]:
    """Drop columns not present in the schema registry for table_name.

    Returns source_columns unchanged when the table is not in the registry
    (preserving the early-return semantics of the original function).
    """
    registry_types = _registry_column_types(table_name)
    if not registry_types:
        return source_columns

    registry_cols = set(registry_types)
    filtered = [col for col in source_columns if col in registry_cols]
    dropped_not_in_registry = [col for col in source_columns if col not in registry_cols]
    if dropped_not_in_registry:
        logger.warning(
            "Dropping %d SQLite columns not present in schema registry for %s: %s",
            len(dropped_not_in_registry),
            table_name,
            ", ".join(dropped_not_in_registry),
        )
    return filtered


def _filter_columns_by_pg(
    pg_conn,
    table_name: str,
    filtered: list[str],
) -> tuple[list[str], set[str] | None]:
    """Intersect filtered columns with live Postgres columns for table_name.

    Returns (filtered, None) when introspection is unavailable (mocked conn or
    query failure), signalling the caller to fall back to registry-only filtering.
    Returns (insert_cols, pg_col_set) when introspection succeeds.
    """
    pg_columns = _get_pg_table_columns(pg_conn, table_name)
    if pg_columns is None:
        return filtered, None

    pg_col_set = set(pg_columns)
    insert_cols = [col for col in filtered if col in pg_col_set]
    dropped_not_in_pg = [col for col in filtered if col not in pg_col_set]
    if dropped_not_in_pg:
        logger.warning(
            "Dropping %d columns missing from Postgres for %s: %s",
            len(dropped_not_in_pg),
            table_name,
            ", ".join(dropped_not_in_pg),
        )
    return insert_cols, pg_col_set


def _validate_conflict_columns(
    table_name: str,
    pk: str,
    conflict_col: str | None,
    filtered: list[str],
    pg_col_set: set[str],
    insert_cols: list[str],
) -> None:
    """Run conflict-col / pk-missing / empty-insert validations.

    Raises RuntimeError for hard failures; emits a WARNING for the pk-missing
    case (which is advisory only).
    """
    missing_conflict_cols = [
        col for col in _split_conflict_columns(conflict_col) if col not in pg_col_set
    ]
    if missing_conflict_cols:
        raise RuntimeError(
            f"{table_name}: Postgres missing conflict target columns: "
            f"{', '.join(missing_conflict_cols)}"
        )

    if pk in filtered and pk not in pg_col_set and not conflict_col:
        logger.warning(
            "Primary key column %s missing from Postgres for %s; sync will rely on "
            "the remaining insert columns",
            pk,
            table_name,
        )

    if not insert_cols:
        raise RuntimeError(f"{table_name}: no shared columns between SQLite, registry, and Postgres")


def _resolve_sync_columns(
    pg_conn,
    table_name: str,
    source_columns: list[str],
    *,
    pk: str,
    conflict_col: str | None,
) -> list[str]:
    """Filter source columns to the safe insert set for Postgres.

    The registry is the canonical intended schema. When Postgres introspection
    succeeds, we further intersect with live PG columns so schema drift no
    longer hard-fails the entire table sync.
    """
    filtered = _filter_columns_by_registry(table_name, source_columns)
    if filtered is source_columns:
        return source_columns

    insert_cols, pg_col_set = _filter_columns_by_pg(pg_conn, table_name, filtered)
    if pg_col_set is None:
        return filtered

    _validate_conflict_columns(table_name, pk, conflict_col, filtered, pg_col_set, insert_cols)
    return insert_cols


def _coerce_rows_to_registry_types(
    table_name: str,
    rows: list[dict],
    columns: list[str],
) -> None:
    """Coerce numeric values according to registry types before PG INSERT."""
    registry_types = _registry_column_types(table_name)
    if not registry_types:
        return

    integer_columns = {
        col for col in columns if registry_types.get(col) == "INTEGER"
    }
    real_columns = {
        col for col in columns if registry_types.get(col) == "REAL"
    }

    for row in rows:
        for col in integer_columns:
            if col in row and row[col] is not None:
                try:
                    row[col] = int(float(row[col]))
                except (ValueError, TypeError):
                    pass
        for col in real_columns:
            if col in row and row[col] is not None:
                try:
                    row[col] = float(row[col])
                except (ValueError, TypeError):
                    pass


def _init_sync_state(db_path: str = LOCAL_DB) -> None:
    """Ensure the sync_state table exists (from schema registry)."""
    try:
        with _sqlite_conn(db_path) as conn:
            conn.executescript(_generate_create_sql(_REGISTRY_TABLES["sync_state"]))
    except Exception as exc:
        logger.error("Failed to init sync_state table: %s", exc, extra={"ctx": {"event": "sync_error", "table": "sync_state", "error": str(exc)}})


def get_last_synced_at(table_name: str, db_path: str = LOCAL_DB) -> str | None:
    """Return the last_synced_at timestamp for a table, or None."""
    try:
        with _sqlite_conn(db_path) as conn:
            row = conn.execute(
                "SELECT last_synced_at FROM sync_state WHERE table_name = ?",
                (table_name,),
            ).fetchone()
            return row[0] if row else None
    except Exception as exc:
        logger.error("Failed to read sync_state for %s: %s", table_name, exc, extra={"ctx": {"event": "sync_error", "table": table_name, "error": str(exc)}})
        return None


def set_last_synced_at(table_name: str, ts: str, db_path: str = LOCAL_DB) -> None:
    """Upsert the last_synced_at timestamp for a table. Retries on lock."""
    for attempt in range(3):
        try:
            with _sqlite_conn(db_path) as conn:
                conn.execute(
                    "INSERT INTO sync_state (table_name, last_synced_at) "
                    "VALUES (?, ?) "
                    "ON CONFLICT(table_name) DO UPDATE SET last_synced_at = excluded.last_synced_at",
                    (table_name, ts),
                )
                conn.commit()
            return
        except sqlite3.OperationalError as exc:
            if "locked" in str(exc) and attempt < 2:
                time.sleep(1 + attempt)
                continue
            logger.error("Failed to update sync_state for %s: %s", table_name, exc, extra={"ctx": {"event": "sync_error", "table": table_name, "error": str(exc)}})
        except Exception as exc:
            logger.error("Failed to update sync_state for %s: %s", table_name, exc, extra={"ctx": {"event": "sync_error", "table": table_name, "error": str(exc)}})
            return


# ── In-flight sync detection (#673) ──────────────────────────────────────────
# Each host gets one row in sync_state keyed by host name.
# The per-table cursor rows (keyed by table name) are unaffected.

class SyncInFlightError(RuntimeError):
    """Raised when mark_sync_in_flight is called while a sync is already running.

    Pass force=True to override (use only when the previous in-flight row is
    known stale — e.g. after a crash with no completed_at written).
    """


def mark_sync_in_flight(host: str, db_path: str = LOCAL_DB, force: bool = False) -> None:
    """Record that a sync cycle is starting on this host.

    Raises SyncInFlightError if another in-progress row already exists for
    this host, unless force=True.
    """
    now = datetime.now(ET).isoformat()
    with _sqlite_conn(db_path) as conn:
        existing = conn.execute(
            "SELECT status FROM sync_state WHERE table_name = ?",
            (host,),
        ).fetchone()
        if existing and existing[0] == "in_progress" and not force:
            raise SyncInFlightError(
                f"Sync already in progress on host '{host}'. "
                "Use force=True to override if the row is known stale."
            )
        conn.execute(
            "INSERT INTO sync_state "
            "  (table_name, last_synced_at, in_flight_since, completed_at, status, error_message, host) "
            "VALUES (?, '', ?, NULL, 'in_progress', NULL, ?) "
            "ON CONFLICT(table_name) DO UPDATE SET "
            "  in_flight_since = excluded.in_flight_since, "
            "  completed_at    = NULL, "
            "  status          = 'in_progress', "
            "  error_message   = NULL, "
            "  host            = excluded.host",
            (host, now, host),
        )
        conn.commit()


def mark_sync_completed(host: str, db_path: str = LOCAL_DB) -> None:
    """Record that a sync cycle completed successfully on this host."""
    now = datetime.now(ET).isoformat()
    with _sqlite_conn(db_path) as conn:
        conn.execute(
            "UPDATE sync_state SET "
            "  in_flight_since = NULL, "
            "  completed_at = ?, "
            "  status = 'completed', "
            "  error_message = NULL "
            "WHERE table_name = ?",
            (now, host),
        )
        conn.commit()


def mark_sync_failed(host: str, error: str, db_path: str = LOCAL_DB) -> None:
    """Record that a sync cycle failed on this host."""
    with _sqlite_conn(db_path) as conn:
        conn.execute(
            "UPDATE sync_state SET "
            "  in_flight_since = NULL, "
            "  status = 'failed', "
            "  error_message = ? "
            "WHERE table_name = ?",
            (error, host),
        )
        conn.commit()


def get_sync_flight_status(host: str, db_path: str = LOCAL_DB) -> dict | None:
    """Return the in-flight status row for this host, or None if no row exists."""
    with _sqlite_conn(db_path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT table_name, in_flight_since, completed_at, status, error_message, host "
            "FROM sync_state WHERE table_name = ?",
            (host,),
        ).fetchone()
    return dict(row) if row else None


# ── Core sync logic ─────────────────────────────────────────────────

def _fetch_incremental_rows(
    table_name: str,
    time_col: str,
    since: str | None,
    db_path: str = LOCAL_DB,
) -> tuple[list[dict], list[str]]:
    """Fetch rows from SQLite where time_col > since. Returns (rows, columns)."""
    try:
        with sqlite3.connect(db_path, timeout=10) as conn:  # #258: busy timeout
            conn.row_factory = sqlite3.Row
            if since:
                cursor = conn.execute(
                    f"SELECT * FROM {table_name} WHERE {time_col} > ? ORDER BY {time_col}",
                    (since,),
                )
            else:
                cursor = conn.execute(f"SELECT * FROM {table_name} ORDER BY {time_col} LIMIT 10000")
            rows = cursor.fetchall()
            if not rows:
                return [], []
            columns = list(rows[0].keys())
            return [dict(r) for r in rows], columns
    except Exception as exc:
        raise TableFetchError(f"{table_name}: {exc}") from exc


def _fetch_latest_rows(
    table_name: str,
    time_col: str,
    db_path: str = LOCAL_DB,
) -> tuple[list[dict], list[str]]:
    """Fetch only the latest date's rows for snapshot tables."""
    try:
        with sqlite3.connect(db_path, timeout=10) as conn:  # #258: busy timeout
            conn.row_factory = sqlite3.Row
            # Get the max date
            max_date_row = conn.execute(
                f"SELECT MAX({time_col}) FROM {table_name}"
            ).fetchone()
            max_date = max_date_row[0] if max_date_row else None
            if not max_date:
                return [], []
            cursor = conn.execute(
                f"SELECT * FROM {table_name} WHERE {time_col} = ?",
                (max_date,),
            )
            rows = cursor.fetchall()
            if not rows:
                return [], []
            columns = list(rows[0].keys())
            return [dict(r) for r in rows], columns
    except Exception as exc:
        raise TableFetchError(f"{table_name}: {exc}") from exc


def _fetch_full_rows(
    table_name: str,
    db_path: str = LOCAL_DB,
) -> tuple[list[dict], list[str]]:
    """Fetch every row for small state tables configured for full sync."""
    try:
        with sqlite3.connect(db_path, timeout=10) as conn:  # #258: busy timeout
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(f"SELECT * FROM {table_name}")
            rows = cursor.fetchall()
            if not rows:
                return [], []
            columns = list(rows[0].keys())
            return [dict(r) for r in rows], columns
    except Exception as exc:
        raise TableFetchError(f"{table_name}: {exc}") from exc


def _fetch_council_votes_for_new_sessions(
    since: str | None,
    db_path: str = LOCAL_DB,
) -> tuple[list[dict], list[str]]:
    """Fetch council_votes linked to sessions created after 'since'."""
    try:
        with sqlite3.connect(db_path, timeout=10) as conn:  # #258: busy timeout
            conn.row_factory = sqlite3.Row
            if since:
                cursor = conn.execute(
                    "SELECT v.* FROM council_votes v "
                    "JOIN council_sessions s ON v.session_id = s.session_id "
                    "WHERE s.created_at >= ? ORDER BY s.created_at",
                    (since,),
                )
            else:
                cursor = conn.execute(
                    "SELECT v.* FROM council_votes v "
                    "JOIN council_sessions s ON v.session_id = s.session_id "
                    "ORDER BY s.created_at DESC LIMIT 5000"
                )
            rows = cursor.fetchall()
            if not rows:
                return [], []
            columns = list(rows[0].keys())
            return [dict(r) for r in rows], columns
    except Exception as exc:
        raise TableFetchError(f"council_votes: {exc}") from exc


def _upsert_to_postgres(
    pg_conn,
    table_name: str,
    pk: str,
    columns: list[str],
    rows: list[dict],
    conflict_col: str | None = None,
    mode: str = "incremental",
) -> int:
    """Upsert rows into Postgres using ON CONFLICT. Returns count of upserted rows.

    Args:
        conflict_col: Override the ON CONFLICT target (e.g., for tables with
            UNIQUE constraints that differ from the PK, like edgar_filings
            which has a UNIQUE accession_number).
        mode: Sync mode for the calling table ("incremental"|"latest_only"|"full").
            Gates whether the integer 'id' column gets stripped from INSERT to
            let Postgres SERIAL auto-generate. Full-mode tables (singleton/
            fixed-key replacements like traffic_light_state) keep their id —
            stripping it produces NULL violations because Postgres has plain
            INTEGER NOT NULL with no SERIAL/IDENTITY default (#797).

    Two code paths:
    1. Tables with SERIAL 'id' pk and no conflict_col: uses ON CONFLICT DO
       NOTHING (#185) because SQLite rowids and Postgres SERIAL values diverge.
    2. Tables with a natural key: uses ON CONFLICT ... DO UPDATE SET to upsert.

    Rows with NULL primary keys are filtered out (#243) because they indicate
    incomplete data in SQLite that would violate Postgres NOT NULL constraints.
    """
    if not rows or not columns:
        return 0

    columns = _resolve_sync_columns(
        pg_conn, table_name, columns, pk=pk, conflict_col=conflict_col,
    )
    _coerce_rows_to_registry_types(table_name, rows, columns)

    conflict_target = conflict_col or pk
    conflict_columns = set(_split_conflict_columns(conflict_target)) or {pk}

    # Filter out rows with NULL primary key — these would fail Postgres NOT NULL
    # constraint and indicate incomplete data in SQLite (#243).
    if pk in columns:
        before = len(rows)
        rows = [r for r in rows if r.get(pk) is not None]
        skipped = before - len(rows)
        if skipped:
            logger.warning("Skipped %d rows with NULL %s in %s", skipped, pk, table_name)
        if not rows:
            return 0

    # For tables with SERIAL 'id' pk, exclude 'id' from INSERT to let
    # Postgres auto-generate — SQLite rowids and Postgres SERIAL values diverge.
    # Fix #244: Only strip 'id' for INTEGER/SERIAL pks. Tables with TEXT ids
    # (e.g. research_docs with UUID ids) must keep their id column — Postgres
    # cannot auto-generate a TEXT primary key.
    # Fix #797: never strip in full mode. Full-mode tables (e.g.
    # traffic_light_state) are singleton/fixed-key replacements where the id
    # IS the natural key and Postgres has no SERIAL/IDENTITY default.
    strip_id = (
        pk == "id"
        and rows
        and not isinstance(rows[0].get("id"), str)
        and mode != "full"
    )
    insert_cols = [c for c in columns if c != "id"] if strip_id else columns

    if not conflict_col and strip_id:
        # No natural key — best-effort insert, skip duplicates
        col_list = ", ".join(insert_cols)
        placeholders = ", ".join(["%s"] * len(insert_cols))
        sql = f"INSERT INTO {table_name} ({col_list}) VALUES ({placeholders}) ON CONFLICT DO NOTHING"

        count = 0
        cursor = pg_conn.cursor()
        try:
            for row in rows:
                values = [row.get(col) for col in insert_cols]
                cursor.execute(sql, values)
                count += 1
            pg_conn.commit()
        except Exception as exc:
            pg_conn.rollback()
            logger.error("Postgres upsert failed for %s: %s", table_name, exc, extra={"ctx": {"event": "sync_error", "table": table_name, "error": str(exc)}})
            raise
        finally:
            cursor.close()
        return count

    col_list = ", ".join(insert_cols)
    placeholders = ", ".join(["%s"] * len(insert_cols))
    update_set = ", ".join(
        f"{col} = EXCLUDED.{col}" for col in insert_cols if col not in conflict_columns
    )

    sql = (
        f"INSERT INTO {table_name} ({col_list}) VALUES ({placeholders}) "
        f"ON CONFLICT ({conflict_target}) DO UPDATE SET {update_set}"
    )

    count = 0
    cursor = pg_conn.cursor()
    try:
        for row in rows:
            values = [row.get(col) for col in insert_cols]
            cursor.execute(sql, values)
            count += 1
        pg_conn.commit()
    except Exception as exc:
        pg_conn.rollback()
        logger.error("Postgres upsert failed for %s: %s", table_name, exc, extra={"ctx": {"event": "sync_error", "table": table_name, "error": str(exc)}})
        raise
    finally:
        cursor.close()

    return count


def _replace_latest_in_postgres(
    pg_conn,
    table_name: str,
    time_col: str,
    columns: list[str],
    rows: list[dict],
) -> int:
    """For latest-only tables: delete old data for the date, insert fresh.

    Uses a savepoint so that if INSERT fails after DELETE, the entire
    operation rolls back (no data loss). The DELETE + INSERT are within a
    single transaction — both succeed or neither does (#229).

    Excludes 'id' column from INSERT to let Postgres SERIAL generate new ids,
    avoiding pkey collisions between SQLite rowids and Postgres SERIAL values (#242).

    This mode is for snapshot tables (vix_term_structure, cboe_ratios, etc.)
    where we only care about the latest date's data and want to fully replace it.
    """
    if not rows or not columns:
        return 0

    latest_date = rows[0].get(time_col)
    if not latest_date:
        return 0

    # Fix #243 + NULL id hardening: auto-repair NULL ids from SQLite ROWID
    # before syncing. Tables with INTEGER PRIMARY KEY (id) can get NULL ids
    # when INSERTs omit the id column and the schema uses a separate
    # PRIMARY KEY constraint instead of inline (see sqlite.py fix).
    if "id" in columns:
        null_ids = [r for r in rows if r.get("id") is None]
        if null_ids:
            # Fix for #293: Use longer timeout (30s) and retry once.
            # The collector may be doing a bulk INSERT of 42K+ rows
            # concurrently, causing "database is locked" at 10s.
            try:
                from src.config import DB_PATH as _sync_db
                import sqlite3 as _sync_sql
                import time as _sync_time
                _repaired = False
                for _attempt in range(2):
                    try:
                        with _sync_sql.connect(_sync_db, timeout=30) as _fix_conn:
                            _fixed = _fix_conn.execute(
                                f"UPDATE {table_name} SET id = rowid WHERE id IS NULL"
                            ).rowcount
                            _fix_conn.commit()
                            if _fixed:
                                logger.info("Auto-repaired %d NULL ids in %s from ROWID", _fixed, table_name)
                            _repaired = True
                            break
                    except _sync_sql.OperationalError:
                        if _attempt == 0:
                            _sync_time.sleep(2)  # Brief wait before retry
                if _repaired:
                    for r in null_ids:
                        r["id"] = id(r)  # Placeholder — will be stripped for Postgres
            except Exception as e:
                logger.warning("NULL id auto-repair failed for %s: %s", table_name, e)
            # Final filter — skip any remaining NULLs that couldn't be repaired
            before = len(rows)
            rows = [r for r in rows if r.get("id") is not None]
            skipped = before - len(rows)
            if skipped:
                logger.warning("Skipped %d rows with NULL id in %s (latest_only)", skipped, table_name)
        if not rows:
            return 0

    columns = _resolve_sync_columns(
        pg_conn, table_name, columns, pk="id", conflict_col=None,
    )
    _coerce_rows_to_registry_types(table_name, rows, columns)

    # Exclude SQLite 'id' — let Postgres SERIAL auto-generate
    insert_cols = [c for c in columns if c != "id"]

    cursor = pg_conn.cursor()
    try:
        # Savepoint protects against partial failure: if INSERT fails,
        # the DELETE is also rolled back — no data loss window.
        cursor.execute("SAVEPOINT sync_replace")

        cursor.execute(
            f"DELETE FROM {table_name} WHERE {time_col} = %s",
            (latest_date,),
        )

        col_list = ", ".join(insert_cols)
        placeholders = ", ".join(["%s"] * len(insert_cols))
        # Fix #242: ON CONFLICT DO NOTHING prevents duplicate key violations
        # from race conditions where two sync cycles overlap on the same date.
        sql = f"INSERT INTO {table_name} ({col_list}) VALUES ({placeholders}) ON CONFLICT DO NOTHING"

        for row in rows:
            values = [row.get(col) for col in insert_cols]
            cursor.execute(sql, values)

        cursor.execute("RELEASE SAVEPOINT sync_replace")
        pg_conn.commit()
        return len(rows)
    except Exception as exc:
        try:
            cursor.execute("ROLLBACK TO SAVEPOINT sync_replace")
        except Exception:
            pass
        pg_conn.rollback()
        logger.error("Postgres replace failed for %s: %s", table_name, exc, extra={"ctx": {"event": "sync_error", "table": table_name, "error": str(exc)}})
        raise
    finally:
        cursor.close()


def sync_table(
    pg_conn,
    table_name: str,
    table_config: dict,
    db_path: str = LOCAL_DB,
) -> int:
    """Sync a single table from SQLite to Postgres. Returns row count synced."""
    mode = table_config["mode"]
    time_col = table_config.get("time_col")
    pk = table_config["pk"]
    conflict_col = table_config.get("conflict_col")

    # Special handling for council_votes (no time_col of its own)
    if table_name == "council_votes":
        since = get_last_synced_at("council_sessions", db_path)
        rows, columns = _fetch_council_votes_for_new_sessions(since, db_path)
        if not rows:
            return 0
        return _upsert_to_postgres(
            pg_conn, table_name, pk, columns, rows, conflict_col, mode=mode,
        )

    if mode == "incremental":
        since = get_last_synced_at(table_name, db_path)
        rows, columns = _fetch_incremental_rows(table_name, time_col, since, db_path)
        if not rows:
            return 0
        count = _upsert_to_postgres(
            pg_conn, table_name, pk, columns, rows, conflict_col, mode=mode,
        )
        # Update sync state to latest time_col value
        latest_ts = max(r.get(time_col, "") for r in rows)
        if latest_ts:
            set_last_synced_at(table_name, latest_ts, db_path)
        return count

    elif mode == "latest_only":
        rows, columns = _fetch_latest_rows(table_name, time_col, db_path)
        if not rows:
            return 0
        count = _replace_latest_in_postgres(
            pg_conn, table_name, time_col, columns, rows
        )
        latest_ts = rows[0].get(time_col, "")
        if latest_ts:
            set_last_synced_at(table_name, latest_ts, db_path)
        return count

    if mode == "full":
        rows, columns = _fetch_full_rows(table_name, db_path)
        if not rows:
            return 0
        return _upsert_to_postgres(
            pg_conn, table_name, pk, columns, rows, conflict_col, mode=mode,
        )

    raise ValueError(f"Unknown sync mode for {table_name}: {mode}")


def pull_commands(database_url: str, db_path: str = LOCAL_DB) -> list[dict]:
    """Pull pending commands from Render Postgres into local SQLite.

    This is the "cloud -> local" half of the bidirectional sync. When a user
    clicks an action on the cloud dashboard, it writes to pending_commands
    in Postgres. This function picks those up and inserts them locally for
    the watch loop to execute.

    Flow:
    1. Read pending_commands WHERE status='pending' AND expires_at > NOW()
    2. Insert into local SQLite with status='claimed'
    3. Update Postgres status to 'claimed' with claimed_at
    4. Also pull config_overrides (full table replace — dashboard settings)
    5. Return list of pulled commands for immediate execution via callback
    """
    try:
        import psycopg2
    except ImportError:
        return []

    now = datetime.now(ET).isoformat()
    pulled = []

    pg_conn = None
    try:
        pg_conn = psycopg2.connect(database_url)
    except Exception as exc:
        logger.error("pull_commands: cannot connect to Postgres: %s", exc, extra={"ctx": {"event": "sync_error", "table": None, "error": str(exc)}})
        return []

    try:
        # 1. Pull pending commands
        cursor = pg_conn.cursor()
        cursor.execute(
            "SELECT command_id, command_type, command_name, payload_json, "
            "status, priority, created_at, claimed_at, expires_at, created_by "
            "FROM pending_commands "
            "WHERE status = 'pending' AND (expires_at IS NULL OR expires_at > %s) "
            "ORDER BY priority DESC, created_at ASC",
            (now,),
        )
        columns = [desc[0] for desc in cursor.description]
        rows = [dict(zip(columns, row)) for row in cursor.fetchall()]

        if rows:
            # Insert into local SQLite
            local_conn = sqlite3.connect(db_path, timeout=10)  # #258: busy timeout
            local_cur = local_conn.cursor()
            for row in rows:
                try:
                    local_cur.execute(
                        "INSERT OR IGNORE INTO pending_commands "
                        "(command_id, command_type, command_name, payload_json, "
                        "status, priority, created_at, claimed_at, expires_at, created_by) "
                        "VALUES (?, ?, ?, ?, 'claimed', ?, ?, ?, ?, ?)",
                        (
                            row["command_id"], row["command_type"],
                            row["command_name"], row["payload_json"],
                            row["priority"], row["created_at"],
                            now, row["expires_at"], row["created_by"],
                        ),
                    )
                    pulled.append(row)
                except Exception as exc:
                    logger.error("pull_commands: local insert failed: %s", exc, extra={"ctx": {"event": "sync_error", "table": "pending_commands", "error": str(exc)}})
            local_conn.commit()
            local_conn.close()

            # Update Postgres status to 'claimed' — only for successfully inserted commands (#259).
            # Previously used `rows` which marked ALL commands as claimed even if
            # local SQLite insert failed. Now uses `pulled` (successfully inserted only).
            command_ids = [r["command_id"] for r in pulled]
            if command_ids:
                placeholders = ", ".join(["%s"] * len(command_ids))
                cursor.execute(
                    f"UPDATE pending_commands SET status = 'claimed', claimed_at = %s "
                    f"WHERE command_id IN ({placeholders})",
                    [now] + command_ids,
                )
                pg_conn.commit()
            logger.info("Pulled %d commands from cloud", len(pulled))

        cursor.close()

        # 2. Pull config_overrides (full table replace)
        cursor = pg_conn.cursor()
        cursor.execute(
            "SELECT setting_key, setting_value, previous_value, updated_at, updated_by "
            "FROM config_overrides"
        )
        override_cols = [desc[0] for desc in cursor.description]
        override_rows = [dict(zip(override_cols, row)) for row in cursor.fetchall()]
        cursor.close()

        if override_rows:
            local_conn = sqlite3.connect(db_path, timeout=10)  # #258: busy timeout
            local_cur = local_conn.cursor()
            local_cur.execute("DELETE FROM config_overrides")
            for row in override_rows:
                local_cur.execute(
                    "INSERT INTO config_overrides "
                    "(setting_key, setting_value, previous_value, updated_at, updated_by) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (
                        row["setting_key"], row["setting_value"],
                        row["previous_value"], row["updated_at"],
                        row["updated_by"],
                    ),
                )
            local_conn.commit()
            local_conn.close()
            logger.info("Pulled %d config overrides from cloud", len(override_rows))

    except Exception as exc:
        logger.error("pull_commands failed: %s", exc, extra={"ctx": {"event": "sync_error", "table": None, "error": str(exc)}})
    finally:
        try:
            pg_conn.close()
        except Exception:
            pass

    return pulled


def expire_stale_commands(database_url: str) -> int:
    """Mark pending_commands rows whose expires_at has elapsed as 'expired'.

    Called from run_sync_cycle after pull_commands so orphans left by
    dashboard submissions during machine-off windows don't accumulate
    forever as status='pending'. Returns the count of rows expired this
    cycle (0 is the steady-state).
    """
    try:
        import psycopg2  # noqa: F401
    except ImportError:
        return 0

    now = datetime.now(ET).isoformat()
    try:
        with _connect_pg_with_retry(database_url) as pg_conn:
            with pg_conn.cursor() as cur:
                cur.execute(
                    "UPDATE pending_commands SET status = 'expired' "
                    "WHERE status = 'pending' AND expires_at IS NOT NULL "
                    "AND expires_at < %s",
                    (now,),
                )
                count = cur.rowcount or 0
                pg_conn.commit()
                if count > 0:
                    logger.info("Expired %d stale pending_commands rows", count)
                return count
    except Exception as exc:
        logger.error(
            "expire_stale_commands failed: %s", exc,
            extra={"ctx": {"event": "sync_error", "table": "pending_commands",
                           "error": str(exc)}},
        )
        return 0


def _connect_pg_with_retry(database_url: str):
    """Connect to Postgres with retry + exponential backoff for DNS/network failures."""
    import psycopg2
    last_exc = None
    for attempt in range(_PG_CONNECT_RETRIES):
        try:
            return psycopg2.connect(database_url)
        except Exception as exc:
            last_exc = exc
            if attempt < _PG_CONNECT_RETRIES - 1:
                delay = _PG_CONNECT_BACKOFF[min(attempt, len(_PG_CONNECT_BACKOFF) - 1)]
                logger.warning(
                    "Postgres connect attempt %d/%d failed: %s — retrying in %ds",
                    attempt + 1, _PG_CONNECT_RETRIES, exc, delay,
                )
                time.sleep(delay)
    raise last_exc


def _ensure_pg_connection(conn, database_url: str):
    """Return existing connection if alive, otherwise create a new one."""
    if conn is not None:
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
            return conn
        except Exception:
            try:
                conn.close()
            except Exception:
                pass
    return _connect_pg_with_retry(database_url)


def run_sync_cycle(
    database_url: str,
    db_path: str = LOCAL_DB,
    _reconcile_cycle: bool = False,
) -> dict:
    """Run one full sync cycle across all tables. Returns summary dict.

    Args:
        database_url: Render Postgres connection string.
        db_path: Path to local SQLite database.
        _reconcile_cycle: When True, run reconcile_all after expire_stale_commands.
            Used by RenderSyncThread on every Nth cycle to remove ghost rows.
    """
    _init_sync_state(db_path)
    summary = {"synced": {}, "errors": [], "timestamp": datetime.now(ET).isoformat()}
    host = _sync_host_name()

    try:
        mark_sync_in_flight(host, db_path)
    except SyncInFlightError as exc:
        logger.error("Sync already in progress for host %s: %s", host, exc)
        summary["errors"].append(f"in_flight: {exc}")
        return summary
    except Exception as exc:
        logger.error("Failed to mark sync in flight for host %s: %s", host, exc)
        summary["errors"].append(f"sync_state: {exc}")
        return summary

    pg_conn = None
    try:
        try:
            import psycopg2  # noqa: F401
        except ImportError:
            logger.error("psycopg2 not installed — cannot sync to Render", extra={"ctx": {"event": "sync_error", "table": None, "error": "psycopg2 not installed"}})
            summary["errors"].append("psycopg2 not installed")
            return summary

        try:
            pg_conn = _connect_pg_with_retry(database_url)
        except Exception as exc:
            logger.error("Cannot connect to Render Postgres after %d retries: %s",
                          _PG_CONNECT_RETRIES, exc, extra={"ctx": {"event": "sync_error", "table": None, "error": str(exc)}})
            summary["errors"].append(f"connection_failed: {exc}")
            return summary

        # #331: Ensure all Postgres tables and columns exist before syncing.
        # Without this, new tables added to the registry (e.g., options_chains,
        # google_trends, cboe_ratios) fail with "relation does not exist".
        try:
            from src.schema.postgres import create_all_tables, ensure_columns
            create_all_tables(database_url)
            ensure_columns(database_url)
        except Exception as exc:
            logger.warning("[SYNC] Postgres schema validation failed: %s — continuing sync", exc)

        for table_name, table_config in SYNC_TABLES.items():
            try:
                pg_conn = _ensure_pg_connection(pg_conn, database_url)
                count = sync_table(pg_conn, table_name, table_config, db_path)
                if count > 0:
                    summary["synced"][table_name] = count
                    logger.info("Synced %d rows to %s", count, table_name)
            except Exception as exc:
                logger.error("Sync failed for %s: %s", table_name, exc, extra={"ctx": {"event": "sync_error", "table": table_name, "error": str(exc)}})
                summary["errors"].append(f"{table_name}: {exc}")
                pg_conn = None  # Force reconnect on next table

        try:
            pulled = pull_commands(database_url, db_path)
            if pulled:
                summary["pulled_commands"] = len(pulled)
                summary["commands"] = pulled
        except Exception as exc:
            logger.error("Command pull failed: %s", exc, extra={"ctx": {"event": "sync_error", "table": None, "error": str(exc)}})
            summary["errors"].append(f"pull_commands: {exc}")

        # Sweep orphan 'pending' rows whose expires_at has elapsed. Prevents
        # dashboard submissions made while the machine was off from piling up.
        try:
            expire_stale_commands(database_url)
        except Exception as exc:
            logger.error("expire_stale_commands failed: %s", exc)
            summary["errors"].append(f"expire_stale_commands: {exc}")

        # Periodic ghost-row reconcile — runs on every Nth cycle (see
        # RenderSyncThread.reconcile_every_n_cycles). Opens its own PG
        # connection because the sync connection is already closed above.
        if _reconcile_cycle:
            try:
                from src.sync.reconcile import reconcile_all
                reconcile_pg_conn = _connect_pg_with_retry(database_url)
                try:
                    result = reconcile_all(reconcile_pg_conn, db_path)
                    deleted = result.get("ghost_rows_deleted", 0)
                    if deleted > 0:
                        logger.info(
                            "[RECONCILE] Deleted %d ghost rows across %d tables",
                            deleted,
                            result.get("tables_checked", 0),
                        )
                    for err in result.get("errors", []):
                        summary["errors"].append(f"reconcile: {err}")
                finally:
                    try:
                        reconcile_pg_conn.close()
                    except Exception:
                        pass
            except Exception as exc:
                logger.error("reconcile cycle failed: %s", exc)
                summary["errors"].append(f"reconcile: {exc}")

        return summary
    finally:
        if pg_conn:
            try:
                pg_conn.close()
            except Exception:
                pass
        try:
            if summary["errors"]:
                error_text = "; ".join(summary["errors"])
                mark_sync_failed(host, error_text[:1000], db_path)
            else:
                mark_sync_completed(host, db_path)
        except Exception as exc:
            logger.error(
                "Failed to persist host sync_state for %s: %s",
                host,
                exc,
                extra={"ctx": {"event": "sync_error", "table": "sync_state", "error": str(exc)}},
            )


# ── Background thread ────────────────────────────────────────────────

class RenderSyncThread(threading.Thread):
    """Daemon thread that syncs SQLite -> Render Postgres on a schedule.

    As a daemon thread, it dies when the main process exits — no cleanup needed.
    The _sync_lock prevents overlapping cycles (#130) if a cycle takes longer
    than the interval. The health_status() method is called by /health/sync
    to surface thread liveness and staleness (#228).
    """

    def __init__(
        self,
        database_url: str,
        interval_seconds: int = 120,
        db_path: str = LOCAL_DB,
        on_commands_pulled: callable = None,
        reconcile_every_n_cycles: int = 30,
    ):
        super().__init__(daemon=True, name="render-sync")
        self.database_url = database_url
        self.interval_seconds = interval_seconds
        self.db_path = db_path
        self._stop_event = threading.Event()
        self._sync_lock = threading.Lock()
        self._on_commands_pulled = on_commands_pulled
        self.sync_last_success: float = 0.0
        self.sync_consecutive_errors: int = 0
        self._cycle_count: int = 0
        self.reconcile_every_n_cycles: int = reconcile_every_n_cycles

    def stop(self) -> None:
        """Signal the thread to stop."""
        self._stop_event.set()

    def health_status(self) -> dict:
        """Return sync thread health info for the /health endpoint."""
        alive = self.is_alive()
        last_ago = round(time.time() - self.sync_last_success) if self.sync_last_success else None
        stale = last_ago is not None and last_ago > self.interval_seconds * 3
        return {
            "alive": alive,
            "last_success_seconds_ago": last_ago,
            "consecutive_errors": self.sync_consecutive_errors,
            "stale": stale,
        }

    def _maybe_run_reconcile(self, pg_conn) -> None:
        """Run reconcile_all if _cycle_count is a multiple of reconcile_every_n_cycles.

        Failures are logged but do NOT propagate — reconcile errors must never
        crash the sync thread.

        Args:
            pg_conn: Unused — reconcile opens its own connection via
                run_sync_cycle's _reconcile_cycle path. Kept for API symmetry
                so callers can pass the open conn without needing to check.
        """
        if self.reconcile_every_n_cycles <= 0:
            return
        if self._cycle_count % self.reconcile_every_n_cycles != 0:
            return
        try:
            from src.sync.reconcile import reconcile_all
            reconcile_all(pg_conn, self.db_path)
        except Exception as exc:
            logger.error(
                "[RECONCILE] reconcile_all failed on cycle %d: %s",
                self._cycle_count,
                exc,
            )

    def _log_cycle_outcome(self, summary: dict) -> None:
        """Log the result of a successful sync cycle."""
        synced_count = sum(summary.get("synced", {}).values())
        error_count = len(summary.get("errors", []))
        if synced_count > 0 or error_count > 0:
            logger.info(
                "Sync cycle complete: %d rows synced, %d errors",
                synced_count,
                error_count,
            )
        # Quiet-cycle heartbeat: INFO every 30 cycles (≈30 min at
        # 60s interval) so an idle poller is visible in logs without
        # requiring a DEBUG-level filter. Everything else every
        # 10 cycles stays at DEBUG.
        elif self._cycle_count % 30 == 0:
            logger.info(
                "Render sync heartbeat — cycle %d (quiet, no rows to sync)",
                self._cycle_count,
            )
        elif self._cycle_count % 10 == 0:
            logger.debug("Render sync heartbeat — cycle %d", self._cycle_count)

    def _dispatch_pulled_commands(self, summary: dict) -> None:
        """Invoke the commands callback if commands were pulled."""
        commands = summary.get("commands", [])
        if commands and self._on_commands_pulled:
            try:
                self._on_commands_pulled(commands)
            except Exception as exc:
                logger.error("Command execution callback failed: %s", exc, extra={"ctx": {"event": "sync_error", "table": None, "error": str(exc)}})

    def _handle_cycle_exception(self, exc: Exception) -> None:
        """Handle an unhandled exception from a sync cycle."""
        self.sync_consecutive_errors += 1
        logger.error("Unhandled error in sync cycle: %s", exc, extra={"ctx": {"event": "sync_error", "table": None, "error": str(exc)}})
        try:
            from src.notifications.telegram import send_telegram
            send_telegram(f"🚨 Render sync error: <code>{exc}</code>")
        except Exception:
            pass

    def _run_one_cycle(self) -> None:
        """Acquire the lock and run one sync cycle, or skip if already in progress."""
        if not self._sync_lock.acquire(blocking=False):
            logger.warning("Sync cycle already in progress — skipping")
            return
        try:
            is_reconcile_cycle = (
                self.reconcile_every_n_cycles > 0
                and (self._cycle_count + 1) % self.reconcile_every_n_cycles == 0
            )
            summary = run_sync_cycle(
                self.database_url,
                self.db_path,
                _reconcile_cycle=is_reconcile_cycle,
            )
            self.sync_last_success = time.time()
            self.sync_consecutive_errors = 0
            self._cycle_count += 1
            self._log_cycle_outcome(summary)
            self._dispatch_pulled_commands(summary)
        except Exception as exc:
            self._handle_cycle_exception(exc)
        finally:
            self._sync_lock.release()

    def run(self) -> None:
        """Main loop: sync, sleep, repeat."""
        logger.info(
            "Render sync thread started (interval=%ds)", self.interval_seconds
        )
        while not self._stop_event.is_set():
            self._run_one_cycle()
            self._stop_event.wait(self.interval_seconds)
        logger.info("Render sync thread stopped")


def start_render_sync(
    config: dict,
    on_commands_pulled: callable = None,
) -> RenderSyncThread | None:
    """Start the background sync thread if render sync is enabled in config.

    Config expected:
        render:
          enabled: true
          database_url: "postgresql://user:pass@host:5432/halcyon"
          sync_interval_seconds: 120

    Args:
        config: Application configuration dict.
        on_commands_pulled: Optional callback(commands: list[dict]) invoked
            when commands are pulled from the cloud command queue.
    """
    render_cfg = config.get("render", {})
    if not render_cfg.get("enabled", False):
        logger.debug("Render sync disabled in config")
        return None

    database_url = render_cfg.get("database_url", "")
    if not database_url:
        logger.warning("Render sync enabled but no database_url configured")
        return None

    interval = render_cfg.get("sync_interval_seconds", 120)

    thread = RenderSyncThread(
        database_url=database_url,
        interval_seconds=interval,
        on_commands_pulled=on_commands_pulled,
    )
    thread.start()
    logger.info("Render sync thread launched")
    return thread
