"""Regression-lock: schema-verify infinite loop on watch loop startup.

PR-#XYZ context: pre-fix, init_value_tables, init_council_tables,
init_training_tables, and initialize_database called create_all_tables
on EVERY function call (not memoized). During watch loop startup,
_print_banner() and _print_status_heartbeat() call versioning functions
which call init_training_tables, and CouncilEngine.__init__ calls
init_council_tables — none of them memoized. Each call emits a
[SCHEMA] Created/verified 68 tables log line, causing a tight loop
of 3-4 schema-verify emissions per second observed at 09:30:41 ET
on 2026-04-27.

The canonical schema verify is _ensure_all_tables() in watch.py,
called ONCE at startup. All per-module init_* helpers must be
memoized so they short-circuit after the first call.
"""

import logging
import sqlite3
import tempfile
import os


def test_schema_verify_fires_once_per_init_helper(caplog, tmp_path):
    """Regression-lock: each init_* helper must call create_all_tables at
    most once per process, not on every function call.

    Pre-fix: calling init_value_tables 5 times emits 5 [SCHEMA] log lines.
    Post-fix: calling init_value_tables 5 times emits exactly 1 [SCHEMA] log line.
    Same for init_council_tables, init_training_tables, initialize_database.
    """
    db_path = str(tmp_path / "test.sqlite3")
    caplog.set_level(logging.INFO, logger="src.schema.sqlite")

    from src.council import value_tracker
    from src.council import engine as council_engine
    from src.training import versioning
    from src.journal import store

    value_tracker._TABLES_INITIALIZED = set()
    council_engine._TABLES_INITIALIZED = set()
    versioning._TABLES_INITIALIZED = set()
    store._TABLES_INITIALIZED = set()

    value_tracker.init_value_tables(db_path)
    value_tracker.init_value_tables(db_path)
    value_tracker.init_value_tables(db_path)
    value_tracker.init_value_tables(db_path)
    value_tracker.init_value_tables(db_path)

    council_engine.init_council_tables(db_path)
    council_engine.init_council_tables(db_path)
    council_engine.init_council_tables(db_path)
    council_engine.init_council_tables(db_path)
    council_engine.init_council_tables(db_path)

    versioning.init_training_tables(db_path)
    versioning.init_training_tables(db_path)
    versioning.init_training_tables(db_path)
    versioning.init_training_tables(db_path)
    versioning.init_training_tables(db_path)

    store.initialize_database(db_path)
    store.initialize_database(db_path)
    store.initialize_database(db_path)
    store.initialize_database(db_path)
    store.initialize_database(db_path)

    schema_logs = [
        r for r in caplog.records
        if "Created/verified" in r.getMessage()
    ]
    assert len(schema_logs) <= 4, (
        f"Schema verify fired {len(schema_logs)} times across 4 init_* helpers "
        f"called 5 times each — should be <=4 (one per helper path, memoized). "
        f"Pre-fix: would fire 20 times (5 per helper). "
        f"This is the regression that caused 3-4/sec [SCHEMA] spam on 2026-04-27 startup. "
        f"Log messages seen: {[r.getMessage() for r in schema_logs]}"
    )
