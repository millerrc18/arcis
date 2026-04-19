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

    For composite primary keys (minute_bars, correlation_matrices,
    factor_loadings), emit the full comma-joined column list as
    `conflict_col` so Postgres ON CONFLICT matches the real composite
    unique constraint. Without this, the upsert targets only the first PK
    column and fails with "no unique or exclusion constraint matching the
    ON CONFLICT specification".
    """
    config = {}
    for name, table in TABLES.items():
        if not table.sync_to_postgres:
            continue
        entry: dict = {"mode": table.sync_mode}
        is_composite = (
            isinstance(table.primary_key, list) and len(table.primary_key) > 1
        )
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
        elif is_composite:
            entry["conflict_col"] = ", ".join(table.primary_key)
        config[name] = entry
    return config
