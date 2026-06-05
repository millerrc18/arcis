"""Derived system-map service for the Founder Console KNOW region (§KNOW).

Produces the architecture/capability/schema SUMMARY the KNOW overview needs,
derived ENTIRELY from machine-readable registries (design law #7
derive-from-source). There are NO hand-typed component lists or counts here:
capability counts come from the capability registry's listing functions and
schema table/column counts come from ``src.schema.registry.TABLES``.

This is a thin SUMMARY producer. The full drill-down payload stays at
GET /api/system/index (src.api.cloud_routes.system_index); this module does
NOT duplicate it.

Fail-closed, per section (mirrors the honest-degradation idiom in
src.api.cloud_routes.system_index): if a registry fails to load, that section
reports ``{"state": "unknown", "error": ...}`` and the top-level
``generation_ok`` flips to False. A failed section NEVER substitutes a stale or
typed fallback. A ``source_sha`` lookup failure is a soft degrade to VERSION,
not a generation failure.

Envelope shape (frozen — P3-T3 returns it verbatim; the frontend consumes it):

    {
      "capabilities": {
        "by_category": {<category>: int},
        "total": int,
        "actions": int,
        "states": int,
        "systems": int,
        "decisions": int,
        "state": "ok" | "unknown",
        # "error": str   (present only when state == "unknown")
      },
      "schema": {
        "tables": [{"name": str, "column_count": int}],
        "table_count": int,
        "state": "ok" | "unknown",
        # "error": str   (present only when state == "unknown")
      },
      "generation_ok": bool,
      "source_sha": str,
      "as_of": str,   # ISO-8601 UTC
    }

Capability sub-count shape chosen: the four registry kinds
(actions/states/systems/decisions) plus a ``by_category`` rollup, with
``total == actions + states + systems + decisions == sum(by_category.values())``.

Called by: src.api.cloud_routes (P3-T3 route — wires this into KNOW)
Calls: src.platform.capability_registry (bootstrap + listing fns),
       src.schema.registry.TABLES, src.version.VERSION
Owns tables: none
Config keys: none
Tests: tests/test_system_map.py
"""
from __future__ import annotations

import logging
import subprocess
from datetime import datetime, timezone
from typing import Any

from src.platform.capability_registry import (
    ensure_bootstrapped,
    list_actions,
    list_decisions,
    list_states,
    list_systems,
)
from src import schema as _schema_pkg  # noqa: F401 — ensures src.schema is importable
import src.schema.registry as schema_registry
from src.version import VERSION

logger = logging.getLogger(__name__)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _derive_capabilities() -> dict[str, Any]:
    """Summarize the capability registry by kind + category.

    Derived live from the registry listing functions (design law #7). On any
    failure the section fails closed: state='unknown' + error, no counts.
    """
    try:
        ensure_bootstrapped()
        actions = list_actions()
        states = list_states()
        systems = list_systems()
        decisions = list_decisions()
        by_category: dict[str, int] = {}
        for entry in [*actions, *states, *systems, *decisions]:
            by_category[entry.category] = by_category.get(entry.category, 0) + 1
        return {
            "by_category": by_category,
            "total": len(actions) + len(states) + len(systems) + len(decisions),
            "actions": len(actions),
            "states": len(states),
            "systems": len(systems),
            "decisions": len(decisions),
            "state": "ok",
        }
    except Exception as exc:  # noqa: BLE001 — fail-closed per section, never fabricate
        logger.warning("[SYSTEM_MAP] capability derivation failed: %r", exc)
        return {"state": "unknown", "error": str(exc)}


def _derive_schema() -> dict[str, Any]:
    """Enumerate the schema registry's tables (name + column count).

    Derived live from src.schema.registry.TABLES (design law #7); table names
    and column counts are never typed. On any failure the section fails closed.
    """
    try:
        tables = [
            {"name": table.name, "column_count": len(table.columns)}
            for table in schema_registry.TABLES.values()
        ]
        return {
            "tables": tables,
            "table_count": len(tables),
            "state": "ok",
        }
    except Exception as exc:  # noqa: BLE001 — fail-closed per section, never fabricate
        logger.warning("[SYSTEM_MAP] schema derivation failed: %r", exc)
        return {"state": "unknown", "error": str(exc)}


def _derive_source_sha() -> str:
    """Short commit SHA via ``git rev-parse``; fall back to VERSION.

    A git failure is a soft degrade (returns VERSION), NOT a generation
    failure — the derived registry data is still authoritative.
    """
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            stderr=subprocess.DEVNULL,
        )
        sha = out.decode("utf-8", "replace").strip()
        if sha:
            return sha
    except Exception as exc:  # noqa: BLE001 — soft degrade to VERSION
        logger.warning("[SYSTEM_MAP] git rev-parse failed, using VERSION: %r", exc)
    return VERSION


def generate_system_map() -> dict[str, Any]:
    """Build the derived system-map summary (capabilities + schema + provenance).

    Every section is derived from a machine-readable registry. Sections fail
    closed independently: a section that cannot load reports state='unknown'
    and flips top-level ``generation_ok`` to False, without raising and without
    a stale/typed fallback.
    """
    capabilities = _derive_capabilities()
    schema = _derive_schema()
    generation_ok = capabilities["state"] == "ok" and schema["state"] == "ok"
    return {
        "capabilities": capabilities,
        "schema": schema,
        "generation_ok": generation_ok,
        "source_sha": _derive_source_sha(),
        "as_of": _utc_now_iso(),
    }
