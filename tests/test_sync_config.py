"""Tests for _topo_sort_tables() in src.schema.sync_config.

Tests use:
- Real registry tables for the council-chain test (integration-style)
- Lightweight synthetic TableDef instances for unit-level edge cases

No external I/O. No DB connections required.
"""

import pytest
from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# Helpers — minimal synthetic TableDef / ForeignKeyDef stubs
# ---------------------------------------------------------------------------

@dataclass
class _FKDef:
    column: str
    references_table: str
    references_column: str


@dataclass
class _TableDef:
    name: str
    foreign_keys: list = field(default_factory=list)
    # Additional fields that generate_sync_tables would produce are not
    # needed here; _topo_sort_tables only reads .foreign_keys per table.


def _make_fake_tables(schema: dict[str, list[str]]) -> dict[str, _TableDef]:
    """Build a {name: TableDef} dict from {name: [referenced_table, ...]}."""
    tables = {}
    for name, deps in schema.items():
        fks = [_FKDef(column=f"{dep}_id", references_table=dep, references_column="id")
               for dep in deps]
        tables[name] = _TableDef(name=name, foreign_keys=fks)
    return tables


# ---------------------------------------------------------------------------
# Import targets
# ---------------------------------------------------------------------------

from src.schema.sync_config import _topo_sort_tables, SyncConfigError  # noqa: E402


# ---------------------------------------------------------------------------
# Test 1: council chain uses real registry tables
# ---------------------------------------------------------------------------

def test_topo_sort_handles_council_chain():
    """council_sessions must appear before council_votes and council_debug_log
    in the sorted output because those tables declare FKs to council_sessions.
    """
    from src.schema.sync_config import generate_sync_tables
    from src.schema.registry import TABLES

    # Use the real sync-eligible tables that include the council chain.
    all_sync = generate_sync_tables()

    # Restrict to just the council tables that exist in registry.
    council_names = {
        "council_sessions",
        "council_votes",
        "council_calibrations",
        "council_debug_log",
        "council_parameter_log",
    }
    subset = {k: v for k, v in all_sync.items() if k in council_names}
    assert len(subset) >= 4, f"Expected at least 4 council tables in sync config, got: {list(subset)}"

    # _topo_sort_tables receives the sync config dict and looks up FKs from
    # the registry.  Pass the full sync config so it has access to all
    # entries (needed for FK resolution inside the subset).
    ordered = _topo_sort_tables(subset)

    assert "council_sessions" in ordered
    assert "council_votes" in ordered
    assert "council_debug_log" in ordered

    sessions_idx = ordered.index("council_sessions")
    votes_idx = ordered.index("council_votes")
    debug_idx = ordered.index("council_debug_log")

    assert sessions_idx < votes_idx, (
        f"council_sessions (idx {sessions_idx}) must precede "
        f"council_votes (idx {votes_idx})"
    )
    assert sessions_idx < debug_idx, (
        f"council_sessions (idx {sessions_idx}) must precede "
        f"council_debug_log (idx {debug_idx})"
    )


def test_generate_sync_tables_orders_fk_parents_first():
    """generate_sync_tables() must preserve FK-safe order for real sync runs."""
    from src.schema.sync_config import generate_sync_tables

    ordered = list(generate_sync_tables())

    assert ordered.index("recommendations") < ordered.index("shadow_trades")
    assert ordered.index("recommendations") < ordered.index("attribution_trades")
    assert ordered.index("council_sessions") < ordered.index("council_votes")
    assert ordered.index("diagnostic_runs") < ordered.index("diagnostic_run_plots")


# ---------------------------------------------------------------------------
# Test 2: no-FK set returns deterministic order
# ---------------------------------------------------------------------------

def test_topo_sort_with_no_fks():
    """Tables with no FK relationships are returned in a deterministic order."""
    from src.schema.registry import TABLES, TableDef, ForeignKeyDef

    # Build a fake tables dict with no FKs using actual TableDef instances
    # from registry as templates but monkey-patching foreign_keys=[] for safety.
    # Easier: just pass a real no-FK subset from the registry.
    no_fk_tables = {
        name: tdef
        for name, tdef in TABLES.items()
        if not tdef.foreign_keys and tdef.sync_to_postgres
    }
    assert len(no_fk_tables) >= 3, "Need at least 3 no-FK sync tables to be meaningful"

    result1 = _topo_sort_tables(no_fk_tables)
    result2 = _topo_sort_tables(no_fk_tables)

    assert result1 == result2, "Same input must produce same output (determinism)"
    assert set(result1) == set(no_fk_tables.keys()), "All input tables must be present in output"


# ---------------------------------------------------------------------------
# Test 3: cycle detection raises SyncConfigError
# ---------------------------------------------------------------------------

def test_topo_sort_detects_cycle():
    """A → B → A cycle must raise SyncConfigError naming both tables."""
    tables = _make_fake_tables({"A": ["B"], "B": ["A"]})

    with pytest.raises(SyncConfigError) as exc_info:
        _topo_sort_tables(tables)

    msg = str(exc_info.value)
    assert "A" in msg and "B" in msg, (
        f"Error message must name both tables in cycle, got: {msg!r}"
    )


# ---------------------------------------------------------------------------
# Test 4: FK to external (non-input) table is ignored without error
# ---------------------------------------------------------------------------

def test_topo_sort_ignores_external_fks():
    """Table with FK pointing to a name NOT in the input dict must not error."""
    tables = _make_fake_tables({
        "child": ["external_parent"],
        "sibling": [],
    })
    # "external_parent" is not in the tables dict — must be treated as external.
    result = _topo_sort_tables(tables)

    assert set(result) == {"child", "sibling"}, f"Unexpected result: {result}"
    # No error raised — that is the primary assertion.


# ---------------------------------------------------------------------------
# Test 5: determinism — same input always produces same output
# ---------------------------------------------------------------------------

def test_topo_sort_deterministic():
    """Repeated calls with same input must return identical list (tie-breaking is stable)."""
    # Mix of tables with and without FK relationships.
    tables = _make_fake_tables({
        "alpha": [],
        "beta": ["alpha"],
        "gamma": [],
        "delta": ["beta"],
        "epsilon": ["gamma"],
    })

    results = [_topo_sort_tables(tables) for _ in range(5)]
    assert all(r == results[0] for r in results[1:]), (
        "All 5 runs must return identical order"
    )
    # Verify structural ordering is correct.
    r = results[0]
    assert r.index("alpha") < r.index("beta"), "alpha must precede beta"
    assert r.index("beta") < r.index("delta"), "beta must precede delta"
    assert r.index("gamma") < r.index("epsilon"), "gamma must precede epsilon"
