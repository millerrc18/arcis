# Purpose: Integration tests for src/tools/capabilityregistry — pure registry read.
# Called by: pytest tests/tools/test_capabilityregistry_integration.py
# Calls: src.tools.capabilityregistry.tables, src.tools.capabilityregistry.table
# Owns tables: none (no DB — registry is module-level frozen data)
# Config keys: none
# Tests: (this file is the test)

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from src.schema.registry import TABLES as _REAL_TABLES

# ---------------------------------------------------------------------------
# Factory helpers — re-decorate with test-isolated log_path
# (mirrors _build_query pattern from test_dbquery_integration.py)
# ---------------------------------------------------------------------------


def _build_tables_fn(log_path: Path):
    """Return a tables() function decorated with test-isolated log_path."""
    from src.tools._safety import safe_op
    from src.tools.capabilityregistry.core import _tables_impl

    @safe_op(name="capabilityregistry", mutates=False, log_path=log_path)
    def _tables(*, sync_only: bool = False) -> dict[str, dict]:
        return _tables_impl(sync_only=sync_only)

    return _tables


def _build_table_fn(log_path: Path):
    """Return a table() function decorated with test-isolated log_path."""
    from src.tools._safety import safe_op
    from src.tools.capabilityregistry.core import _table_impl

    @safe_op(name="capabilityregistry", mutates=False, log_path=log_path)
    def _table(name: str) -> dict:
        return _table_impl(name)

    return _table


# ---------------------------------------------------------------------------
# (a) tables() count + 11-key contract
# ---------------------------------------------------------------------------

_EXPECTED_KEYS = frozenset({
    "name",
    "description",
    "columns",
    "primary_key",
    "indexes",
    "foreign_keys",
    "sync_to_postgres",
    "sync_mode",
    "sync_time_column",
    "sync_pk",
    "sync_conflict_col",
    "sync_reconcile",
})

_EXPECTED_COLUMN_KEYS = frozenset({"name", "type", "nullable", "default", "description", "autoincrement"})


def test_tables_count_and_keys(tmp_path):
    """(a) tables() returns 80 entries each with the 11-key output shape + success event logged."""
    log = tmp_path / "tool-execution.log"
    _tables = _build_tables_fn(log)
    result = _tables()
    assert len(result) == 80
    for tname, tdef in result.items():
        assert set(tdef.keys()) == _EXPECTED_KEYS, (
            f"Missing/extra keys in {tname}: {set(tdef.keys()) ^ _EXPECTED_KEYS}"
        )
    # success event recorded
    assert log.exists()
    content = log.read_text(encoding="utf-8")
    assert "success" in content


# ---------------------------------------------------------------------------
# (b) tables(sync_only=True) — filter works
# ---------------------------------------------------------------------------


def test_tables_sync_only(tmp_path):
    """(b) sync_only=True returns only tables with sync_to_postgres=True."""
    log = tmp_path / "tool-execution.log"
    _tables = _build_tables_fn(log)
    result = _tables(sync_only=True)
    assert len(result) > 0
    for tname, tdef in result.items():
        assert tdef["sync_to_postgres"] is True, (
            f"{tname} has sync_to_postgres=False in sync_only result"
        )
    total = _tables()
    # sync_only count must be <= total (all 80 sync in this registry)
    assert len(result) <= len(total)


# ---------------------------------------------------------------------------
# (c) table('shadow_trades') — single table lookup
# ---------------------------------------------------------------------------


def test_table_shadow_trades(tmp_path):
    """(c) table('shadow_trades') returns correct single-table dict + success event logged."""
    log = tmp_path / "tool-execution.log"
    _table = _build_table_fn(log)
    result = _table("shadow_trades")
    assert result["name"] == "shadow_trades"
    assert isinstance(result["columns"], list)
    assert len(result["columns"]) > 0
    # success event recorded
    assert log.exists()
    content = log.read_text(encoding="utf-8")
    assert "success" in content


# ---------------------------------------------------------------------------
# (d) table('does_not_exist_xyz') — raises CapabilityRegistryError
# ---------------------------------------------------------------------------


def test_table_unknown_raises(tmp_path):
    """(d) table() on unknown name raises CapabilityRegistryError with count in message."""
    from src.tools.capabilityregistry import CapabilityRegistryError

    log = tmp_path / "tool-execution.log"
    _table = _build_table_fn(log)
    with pytest.raises(CapabilityRegistryError) as exc_info:
        _table("does_not_exist_xyz")
    msg = str(exc_info.value)
    assert "does_not_exist_xyz" in msg
    assert "80" in msg
    # error event recorded
    assert log.exists()
    content = log.read_text(encoding="utf-8")
    assert "error" in content


# ---------------------------------------------------------------------------
# (e) JSON-serializable output
# ---------------------------------------------------------------------------


def test_tables_json_serializable():
    """(e) tables() output is JSON-serializable via json.dumps.

    Verify-by-mutation: replacing dataclasses.asdict(t) with t.__dict__ would
    leave nested ColumnDef objects that fail json.dumps — this test would fail.
    """
    from src.tools.capabilityregistry import tables as _tables
    result = _tables()
    serialized = json.dumps(result)
    parsed = json.loads(serialized)
    assert len(parsed) == 80


# ---------------------------------------------------------------------------
# (f) composite primary_key — at least one table has list-typed PK
# ---------------------------------------------------------------------------


def test_composite_primary_key_exists():
    """(f) At least one table in TABLES has a list-typed primary_key (composite PK).

    If NONE do, skip with pytest.skip rather than fail — this tests support
    for both str and list[str] forms in the output contract.
    """
    from src.tools.capabilityregistry import tables as _tables

    composite_tables = [
        name for name, tdef in _REAL_TABLES.items()
        if isinstance(tdef.primary_key, list)
    ]
    if not composite_tables:
        pytest.skip("no composite PK in registry")
    result = _tables()
    for name in composite_tables:
        assert isinstance(result[name]["primary_key"], list), (
            f"{name} should have list primary_key in output"
        )


# ---------------------------------------------------------------------------
# (g) CLI subprocess: --table shadow_trades --json → valid JSON + exit 0
# ---------------------------------------------------------------------------


def test_cli_table_json():
    """(g) CLI subprocess: --table shadow_trades --json exits 0 with valid JSON."""
    proc = subprocess.run(
        [sys.executable, "-m", "src.tools.capabilityregistry",
         "--table", "shadow_trades", "--json"],
        capture_output=True,
        text=True,
        cwd=str(Path(__file__).parent.parent.parent),
    )
    assert proc.returncode == 0, f"exit code {proc.returncode}: stderr={proc.stderr!r}"
    parsed = json.loads(proc.stdout)
    assert parsed["name"] == "shadow_trades"


# ---------------------------------------------------------------------------
# (h) CLI subprocess: unknown table --json → error envelope + exit 1
# ---------------------------------------------------------------------------


def test_cli_unknown_table_json():
    """(h) CLI subprocess: unknown table --json → error envelope + exit 1."""
    proc = subprocess.run(
        [sys.executable, "-m", "src.tools.capabilityregistry",
         "--table", "unknown_table_name_xyz", "--json"],
        capture_output=True,
        text=True,
        cwd=str(Path(__file__).parent.parent.parent),
    )
    assert proc.returncode == 1, f"exit code {proc.returncode}"
    parsed = json.loads(proc.stdout)
    assert "error" in parsed
    assert parsed["error"]["type"] == "CapabilityRegistryError"
