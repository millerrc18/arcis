"""Generate SYNC_TABLES config from the schema registry.

Called by: src.sync.render_sync
Calls: src.schema.registry
Owns tables: none
Config keys: none
Tests: tests/test_schema.py
"""

from src.schema.registry import TABLES


def generate_sync_tables() -> dict[str, dict]:
    """Generate SYNC_TABLES config.

    Only includes tables where sync_to_postgres=True.
    """
    config = {}
    for name, table in TABLES.items():
        if not table.sync_to_postgres:
            continue
        entry: dict = {"mode": table.sync_mode}
        pk = table.sync_pk or (
            table.primary_key
            if isinstance(table.primary_key, str)
            else table.primary_key[0]
        )
        entry["pk"] = pk
        if table.sync_mode in ("incremental", "latest_only") and table.sync_time_column:
            entry["time_col"] = table.sync_time_column
        if table.sync_conflict_col:
            entry["conflict_col"] = table.sync_conflict_col
        config[name] = entry
    return config
