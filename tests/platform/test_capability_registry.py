"""Core registry mechanics tests.

Covers: empty-registry state, single registration, idempotent re-registration
with identical metadata, conflict rejection across different metadata,
categorization, cross-registry name reuse, bootstrap idempotency.
"""
from __future__ import annotations

from datetime import date

import pytest

from src.platform.capability_registry import (
    ACTIONS,
    DECISIONS,
    STATES,
    SYSTEMS,
    CapabilityRegistryError,
    all_entries,
    clear_registries_for_tests,
    get_action,
    list_actions,
    list_decisions,
    list_states,
    list_systems,
    register_action,
    register_decision,
    register_state,
    register_system,
)
from src.platform.capability_registry.bootstrap import (
    bootstrap_errors,
    ensure_bootstrapped,
    reset_for_tests,
)


BASE_META = dict(
    description="A capability for tests.",
    category="testing",
    version="1.0",
    maintainer="ai_session",
    introduced_in="v0.25.0",
    last_reviewed_date=date(2026, 4, 18),
)

VALID_SCHEMA = {"type": "object", "properties": {}, "additionalProperties": False}


@pytest.fixture(autouse=True)
def _isolated_registries():
    """Snapshot and restore registries around each test.

    Prevents cross-test pollution from the bootstrap's real-module imports
    that run in other tests. We snapshot what's already registered (from
    prior imports in this test session), clear, run the test, then restore.
    """
    saved = (
        dict(ACTIONS),
        dict(STATES),
        dict(SYSTEMS),
        dict(DECISIONS),
    )
    clear_registries_for_tests()
    try:
        yield
    finally:
        clear_registries_for_tests()
        ACTIONS.update(saved[0])
        STATES.update(saved[1])
        SYSTEMS.update(saved[2])
        DECISIONS.update(saved[3])


def test_empty_registries_start_empty():
    assert list_actions() == []
    assert list_states() == []
    assert list_systems() == []
    assert list_decisions() == []
    assert all_entries() == []


def test_register_action_populates_registry():
    @register_action(
        name="demo_action",
        kickoff_endpoint="/api/demo",
        input_schema=VALID_SCHEMA,
        output_schema=VALID_SCHEMA,
        estimated_duration="1 minute",
        **BASE_META,
    )
    def fn():
        return "hello"

    assert len(list_actions()) == 1
    entry = get_action("demo_action")
    assert entry is not None
    assert entry.name == "demo_action"
    assert fn() == "hello"  # decorator returns the function unchanged


def test_register_state_stores_callable():
    @register_state(
        name="demo_state",
        refresh_hint="real-time",
        **BASE_META,
    )
    def query():
        return {"value": 7}

    states = list_states()
    assert len(states) == 1
    assert states[0].query_function() == {"value": 7}


def test_register_system_stores_callable():
    @register_system(
        name="demo_system",
        expected_runtime="always",
        **BASE_META,
    )
    def health():
        return {"status": "ok", "detail": "fine"}

    systems = list_systems()
    assert len(systems) == 1
    assert systems[0].health_check_function()["status"] == "ok"


def test_register_decision_populates_registry():
    register_decision(
        name="demo_decision",
        decision_text="We will do X.",
        rationale="Because Y.",
        revisit_trigger="Z",
        **BASE_META,
    )
    decisions = list_decisions()
    assert len(decisions) == 1
    assert decisions[0].decision_text == "We will do X."


def test_duplicate_name_with_identical_metadata_is_idempotent():
    kwargs = dict(
        name="same",
        kickoff_endpoint="/api/demo",
        input_schema=VALID_SCHEMA,
        output_schema=VALID_SCHEMA,
        estimated_duration="1 minute",
        **BASE_META,
    )

    @register_action(**kwargs)
    def fn1():
        return "a"

    @register_action(**kwargs)
    def fn2():
        return "b"

    # Only one entry even though register fired twice; fn identity not tracked.
    assert len(list_actions()) == 1
    # The stored entry reflects the metadata (which was identical across calls).
    assert get_action("same").kickoff_endpoint == "/api/demo"


def test_duplicate_name_with_different_metadata_raises():
    @register_action(
        name="same",
        kickoff_endpoint="/api/first",
        input_schema=VALID_SCHEMA,
        output_schema=VALID_SCHEMA,
        estimated_duration="1 minute",
        **BASE_META,
    )
    def fn1():
        return "a"

    with pytest.raises(CapabilityRegistryError) as exc_info:
        @register_action(
            name="same",
            kickoff_endpoint="/api/second",  # different!
            input_schema=VALID_SCHEMA,
            output_schema=VALID_SCHEMA,
            estimated_duration="1 minute",
            **BASE_META,
        )
        def fn2():
            return "b"
    assert "already registered" in str(exc_info.value)


def test_categorization_distinguishes_registries():
    @register_action(
        name="act_one",
        kickoff_endpoint="/api/x",
        input_schema=VALID_SCHEMA,
        output_schema=VALID_SCHEMA,
        estimated_duration="1m",
        **BASE_META,
    )
    def act():
        pass

    @register_state(
        name="state_one",
        refresh_hint="real-time",
        **BASE_META,
    )
    def st():
        return {}

    assert get_action("act_one").kind == "action"
    assert list_states()[0].kind == "state"
    assert get_action("state_one") is None  # wrong registry
    assert len(list_actions()) == 1
    assert len(list_states()) == 1


def test_same_name_across_different_registries_allowed():
    # Spec: names are unique within a registry, not globally.
    common_name = "overlap"

    @register_action(
        name=common_name,
        kickoff_endpoint="/api/x",
        input_schema=VALID_SCHEMA,
        output_schema=VALID_SCHEMA,
        estimated_duration="1m",
        **BASE_META,
    )
    def act():
        pass

    @register_state(
        name=common_name,
        refresh_hint="real-time",
        **BASE_META,
    )
    def st():
        return {}

    assert get_action(common_name) is not None
    assert list_states()[0].name == common_name


def test_deprecated_action_with_replacement_registers():
    @register_action(
        name="old_tool",
        kickoff_endpoint="/api/old",
        input_schema=VALID_SCHEMA,
        output_schema=VALID_SCHEMA,
        estimated_duration="1m",
        deprecated=True,
        deprecated_replacement="new_tool",
        **BASE_META,
    )
    def fn():
        pass

    entry = get_action("old_tool")
    assert entry.deprecated is True
    assert entry.deprecated_replacement == "new_tool"


def test_missing_required_field_raises_at_decoration_time():
    # estimated_duration is required; omitting it must fail before the fn runs.
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        @register_action(
            name="incomplete",
            kickoff_endpoint="/api/demo",
            input_schema=VALID_SCHEMA,
            output_schema=VALID_SCHEMA,
            # estimated_duration missing
            **BASE_META,
        )
        def fn():
            pass


def test_all_entries_returns_every_registry():
    @register_action(
        name="act",
        kickoff_endpoint="/api/x",
        input_schema=VALID_SCHEMA,
        output_schema=VALID_SCHEMA,
        estimated_duration="1m",
        **BASE_META,
    )
    def act():
        pass

    @register_state(name="st", refresh_hint="rt", **BASE_META)
    def st():
        return {}

    @register_system(name="sys", expected_runtime="always", **BASE_META)
    def sys_health():
        return {"status": "ok", "detail": ""}

    register_decision(
        name="dec",
        decision_text="X",
        rationale="Y",
        revisit_trigger="Z",
        **BASE_META,
    )

    entries = all_entries()
    names = {e.name for e in entries}
    assert names == {"act", "st", "sys", "dec"}
    assert len(entries) == 4


def test_entries_sorted_by_category_then_name():
    @register_action(
        name="zeta",
        kickoff_endpoint="/api/z",
        input_schema=VALID_SCHEMA,
        output_schema=VALID_SCHEMA,
        estimated_duration="1m",
        **{**BASE_META, "category": "alpha"},
    )
    def z():
        pass

    @register_action(
        name="alpha",
        kickoff_endpoint="/api/a",
        input_schema=VALID_SCHEMA,
        output_schema=VALID_SCHEMA,
        estimated_duration="1m",
        **{**BASE_META, "category": "alpha"},
    )
    def a():
        pass

    @register_action(
        name="middle",
        kickoff_endpoint="/api/m",
        input_schema=VALID_SCHEMA,
        output_schema=VALID_SCHEMA,
        estimated_duration="1m",
        **{**BASE_META, "category": "bravo"},
    )
    def m():
        pass

    result = [e.name for e in list_actions()]
    # within category 'alpha': alpha then zeta; category 'bravo': middle
    assert result == ["alpha", "zeta", "middle"]


def test_bootstrap_is_idempotent():
    reset_for_tests()
    ensure_bootstrapped()
    first_errs = bootstrap_errors()
    ensure_bootstrapped()
    second_errs = bootstrap_errors()
    # Second call is a no-op (skips the import loop entirely).
    assert first_errs == second_errs
