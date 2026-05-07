"""check_cloud_deploy_imports.py — cloud-req fast-lane AST walker.

Walks the transitive import graph reachable from src/api/cloud_app.py and
asserts every top-level package is either stdlib or present in
requirements-cloud.txt. Sub-second runtime; used by T7 PR-gate test and
T8 slow-lane CI check.

Recurrence history of this bug class:
  1. jsonschema — cloud deploy crashed with ModuleNotFoundError
  2. numpy       — same
  3. requests    — same
  4. scipy       — Sprint 3 T1 deploy fix (#1007)

Usage:
  python scripts/check_cloud_deploy_imports.py          # exits 0 on clean
  python scripts/check_cloud_deploy_imports.py --json   # machine-readable

Exit codes:
  0 — all imports satisfied
  1 — one or more top-level packages are missing from requirements-cloud.txt
"""

from __future__ import annotations

import ast
import os
import re
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# STOP-LIST: prefixes that the walker MUST NOT descend into.
# Rationale: test fixtures and scripts are not shipped to the cloud deployment,
# so their imports are irrelevant to the cloud requirements check.
# ---------------------------------------------------------------------------
WALK_STOP_PREFIXES: tuple[str, ...] = (
    "tests/",
    "tests\\",
    "scripts/",
    "scripts\\",
)

# ---------------------------------------------------------------------------
# LOCAL_PACKAGES: top-level names that are repo-local directories, not PyPI.
# These are valid imports when the repo root is on sys.path but are NEVER
# deployed as pip packages, so the check must not flag them as missing.
# ---------------------------------------------------------------------------
LOCAL_PACKAGES: frozenset[str] = frozenset({"src", "scripts", "tests"})

# ---------------------------------------------------------------------------
# NON_CLOUD_PACKAGES: PyPI packages that are in requirements.txt (full local
# environment) but intentionally NOT deployed to the cloud environment.
# These packages are reachable from cloud_app.py transitively (via registry
# population imports like src.shadow_trading, src.trading, src.training), but
# their code paths that require these packages are NOT exercised on Render.
# When the full transitive walker reaches them, they must not be flagged as
# violations — the operator has intentionally excluded them from cloud.
# ---------------------------------------------------------------------------
NON_CLOUD_PACKAGES: frozenset[str] = frozenset({
    "anthropic",   # src/training/claude_client.py — local LLM training only
    "alpaca",      # src/shadow_trading/alpaca_*.py — local broker only
    "ib_async",    # src/trading/ib_broker.py — local IB Gateway only
    "pandas",      # src/data_ingestion/market_data.py — local data pipeline only
    "yfinance",    # src/data_ingestion/market_data.py, src/analytics/spy_benchmark.py
    "pandas_market_calendars",  # src/scheduler/holidays.py — local scheduler only
})

# Alias map: PyPI package name → importable top-level name.
# Required because PyPI names and import names differ for these packages.
_PYPI_TO_IMPORT: dict[str, str] = {
    "psycopg2-binary": "psycopg2",
    "python-dotenv": "dotenv",
    "PyYAML": "yaml",
    "pillow": "PIL",
    "scikit-learn": "sklearn",
}


def _repo_root() -> Path:
    """Return the repository root (parent of scripts/)."""
    return Path(__file__).resolve().parent.parent


def _parse_requirements(req_file: Path) -> set[str]:
    """Parse requirements-cloud.txt → set of importable top-level package names.

    Strips comments, blank lines, and version specifiers.  Applies the
    _PYPI_TO_IMPORT alias map so ``psycopg2-binary`` resolves to ``psycopg2``.
    """
    packages: set[str] = set()
    if not req_file.exists():
        return packages
    for raw_line in req_file.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        # Strip inline comment
        line = line.split("#")[0].strip()
        if not line:
            continue
        # Strip version specifier (>=, ==, <=, ~=, !=, <, >)
        pkg_name = re.split(r"[><=!~\s\[]", line)[0].strip()
        if not pkg_name:
            continue
        # Normalise: PyPI uses dashes, imports use underscores for some pkgs
        import_name = _PYPI_TO_IMPORT.get(pkg_name, pkg_name.replace("-", "_"))
        # Also add the raw normalised form in case the alias map doesn't cover it
        packages.add(import_name.lower())
        packages.add(import_name)
    return packages


def _top_level(module_name: str) -> str:
    """Return the top-level package from a dotted module name."""
    return module_name.split(".")[0]


def _resolve_src_module(dotted: str, repo: Path) -> Path | None:
    """Resolve a ``src.X.Y`` import to an absolute path under repo/src/.

    Returns the .py file path if it exists, else None.
    """
    if not dotted.startswith("src."):
        return None
    remainder = dotted[len("src."):]
    parts = remainder.split(".")
    # Try src/X/Y.py first, then src/X/Y/__init__.py
    as_module = repo / "src" / Path(*parts).with_suffix(".py")
    as_pkg = repo / "src" / Path(*parts) / "__init__.py"
    if as_module.exists():
        return as_module
    if as_pkg.exists():
        return as_pkg
    return None


def _is_stop_listed(rel_path: str) -> bool:
    """Return True if rel_path starts with a stop-list prefix."""
    norm = rel_path.replace("\\", "/")
    return any(norm.startswith(p.replace("\\", "/")) for p in WALK_STOP_PREFIXES)


def collect_external_imports(
    entry_file: Path,
    repo: Path,
) -> list[tuple[str, str, str]]:
    """Walk the transitive import graph from entry_file.

    Returns a list of (rel_path, import_stmt, top_level_pkg) tuples for every
    top-level package that is NOT ``src`` (i.e. not an internal src.* import).

    Traversal rules:
    - Start at entry_file (cloud_app.py)
    - Recurse into all src.* imports transitively through all of src/
    - Never visits the same file twice
    - Never descends into WALK_STOP_PREFIXES paths (tests/, scripts/)
    """
    visited: set[Path] = set()
    results: list[tuple[str, str, str]] = []
    worklist: list[Path] = [entry_file.resolve()]

    while worklist:
        current = worklist.pop()
        if current in visited:
            continue
        visited.add(current)

        rel = str(current.relative_to(repo)).replace("\\", "/")
        if _is_stop_listed(rel):
            continue

        try:
            source = current.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        try:
            tree = ast.parse(source, filename=str(current))
        except SyntaxError:
            continue

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    pkg = _top_level(alias.name)
                    stmt = f"import {alias.name}"
                    if pkg != "src":
                        results.append((rel, stmt, pkg))
            elif isinstance(node, ast.ImportFrom):
                if node.module is None:
                    continue
                pkg = _top_level(node.module)
                stmt = f"from {node.module} import ..."
                if node.level and node.level > 0:
                    # Relative import — skip (not used in this codebase at top-level)
                    continue
                if pkg == "src":
                    resolved = _resolve_src_module(node.module, repo)
                    if resolved is not None:
                        resolved_rel = str(resolved.relative_to(repo)).replace(
                            "\\", "/"
                        )
                        if not _is_stop_listed(resolved_rel) and resolved not in visited:
                            worklist.append(resolved)
                else:
                    results.append((rel, stmt, pkg))

    return results


def check_cloud_imports(
    repo: Path | None = None,
    entry: str = "src/api/cloud_app.py",
    req_file: str = "requirements-cloud.txt",
) -> tuple[bool, list[str]]:
    """Run the import check.

    Returns (ok: bool, messages: list[str]).  When ok is True, messages
    contains only the summary line.  When ok is False, messages describes
    each violation.
    """
    if repo is None:
        repo = _repo_root()

    entry_path = repo / entry
    req_path = repo / req_file

    stdlib_names = sys.stdlib_module_names  # frozenset, Python 3.10+
    cloud_pkgs = _parse_requirements(req_path)

    external_imports = collect_external_imports(entry_path, repo)

    # Deduplicate by top-level package
    seen_pkgs: set[str] = set()
    violations: list[tuple[str, str, str]] = []

    for rel_path, stmt, pkg in external_imports:
        if pkg in seen_pkgs:
            continue
        seen_pkgs.add(pkg)
        pkg_lower = pkg.lower()
        if pkg_lower in stdlib_names or pkg in stdlib_names:
            continue
        # Local repo packages — not PyPI, not flagged
        if pkg in LOCAL_PACKAGES or pkg_lower in LOCAL_PACKAGES:
            continue
        # Packages intentionally excluded from cloud (local-only trading infra)
        if pkg in NON_CLOUD_PACKAGES or pkg_lower in {p.lower() for p in NON_CLOUD_PACKAGES}:
            continue
        # Check against cloud packages (case-insensitive + original)
        if pkg in cloud_pkgs or pkg_lower in {p.lower() for p in cloud_pkgs}:
            continue
        violations.append((rel_path, stmt, pkg))

    if not violations:
        return True, [
            f"OK: all imports satisfied (checked {len(seen_pkgs)} top-level packages)"
        ]

    messages: list[str] = [
        f"FAIL: {len(violations)} top-level package(s) reachable from {entry}"
        " are missing from requirements-cloud.txt:",
        "",
    ]
    for rel_path, stmt, pkg in violations:
        messages.append(f"  - {rel_path}: `{stmt}` -> missing top-level package: '{pkg}'")
        messages.append(
            f"    Hint: add '{pkg}>=<version>' to requirements-cloud.txt"
            " (see comment format in that file for examples)"
        )
    return False, messages


def main(argv: list[str] | None = None) -> int:
    import argparse
    import json as _json

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--json", action="store_true", help="Output machine-readable JSON"
    )
    parser.add_argument(
        "--entry",
        default="src/api/cloud_app.py",
        help="Entry point relative to repo root",
    )
    parser.add_argument(
        "--req-file",
        default="requirements-cloud.txt",
        help="Requirements file relative to repo root",
    )
    args = parser.parse_args(argv)

    repo = _repo_root()
    ok, messages = check_cloud_imports(
        repo=repo, entry=args.entry, req_file=args.req_file
    )

    if args.json:
        print(_json.dumps({"ok": ok, "messages": messages}, indent=2))
    else:
        for line in messages:
            print(line)

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
