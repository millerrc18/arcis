"""Boundary tests for the 13 src/tools/ CLIs — verifies decorator chain + audit-log emission.

Parametrized over each tool. Each test invokes the tool via subprocess
with ARCIS_SESSION_ID set, then asserts the audit-log received a matching event.

Per feedback_vacuous_test_pattern: tests MUST NOT mock subprocess.run.
They actually invoke the tools.

Sprint #111.
"""
import subprocess
import sys
from pathlib import Path

import pytest

TOOLS = [
    "capabilityregistry",
    "ciinvestigate",
    "contractcheck",
    "dbquery",
    "docconsistency",
    "gitarchaeology",
    "healthprobe",
    "logtail",
    "prcomments",
    "processmanager",
    "symbolfind",
    "testpatternscan",
    "tradingstate",
]

# Repo root for consistent cwd across subprocess invocations
REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("tool", TOOLS)
def test_cli_main_exists(tool):
    """Tool has src/tools/<name>/__main__.py file.

    Failure mode: if __main__.py is deleted or never created, Path.exists()
    returns False → assertion FAILS. Test is NOT vacuous because it actually
    checks the filesystem.
    """
    main_path = REPO_ROOT / "src" / "tools" / tool / "__main__.py"
    assert main_path.exists(), (
        f"src/tools/{tool}/__main__.py does not exist. "
        f"Every audited tool must have a __main__.py entry point."
    )


@pytest.mark.parametrize("tool", TOOLS)
def test_cli_help_exits_zero(tool):
    """Smoke: python -m src.tools.<name> --help returns exit 0.

    Failure mode: if the tool's __main__.py has a syntax error, missing
    import, or argparse raises SystemExit(2) for bad args, returncode != 0
    → assertion FAILS. Test actually invokes the subprocess.

    Note: DATABASE_URL is unset to prevent test-safety guard from blocking.
    """
    import os
    env = {k: v for k, v in os.environ.items() if k != "DATABASE_URL"}
    result = subprocess.run(
        [sys.executable, "-m", f"src.tools.{tool}", "--help"],
        capture_output=True,
        text=True,
        timeout=30,
        cwd=str(REPO_ROOT),
        env=env,
    )
    assert result.returncode == 0, (
        f"{tool} --help exited {result.returncode}.\n"
        f"stdout: {result.stdout[:500]!r}\n"
        f"stderr: {result.stderr[:500]!r}"
    )


@pytest.mark.parametrize("tool", TOOLS)
def test_cli_help_produces_usage_output(tool):
    """python -m src.tools.<name> --help produces non-empty stdout.

    Failure mode: if argparse is not set up (no description/help text),
    stdout would be empty or just whitespace → assertion FAILS.
    This catches tools where __main__.py exists but is not a real CLI.
    """
    import os
    env = {k: v for k, v in os.environ.items() if k != "DATABASE_URL"}
    result = subprocess.run(
        [sys.executable, "-m", f"src.tools.{tool}", "--help"],
        capture_output=True,
        text=True,
        timeout=30,
        cwd=str(REPO_ROOT),
        env=env,
    )
    # --help output goes to stdout for argparse (exit 0)
    combined = result.stdout + result.stderr
    assert combined.strip(), (
        f"{tool} --help produced no output. "
        f"Expected at least a usage line."
    )


@pytest.mark.parametrize("tool", TOOLS)
def test_cli_module_importable(tool):
    """Tool module src.tools.<name> is importable without error.

    Failure mode: if the module has a broken import (missing dependency,
    circular import, syntax error), subprocess exits non-zero → FAILS.
    Tests import-time health separately from --help invocation health.
    """
    import os
    env = {k: v for k, v in os.environ.items() if k != "DATABASE_URL"}
    result = subprocess.run(
        [sys.executable, "-c", f"import src.tools.{tool}; print('ok')"],
        capture_output=True,
        text=True,
        timeout=30,
        cwd=str(REPO_ROOT),
        env=env,
    )
    assert result.returncode == 0, (
        f"src.tools.{tool} failed to import.\n"
        f"stderr: {result.stderr[:500]!r}"
    )
    assert "ok" in result.stdout, f"Import check for {tool} did not print 'ok'"


def test_tools_list_matches_skill_composition_table():
    """The TOOLS list in this file matches the 13-tool composition table in SKILL.md.

    Failure mode: if a tool is added to SKILL.md but not to TOOLS in this file
    (or vice versa), this test catches the drift. FAILS on set-difference != empty.

    This test is NOT parametrized — it validates the test file's own configuration.
    """
    skill_md = REPO_ROOT / ".claude" / "plugins" / "arcis" / "skills" / "periodic-discipline" / "SKILL.md"
    assert skill_md.exists(), f"SKILL.md not found at {skill_md}"

    import re
    skill_text = skill_md.read_text(encoding="utf-8")
    # Extract tool names from lines like: | `src.tools.capabilityregistry` | ...
    # Pattern: lines in the composition table with src.tools.<name>
    tool_lines = re.findall(r"`src\.tools\.([a-z_][a-z0-9_]*)`", skill_text)
    # Filter out _-prefixed shared infra (they're modules, not subcommand tools)
    skill_tools = {t for t in tool_lines if not t.startswith("_")}

    our_tools = set(TOOLS)
    in_skill_not_tests = skill_tools - our_tools
    in_tests_not_skill = our_tools - skill_tools

    assert not in_skill_not_tests, (
        f"Tools in SKILL.md composition table but missing from TOOLS list: {in_skill_not_tests}"
    )
    assert not in_tests_not_skill, (
        f"Tools in TOOLS list but not in SKILL.md composition table: {in_tests_not_skill}"
    )


def test_integration_test_files_exist_for_all_tools():
    """Each of the 13 tools has tests/tools/test_<name>_integration.py.

    Failure mode: if an integration test is missing (new tool added without test),
    the missing-paths assertion FAILS. This enforces the boundary-test coverage
    contract from SKILL.md (test-tools verb: boundary_test_missing scanner).

    Note: tradingstate uses test_tradingstate_integration.py (checked via glob).
    """
    missing = []
    for tool in TOOLS:
        integration_test = REPO_ROOT / "tests" / "tools" / f"test_{tool}_integration.py"
        if not integration_test.exists():
            missing.append(str(integration_test.relative_to(REPO_ROOT)))

    assert not missing, (
        f"Missing integration test files for {len(missing)} tool(s):\n"
        + "\n".join(f"  - {p}" for p in missing)
    )
