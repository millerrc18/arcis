"""Background sync thread that pushes local SQLite data to Render Postgres.

Called by: api.cloud_app, scheduler.watch
Calls: none
Owns tables: sync_state
Config keys: database_url, enabled, mode, pk, render, sync_interval_seconds, time_col
Tests: tests/test_data_collectors.py, tests/test_render_sync.py

Runs every sync_interval_seconds (default 120s) as a daemon thread.
Tracks last_synced_at per table in a local sync_state SQLite table.
Handles failures gracefully -- log and retry next cycle, never crash.
Per-table Postgres reconnection: if the connection dies mid-cycle,
each table attempts reconnect (3 retries with 2/5/10s backoff) independently.
"""

import json
import logging
import sqlite3
import threading
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from src.config import DB_PATH

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
# NOTE: pending_commands and config_overrides are PULLED from cloud, not pushed
# (handled by pull_commands() in the sync cycle)


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


def _init_sync_state(db_path: str = LOCAL_DB) -> None:
    """Ensure the sync_state table exists (from schema registry)."""
    try:
        with _sqlite_conn(db_path) as conn:
            conn.executescript(_generate_create_sql(_REGISTRY_TABLES["sync_state"]))
    except Exception as exc:
        logger.error("Failed to init sync_state table: %s", exc)


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
        logger.error("Failed to read sync_state for %s: %s", table_name, exc)
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
            logger.error("Failed to update sync_state for %s: %s", table_name, exc)
        except Exception as exc:
            logger.error("Failed to update sync_state for %s: %s", table_name, exc)
            return


# ── Core sync logic ─────────────────────────────────────────────────

def _fetch_incremental_rows(
    table_name: str,
    time_col: str,
    since: str | None,
    db_path: str = LOCAL_DB,
) -> tuple[list[dict], list[str]]:
    """Fetch rows from SQLite where time_col > since. Returns (rows, columns)."""
    try:
        with sqlite3.connect(db_path) as conn:
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
        with sqlite3.connect(db_path) as conn:
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
        with sqlite3.connect(db_path) as conn:
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
        with sqlite3.connect(db_path) as conn:
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
) -> int:
    """Upsert rows into Postgres using ON CONFLICT. Returns count of upserted rows.

    Args:
        conflict_col: Override the ON CONFLICT target (e.g., for tables with
            UNIQUE constraints that differ from the PK, like edgar_filings
            which has a UNIQUE accession_number).
    """
    if not rows or not columns:
        return 0

    conflict_target = conflict_col or pk
    col_list = ", ".join(columns)
    placeholders = ", ".join(["%s"] * len(columns))
    update_set = ", ".join(
        f"{col} = EXCLUDED.{col}" for col in columns if col != conflict_target
    )

    sql = (
        f"INSERT INTO {table_name} ({col_list}) VALUES ({placeholders}) "
        f"ON CONFLICT ({conflict_target}) DO UPDATE SET {update_set}"
    )

    count = 0
    cursor = pg_conn.cursor()
    try:
        for row in rows:
            values = [row.get(col) for col in columns]
            cursor.execute(sql, values)
            count += 1
        pg_conn.commit()
    except Exception as exc:
        pg_conn.rollback()
        logger.error("Postgres upsert failed for %s: %s", table_name, exc)
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
    """For latest-only tables: delete old data for the date, insert fresh."""
    if not rows or not columns:
        return 0

    latest_date = rows[0].get(time_col)
    if not latest_date:
        return 0

    cursor = pg_conn.cursor()
    try:
        cursor.execute(
            f"DELETE FROM {table_name} WHERE {time_col} = %s",
            (latest_date,),
        )

        col_list = ", ".join(columns)
        placeholders = ", ".join(["%s"] * len(columns))
        sql = f"INSERT INTO {table_name} ({col_list}) VALUES ({placeholders})"

        for row in rows:
            values = [row.get(col) for col in columns]
            cursor.execute(sql, values)

        pg_conn.commit()
        return len(rows)
    except Exception as exc:
        pg_conn.rollback()
        logger.error("Postgres replace failed for %s: %s", table_name, exc)
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
        return _upsert_to_postgres(pg_conn, table_name, pk, columns, rows, conflict_col)

    if mode == "incremental":
        since = get_last_synced_at(table_name, db_path)
        rows, columns = _fetch_incremental_rows(table_name, time_col, since, db_path)
        if not rows:
            return 0
        count = _upsert_to_postgres(pg_conn, table_name, pk, columns, rows, conflict_col)
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
        return _upsert_to_postgres(pg_conn, table_name, pk, columns, rows, conflict_col)

    raise ValueError(f"Unknown sync mode for {table_name}: {mode}")


def pull_commands(database_url: str, db_path: str = LOCAL_DB) -> list[dict]:
    """Pull pending commands from Render Postgres into local SQLite.

    1. Read pending_commands WHERE status='pending' AND expires_at > NOW()
    2. Insert into local SQLite
    3. Update Postgres status to 'claimed' with claimed_at
    4. Also pull config_overrides (full table replace)
    5. Return list of pulled commands for immediate execution
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
        logger.error("pull_commands: cannot connect to Postgres: %s", exc)
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
            local_conn = sqlite3.connect(db_path)
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
                    logger.error("pull_commands: local insert failed: %s", exc)
            local_conn.commit()
            local_conn.close()

            # Update Postgres status to 'claimed'
            command_ids = [r["command_id"] for r in rows]
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
            local_conn = sqlite3.connect(db_path)
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
        logger.error("pull_commands failed: %s", exc)
    finally:
        try:
            pg_conn.close()
        except Exception:
            pass

    return pulled


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


def run_sync_cycle(database_url: str, db_path: str = LOCAL_DB) -> dict:
    """Run one full sync cycle across all tables. Returns summary dict."""
    try:
        import psycopg2  # noqa: F401
    except ImportError:
        logger.error("psycopg2 not installed — cannot sync to Render")
        return {"synced": {}, "errors": ["psycopg2 not installed"],
                "timestamp": datetime.now(ET).isoformat()}

    _init_sync_state(db_path)
    summary = {"synced": {}, "errors": [], "timestamp": datetime.now(ET).isoformat()}

    pg_conn = None
    try:
        pg_conn = _connect_pg_with_retry(database_url)
    except Exception as exc:
        logger.error("Cannot connect to Render Postgres after %d retries: %s",
                      _PG_CONNECT_RETRIES, exc)
        summary["errors"].append(f"connection_failed: {exc}")
        return summary

    try:
        for table_name, table_config in SYNC_TABLES.items():
            try:
                pg_conn = _ensure_pg_connection(pg_conn, database_url)
                count = sync_table(pg_conn, table_name, table_config, db_path)
                if count > 0:
                    summary["synced"][table_name] = count
                    logger.info("Synced %d rows to %s", count, table_name)
            except Exception as exc:
                logger.error("Sync failed for %s: %s", table_name, exc)
                summary["errors"].append(f"{table_name}: {exc}")
                pg_conn = None  # Force reconnect on next table
    finally:
        if pg_conn:
            try:
                pg_conn.close()
            except Exception:
                pass

    # Pull commands from cloud (bidirectional)
    try:
        pulled = pull_commands(database_url, db_path)
        if pulled:
            summary["pulled_commands"] = len(pulled)
            summary["commands"] = pulled
    except Exception as exc:
        logger.error("Command pull failed: %s", exc)
        summary["errors"].append(f"pull_commands: {exc}")

    return summary


# ── Background thread ────────────────────────────────────────────────

class RenderSyncThread(threading.Thread):
    """Daemon thread that syncs SQLite -> Render Postgres on a schedule."""

    def __init__(
        self,
        database_url: str,
        interval_seconds: int = 120,
        db_path: str = LOCAL_DB,
        on_commands_pulled: callable = None,
    ):
        super().__init__(daemon=True, name="render-sync")
        self.database_url = database_url
        self.interval_seconds = interval_seconds
        self.db_path = db_path
        self._stop_event = threading.Event()
        self._sync_lock = threading.Lock()
        self._on_commands_pulled = on_commands_pulled
        self.sync_last_success: float = 0.0

    def stop(self) -> None:
        """Signal the thread to stop."""
        self._stop_event.set()

    def run(self) -> None:
        """Main loop: sync, sleep, repeat."""
        logger.info(
            "Render sync thread started (interval=%ds)", self.interval_seconds
        )
        while not self._stop_event.is_set():
            if not self._sync_lock.acquire(blocking=False):
                logger.warning("Sync cycle already in progress — skipping")
                self._stop_event.wait(self.interval_seconds)
                continue
            try:
                summary = run_sync_cycle(self.database_url, self.db_path)
                self.sync_last_success = time.time()
                synced_count = sum(summary.get("synced", {}).values())
                error_count = len(summary.get("errors", []))
                if synced_count > 0 or error_count > 0:
                    logger.info(
                        "Sync cycle complete: %d rows synced, %d errors",
                        synced_count,
                        error_count,
                    )
                # Execute pulled commands via callback
                commands = summary.get("commands", [])
                if commands and self._on_commands_pulled:
                    try:
                        self._on_commands_pulled(commands)
                    except Exception as exc:
                        logger.error("Command execution callback failed: %s", exc)
            except Exception as exc:
                logger.error("Unhandled error in sync cycle: %s", exc)
                try:
                    from src.notifications.telegram import send_telegram
                    send_telegram(f"🚨 Render sync error: <code>{exc}</code>")
                except Exception:
                    pass
            finally:
                self._sync_lock.release()

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
