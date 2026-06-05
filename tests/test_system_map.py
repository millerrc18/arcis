"""Tests for the derived system-map service (Founder Console P3-T2).

Covers src.console.system_map — the §KNOW module that derives an
architecture/capability/schema SUMMARY entirely from machine-readable
registries (design law #7 derive-from-source; NO hand-typed component
lists or counts).

Design-law assertions enforced:
  derive-from-source (#7) — capability counts come from the live
      capability_registry listing functions; schema table count comes
      from src.schema.registry.TABLES. Nothing is hardcoded (the test
      reads the authoritative counts LIVE and compares).
  fail-closed (per-section) — when a registry listing function raises,
      that section reports state='unknown' with an error, the top-level
      generation_ok flips to False, and NO exception escapes and NO
      stale/typed fallback is substituted.
  internal consistency — capabilities.total == the sum of the derived
      per-kind counts.

No DB is required: the module reads in-memory registries plus a
``git rev-parse`` subprocess only, so these tests do not skip on
TEST_DATABASE_URL.
"""
from __future__ import annotations

from src.console import system_map


# ── envelope shape ────────────────────────────────────────────────────────────

def test_generate_system_map_returns_exact_envelope():
    result = system_map.generate_system_map()

    # top-level keys
    assert set(result) == {
        "capabilities",
        "schema",
        "generation_ok",
        "source_sha",
        "as_of",
    }
    assert isinstance(result["generation_ok"], bool)
    assert isinstance(result["as_of"], str) and result["as_of"]

    caps = result["capabilities"]
    assert set(caps) == {
        "by_category",
        "total",
        "actions",
        "states",
        "systems",
        "decisions",
        "state",
    }
    assert caps["state"] in ("ok", "unknown")
    assert isinstance(caps["by_category"], dict)
    assert all(isinstance(v, int) for v in caps["by_category"].values())
    for key in ("total", "actions", "states", "systems", "decisions"):
        assert isinstance(caps[key], int)

    schema = result["schema"]
    assert set(schema) == {"tables", "table_count", "state"}
    assert schema["state"] in ("ok", "unknown")
    assert isinstance(schema["tables"], list)
    for entry in schema["tables"]:
        assert set(entry) == {"name", "column_count"}
        assert isinstance(entry["name"], str) and entry["name"]
        assert isinstance(entry["column_count"], int)


# ── happy path: derived, consistent, non-vacuous ──────────────────────────────

def test_capabilities_total_equals_sum_of_per_kind_counts():
    caps = system_map.generate_system_map()["capabilities"]
    assert caps["total"] == (
        caps["actions"] + caps["states"] + caps["systems"] + caps["decisions"]
    )
    # by_category sums to the same total
    assert sum(caps["by_category"].values()) == caps["total"]


def test_capability_counts_match_live_registry():
    from src.platform.capability_registry import (
        ensure_bootstrapped,
        list_actions,
        list_decisions,
        list_states,
        list_systems,
    )

    ensure_bootstrapped()
    caps = system_map.generate_system_map()["capabilities"]
    assert caps["actions"] == len(list_actions())
    assert caps["states"] == len(list_states())
    assert caps["systems"] == len(list_systems())
    assert caps["decisions"] == len(list_decisions())


def test_capabilities_non_vacuous_real_category_present():
    """At least one real registered category must appear (not an empty map)."""
    from src.platform.capability_registry import (
        ensure_bootstrapped,
        list_actions,
        list_decisions,
        list_states,
        list_systems,
    )

    ensure_bootstrapped()
    live_categories = {
        e.category
        for e in list_actions() + list_states() + list_systems() + list_decisions()
    }
    assert live_categories  # registry is populated at all

    result = system_map.generate_system_map()
    caps = result["capabilities"]
    assert caps["state"] == "ok"
    assert caps["by_category"]
    # every derived category is a real registered category — nothing fabricated
    assert set(caps["by_category"]) <= live_categories
    # and at least one real category survived into the summary
    assert live_categories & set(caps["by_category"])


def test_schema_table_count_matches_live_registry():
    from src.schema.registry import TABLES

    result = system_map.generate_system_map()
    schema = result["schema"]
    assert schema["state"] == "ok"
    assert schema["table_count"] == len(TABLES)
    assert len(schema["tables"]) == len(TABLES)
    # column_count derived from the live TableDef, not typed
    sample_name = next(iter(TABLES))
    derived = {t["name"]: t["column_count"] for t in schema["tables"]}
    assert derived[sample_name] == len(TABLES[sample_name].columns)


def test_source_sha_non_empty():
    result = system_map.generate_system_map()
    assert isinstance(result["source_sha"], str)
    assert result["source_sha"]


def test_generation_ok_true_on_happy_path():
    assert system_map.generate_system_map()["generation_ok"] is True


# ── fail-closed: a registry that raises degrades its section only ─────────────

def test_capability_section_fails_closed(monkeypatch):
    """A raising capability listing fn → capabilities.state='unknown',
    generation_ok=False, an error string, and NO exception."""
    def _boom():
        raise RuntimeError("capability registry exploded")

    monkeypatch.setattr(system_map, "list_actions", _boom)

    result = system_map.generate_system_map()
    caps = result["capabilities"]
    assert caps["state"] == "unknown"
    assert "error" in caps and caps["error"]
    assert result["generation_ok"] is False
    # schema section is independent and should still be derivable
    assert result["schema"]["state"] == "ok"
    # no stale/typed fallback: the failed section did not invent counts
    assert "by_category" not in caps or caps["by_category"] == {}


def test_schema_section_fails_closed(monkeypatch):
    """A schema-registry access failure → schema.state='unknown',
    generation_ok=False, an error string, capabilities unaffected."""
    class _ExplodingTables:
        def __iter__(self):
            raise RuntimeError("schema registry exploded")

        def items(self):
            raise RuntimeError("schema registry exploded")

        def values(self):
            raise RuntimeError("schema registry exploded")

        def __len__(self):
            raise RuntimeError("schema registry exploded")

    import src.schema.registry as schema_registry

    monkeypatch.setattr(schema_registry, "TABLES", _ExplodingTables())

    result = system_map.generate_system_map()
    schema = result["schema"]
    assert schema["state"] == "unknown"
    assert "error" in schema and schema["error"]
    assert result["generation_ok"] is False
    assert result["capabilities"]["state"] == "ok"


def test_source_sha_falls_back_to_version(monkeypatch):
    """When git rev-parse fails, source_sha falls back to VERSION (never empty)."""
    import subprocess

    def _raise(*_args, **_kwargs):
        raise subprocess.SubprocessError("git unavailable")

    monkeypatch.setattr(system_map.subprocess, "check_output", _raise)

    from src.version import VERSION

    result = system_map.generate_system_map()
    assert result["source_sha"] == VERSION
    # a git failure is NOT a generation failure
    assert result["generation_ok"] is True
