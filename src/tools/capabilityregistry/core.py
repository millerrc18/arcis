"""CapabilityRegistryQuery v1 — read-only inspection of src.schema.registry.TABLES.

PERMITTED EXCEPTION (spec §2.2 / DD-13): this module imports TABLES directly from
src.schema.registry. This is the single authorised exception to the tool-layer's
zero-external-import rule. The registry is module-level frozen data (no DB, no
network, no runtime apparatus) — it is safe to import at any time. All other
src.schema.* and src.config.* imports are prohibited.

Called by: src/tools/capabilityregistry/__main__.py, operator agents, tests
Calls: src.tools._safety.safe_op, src.schema.registry.TABLES (PERMITTED)
Owns tables: none (read-only view of registry metadata)
Config keys: none
Tests: tests/tools/test_capabilityregistry_integration.py
"""

from __future__ import annotations

import dataclasses

from src.schema.registry import TABLES  # PERMITTED EXCEPTION per spec §2.2 — see module header
from src.tools._safety import safe_op


class CapabilityRegistryError(RuntimeError):
    """Base error for capabilityregistry tool."""


def _tables_impl(*, sync_only: bool = False) -> dict[str, dict]:
    """Core logic for tables() — exposed for test factory re-decoration."""
    items = TABLES.items()
    if sync_only:
        items = ((n, t) for n, t in items if t.sync_to_postgres)
    return {name: dataclasses.asdict(t) for name, t in items}


def _table_impl(name: str) -> dict:
    """Core logic for table() — exposed for test factory re-decoration."""
    if name not in TABLES:
        raise CapabilityRegistryError(
            f"Unknown table: {name!r}. {len(TABLES)} registered."
        )
    return dataclasses.asdict(TABLES[name])


@safe_op(name="capabilityregistry", mutates=False)
def tables(*, sync_only: bool = False) -> dict[str, dict]:
    """Return all tables as {name: asdict(TableDef)}. sync_only filters sync_to_postgres=True."""
    return _tables_impl(sync_only=sync_only)


@safe_op(name="capabilityregistry", mutates=False)
def table(name: str) -> dict:
    """Return single table as asdict(TableDef). Raises CapabilityRegistryError if name not registered."""
    return _table_impl(name)
