"""Tests for the workflow_parity scanner logic in audit-skills.md Scanner 4.

Verifies that the scanner is job-aware: it compares each verb's runbook tools
against the corresponding CI job's tools only (not the union of all jobs).

This eliminates the false-positive class where tools from one CI job appear as
'missing_in_runbook' for an unrelated verb's runbook.
"""

import json
import os
import re
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
import yaml

AUDIT_SKILLS_MD = Path(
    ".claude/plugins/arcis/skills/periodic-discipline/audits/audit-skills.md"
)

# Minimal fake workflow YAML — two jobs, each using different tools.
# audit-skills uses docconsistency + _execution_log
# test-tools uses _execution_log only
FAKE_WORKFLOW_YAML = """
jobs:
  audit-skills:
    steps:
      - name: Run
        run: |
          python -m src.tools._execution_log --tool-name x
          python -m src.tools.docconsistency scan --json --target .
  test-tools:
    steps:
      - name: Run
        run: |
          python -m src.tools._execution_log --tool-name y
"""

# Minimal runbook content for each verb
RUNBOOK_AUDIT_SKILLS = "python -m src.tools._execution_log\npython -m src.tools.docconsistency scan"
RUNBOOK_CURATE_MEMORY = "python -m src.tools._execution_log"
RUNBOOK_TEST_TOOLS = "python -m src.tools._execution_log"


def _extract_scanner4_code(md_path: Path) -> str:
    """Extract the python-c block from Scanner 4 in audit-skills.md."""
    text = md_path.read_text(encoding="utf-8")
    # Find Scanner 4 section
    scanner4_match = re.search(
        r"## Scanner 4: workflow_parity.*?```bash\n(.*?)```",
        text,
        re.DOTALL,
    )
    assert scanner4_match, "Could not find Scanner 4 bash block in audit-skills.md"
    bash_block = scanner4_match.group(1)
    # Extract the python -c "..." block content
    py_match = re.search(r'python -c "\n(.*?)" >> "\$RAW"', bash_block, re.DOTALL)
    assert py_match, "Could not find python -c block inside Scanner 4 bash block"
    return textwrap.dedent(py_match.group(1))


def _run_scanner4_with_mocks(
    wf_yaml: str,
    runbooks: dict[str, str],
    tmp_path: Path,
) -> list[dict]:
    """
    Run the Scanner 4 Python logic in a subprocess against mock files.
    Returns parsed findings list.
    """
    # Write mock workflow file
    wf_path = tmp_path / ".github" / "workflows" / "periodic-discipline.yml"
    wf_path.parent.mkdir(parents=True)
    wf_path.write_text(wf_yaml, encoding="utf-8")

    # Write mock runbook files
    audits_dir = tmp_path / ".claude/plugins/arcis/skills/periodic-discipline/audits"
    audits_dir.mkdir(parents=True)
    for verb, content in runbooks.items():
        (audits_dir / f"{verb}.md").write_text(content, encoding="utf-8")

    # Extract the scanner code
    scanner_code = _extract_scanner4_code(AUDIT_SKILLS_MD)

    # Patch file paths to use tmp_path
    patched_code = scanner_code.replace(
        "Path('.github/workflows/periodic-discipline.yml')",
        f"Path(r'{wf_path}')",
    ).replace(
        "Path(f'.claude/plugins/arcis/skills/periodic-discipline/audits/{verb}.md')",
        f"Path(r'{audits_dir}') / f'{{verb}}.md'",
    )

    # Write patched script to temp file
    script = tmp_path / "scanner4.py"
    script.write_text(patched_code, encoding="utf-8")

    env = os.environ.copy()
    env["PD_TS"] = "2026-01-01T00:00:00Z"
    env["INVOCATION_ID"] = "TEST-001"

    result = subprocess.run(
        [sys.executable, str(script)],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(tmp_path),
    )
    assert result.returncode == 0, f"Scanner exited non-zero:\n{result.stderr}"

    findings = []
    for line in result.stdout.strip().splitlines():
        if line.strip():
            findings.append(json.loads(line))
    return findings


class TestWorkflowParityScannerJobAware:
    """Scanner 4 must be job-aware: compare each verb to its own CI job only."""

    def test_no_false_positives_curate_memory_skipped(self, tmp_path):
        """curate-memory has no CI job — scanner must skip it silently (no findings)."""
        findings = _run_scanner4_with_mocks(
            FAKE_WORKFLOW_YAML,
            {
                "audit-skills": RUNBOOK_AUDIT_SKILLS,
                "curate-memory": RUNBOOK_CURATE_MEMORY,
                "test-tools": RUNBOOK_TEST_TOOLS,
            },
            tmp_path,
        )
        curate_findings = [
            f for f in findings if "curate-memory" in f.get("root_cause_key", "")
        ]
        assert curate_findings == [], (
            f"curate-memory must produce zero findings (has no CI job), "
            f"got: {curate_findings}"
        )

    def test_no_false_positives_test_tools_uses_own_job(self, tmp_path):
        """test-tools runbook uses only _execution_log; test-tools CI job uses only
        _execution_log. No missing_in_runbook finding should fire for docconsistency."""
        findings = _run_scanner4_with_mocks(
            FAKE_WORKFLOW_YAML,
            {
                "audit-skills": RUNBOOK_AUDIT_SKILLS,
                "curate-memory": RUNBOOK_CURATE_MEMORY,
                "test-tools": RUNBOOK_TEST_TOOLS,
            },
            tmp_path,
        )
        test_tools_drift = [
            f
            for f in findings
            if "test-tools" in f.get("root_cause_key", "")
            and "docconsistency" in f.get("root_cause_key", "")
        ]
        assert test_tools_drift == [], (
            f"docconsistency must NOT appear as missing_in_runbook for test-tools "
            f"(it belongs to audit-skills job only), got: {test_tools_drift}"
        )

    def test_zero_findings_when_all_pairs_match(self, tmp_path):
        """When every CI job matches its runbook exactly, zero findings emitted."""
        findings = _run_scanner4_with_mocks(
            FAKE_WORKFLOW_YAML,
            {
                "audit-skills": RUNBOOK_AUDIT_SKILLS,
                "curate-memory": RUNBOOK_CURATE_MEMORY,
                "test-tools": RUNBOOK_TEST_TOOLS,
            },
            tmp_path,
        )
        non_advisory = [f for f in findings if not f.get("advisory", False)]
        assert non_advisory == [], (
            f"Expected zero workflow_drift findings, got: {non_advisory}"
        )

    def test_real_mismatch_still_detected(self, tmp_path):
        """A genuine mismatch (tool in CI job but not in its runbook) IS flagged."""
        findings = _run_scanner4_with_mocks(
            FAKE_WORKFLOW_YAML,
            {
                "audit-skills": "python -m src.tools._execution_log",  # missing docconsistency
                "test-tools": RUNBOOK_TEST_TOOLS,
            },
            tmp_path,
        )
        missing_in_rb = [
            f
            for f in findings
            if "missing_in_runbook" in f.get("root_cause_key", "")
            and "audit-skills" in f.get("root_cause_key", "")
            and "docconsistency" in f.get("root_cause_key", "")
        ]
        assert len(missing_in_rb) == 1, (
            f"Expected exactly 1 missing_in_runbook finding for audit-skills/docconsistency, "
            f"got: {missing_in_rb}"
        )

    def test_workflow_missing_exits_cleanly(self, tmp_path):
        """When the workflow file doesn't exist, scanner exits 0 with no output."""
        audits_dir = tmp_path / ".claude/plugins/arcis/skills/periodic-discipline/audits"
        audits_dir.mkdir(parents=True)
        (audits_dir / "audit-skills.md").write_text(RUNBOOK_AUDIT_SKILLS, encoding="utf-8")

        scanner_code = _extract_scanner4_code(AUDIT_SKILLS_MD)
        wf_path = tmp_path / ".github" / "workflows" / "periodic-discipline.yml"
        patched_code = scanner_code.replace(
            "Path('.github/workflows/periodic-discipline.yml')",
            f"Path(r'{wf_path}')",
        ).replace(
            "Path(f'.claude/plugins/arcis/skills/periodic-discipline/audits/{verb}.md')",
            f"Path(r'{audits_dir}') / f'{{verb}}.md'",
        )

        script = tmp_path / "scanner4_nowf.py"
        script.write_text(patched_code, encoding="utf-8")

        env = os.environ.copy()
        env["PD_TS"] = "2026-01-01T00:00:00Z"
        env["INVOCATION_ID"] = "TEST-002"

        result = subprocess.run(
            [sys.executable, str(script)],
            capture_output=True,
            text=True,
            env=env,
            cwd=str(tmp_path),
        )
        assert result.returncode == 0, f"Scanner should exit 0 when workflow missing, got stderr: {result.stderr}"
        assert result.stdout.strip() == "", (
            f"Scanner should emit no output when workflow missing, got: {result.stdout!r}"
        )
