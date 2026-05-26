"""Tests for the data-anomaly operate runbook.

Called by: test suite
Calls: none
Owns tables: none
Config keys: none
Tests: .claude/plugins/arcis/skills/operate/runbooks/data-anomaly.md
"""
import re
from pathlib import Path

import yaml

RUNBOOK_PATH = Path(
    ".claude/plugins/arcis/skills/operate/runbooks/data-anomaly.md"
)


def _read_runbook() -> str:
    return RUNBOOK_PATH.read_text(encoding="utf-8")


def _parse_frontmatter(content: str) -> dict:
    parts = content.split("---")
    # parts[0] is empty string before first ---
    # parts[1] is the frontmatter YAML
    return yaml.safe_load(parts[1])


def test_runbook_file_exists():
    """The runbook file must exist at the expected path."""
    assert RUNBOOK_PATH.exists(), f"Expected runbook at {RUNBOOK_PATH}"


def test_frontmatter_mutations_false():
    """mutations must be false (diagnostic-only)."""
    content = _read_runbook()
    fm = _parse_frontmatter(content)
    assert fm["mutations"] is False, (
        f"mutations must be false, got {fm['mutations']!r}"
    )


def test_frontmatter_required_tools_capabilityregistry():
    """required-tools must include 'capabilityregistry' (FB1: Python module name, not conceptual name)."""
    content = _read_runbook()
    fm = _parse_frontmatter(content)
    required_tools = fm.get("required-tools", [])
    assert "capabilityregistry" in required_tools, (
        f"required-tools must include 'capabilityregistry', got {required_tools!r}"
    )


def test_frontmatter_required_tools_no_capabilityregistryquery():
    """required-tools must NOT include 'capabilityregistryquery' (FB1: that is a conceptual name, not a module)."""
    content = _read_runbook()
    fm = _parse_frontmatter(content)
    required_tools = fm.get("required-tools", [])
    assert "capabilityregistryquery" not in required_tools, (
        f"required-tools must not include 'capabilityregistryquery' (FB1 violation), got {required_tools!r}"
    )


def test_five_steps_present():
    """The runbook must have exactly 5 numbered steps."""
    content = _read_runbook()
    # Match "### Step N —" patterns in the body
    step_matches = re.findall(r"^### Step \d+", content, re.MULTILINE)
    assert len(step_matches) == 5, (
        f"Expected 5 steps, found {len(step_matches)}: {step_matches}"
    )


def test_abcd_categorization_present():
    """A/B/C/D categorization must be prose-defined (at least 4 category labels)."""
    content = _read_runbook()
    # Look for A., B., C., D. category labels
    category_matches = re.findall(r"\b[ABCD]\.", content)
    unique_cats = set(category_matches)
    assert len(unique_cats) >= 4, (
        f"Expected A. B. C. D. categorization, found only: {unique_cats}"
    )


def test_frontmatter_name_matches_filename():
    """name field in frontmatter must match the filename."""
    content = _read_runbook()
    fm = _parse_frontmatter(content)
    assert fm["name"] == "data-anomaly", (
        f"name must be 'data-anomaly', got {fm['name']!r}"
    )


def test_frontmatter_verb_is_runbook():
    """verb field must be 'runbook'."""
    content = _read_runbook()
    fm = _parse_frontmatter(content)
    assert fm["verb"] == "runbook", f"verb must be 'runbook', got {fm['verb']!r}"


def test_db_investigator_dynamic_context_shape():
    """db-investigator DYNAMIC CONTEXT must mirror GQ1 shape: MANDATE, INVESTIGATION_MODE, WORKTREE_PATH fields."""
    content = _read_runbook()
    # The GQ1 shape requires MANDATE, INVESTIGATION_MODE, and optionally FOCUS_TABLES, WORKTREE_PATH
    assert "**MANDATE:**" in content, "DYNAMIC CONTEXT must include MANDATE field"
    assert "**INVESTIGATION_MODE:**" in content, "DYNAMIC CONTEXT must include INVESTIGATION_MODE field"
    assert "**WORKTREE_PATH:**" in content, "DYNAMIC CONTEXT must include WORKTREE_PATH field"


def test_no_deferral_language():
    """Runbook must not contain deferral language per spec.

    The spec prohibits 'we'll do later' / 'handle later' / 'future task' patterns.
    'out of skill scope' in the Escalation section is legitimate spec-authored boundary
    prose, not deferral of findings — so only exact deferral phrases are banned.
    """
    content = _read_runbook()
    deferral_patterns = [
        "we'll do later",
        "handle later",
        "future task",
        "we will do later",
    ]
    lower_content = content.lower()
    for pattern in deferral_patterns:
        assert pattern not in lower_content, (
            f"Runbook contains deferral language: '{pattern}'"
        )


def test_rollback_section_diagnostic_only():
    """Rollback section must note diagnostic-only / no mutations."""
    content = _read_runbook()
    assert "## Rollback" in content, "Runbook must have a ## Rollback section"
    rollback_start = content.index("## Rollback")
    rollback_section = content[rollback_start:rollback_start + 300]
    lower = rollback_section.lower()
    assert "diagnostic" in lower or "no mutation" in lower, (
        "Rollback section must note diagnostic-only nature"
    )


def test_abandonment_recovery_noop():
    """Abandonment recovery section must note no-op (mutations=false)."""
    content = _read_runbook()
    assert "Abandonment recovery" in content or "abandonment recovery" in content.lower(), (
        "Runbook must have an abandonment recovery section"
    )
    lower = content.lower()
    idx = lower.index("abandonment recovery")
    section = content[idx:idx + 400]
    assert "no-op" in section.lower() or "no mutations" in section.lower() or "diagnostic" in section.lower(), (
        "Abandonment recovery section must note it is a no-op for diagnostic runbooks"
    )
