"""Cross-runbook frontmatter consistency tests for the operate skill.

Sibling-search prevention test added during PR #1180 dual-Opus QA cycle. Both
reviewers independently flagged that the only runbook frontmatter test target
was data-anomaly.md, which let the watchloop-wedged.md `risk:` vs `risk-level:`
drift ship through to the merge gate. This file parametrizes the schema check
across all 5 v1 runbooks so any future drift surfaces at commit time.

Called by: pytest
Calls: yaml.safe_load on each runbook
Owns tables: none
Config keys: none
Tests: 1 parametrized acceptance per runbook + 1 inline-matrix consistency check
"""
from pathlib import Path

import pytest
import yaml

RUNBOOKS_DIR = Path(__file__).resolve().parents[1] / (
    ".claude/plugins/arcis/skills/operate/runbooks"
)

REQUIRED_KEYS = {"name", "verb", "mutations", "risk-level", "required-tools"}
VALID_RISK_LEVELS = {"low", "medium", "high"}


def _parse_frontmatter(runbook_path: Path) -> dict:
    text = runbook_path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        raise AssertionError(
            f"{runbook_path.name} does not start with YAML frontmatter delimiter"
        )
    end_idx = text.find("\n---\n", 4)
    if end_idx == -1:
        raise AssertionError(
            f"{runbook_path.name} has no closing YAML frontmatter delimiter"
        )
    return yaml.safe_load(text[4:end_idx])


@pytest.mark.parametrize(
    "runbook_name",
    [
        "watchloop-wedged.md",
        "pg-tests-red.md",
        "training-failed.md",
        "gpu-degraded.md",
        "data-anomaly.md",
    ],
)
def test_runbook_frontmatter_required_keys(runbook_name: str) -> None:
    runbook_path = RUNBOOKS_DIR / runbook_name
    assert runbook_path.exists(), f"Runbook missing: {runbook_path}"
    fm = _parse_frontmatter(runbook_path)

    missing = REQUIRED_KEYS - set(fm.keys())
    assert not missing, (
        f"{runbook_name} frontmatter missing required key(s): {sorted(missing)}. "
        f"Spec §4 validator check (a) requires all of {sorted(REQUIRED_KEYS)}. "
        f"Note: the canonical risk key is `risk-level`, NOT `risk` (PR #1180 reviewer catch)."
    )

    assert fm["verb"] == "runbook", f"{runbook_name} verb must be 'runbook'"
    assert isinstance(fm["mutations"], bool), f"{runbook_name} mutations must be bool"
    assert fm["risk-level"] in VALID_RISK_LEVELS, (
        f"{runbook_name} risk-level={fm['risk-level']!r} not in {VALID_RISK_LEVELS}"
    )


def test_no_runbook_uses_legacy_risk_key() -> None:
    """Sibling-search test: ensure no runbook regresses to `risk:` (non-canonical).

    Spec §4 enumerates `risk-level` as the validator-required key. Allowing
    `risk:` would silently bypass the DA7 validator at runtime.
    """
    offenders = []
    for runbook_path in sorted(RUNBOOKS_DIR.glob("*.md")):
        fm = _parse_frontmatter(runbook_path)
        if "risk" in fm and "risk-level" not in fm:
            offenders.append(f"{runbook_path.name}: uses legacy `risk:` key only")
    assert not offenders, "Runbooks using non-canonical `risk:` key:\n  " + "\n  ".join(
        offenders
    )


def test_orchestrator_inline_matrix_matches_authorization_matrix() -> None:
    """Cross-file consistency: orchestrator inline summary must not list actions
    that the reference matrix removed.

    Both PR #1180 reviewers independently flagged that the orchestrator's
    inline action summary at commands/operate.md continued to list 3 removed
    actions (post-pr-summary, force-broker-poll, regenerate-stale-audit) after
    the reference matrix removed them. This test enforces consistency.
    """
    plugin_root = Path(__file__).resolve().parents[1] / ".claude/plugins/arcis"
    orchestrator = (plugin_root / "commands/operate.md").read_text(encoding="utf-8")
    matrix_path = (
        plugin_root / "skills/operate/references/action-authorization-matrix.md"
    )
    matrix = matrix_path.read_text(encoding="utf-8")

    removed_marker = "## Removed actions"
    assert removed_marker in matrix, "matrix missing 'Removed actions' section"
    removed_section = matrix.split(removed_marker, 1)[1].split("\n---", 1)[0]

    removed_actions = []
    for line in removed_section.splitlines():
        stripped = line.strip()
        if stripped.startswith("| `") and "removed reason" not in stripped.lower():
            action = stripped.split("`")[1]
            removed_actions.append(action)

    assert removed_actions, "Could not extract removed action names from matrix"

    inline_marker = "### Inline summary (full table in §7):"
    assert inline_marker in orchestrator, (
        "Orchestrator missing the '### Inline summary' marker — table layout changed?"
    )
    inline_section = orchestrator.split(inline_marker, 1)[1].split("\n---", 1)[0]
    inline_rows = [
        line.strip()
        for line in inline_section.splitlines()
        if line.strip().startswith("| `")
    ]

    listed_as_valid = []
    for action in removed_actions:
        for row in inline_rows:
            cells = [c.strip() for c in row.strip("|").split("|")]
            if cells and cells[0].strip("`").startswith(action):
                listed_as_valid.append(action)
                break

    assert not listed_as_valid, (
        f"Orchestrator inline summary table lists actions that the reference "
        f"matrix REMOVED: {listed_as_valid}. Drop the row(s) from the inline "
        f"summary or restore them in the reference matrix with --help probe "
        f"evidence. Prose callouts documenting the removal are fine — only "
        f"table rows that present a removed action as actionable count."
    )
