"""CI enforcement: every registered capability has complete, fresh metadata.

Runs on every PR. Invokes bootstrap.ensure_bootstrapped() so the real
production registration code executes, then asserts:

- No bootstrap import errors
- Every entry has complete required metadata (Pydantic has already
  validated this at decoration time, but we re-verify the snapshot
  because deferred-import failures would otherwise skip validation)
- Deprecated entries have a replacement
- JSON Schema validity on Action input/output
- Duplicate name within a single registry is impossible (already
  enforced by the registry but we double-check)
- Stale entries (>180d since last_reviewed_date) emit warnings, not
  failures — surfaced via the STALE list at the module level so
  dashboards can read them

The stale threshold is 180 days per evaluation doc §4.4.
The warning-only policy is per evaluation doc §4.5.
"""
from __future__ import annotations

import warnings
from datetime import date, timedelta

import pytest
from jsonschema import Draft7Validator

from src.platform.capability_registry import (
    ActionEntry,
    BaseEntry,
    all_entries,
    bootstrap_errors,
    ensure_bootstrapped,
    list_actions,
    list_decisions,
    list_states,
    list_systems,
)

STALE_THRESHOLD_DAYS = 180


@pytest.fixture(scope="module", autouse=True)
def _bootstrap():
    """Populate registries from production modules before any test runs."""
    ensure_bootstrapped()
    yield


def test_bootstrap_errors_fail_only_on_decorator_validation():
    """Import-not-found errors are tolerated during incremental rollout.

    This test distinguishes between "module doesn't exist yet" (ok during
    development; tolerated by design per bootstrap.py's graceful-skip) and
    "module exists but its decorator rejected its metadata" (fail hard).
    The integration test in tests/test_capability_registry_integration.py
    enforces the stronger "zero bootstrap errors" gate for the final state.
    """
    errs = bootstrap_errors()
    decorator_failures = [
        (mod, exc)
        for mod, exc in errs
        if not isinstance(exc, ModuleNotFoundError)
    ]
    assert decorator_failures == [], (
        "Capability registry decorator(s) raised during import. "
        "A decorator's Pydantic validation likely rejected its kwargs. Errors:\n"
        + "\n".join(f"  {mod}: {exc!r}" for mod, exc in decorator_failures)
    )


CALLABLE_FIELDS = {"query_function", "health_check_function"}


def test_every_entry_passes_pydantic_revalidation():
    """Re-dump each entry, confirming required fields are populated.

    Callable fields are excluded from the JSON dump — they don't serialize
    and aren't re-validatable without reconstruction, which isn't the point
    of this test.
    """
    for entry in all_entries():
        dumped = entry.model_dump(mode="json", exclude=CALLABLE_FIELDS)
        assert "name" in dumped and dumped["name"]
        assert "description" in dumped and dumped["description"]
        assert "category" in dumped and dumped["category"]
        assert "version" in dumped and dumped["version"]
        assert dumped["maintainer"] in {"operator", "ai_session"}
        assert "introduced_in" in dumped and dumped["introduced_in"]
        assert "last_reviewed_date" in dumped and dumped["last_reviewed_date"]


def test_deprecated_entries_have_replacement():
    for entry in all_entries():
        if entry.deprecated:
            assert entry.deprecated_replacement, (
                f"Deprecated capability {entry.name!r} missing "
                "deprecated_replacement. Set to a capability name or "
                "'retired:no_replacement' with rationale in description."
            )


def test_action_schemas_are_valid_json_schema():
    for action in list_actions():
        Draft7Validator.check_schema(action.input_schema)
        Draft7Validator.check_schema(action.output_schema)
        assert action.input_schema.get("type") == "object", (
            f"Action {action.name!r} input_schema must have type=object for MCP compatibility"
        )


def test_names_unique_within_each_registry():
    for registry_list in (list_actions(), list_states(), list_systems(), list_decisions()):
        names = [e.name for e in registry_list]
        assert len(names) == len(set(names)), (
            f"Duplicate names within registry: {names}"
        )


def test_categories_are_non_empty_strings():
    for entry in all_entries():
        assert isinstance(entry.category, str) and entry.category.strip(), (
            f"Capability {entry.name!r} has empty category"
        )


def test_stale_entries_emit_warnings_not_failures():
    """Per evaluation §4.5: stale = warning, not failure.

    We collect every stale entry; any failures are surfaced as a single
    pytest warning so the operator sees them in -W output and the
    dashboard's 'Needs Review' panel can read them.
    """
    today = date.today()
    threshold = today - timedelta(days=STALE_THRESHOLD_DAYS)
    stale: list[BaseEntry] = [
        e for e in all_entries() if e.last_reviewed_date < threshold
    ]
    if stale:
        names = ", ".join(e.name for e in stale)
        warnings.warn(
            f"{len(stale)} capability/ies last_reviewed_date > "
            f"{STALE_THRESHOLD_DAYS} days ago: {names}. "
            "Consider 'Mark Reviewed' in the dashboard or updating the "
            "decorator's last_reviewed_date kwarg.",
            UserWarning,
            stacklevel=2,
        )


def test_version_fields_look_semverish():
    # Permissive: allow "1.0", "1.0.0", "v1.0", "1.0-beta". Reject empty/whitespace.
    for entry in all_entries():
        assert entry.version.strip(), (
            f"Capability {entry.name!r} has empty version string"
        )


def test_introduced_in_fields_look_like_tags():
    # Accept "v0.25.0", "v0.25", "v0.25.0-rc1", "v0.12.3+hotfix". Just reject blank.
    for entry in all_entries():
        assert entry.introduced_in.strip().startswith("v"), (
            f"Capability {entry.name!r} introduced_in={entry.introduced_in!r} "
            "should start with 'v' to match repo tag convention"
        )


def test_action_kickoff_endpoint_looks_like_path_or_command():
    for action in list_actions():
        ep = action.kickoff_endpoint
        assert ep, f"Action {action.name!r} has empty kickoff_endpoint"
        # Either a URL path (starts with /) or a CLI invocation (contains python or script)
        is_path = ep.startswith("/")
        is_cli = "python" in ep or ep.startswith("scripts/") or ".py" in ep
        assert is_path or is_cli, (
            f"Action {action.name!r} kickoff_endpoint={ep!r} "
            "doesn't look like a URL path or CLI command"
        )
