"""Minimal Draft-7 JSON Schema builder for capability ACTION I/O.

`simple_io_schema` returns a top-level `{type: "object", ...}` schema that
passes `jsonschema.Draft7Validator.check_schema` and satisfies the
capability registry's `ActionEntry.input_schema`/`output_schema` validators
(which require a dict that check_schema accepts and that declares a
top-level `type`). Used by the en-bloc ACTION registration hosts so each
handler/engine kickoff carries a real, non-empty I/O contract.

Called by: src.scheduler.handler_registration and other ACTION hosts
Calls: none
Owns tables: none
Config keys: none
Tests: tests/platform/test_io_schemas.py
"""
from __future__ import annotations

from typing import Any, Optional


def simple_io_schema(
    properties: Optional[dict[str, Any]] = None,
    required: Optional[list[str]] = None,
) -> dict[str, Any]:
    """Build a minimal valid Draft-7 object schema.

    Args:
        properties: Mapping of property name -> property subschema. Defaults
            to an empty object (no declared properties).
        required: List of required property names. Defaults to none required.

    Returns:
        A Draft-7 JSON Schema dict with top-level ``type: "object"``,
        suitable for ACTION ``input_schema``/``output_schema``.
    """
    return {
        "type": "object",
        "properties": properties or {},
        "required": required or [],
        "additionalProperties": False,
    }
