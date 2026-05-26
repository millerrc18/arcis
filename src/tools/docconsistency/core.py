"""DocConsistency v1 core — regex scanner for dead file:line refs in markdown docs.

Purpose: Scan documentation files for inline `file.py:N` or `file.py:N-M`
references and verify each referred file exists with at least that many lines.
Implements class (a) ONLY — dead file:line refs. Classes (b) API signature
drift, (c) docstring-vs-code drift, and (d) symbol existence are deferred.

Called by: src.tools.docconsistency.__main__, src.tools.docconsistency.__init__
Calls: re, yaml, os.path.getmtime (stdlib only — no cross-tool deps)
Owns tables: none
Config keys: none (uses data/docconsistency-allowlist.yaml by convention)
Tests: tests/tools/test_docconsistency_integration.py
"""

from __future__ import annotations

import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from src.tools._safety import safe_op


# ═══════════════════════════════════════════════════════════════════
# Error classes
# ═══════════════════════════════════════════════════════════════════


class DocConsistencyError(RuntimeError):
    """Root error for the DocConsistency tool."""


class DocConsistencyAllowlistError(DocConsistencyError):
    """Raised when the allowlist YAML file is present but malformed."""


class DocConsistencyTargetMissingError(DocConsistencyError):
    """Raised when an explicitly-specified --target path does not exist on disk."""


# ═══════════════════════════════════════════════════════════════════
# Regex — Pattern A (single line) and Pattern B (line range)
# Pattern C (comma-list e.g. file.py:266,340) is intentionally NOT matched — v2 deferral.
# ═══════════════════════════════════════════════════════════════════

_REF_PATTERN = re.compile(
    r"`?"                                              # optional opening backtick
    r"(?P<path>[\w/.\-]+\.(?:py|md|yaml|yml|json|sql|toml|ini|cfg|sh|js|ts|html))"
    r":"
    r"(?P<line>\d+)"
    r"(?:-\d+)?"                                       # optional end of range — capture only start
    r"`?"                                              # optional closing backtick
)

# Age filter constant: 90 days in seconds
_NINETY_DAYS_S = 90 * 24 * 60 * 60


# ═══════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════


def _find_repo_root(start: Path) -> Path:
    """Walk up from start until we find a directory containing .git or pyproject.toml."""
    current = start.resolve()
    for _ in range(20):
        if (current / ".git").exists() or (current / "pyproject.toml").exists():
            return current
        parent = current.parent
        if parent == current:
            break
        current = parent
    return start.resolve()


def _default_targets(repo_root: Path) -> list[str]:
    """Return the default list of target file paths to scan.

    Always includes CHANGELOG.md and README.md. Includes every .md in
    docs/standards/ (gracefully returns [] if directory is empty or missing).
    Includes docs/operator-guide.md and docs/cli-reference.md if they exist.
    Includes every .md in docs/audits/ whose mtime is within the last 90 days.
    """
    now_ts = time.time()
    targets: list[str] = []

    # Always scan CHANGELOG.md and README.md (no age filter)
    for name in ("CHANGELOG.md", "README.md"):
        p = repo_root / name
        if p.is_file():
            targets.append(str(p))

    # Every .md in docs/standards/ (graceful on missing or empty directory)
    standards_dir = repo_root / "docs" / "standards"
    if standards_dir.is_dir():
        for p in sorted(standards_dir.glob("*.md")):
            targets.append(str(p))

    # Fixed documentation files
    for rel in ("docs/operator-guide.md", "docs/cli-reference.md"):
        p = repo_root / rel
        if p.is_file():
            targets.append(str(p))

    # Every .md in docs/audits/ modified within the last 90 days
    audits_dir = repo_root / "docs" / "audits"
    if audits_dir.is_dir():
        for p in sorted(audits_dir.rglob("*.md")):
            try:
                mtime = os.path.getmtime(str(p))
                if (now_ts - mtime) <= _NINETY_DAYS_S:
                    targets.append(str(p))
            except OSError:
                pass

    return targets


def _load_allowlist(path: Path) -> list[str]:
    """Load the allowlist YAML file and return the list of suppressed refs.

    Returns empty list if the file does not exist (graceful fresh-clone behavior).
    Raises DocConsistencyAllowlistError if the file exists but is malformed.
    """
    if not path.is_file():
        return []

    try:
        raw = path.read_text(encoding="utf-8")
        data = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise DocConsistencyAllowlistError(
            f"allowlist YAML malformed at {path}: {exc}"
        ) from exc
    except OSError as exc:
        raise DocConsistencyAllowlistError(
            f"allowlist YAML could not be read at {path}: {exc}"
        ) from exc

    if data is None:
        return []

    if not isinstance(data, dict) or "allowlist" not in data:
        raise DocConsistencyAllowlistError(
            f"allowlist YAML at {path} must have a top-level 'allowlist:' key; "
            f"got: {type(data).__name__}"
        )

    entries = data["allowlist"]
    if entries is None:
        return []

    if not isinstance(entries, list):
        raise DocConsistencyAllowlistError(
            f"allowlist YAML 'allowlist:' value at {path} must be a list; "
            f"got: {type(entries).__name__}"
        )

    return [str(e) for e in entries]


def _count_lines(file_path: Path) -> int:
    """Return the number of lines in a file. Returns 0 on read error."""
    try:
        content = file_path.read_text(encoding="utf-8")
        return len(content.splitlines())
    except OSError:
        return 0


def _resolve_targets(
    targets: list[str] | None,
    repo_root: Path,
) -> list[str]:
    """Resolve explicit targets list (raising on missing) or default targets."""
    if targets is None:
        return _default_targets(repo_root)
    resolved: list[str] = []
    for t in targets:
        p = Path(t)
        if not p.is_absolute():
            p = repo_root / t
        if not p.is_file():
            raise DocConsistencyTargetMissingError(
                f"explicit target does not exist: {t}"
            )
        resolved.append(str(p))
    return resolved


def _scan_file(
    target_path: Path,
    repo_root: Path,
    allowlist_set: set[str],
) -> tuple[int, int, int, list[dict[str, Any]]]:
    """Scan one file for file:line refs; return (found, ok, allowlisted, findings)."""
    refs_found = 0
    refs_verified_ok = 0
    refs_allowlisted = 0
    findings: list[dict[str, Any]] = []

    try:
        content = target_path.read_text(encoding="utf-8")
    except OSError:
        return refs_found, refs_verified_ok, refs_allowlisted, findings

    doc_path = str(target_path.relative_to(repo_root)).replace("\\", "/")
    for line_idx, line_text in enumerate(content.splitlines(), start=1):
        for match in _REF_PATTERN.finditer(line_text):
            ref_path = match.group("path")
            ref_line = int(match.group("line"))
            normalized_ref = f"{ref_path}:{ref_line}"
            refs_found += 1

            if normalized_ref in allowlist_set:
                refs_allowlisted += 1
                continue

            resolved_ref = repo_root / ref_path
            if not resolved_ref.is_file():
                alt_resolved = target_path.parent / ref_path
                if not alt_resolved.is_file():
                    findings.append({
                        "doc_path": doc_path,
                        "doc_line": line_idx,
                        "ref": normalized_ref,
                        "severity": "file_missing",
                        "detail": (
                            f"referenced file '{ref_path}' does not exist "
                            f"relative to repo root '{repo_root}'"
                        ),
                    })
                    continue

            line_count = _count_lines(resolved_ref)
            if line_count < ref_line:
                findings.append({
                    "doc_path": doc_path,
                    "doc_line": line_idx,
                    "ref": normalized_ref,
                    "severity": "line_missing",
                    "detail": (
                        f"referenced file '{ref_path}' has {line_count} lines "
                        f"but ref points to line {ref_line}"
                    ),
                })
                continue

            refs_verified_ok += 1

    return refs_found, refs_verified_ok, refs_allowlisted, findings


# ═══════════════════════════════════════════════════════════════════
# Public API
# ═══════════════════════════════════════════════════════════════════


@safe_op(name="docconsistency", mutates=False)
def scan(
    targets: list[str] | None = None,
    *,
    allowlist_path: Path | None = None,
    repo_root: Path | None = None,
) -> dict[str, Any]:
    """Scan markdown targets for file:line refs; verify each exists.

    Returns dict with keys: scan_at, targets_scanned, refs_found,
    refs_verified_ok, refs_allowlisted, findings. Each finding has:
    doc_path, doc_line, ref, severity ('file_missing'|'line_missing'), detail.

    Args:
        targets:        Explicit list of file paths. None = default scope.
        allowlist_path: Path to allowlist YAML. None = data/docconsistency-allowlist.yaml.
        repo_root:      Repository root. None = derived from __file__.
    """
    if repo_root is None:
        repo_root = _find_repo_root(Path(__file__))
    repo_root = Path(repo_root)

    if allowlist_path is None:
        allowlist_path = repo_root / "data" / "docconsistency-allowlist.yaml"

    allowlist_set: set[str] = set(_load_allowlist(Path(allowlist_path)))
    resolved_targets = _resolve_targets(targets, repo_root)

    scan_at = datetime.now(timezone.utc).isoformat()
    refs_found = 0
    refs_verified_ok = 0
    refs_allowlisted = 0
    all_findings: list[dict[str, Any]] = []

    for target_path_str in resolved_targets:
        found, ok, allow, findings = _scan_file(
            Path(target_path_str), repo_root, allowlist_set
        )
        refs_found += found
        refs_verified_ok += ok
        refs_allowlisted += allow
        all_findings.extend(findings)

    return {
        "scan_at": scan_at,
        "targets_scanned": resolved_targets,
        "refs_found": refs_found,
        "refs_verified_ok": refs_verified_ok,
        "refs_allowlisted": refs_allowlisted,
        "findings": all_findings,
    }
