# Capability Registry

> Single source of truth for "what does Halcyon Lab do, and what is its state?"

Introduced in v0.25.0 (Sprint 1B). Design rationale in
`docs/sprints/capability_registry_v1_evaluation.md`; research findings in
`docs/sprints/capability_registry_v1_research_findings.md`.

## What it is

Four in-process registries populated at import time via decorators:

| Registry | Decorator | Purpose |
|---|---|---|
| ACTIONS | `@register_action` | Kickoff-able operations (diagnostics, backtests, backfills) |
| STATES | `@register_state` | Read-only snapshots of platform state |
| SYSTEMS | `@register_system` | Persistent background systems with health checks |
| DECISIONS | `register_decision(...)` | Strategic facts + rationale + revisit trigger |

A unified endpoint `GET /api/system/index` serves all four as a single
JSON payload. Dashboards, CC sessions, and future MCP clients see the
same shape.

## Why it exists

Halcyon Lab is a solo-operator + AI-pair-programmer platform. Two
structural risks the registry mitigates:

- **Operator forgetting:** "What did we build 6 months ago? What's
  deprecated? What's configured but off?"
- **AI session context fragmentation:** Each CC / Claude session starts
  with partial context. The registry is a canonical, machine-readable
  table of contents.

Schema is MCP-compatible. v2 can wrap the registry as an MCP server
without any schema redesign.

## How to add a capability

### Action (kickoff-able operation)

```python
from datetime import date
from src.platform.capability_registry import register_action

@register_action(
    name="my_action",                           # snake_case or kebab-case
    description="One or two sentences.",
    category="diagnostics",                     # free-form grouping label
    version="1.0",
    maintainer="ai_session",                    # or "operator"
    introduced_in="v0.25.0",
    last_reviewed_date=date(2026, 4, 18),
    kickoff_endpoint="/api/my-action",          # URL or CLI command
    history_endpoint="/api/my-action/runs",     # optional
    input_schema={"type": "object", ...},       # valid Draft-7 JSON Schema
    output_schema={"type": "object", ...},
    estimated_duration="1-5 minutes",
    ui_kickoff_available=True,                  # False for CLI-only
)
def my_action_capability() -> dict:
    """Registration anchor; real kickoff hits the endpoint."""
    return {}
```

### State (read-only snapshot)

```python
from src.platform.capability_registry import register_state

@register_state(
    name="my_state",
    description="What this state tells you.",
    category="shadow-trading",
    version="1.0",
    maintainer="ai_session",
    introduced_in="v0.25.0",
    last_reviewed_date=date(2026, 4, 18),
    refresh_hint="real-time",
)
def my_state_query() -> dict:
    """Must return {'value': ...}. Called per request with 2s timeout."""
    return {"value": {"count": 42}}
```

### System (background daemon with health check)

```python
from src.platform.capability_registry import register_system

@register_system(
    name="my_daemon",
    description="What this daemon does.",
    category="orchestration",
    version="1.0",
    maintainer="operator",
    introduced_in="v0.25.0",
    last_reviewed_date=date(2026, 4, 18),
    expected_runtime="always",
)
def my_daemon_health() -> dict:
    """Must return {'status': 'ok'|'degraded'|'down', 'detail': str}."""
    return {"status": "ok", "detail": "running"}
```

### Decision (strategic fact — no code)

Add to `src/platform/capability_registry/decisions.py`:

```python
register_decision(
    name="my_decision",
    description="One-line summary.",
    category="strategy",
    version="1.0",
    maintainer="operator",
    introduced_in="v0.25.0",
    last_reviewed_date=date(2026, 4, 18),
    decision_text="We will do X.",
    rationale="Because Y is better than Z.",
    revisit_trigger="After N trades OR when condition X changes.",
)
```

### Don't forget the bootstrap

If your capability lives in a new module, add its dotted path to
`CAPABILITY_MODULES` in `src/platform/capability_registry/bootstrap.py`.
Existing modules (`src.diagnostics`, `src.platform`, etc.) are already
enumerated; adding a decorator inside them requires no bootstrap change.

## CI enforcement

`tests/test_capability_registry_metadata.py` runs on every PR. It:

1. Bootstraps the registry.
2. Fails if any decorator-time validation raised (ModuleNotFoundError
   tolerated during incremental rollout; full cleanliness enforced by
   `tests/test_capability_registry_integration.py`).
3. Verifies every entry has complete metadata.
4. Verifies deprecated entries have `deprecated_replacement`.
5. Validates Action input/output schemas as Draft-7 JSON Schema.
6. Emits warnings (not failures) for entries with `last_reviewed_date`
   older than 180 days. Warning-only policy per evaluation §4.5.

`tests/test_capability_registry_integration.py` is stricter and is the
authoritative final-state gate:

1. Zero bootstrap errors.
2. >= 18 capabilities registered.
3. Every registry type has entries.
4. `/api/system/index` round-trip + `/mark-reviewed` round-trip succeed.

## Deprecating a capability

Mark `deprecated=True` AND set `deprecated_replacement`. Options for the
replacement value:

- Another capability's `name` (most common: "superseded by X")
- `"retired:no_replacement"` — rare; document rationale in `description`

Deprecated entries remain in the registry so operators looking for them
see the redirect. Remove the decorator only after a release cycle where
the deprecation was visible.

## Stale threshold and Mark Reviewed

`last_reviewed_date` > 180 days = stale. The dashboard's card shows a
review pill; the detail modal has a Mark Reviewed button.

v1 stores the review override in `operator_view_state.last_reviewed_date_override`
(local SQLite, not synced to Postgres). v1.1 will automatically edit the
source file so the review persists across repo checkouts.

## FAQs

**Why not a DB-backed registry?** DB rows drift from code. The whole
point is that the code IS the row. See evaluation doc §3.1.

**Why four specialized registries, not one union?** Each entry type has
distinct required fields; union would force Optional on most fields and
erase the self-documenting schema. See evaluation doc §3.2.

**Why is `last_reviewed_date` hardcoded in each decorator?** It documents
"someone looked at this on date X." The Mark Reviewed override layer
adds a second signal; v1.1 reconciles them.

**How do I expose this as an MCP server?** Not v1 scope. The `input_schema`
/ `output_schema` are already Draft-7 JSON Schema (MCP-compatible), so
v2 can wrap the registries without schema work. See evaluation doc §4.7.
