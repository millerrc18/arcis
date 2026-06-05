"""CI anti-drift oracle tests for the derived fund-ladder and system-map (P3-T5).

Every guard derives its EXPECTED value from a LIVE source module — never a
static literal or snapshot. This mirrors the convention established in
tests/test_capability_registry_coverage.py (#88).

Task scope: tests/test_console_derived_drift.py (FILES_IN_SCOPE only).
Services under test are READ-ONLY: src/console/fund_ladder.py and
src/console/system_map.py are not modified here.

Guard inventory:
  1. schema table_count vs registry.TABLES
  2. schema table names — each in registry.TABLES
  3. capability per-kind counts vs live list_*() lengths
  4. capability total == sum-of-parts (structural invariant)
  5. fund-ladder gate metric_ids all in GATE_TARGETS AND metric REGISTRY
  6. source_sha is a non-empty string in both generators
  7. fail-closed: broken trade source -> generation_ok=False (no exception)
  8. fail-closed: broken capability listing fn -> generation_ok=False (no exception)
"""
from __future__ import annotations

import pytest

from src.console.fund_ladder import generate_fund_ladder
from src.console.system_map import generate_system_map
from src.console.gate_targets import GATE_TARGETS
import src.metrics.registry as metric_registry
import src.schema.registry as schema_registry
from src.platform.capability_registry import (
    ensure_bootstrapped,
    list_actions,
    list_decisions,
    list_states,
    list_systems,
)


@pytest.fixture(scope="module", autouse=True)
def _bootstrap():
    """Populate capability registries before any guard runs."""
    ensure_bootstrapped()
    yield


# ---------------------------------------------------------------------------
# Guard 1 — system-map schema table_count derives from registry.TABLES
# ---------------------------------------------------------------------------

def test_system_map_schema_table_count_matches_registry():
    """schema.table_count in generate_system_map() MUST equal len(registry.TABLES).

    Oracle: src.schema.registry.TABLES loaded live — no literal. Adding a new
    table without updating the system-map generator would surface here only if
    the generator computed the count independently; it calls the registry, so
    this guard proves the derivation path is intact end-to-end.
    """
    result = generate_system_map()
    assert result["schema"]["state"] == "ok", (
        f"Schema section failed unexpectedly: {result['schema']}"
    )
    expected = len(schema_registry.TABLES)
    actual = result["schema"]["table_count"]
    assert actual == expected, (
        f"system_map schema table_count={actual} != len(TABLES)={expected}. "
        "The system-map is not deriving its count from the live registry."
    )


# ---------------------------------------------------------------------------
# Guard 2 — every table name in schema.tables is a key in registry.TABLES
# ---------------------------------------------------------------------------

def test_system_map_table_names_are_real_registry_keys():
    """Every schema.tables[*].name returned by generate_system_map() is a key
    in src.schema.registry.TABLES.

    Oracle: TABLES keys — live. A hand-typed or stale table name would fail
    this guard immediately, proving the names are derived, not fabricated.
    """
    result = generate_system_map()
    assert result["schema"]["state"] == "ok", (
        f"Schema section failed: {result['schema']}"
    )
    registry_keys = set(schema_registry.TABLES.keys())
    for entry in result["schema"]["tables"]:
        name = entry["name"]
        assert name in registry_keys, (
            f"system_map returned table name {name!r} that is not a key in "
            f"registry.TABLES. Served table list is not derived from the registry."
        )


# ---------------------------------------------------------------------------
# Guard 3 — capability per-kind counts match live list_*() lengths
# ---------------------------------------------------------------------------

def test_system_map_capability_kind_counts_match_live_registry():
    """capabilities.actions/states/systems/decisions must equal the live
    list_*() lengths at call time.

    Oracle: list_actions(), list_states(), list_systems(), list_decisions()
    — all live. A count cached after a previous bootstrap that omitted a
    newly-registered capability would fail this guard.
    """
    result = generate_system_map()
    assert result["capabilities"]["state"] == "ok", (
        f"Capabilities section failed: {result['capabilities']}"
    )
    caps = result["capabilities"]

    expected_actions = len(list_actions())
    expected_states = len(list_states())
    expected_systems = len(list_systems())
    expected_decisions = len(list_decisions())

    assert caps["actions"] == expected_actions, (
        f"capabilities.actions={caps['actions']} != len(list_actions())={expected_actions}"
    )
    assert caps["states"] == expected_states, (
        f"capabilities.states={caps['states']} != len(list_states())={expected_states}"
    )
    assert caps["systems"] == expected_systems, (
        f"capabilities.systems={caps['systems']} != len(list_systems())={expected_systems}"
    )
    assert caps["decisions"] == expected_decisions, (
        f"capabilities.decisions={caps['decisions']} != len(list_decisions())={expected_decisions}"
    )


# ---------------------------------------------------------------------------
# Guard 4 — capabilities.total is the sum of all four kinds (structural)
# ---------------------------------------------------------------------------

def test_system_map_capability_total_equals_sum_of_parts():
    """capabilities.total MUST equal actions+states+systems+decisions AND
    equal sum(by_category.values()).

    This is a structural invariant, not a registry-count oracle. The guard
    catches an off-by-one in the total computation or a by_category rollup
    that misses a category.
    """
    result = generate_system_map()
    assert result["capabilities"]["state"] == "ok", (
        f"Capabilities section failed: {result['capabilities']}"
    )
    caps = result["capabilities"]
    sum_of_parts = caps["actions"] + caps["states"] + caps["systems"] + caps["decisions"]
    assert caps["total"] == sum_of_parts, (
        f"capabilities.total={caps['total']} != actions+states+systems+decisions={sum_of_parts}"
    )
    sum_by_category = sum(caps["by_category"].values())
    assert caps["total"] == sum_by_category, (
        f"capabilities.total={caps['total']} != sum(by_category)={sum_by_category}. "
        f"by_category: {caps['by_category']}"
    )


# ---------------------------------------------------------------------------
# Guard 5 — fund-ladder gate metric_ids are in GATE_TARGETS and metric REGISTRY
# ---------------------------------------------------------------------------

def test_fund_ladder_gate_metric_ids_in_gate_targets_and_metric_registry():
    """Every gate metric_id in generate_fund_ladder() must be a key in
    src.console.gate_targets.GATE_TARGETS AND in src.metrics.registry.REGISTRY.

    Oracle: GATE_TARGETS and REGISTRY — both loaded live. An orphan or
    hand-typed gate id that isn't wired to the single-source thresholds and
    the metric registry would fail this guard. The guard iterates all phases
    including pending ones (those use _pending_gate which still carries the
    metric_id).
    """
    result = generate_fund_ladder()
    gate_target_keys = set(GATE_TARGETS.keys())
    registry_keys = set(metric_registry.REGISTRY.keys())

    for phase in result["ladder"]:
        for gate in phase["gates"]:
            mid = gate["metric_id"]
            assert mid in gate_target_keys, (
                f"Phase {phase['phase']} gate {mid!r} is not in GATE_TARGETS. "
                "An orphan gate metric_id was found — it must be registered "
                "in src.console.gate_targets.GATE_TARGETS."
            )
            assert mid in registry_keys, (
                f"Phase {phase['phase']} gate {mid!r} is not in metric REGISTRY. "
                "Gate metric ids must be registered in src.metrics.registry.REGISTRY."
            )


# ---------------------------------------------------------------------------
# Guard 6 — source_sha is a non-empty string in both generators
# ---------------------------------------------------------------------------

def test_fund_ladder_source_sha_is_nonempty():
    """generate_fund_ladder() must populate a non-empty source_sha.

    Proves provenance is always stamped — the generator never returns an
    empty string or missing key.
    """
    result = generate_fund_ladder()
    sha = result.get("source_sha")
    assert isinstance(sha, str) and sha.strip(), (
        f"generate_fund_ladder() returned empty/missing source_sha: {sha!r}"
    )


def test_system_map_source_sha_is_nonempty():
    """generate_system_map() must populate a non-empty source_sha.

    Proves provenance is always stamped — the generator never returns an
    empty string or missing key.
    """
    result = generate_system_map()
    sha = result.get("source_sha")
    assert isinstance(sha, str) and sha.strip(), (
        f"generate_system_map() returned empty/missing source_sha: {sha!r}"
    )


# ---------------------------------------------------------------------------
# Guard 7 — fail-closed: broken trade source -> generation_ok=False, no raise
# ---------------------------------------------------------------------------

def test_fund_ladder_fails_closed_when_trade_source_raises(monkeypatch):
    """When _fetch_closed_trades raises, generate_fund_ladder() must:
      - set generation_ok=False
      - NOT raise an exception
      - NOT serve a fabricated/stale value (gates must all be state='unknown')

    Oracle: the trade source function name is taken from the live module
    (src.console.fund_ladder._fetch_closed_trades). Patching the REAL import
    target proves the fail-closed path is exercised end-to-end.
    """
    import src.console.fund_ladder as fl_module

    def _explode(*args, **kwargs):
        raise RuntimeError("injected failure — trade source unavailable")

    monkeypatch.setattr(fl_module, "_fetch_closed_trades", _explode)

    result = generate_fund_ladder()
    assert result["generation_ok"] is False, (
        "generate_fund_ladder() must return generation_ok=False when "
        "_fetch_closed_trades raises, but got generation_ok=True."
    )
    # Every current-phase gate must degrade to unknown, not carry a stale value
    for phase in result["ladder"]:
        if phase["status"] in {"active", "complete"}:
            for gate in phase["gates"]:
                assert gate["state"] == "unknown", (
                    f"Phase {phase['phase']} gate {gate['metric_id']!r} has "
                    f"state={gate['state']!r} after a trade-source failure — "
                    "expected 'unknown' (fail-closed contract)."
                )


# ---------------------------------------------------------------------------
# Guard 8 — fail-closed: broken capability listing -> generation_ok=False, no raise
# ---------------------------------------------------------------------------

def test_system_map_fails_closed_when_list_actions_raises(monkeypatch):
    """When list_actions raises inside _derive_capabilities(), generate_system_map()
    must:
      - set generation_ok=False
      - NOT raise an exception
      - set capabilities.state='unknown'

    Oracle: the capability listing function name is list_actions, which is the
    real function called inside src.console.system_map._derive_capabilities().
    Patching it at the system_map module's import namespace proves the
    fail-closed path is exercised.
    """
    import src.console.system_map as sm_module

    def _explode(*args, **kwargs):
        raise RuntimeError("injected failure — capability registry unavailable")

    monkeypatch.setattr(sm_module, "list_actions", _explode)

    result = generate_system_map()
    assert result["generation_ok"] is False, (
        "generate_system_map() must return generation_ok=False when "
        "list_actions raises, but got generation_ok=True."
    )
    assert result["capabilities"]["state"] == "unknown", (
        f"capabilities.state should be 'unknown' after list_actions failure, "
        f"but got {result['capabilities']['state']!r}."
    )
