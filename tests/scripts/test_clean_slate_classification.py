"""Completeness CI guard for the clean-slate WIPE/KEEP partition (#95, T2).

Asserts the partition is an exhaustive, disjoint cover of set(registry.TABLES)
(n==80), and that EXPECTED_FK_EDGES matches the 6 spec edges. Includes
verify-by-mutation: injecting a fake table into a COPY of registry.TABLES (and
removing a name from both sets) must make assert_partition_complete() RAISE —
proving the guard is not theater (memory: feedback_vacuous_test_pattern).
"""

from __future__ import annotations

import pytest

from scripts._clean_slate import classification as cls
from src.schema import registry


def test_partition_is_exhaustive_and_disjoint():
    universe = set(registry.TABLES)
    wipe, keep = set(cls.WIPE_TABLES), set(cls.KEEP_TABLES)
    assert wipe | keep == universe, (
        f"partition not exhaustive: missing={sorted(universe - (wipe | keep))} "
        f"extra={sorted((wipe | keep) - universe)}"
    )
    assert wipe & keep == set(), f"partition overlap: {sorted(wipe & keep)}"


def test_counts_pinned_53_27_80():
    assert len(cls.WIPE_TABLES) == 53
    assert len(cls.KEEP_TABLES) == 27
    assert len(cls.WIPE_TABLES) + len(cls.KEEP_TABLES) == 80
    assert len(set(registry.TABLES)) == cls.EXPECTED_REGISTRY_COUNT == 80


def test_assert_partition_complete_passes_on_real_registry():
    # Must not raise against the real registry.
    cls.assert_partition_complete()


def test_expected_fk_edges_match_spec():
    expected = frozenset({
        ("shadow_trades", "recommendation_id", "recommendations"),
        ("shadow_trades", "strategy_id", "strategy_registry"),
        ("council_votes", "session_id", "council_sessions"),
        ("council_debug_log", "session_id", "council_sessions"),
        ("diagnostic_run_plots", "run_id", "diagnostic_runs"),
        ("attribution_trades", "recommendation_id", "recommendations"),
    })
    assert cls.EXPECTED_FK_EDGES == expected
    assert len(cls.EXPECTED_FK_EDGES) == 6


def test_expected_fk_edges_are_all_wipe_to_wipe():
    # The FK-safety proof: every expected edge's child AND parent are in WIPE,
    # so a single multi-table TRUNCATE ... CASCADE cannot reach keep data.
    for child, _col, parent in cls.EXPECTED_FK_EDGES:
        assert child in cls.WIPE_TABLES, f"FK child {child} not in WIPE"
        assert parent in cls.WIPE_TABLES, f"FK parent {parent} not in WIPE"


def test_expected_fk_edges_match_live_registry_definitions():
    # The constant must mirror the registry's actual FK definitions touching
    # WIPE tables (normalized to (child, col, parent)).
    live: set[tuple[str, str, str]] = set()
    for tname, tdef in registry.TABLES.items():
        for fk in tdef.foreign_keys:
            if tname in cls.WIPE_TABLES or fk.references_table in cls.WIPE_TABLES:
                live.add((tname, fk.column, fk.references_table))
    assert live == set(cls.EXPECTED_FK_EDGES)


# ── verify-by-mutation: prove the guard actually fires ──────────────────────


def test_guard_raises_on_injected_unregistered_table(monkeypatch):
    # Inject a fake table into a COPY of registry.TABLES → 'missing' set non-empty.
    fake = dict(registry.TABLES)
    fake["__cs_fake_unclassified_table__"] = object()  # value irrelevant to the guard
    monkeypatch.setattr(registry, "TABLES", fake)
    with pytest.raises(AssertionError) as exc:
        cls.assert_partition_complete()
    assert "missing=" in str(exc.value)
    assert "__cs_fake_unclassified_table__" in str(exc.value)


def test_guard_raises_when_name_removed_from_both_sets(monkeypatch):
    # Remove a real table from BOTH partition sets → it becomes 'missing'.
    shrunk_wipe = frozenset(cls.WIPE_TABLES - {"shadow_trades"})
    monkeypatch.setattr(cls, "WIPE_TABLES", shrunk_wipe)
    with pytest.raises(AssertionError) as exc:
        cls.assert_partition_complete()
    assert "shadow_trades" in str(exc.value)


def test_guard_raises_on_overlap(monkeypatch):
    # Put a KEEP table also into WIPE → overlap non-empty.
    overlapping_wipe = frozenset(cls.WIPE_TABLES | {"minute_bars"})
    monkeypatch.setattr(cls, "WIPE_TABLES", overlapping_wipe)
    with pytest.raises(AssertionError) as exc:
        cls.assert_partition_complete()
    assert "overlap=" in str(exc.value)
    assert "minute_bars" in str(exc.value)


def test_guard_raises_on_count_pin_drift(monkeypatch):
    # Registry with 81 tables but a still-exhaustive/disjoint partition must
    # still trip via the count-pin. Add one table to registry AND to KEEP.
    fake_registry = dict(registry.TABLES)
    fake_registry["__cs_extra__"] = object()
    monkeypatch.setattr(registry, "TABLES", fake_registry)
    monkeypatch.setattr(cls, "KEEP_TABLES", frozenset(cls.KEEP_TABLES | {"__cs_extra__"}))
    with pytest.raises(AssertionError) as exc:
        cls.assert_partition_complete()
    assert "count drift" in str(exc.value) or "EXPECTED_REGISTRY_COUNT" in str(exc.value)
