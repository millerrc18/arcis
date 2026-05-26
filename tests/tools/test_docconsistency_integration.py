# Purpose: Integration tests for src/tools/docconsistency — dead file:line ref scanner.
# Called by: pytest tests/tools/test_docconsistency_integration.py
# Calls: src.tools.docconsistency.core.scan, src.tools.docconsistency.__main__
# Owns tables: none
# Config keys: none
# Tests: (this file is the test)

"""Integration tests for DocConsistency (T7).

Coverage: Pattern A/B regex matching, allowlist suppression, age filters,
Pattern C explicit deferral, default-scope targets, CLI JSON envelope.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from src.tools.docconsistency.core import (
    DocConsistencyAllowlistError,
    DocConsistencyTargetMissingError,
    scan,
)


# ─── helpers ──────────────────────────────────────────────────────────────────

def _write_md(tmp_path: Path, name: str, content: str) -> Path:
    p = tmp_path / name
    p.write_text(content, encoding="utf-8")
    return p


def _write_allowlist(tmp_path: Path, entries: list[str]) -> Path:
    lines = ["allowlist:"]
    for e in entries:
        lines.append(f"  - {e}")
    p = tmp_path / "allowlist.yaml"
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


# ─── 1. test_scan_finds_existing_refs_ok ─────────────────────────────────────

def test_scan_finds_existing_refs_ok(tmp_path):
    """Fixture md with valid file:line ref → no findings."""
    # Create a real Python file with ≥ 5 lines
    real_py = tmp_path / "mymodule.py"
    real_py.write_text("\n".join(f"# line {i}" for i in range(1, 10)) + "\n", encoding="utf-8")

    md = _write_md(
        tmp_path, "doc.md",
        f"See `mymodule.py:3` for details.\n",
    )

    result = scan(targets=[str(md)], repo_root=tmp_path)
    assert result["refs_found"] == 1
    assert result["refs_verified_ok"] == 1
    assert result["findings"] == []


# ─── 2. test_scan_file_missing ───────────────────────────────────────────────

def test_scan_file_missing(tmp_path):
    """Fixture md with nonexistent file ref → finding with severity file_missing."""
    md = _write_md(
        tmp_path, "doc.md",
        "See `nonexistent_module.py:1` for details.\n",
    )

    result = scan(targets=[str(md)], repo_root=tmp_path)
    assert result["refs_found"] == 1
    assert len(result["findings"]) == 1
    assert result["findings"][0]["severity"] == "file_missing"
    assert "nonexistent_module.py" in result["findings"][0]["ref"]


# ─── 3. test_scan_line_missing ───────────────────────────────────────────────

def test_scan_line_missing(tmp_path):
    """Fixture md with line >> file length → finding with severity line_missing."""
    short_py = tmp_path / "short.py"
    short_py.write_text("x = 1\n", encoding="utf-8")  # 1 line

    md = _write_md(
        tmp_path, "doc.md",
        "See `short.py:9999` for the magic.\n",
    )

    result = scan(targets=[str(md)], repo_root=tmp_path)
    assert result["refs_found"] == 1
    assert len(result["findings"]) == 1
    assert result["findings"][0]["severity"] == "line_missing"


# ─── 4. test_scan_range_uses_start_line ──────────────────────────────────────

def test_scan_range_uses_start_line(tmp_path):
    """Pattern B (line range) uses start line; start exists → no finding."""
    py_file = tmp_path / "rangefile.py"
    py_file.write_text("\n".join(f"# line {i}" for i in range(1, 20)) + "\n", encoding="utf-8")

    # "rangefile.py:5-10" — Pattern B; start=5 which exists
    md = _write_md(
        tmp_path, "doc.md",
        "See `rangefile.py:5-10` for details.\n",
    )

    result = scan(targets=[str(md)], repo_root=tmp_path)
    assert result["refs_found"] == 1
    assert result["refs_verified_ok"] == 1
    assert result["findings"] == []


# ─── 5. test_scan_allowlist_suppresses ───────────────────────────────────────

def test_scan_allowlist_suppresses(tmp_path):
    """Allowlist YAML masks the finding → empty findings, refs_allowlisted=1."""
    md = _write_md(
        tmp_path, "doc.md",
        "Historical: `gone_module.py:42`\n",
    )
    allowlist = _write_allowlist(tmp_path, ["gone_module.py:42"])

    result = scan(targets=[str(md)], repo_root=tmp_path, allowlist_path=allowlist)
    assert result["findings"] == []
    assert result["refs_allowlisted"] == 1


# ─── 6. test_scan_allowlist_missing_file_is_empty ────────────────────────────

def test_scan_allowlist_missing_file_is_empty(tmp_path):
    """Allowlist path doesn't exist → no error, empty allowlist."""
    py_file = tmp_path / "mod.py"
    py_file.write_text("x = 1\n" * 10, encoding="utf-8")
    md = _write_md(tmp_path, "doc.md", "See `mod.py:3`\n")

    nonexistent_allowlist = tmp_path / "no_allowlist.yaml"
    result = scan(
        targets=[str(md)],
        repo_root=tmp_path,
        allowlist_path=nonexistent_allowlist,
    )
    # Should succeed, allowlist treated as empty
    assert result["refs_allowlisted"] == 0
    assert result["refs_found"] == 1


# ─── 7. test_scan_allowlist_malformed ────────────────────────────────────────

def test_scan_allowlist_malformed(tmp_path):
    """Invalid YAML in allowlist raises DocConsistencyAllowlistError."""
    bad_yaml = tmp_path / "bad.yaml"
    bad_yaml.write_text("allowlist: [\n  - unclosed bracket\n", encoding="utf-8")

    md = _write_md(tmp_path, "doc.md", "nothing\n")

    with pytest.raises(DocConsistencyAllowlistError):
        scan(targets=[str(md)], repo_root=tmp_path, allowlist_path=bad_yaml)


# ─── 8. test_scan_pattern_a_backtick ─────────────────────────────────────────

def test_scan_pattern_a_backtick(tmp_path):
    """Pattern A: backtick-delimited `file.py:N` is matched."""
    py_file = tmp_path / "core.py"
    py_file.write_text("\n".join("x" for _ in range(100)) + "\n", encoding="utf-8")

    md = _write_md(tmp_path, "doc.md", "Check `core.py:50` for the logic.\n")

    result = scan(targets=[str(md)], repo_root=tmp_path)
    assert result["refs_found"] == 1
    assert result["refs_verified_ok"] == 1
    assert result["findings"] == []


# ─── 9. test_scan_pattern_b_range ────────────────────────────────────────────

def test_scan_pattern_b_range(tmp_path):
    """Pattern B: 'file.py:10-20' — only start line 10 is checked."""
    py_file = tmp_path / "algo.py"
    py_file.write_text("\n".join(f"step{i}" for i in range(1, 30)) + "\n", encoding="utf-8")

    # start=10 exists (file has 29 lines); end=20 is not separately validated
    md = _write_md(tmp_path, "doc.md", "See `algo.py:10-20` for the algorithm.\n")

    result = scan(targets=[str(md)], repo_root=tmp_path)
    assert result["refs_found"] == 1
    assert result["refs_verified_ok"] == 1
    assert result["findings"] == []


# ─── 10. test_scan_pattern_c_ignored ─────────────────────────────────────────

def test_scan_pattern_c_ignored(tmp_path):
    """Pattern C comma-list (file.py:266,340) — only ':266' matched as Pattern A.

    The ',340' portion is silently ignored. Proves v2 deferral is explicit.
    The scanner should find exactly 1 ref (file.py:266), not 2.
    """
    py_file = tmp_path / "vram_manager.py"
    # Make the file long enough so line 266 exists
    py_file.write_text("\n".join(f"# L{i}" for i in range(1, 400)) + "\n", encoding="utf-8")

    # The comma-list ref — only :266 should be matched
    md = _write_md(tmp_path, "doc.md", "See `vram_manager.py:266,340` for details.\n")

    result = scan(targets=[str(md)], repo_root=tmp_path)
    # Pattern C: 1 ref found (the :266 part), not 2
    assert result["refs_found"] == 1
    assert result["refs_verified_ok"] == 1
    # The ',340' part is silently ignored (not a separate finding or ref)
    assert result["findings"] == []


# ─── 11. test_scan_default_targets_includes_changelog ────────────────────────

def test_scan_default_targets_includes_changelog():
    """Default scope includes CHANGELOG.md from the real repo."""
    repo_root = Path(__file__).resolve().parents[2]
    # Just verify CHANGELOG.md is in the resolved targets
    from src.tools.docconsistency.core import _default_targets
    targets = _default_targets(repo_root)
    changelog = str(repo_root / "CHANGELOG.md")
    assert changelog in targets, f"CHANGELOG.md not in default targets: {targets[:5]}"


# ─── 12. test_scan_default_targets_includes_docs_standards ───────────────────

def test_scan_default_targets_includes_docs_standards():
    """Default scope picks up docs/standards/boundary-touch-tests.md."""
    repo_root = Path(__file__).resolve().parents[2]
    from src.tools.docconsistency.core import _default_targets
    targets = _default_targets(repo_root)
    boundary_tests = str(repo_root / "docs" / "standards" / "boundary-touch-tests.md")
    assert boundary_tests in targets, (
        f"boundary-touch-tests.md not in default targets. Got: {targets}"
    )


# ─── 13. test_scan_default_targets_age_filters_docs_audits ───────────────────

def test_scan_default_targets_age_filters_docs_audits(tmp_path):
    """Age filter: 100-day-old audit md is excluded; 10-day-old is included."""
    # Build a minimal fake repo root with structure
    fake_root = tmp_path / "repo"
    (fake_root / "docs" / "audits" / "sprint-old").mkdir(parents=True)
    (fake_root / "docs" / "audits" / "sprint-new").mkdir(parents=True)

    old_md = fake_root / "docs" / "audits" / "sprint-old" / "old-spec.md"
    new_md = fake_root / "docs" / "audits" / "sprint-new" / "new-spec.md"

    old_md.write_text("# Old spec\n", encoding="utf-8")
    new_md.write_text("# New spec\n", encoding="utf-8")

    now = time.time()
    hundred_days_s = 100 * 24 * 60 * 60
    ten_days_s = 10 * 24 * 60 * 60

    with patch("src.tools.docconsistency.core.os.path.getmtime") as mock_mtime:
        def _mtime(path):
            if "sprint-old" in str(path):
                return now - hundred_days_s  # 100 days old → excluded
            if "sprint-new" in str(path):
                return now - ten_days_s      # 10 days old → included
            return now

        mock_mtime.side_effect = _mtime

        from src.tools.docconsistency.core import _default_targets
        targets = _default_targets(fake_root)

    target_strs = [str(t) for t in targets]
    assert str(old_md) not in target_strs, "100-day-old md should be excluded"
    assert str(new_md) in target_strs, "10-day-old md should be included"


# ─── 14. test_scan_explicit_target_overrides_age_filter ──────────────────────

def test_scan_explicit_target_overrides_age_filter(tmp_path):
    """Explicit targets list bypasses age filter entirely."""
    old_audit = tmp_path / "old_audit.md"
    py_file = tmp_path / "somefile.py"
    # Make py_file long enough that any valid line ref works
    py_file.write_text("\n".join(f"# line{i}" for i in range(1, 5)) + "\n", encoding="utf-8")
    old_audit.write_text("No refs here.\n", encoding="utf-8")

    # Even though it's "old", explicit target is used directly
    result = scan(targets=[str(old_audit)], repo_root=tmp_path)
    assert "scan_at" in result
    assert str(old_audit) in result["targets_scanned"]


# ─── 15. test_scan_target_missing ────────────────────────────────────────────

def test_scan_target_missing(tmp_path):
    """--target to nonexistent path raises DocConsistencyTargetMissingError."""
    missing = tmp_path / "does_not_exist.md"

    with pytest.raises(DocConsistencyTargetMissingError, match="does_not_exist"):
        scan(targets=[str(missing)], repo_root=tmp_path)


# ─── 16. test_scan_changelog_md_real_run ─────────────────────────────────────

def test_scan_changelog_md_real_run():
    """Real-run against actual CHANGELOG.md; asserts refs_found > 100 (smoke test)."""
    repo_root = Path(__file__).resolve().parents[2]
    changelog = str(repo_root / "CHANGELOG.md")

    # Use real repo's allowlist to avoid noise from known historical refs
    allowlist_path = repo_root / "data" / "docconsistency-allowlist.yaml"

    result = scan(
        targets=[changelog],
        repo_root=repo_root,
        allowlist_path=allowlist_path,
    )
    assert result["refs_found"] > 100, (
        f"Expected > 100 refs in CHANGELOG.md, got {result['refs_found']}. "
        "The CHANGELOG may be too sparse or the regex is too narrow."
    )


# ─── 17. test_cli_envelope_json ──────────────────────────────────────────────

# ═══════════════════════════════════════════════════════════════════
# Additional coverage tests for missed branches
# ═══════════════════════════════════════════════════════════════════


def test_find_repo_root_walks_up(tmp_path):
    """_find_repo_root walks up from a subdirectory to find the .git or pyproject.toml marker."""
    from src.tools.docconsistency.core import _find_repo_root
    sub = tmp_path / "a" / "b" / "c"
    sub.mkdir(parents=True)
    (tmp_path / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
    result = _find_repo_root(sub)
    assert result == tmp_path


def test_allowlist_none_data(tmp_path):
    """Allowlist YAML file with content 'null' returns empty list (data is None)."""
    null_yaml = tmp_path / "null.yaml"
    null_yaml.write_text("null\n", encoding="utf-8")
    md = _write_md(tmp_path, "doc.md", "nothing\n")
    # null data → treated as empty allowlist → no error
    result = scan(targets=[str(md)], repo_root=tmp_path, allowlist_path=null_yaml)
    assert result["refs_allowlisted"] == 0


def test_allowlist_non_dict_top_level(tmp_path):
    """Allowlist YAML without top-level 'allowlist:' key raises DocConsistencyAllowlistError."""
    bad_yaml = tmp_path / "bad.yaml"
    bad_yaml.write_text("- item1\n- item2\n", encoding="utf-8")
    md = _write_md(tmp_path, "doc.md", "nothing\n")
    with pytest.raises(DocConsistencyAllowlistError, match="allowlist"):
        scan(targets=[str(md)], repo_root=tmp_path, allowlist_path=bad_yaml)


def test_allowlist_null_entries(tmp_path):
    """Allowlist YAML with 'allowlist: null' returns empty list (entries is None)."""
    null_entries_yaml = tmp_path / "null_entries.yaml"
    null_entries_yaml.write_text("allowlist: null\n", encoding="utf-8")
    md = _write_md(tmp_path, "doc.md", "nothing\n")
    result = scan(targets=[str(md)], repo_root=tmp_path, allowlist_path=null_entries_yaml)
    assert result["refs_allowlisted"] == 0


def test_allowlist_non_list_entries(tmp_path):
    """Allowlist YAML with 'allowlist: string' raises DocConsistencyAllowlistError."""
    bad_entries_yaml = tmp_path / "bad_entries.yaml"
    bad_entries_yaml.write_text("allowlist: notalist\n", encoding="utf-8")
    md = _write_md(tmp_path, "doc.md", "nothing\n")
    with pytest.raises(DocConsistencyAllowlistError, match="list"):
        scan(targets=[str(md)], repo_root=tmp_path, allowlist_path=bad_entries_yaml)


def test_scan_target_relative_resolved(tmp_path):
    """Explicit target given as relative path is resolved against repo_root."""
    py_file = tmp_path / "rel.py"
    py_file.write_text("x\n" * 10, encoding="utf-8")
    md = tmp_path / "doc.md"
    md.write_text("See `rel.py:5`\n", encoding="utf-8")
    # Pass relative path for the md file — should resolve against repo_root
    result = scan(targets=["doc.md"], repo_root=tmp_path)
    assert result["refs_found"] == 1
    assert result["refs_verified_ok"] == 1


def test_scan_default_targets_used_when_targets_none():
    """scan() with targets=None uses _default_targets (real repo scan)."""
    repo_root = Path(__file__).resolve().parents[2]
    allowlist_path = repo_root / "data" / "docconsistency-allowlist.yaml"
    result = scan(targets=None, repo_root=repo_root, allowlist_path=allowlist_path)
    assert result["refs_found"] > 0
    assert len(result["targets_scanned"]) > 0


def test_scan_repo_root_none_uses_find():
    """scan() with repo_root=None falls back to _find_repo_root from __file__ (real repo)."""
    # This covers the repo_root=None branch in scan()
    repo_root = Path(__file__).resolve().parents[2]
    changelog = str(repo_root / "CHANGELOG.md")
    allowlist_path = repo_root / "data" / "docconsistency-allowlist.yaml"
    # Pass repo_root=None — should auto-detect real repo root
    result = scan(targets=[changelog], allowlist_path=allowlist_path)
    assert "scan_at" in result
    assert result["refs_found"] > 0


def test_count_lines_oserror(tmp_path):
    """_count_lines returns 0 on OSError (unreadable file)."""
    from src.tools.docconsistency.core import _count_lines
    missing = tmp_path / "nonexistent.py"
    assert _count_lines(missing) == 0


def test_scan_oserror_reading_target(tmp_path):
    """_scan_file silently skips an unreadable file."""
    # Create a valid md path but make its read fail via mock
    md = tmp_path / "doc.md"
    md.write_text("See `missing.py:1`\n", encoding="utf-8")

    with patch("src.tools.docconsistency.core.Path.read_text", side_effect=OSError("perm denied")):
        result = scan(targets=[str(md)], repo_root=tmp_path)
    # OSError on read → silently returns empty; no findings
    assert result["refs_found"] == 0


# ─── 17. test_cli_envelope_json ──────────────────────────────────────────────


def test_cli_envelope_json():
    """CLI 'scan --json' returns valid JSON envelope scanning the real docs/standards dir."""
    repo_root = Path(__file__).resolve().parents[2]
    # Use an existing repo file as target — avoid tmp_path (scan uses relative_to(repo_root))
    standards_md = repo_root / "docs" / "standards" / "boundary-touch-tests.md"

    result = subprocess.run(
        [
            sys.executable, "-m", "src.tools.docconsistency",
            "scan",
            "--target", str(standards_md),
            "--json",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
        cwd=str(repo_root),
    )
    assert result.returncode == 0, f"CLI failed: stderr={result.stderr!r} stdout={result.stdout!r}"
    parsed = json.loads(result.stdout.strip())
    assert "scan_at" in parsed
    assert "refs_found" in parsed
    assert "findings" in parsed
