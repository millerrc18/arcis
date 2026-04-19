"""Pydantic models for the four capability registry entry types.

Every registered capability is a validated Pydantic model. Missing or
malformed metadata raises at decorator time, so CI catches drift before merge.

Called by: src.platform.capability_registry.registry (at decoration time)
Calls: jsonschema (validates Action input/output schemas as Draft-7)
Owns tables: none
Config keys: none
Tests: tests/platform/test_capability_registry_schemas.py
"""
from __future__ import annotations

from datetime import date
from typing import Any, Callable, Literal, Optional

from jsonschema import Draft7Validator
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

MaintainerType = Literal["operator", "ai_session"]
RegistryKind = Literal["action", "state", "system", "decision"]


class BaseEntry(BaseModel):
    """Shared metadata across all four registry entry types.

    Every required field must be populated by the caller; Pydantic rejects
    partial metadata. The `deprecated` + `deprecated_replacement` pair is
    cross-validated by the registry's own model_validator subclasses.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=False)

    name: str = Field(..., min_length=1, max_length=128)
    description: str = Field(..., min_length=1, max_length=1024)
    category: str = Field(..., min_length=1, max_length=64)
    version: str = Field(..., min_length=1, max_length=32)
    maintainer: MaintainerType
    introduced_in: str = Field(..., min_length=1, max_length=32)
    last_reviewed_date: date
    deprecated: bool = False
    deprecated_replacement: Optional[str] = None
    kind: RegistryKind

    @field_validator("name")
    @classmethod
    def _name_is_snake_or_hyphen(cls, value: str) -> str:
        if not all(ch.isalnum() or ch in {"_", "-"} for ch in value):
            raise ValueError(
                f"Capability name {value!r} must be alphanumeric plus underscore/hyphen",
            )
        return value

    @field_validator("description")
    @classmethod
    def _description_has_content(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("description must contain non-whitespace content")
        return value

    @model_validator(mode="after")
    def _deprecated_requires_replacement(self) -> "BaseEntry":
        if self.deprecated and not self.deprecated_replacement:
            raise ValueError(
                f"Capability {self.name!r} marked deprecated=True but "
                f"deprecated_replacement is not set. Pass a replacement "
                f"name or 'retired:no_replacement' with a one-sentence "
                f"rationale in the description.",
            )
        if not self.deprecated and self.deprecated_replacement:
            raise ValueError(
                f"Capability {self.name!r} sets deprecated_replacement "
                f"but is not deprecated; unset one or the other.",
            )
        return self


def _validate_json_schema(schema: dict[str, Any], field_name: str) -> dict[str, Any]:
    """Check a dict is a valid Draft-7 JSON Schema (MCP-compatible shape)."""
    if not isinstance(schema, dict):
        raise ValueError(f"{field_name} must be a dict, got {type(schema).__name__}")
    try:
        Draft7Validator.check_schema(schema)
    except Exception as exc:
        raise ValueError(f"{field_name} is not a valid Draft-7 JSON Schema: {exc}") from exc
    if "type" not in schema:
        raise ValueError(f"{field_name} must declare a top-level 'type' field (MCP expects this)")
    return schema


class ActionEntry(BaseEntry):
    """A kickoff-able operation exposed to operators or automation.

    Maps cleanly to MCP tool definitions: `name`, `description`, and
    `input_schema` are the trio MCP servers expose. `output_schema`,
    `kickoff_endpoint`, and `estimated_duration` are halcyon-lab additions
    for dashboard UX.
    """

    kind: Literal["action"] = "action"
    kickoff_endpoint: str = Field(..., min_length=1)
    history_endpoint: Optional[str] = None
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    estimated_duration: str = Field(..., min_length=1, max_length=64)
    ui_kickoff_available: bool = True

    @field_validator("input_schema")
    @classmethod
    def _input_schema_valid(cls, value: dict[str, Any]) -> dict[str, Any]:
        return _validate_json_schema(value, "input_schema")

    @field_validator("output_schema")
    @classmethod
    def _output_schema_valid(cls, value: dict[str, Any]) -> dict[str, Any]:
        return _validate_json_schema(value, "output_schema")


class StateEntry(BaseEntry):
    """A read-only snapshot of some platform state.

    `query_function` is invoked at endpoint-request time. It must return a
    JSON-serializable dict with a `value` key (scalar or dict) for delta
    tracking. If the function raises or exceeds the endpoint's timeout,
    the endpoint returns an `unavailable` or `timeout` payload without
    breaking other entries' rendering.
    """

    kind: Literal["state"] = "state"
    query_function: Callable[[], dict[str, Any]]
    refresh_hint: str = Field(..., min_length=1, max_length=64)

    @field_validator("query_function")
    @classmethod
    def _query_is_callable(cls, value: Any) -> Callable[[], dict[str, Any]]:
        if not callable(value):
            raise ValueError("query_function must be callable")
        return value


class SystemEntry(BaseEntry):
    """A persistent background system with a health check.

    `health_check_function` returns a dict with at least `{status: ok|degraded|down, detail: str}`.
    Same timeout + isolation semantics as StateEntry.
    """

    kind: Literal["system"] = "system"
    health_check_function: Callable[[], dict[str, Any]]
    expected_runtime: str = Field(..., min_length=1, max_length=64)

    @field_validator("health_check_function")
    @classmethod
    def _health_is_callable(cls, value: Any) -> Callable[[], dict[str, Any]]:
        if not callable(value):
            raise ValueError("health_check_function must be callable")
        return value


class DecisionEntry(BaseEntry):
    """A strategic decision or configuration fact recorded for future review.

    Decisions don't have a natural code home (they're facts, not behaviors),
    so they're registered en-bloc by `src/platform/capability_registry/decisions.py`.
    The `revisit_trigger` documents under what condition to re-evaluate — it's
    the key artifact that fights drift on strategic decisions.
    """

    kind: Literal["decision"] = "decision"
    decision_text: str = Field(..., min_length=1, max_length=2048)
    rationale: str = Field(..., min_length=1, max_length=2048)
    revisit_trigger: str = Field(..., min_length=1, max_length=1024)
