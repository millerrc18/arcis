"""Generate SYNC_TABLES config from the schema registry.

Called by: src.api.cloud_app, src.startup_checks (post one-DB cutover —
    render_sync.py was deleted in SP5 §J5/§J6 Phase 3-revised)
Calls: src.schema.registry
Owns tables: none
Config keys: none
Tests: tests/test_schema.py, tests/test_sync_config.py
"""

from collections import deque

from src.schema.registry import TABLES


class SyncConfigError(Exception):
    """Raised when sync configuration is invalid (e.g. FK cycle detected)."""


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
    sync_tables = {
        name: table for name, table in TABLES.items() if table.sync_to_postgres
    }
    for name in _topo_sort_tables(sync_tables):
        table = sync_tables[name]
        entry: dict = {"mode": table.sync_mode, "sync_reconcile": table.sync_reconcile}
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


def _topo_sort_tables(tables: dict) -> list[str]:
    """Return table names in FK-safe dependency order (parents before children).

    Uses Kahn's BFS algorithm; ties broken alphabetically for determinism.
    FK references to names NOT in ``tables`` are silently ignored (external).
    Raises SyncConfigError naming the offending tables if a cycle is detected.
    """
    names = set(tables.keys())

    # Build adjacency list: parent -> set of children that depend on it.
    # Also track in-degree for each node.
    children: dict[str, set[str]] = {n: set() for n in names}
    in_degree: dict[str, int] = {n: 0 for n in names}

    for child_name, table_def in tables.items():
        seen_parents: set[str] = set()
        registry_def = TABLES.get(child_name)
        fk_source = getattr(table_def, "foreign_keys", None)
        if fk_source is None and registry_def is not None:
            fk_source = registry_def.foreign_keys
        if not fk_source:
            continue
        for fk in fk_source:
            parent = fk.references_table
            if parent not in names or parent == child_name or parent in seen_parents:
                continue
            seen_parents.add(parent)
            children[parent].add(child_name)
            in_degree[child_name] += 1

    # Kahn's algorithm: initialise queue with zero-in-degree nodes, sorted
    # alphabetically for a stable, deterministic tie-break.
    queue: deque[str] = deque(sorted(n for n in names if in_degree[n] == 0))
    result: list[str] = []

    while queue:
        node = queue.popleft()
        result.append(node)
        for child in sorted(children[node]):
            in_degree[child] -= 1
            if in_degree[child] == 0:
                queue.append(child)

    if len(result) != len(names):
        cycle_tables = sorted(n for n in names if n not in set(result))
        raise SyncConfigError(
            f"FK cycle detected among tables: {', '.join(cycle_tables)}"
        )

    return result
