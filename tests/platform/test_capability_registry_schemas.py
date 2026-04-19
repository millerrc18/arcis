"""Pydantic schema tests for the capability registry entry models.

Covers: required-field enforcement, deprecated/replacement cross-validation,
JSON Schema validity on Action input/output, callable enforcement on
State query + System health functions.
"""
from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError

from src.platform.capability_registry.schemas import (
    ActionEntry,
    DecisionEntry,
    StateEntry,
    SystemEntry,
)


BASE_FIELDS = {
    "description": "A capability.",
    "category": "diagnostics",
    "version": "1.0",
    "maintainer": "ai_session",
    "introduced_in": "v0.25.0",
    "last_reviewed_date": date(2026, 4, 18),
}


def _valid_schema() -> dict:
    return {"type": "object", "properties": {}, "additionalProperties": False}


def test_action_entry_happy_path():
    entry = ActionEntry(
        name="demo_action",
        kickoff_endpoint="/api/demo",
        input_schema=_valid_schema(),
        output_schema=_valid_schema(),
        estimated_duration="1 minute",
        **BASE_FIELDS,
    )
    assert entry.kind == "action"
    assert entry.ui_kickoff_available is True
    assert entry.deprecated is False


def test_action_entry_rejects_non_object_schema():
    with pytest.raises(ValidationError) as exc_info:
        ActionEntry(
            name="demo_action",
            kickoff_endpoint="/api/demo",
            input_schema={},
            output_schema=_valid_schema(),
            estimated_duration="1 minute",
            **BASE_FIELDS,
        )
    assert "top-level 'type'" in str(exc_info.value)


def test_action_entry_rejects_invalid_json_schema():
    bad_schema = {"type": "not-a-real-json-schema-type"}
    with pytest.raises(ValidationError) as exc_info:
        ActionEntry(
            name="demo_action",
            kickoff_endpoint="/api/demo",
            input_schema=bad_schema,
            output_schema=_valid_schema(),
            estimated_duration="1 minute",
            **BASE_FIELDS,
        )
    assert "Draft-7 JSON Schema" in str(exc_info.value)


def test_action_entry_missing_required_field():
    with pytest.raises(ValidationError):
        ActionEntry(
            name="demo_action",
            kickoff_endpoint="/api/demo",
            input_schema=_valid_schema(),
            output_schema=_valid_schema(),
            **BASE_FIELDS,
        )


def test_deprecated_without_replacement_fails():
    fields = dict(BASE_FIELDS, deprecated=True)
    with pytest.raises(ValidationError) as exc_info:
        ActionEntry(
            name="old_action",
            kickoff_endpoint="/api/demo",
            input_schema=_valid_schema(),
            output_schema=_valid_schema(),
            estimated_duration="1 minute",
            **fields,
        )
    assert "deprecated_replacement" in str(exc_info.value)


def test_deprecated_with_replacement_succeeds():
    fields = dict(
        BASE_FIELDS,
        deprecated=True,
        deprecated_replacement="new_action",
    )
    entry = ActionEntry(
        name="old_action",
        kickoff_endpoint="/api/demo",
        input_schema=_valid_schema(),
        output_schema=_valid_schema(),
        estimated_duration="1 minute",
        **fields,
    )
    assert entry.deprecated is True
    assert entry.deprecated_replacement == "new_action"


def test_replacement_without_deprecated_fails():
    fields = dict(BASE_FIELDS, deprecated_replacement="new_action")
    with pytest.raises(ValidationError):
        ActionEntry(
            name="old_action",
            kickoff_endpoint="/api/demo",
            input_schema=_valid_schema(),
            output_schema=_valid_schema(),
            estimated_duration="1 minute",
            **fields,
        )


def test_state_entry_requires_callable():
    with pytest.raises(ValidationError):
        StateEntry(
            name="demo_state",
            query_function="not a callable",
            refresh_hint="real-time",
            **BASE_FIELDS,
        )


def test_state_entry_happy_path():
    def query():
        return {"value": 42}

    entry = StateEntry(
        name="demo_state",
        query_function=query,
        refresh_hint="real-time",
        **BASE_FIELDS,
    )
    assert entry.kind == "state"
    assert entry.query_function() == {"value": 42}


def test_system_entry_requires_callable_health():
    with pytest.raises(ValidationError):
        SystemEntry(
            name="demo_system",
            health_check_function=None,
            expected_runtime="always",
            **BASE_FIELDS,
        )


def test_system_entry_happy_path():
    def health():
        return {"status": "ok", "detail": "healthy"}

    entry = SystemEntry(
        name="demo_system",
        health_check_function=health,
        expected_runtime="always",
        **BASE_FIELDS,
    )
    assert entry.kind == "system"
    assert entry.health_check_function()["status"] == "ok"


def test_decision_entry_happy_path():
    entry = DecisionEntry(
        name="demo_decision",
        decision_text="We will do X.",
        rationale="Because Y is better than Z.",
        revisit_trigger="After 100 trades",
        **BASE_FIELDS,
    )
    assert entry.kind == "decision"


def test_decision_entry_missing_rationale():
    with pytest.raises(ValidationError):
        DecisionEntry(
            name="demo_decision",
            decision_text="We will do X.",
            revisit_trigger="After 100 trades",
            **BASE_FIELDS,
        )


def test_name_rejects_spaces_and_symbols():
    with pytest.raises(ValidationError):
        DecisionEntry(
            name="bad name with spaces",
            decision_text="X",
            rationale="Y",
            revisit_trigger="Z",
            **BASE_FIELDS,
        )
    with pytest.raises(ValidationError):
        DecisionEntry(
            name="bad.name",
            decision_text="X",
            rationale="Y",
            revisit_trigger="Z",
            **BASE_FIELDS,
        )


def test_description_cannot_be_whitespace_only():
    fields = dict(BASE_FIELDS, description="   ")
    with pytest.raises(ValidationError):
        DecisionEntry(
            name="demo",
            decision_text="X",
            rationale="Y",
            revisit_trigger="Z",
            **fields,
        )
