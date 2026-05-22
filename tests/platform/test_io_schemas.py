"""Unit tests for simple_io_schema (ACTION I/O schema builder)."""
from __future__ import annotations

from jsonschema import Draft7Validator

from src.platform.capability_registry._io_schemas import simple_io_schema


def test_default_schema_is_valid_draft7_object():
    schema = simple_io_schema()
    Draft7Validator.check_schema(schema)
    assert schema["type"] == "object"
    assert schema["properties"] == {}
    assert schema["required"] == []


def test_schema_with_properties_and_required_is_valid():
    schema = simple_io_schema(
        properties={
            "at": {"type": "string", "format": "date-time"},
            "force": {"type": "boolean"},
        },
        required=["at"],
    )
    Draft7Validator.check_schema(schema)
    assert schema["type"] == "object"
    assert set(schema["properties"]) == {"at", "force"}
    assert schema["required"] == ["at"]


def test_schema_passes_actionentry_validator_shape():
    """ActionEntry requires a dict that check_schema accepts AND a top-level type."""
    schema = simple_io_schema(properties={"x": {"type": "integer"}})
    assert isinstance(schema, dict)
    assert "type" in schema
    Draft7Validator.check_schema(schema)
