"""Capability Registry — self-introspecting system metadata.

Four specialized in-process registries populated at import time via
decorators:

    @register_action(...)   — kickoff-able operations (diagnostics, backtests)
    @register_state(...)    — read-only state queries
    @register_system(...)   — persistent background systems + health checks
    register_decision(...)  — strategic facts and configuration decisions

A unified endpoint GET /api/system/index serves all four as a single JSON
payload so dashboards, CC sessions, and future MCP clients see the same
source of truth.

See docs/capability_registry.md for the full spec and
docs/sprints/capability_registry_v1_evaluation.md for design rationale.
"""
from __future__ import annotations

from src.platform.capability_registry.schemas import (
    ActionEntry,
    BaseEntry,
    DecisionEntry,
    StateEntry,
    SystemEntry,
)

__all__ = [
    "ActionEntry",
    "BaseEntry",
    "DecisionEntry",
    "StateEntry",
    "SystemEntry",
]
