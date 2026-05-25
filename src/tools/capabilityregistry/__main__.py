"""CLI entry point for the CapabilityRegistryQuery tool — python -m src.tools.capabilityregistry.

Called by: operator agents, test subprocesses (pytest subprocess cases g, h)
Calls: src.tools.capabilityregistry.core.tables, src.tools.capabilityregistry.core.table,
       src.tools._cli_envelope.run_cli
Owns tables: none
Config keys: none
Tests: tests/tools/test_capabilityregistry_integration.py (subprocess cases g, h)
"""

from __future__ import annotations

import argparse
import json as json_mod

from src.tools._cli_envelope import run_cli
from src.tools.capabilityregistry.core import table, tables


def _render_single_table_markdown(tdef: dict) -> str:
    """Render a single TableDef dict as markdown (spec §3.4)."""
    lines = []
    lines.append(f"# Table: {tdef['name']}")
    lines.append(tdef["description"])
    lines.append("")
    cols = tdef["columns"]
    lines.append(f"## Columns ({len(cols)})")
    lines.append("| Name | Type | Null | Default | Note |")
    lines.append("|------|------|------|---------|------|")
    for col in cols:
        null = "NO" if not col["nullable"] else "YES"
        default = "(auto)" if col.get("autoincrement") else (col["default"] or "")
        note = col.get("description", "")
        lines.append(f"| {col['name']} | {col['type']} | {null} | {default} | {note} |")
    lines.append("")
    pk = tdef["primary_key"]
    pk_str = ", ".join(pk) if isinstance(pk, list) else pk
    lines.append(f"## Primary Key: {pk_str}")
    if tdef["sync_to_postgres"]:
        lines.append(
            f"## Sync: sync_to_postgres={tdef['sync_to_postgres']}, "
            f"mode={tdef['sync_mode']}, "
            f"time_column={tdef['sync_time_column']}"
        )
    return "\n".join(lines)


def _render_all_tables_markdown(result: dict) -> str:
    """Render all tables as a summary markdown table (spec §3.4)."""
    sync_count = sum(1 for t in result.values() if t["sync_to_postgres"])
    lines = []
    lines.append(f"# Capability Registry ({len(result)} tables, {sync_count} sync'd)")
    lines.append("| Name | Description | Columns | Sync |")
    lines.append("|------|-------------|---------|------|")
    for tname, tdef in result.items():
        desc = tdef["description"]
        ncols = len(tdef["columns"])
        sync = f"True ({tdef['sync_mode']})" if tdef["sync_to_postgres"] else "False"
        lines.append(f"| {tname} | {desc} | {ncols} | {sync} |")
    return "\n".join(lines)


def _run(*, table: str | None, sync_only: bool, json: bool) -> str:
    """Dispatch to tables() or table(name) and return formatted string.

    Called by run_cli(**vars(args_namespace)). Raises CapabilityRegistryError
    on failure — run_cli handles the JSON envelope.
    """
    if table is not None:
        from src.tools.capabilityregistry.core import table as _table_fn
        result = _table_fn(table)
        if json:
            return json_mod.dumps(result)
        return _render_single_table_markdown(result)
    else:
        from src.tools.capabilityregistry.core import tables as _tables_fn
        result = _tables_fn(sync_only=sync_only)
        if json:
            return json_mod.dumps(result)
        return _render_all_tables_markdown(result)


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="python -m src.tools.capabilityregistry",
        description="Read-only inspection of the Arcis schema registry (TABLES).",
    )
    parser.add_argument(
        "--table",
        default=None,
        metavar="NAME",
        help="Return a single table by name",
    )
    parser.add_argument(
        "--sync-only",
        action="store_true",
        dest="sync_only",
        help="Filter to tables where sync_to_postgres=True",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="json",
        help="Output JSON instead of markdown",
    )

    args = parser.parse_args()

    run_cli(
        tool_name="capabilityregistry",
        fn=_run,
        args_namespace=args,
        json_mode=args.json,
    )


if __name__ == "__main__":
    main()
