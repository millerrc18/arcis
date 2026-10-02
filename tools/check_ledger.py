"""SCOPE.md §6.2: fail if any subpackage of src/arcis/ lacks a ledger row
in §3.1/§3.2 or is not marked Active.

Usage: python tools/check_ledger.py [repo-root]
Exits 0 when the ledger covers every subpackage, 1 otherwise.
"""
import re
import sys
from pathlib import Path


def find_ledger_rows(scope_path: Path) -> dict[str, str]:
    """Parse the §3.1 and §3.2 tables. Returns {package: active} with
    active normalized to lowercase ("yes"/"no")."""
    rows: dict[str, str] = {}
    section: str | None = None
    pkg_idx = active_idx = -1
    for line in scope_path.read_text().splitlines():
        if line.startswith("### 3.1"):
            section = "3.1"
            continue
        if line.startswith("### 3.2"):
            section = "3.2"
            continue
        if line.startswith("### 3.3"):
            section = None
            continue
        if section is None or not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.split("|")[1:-1]]
        if all(re.fullmatch(r":?-+:?", c) for c in cells):
            continue  # separator row
        if "Package" in cells:
            pkg_idx = cells.index("Package")
            active_idx = cells.index("Active")
            continue
        if pkg_idx < 0 or len(cells) <= max(pkg_idx, active_idx):
            continue
        package = cells[pkg_idx].strip("`").strip()
        active = cells[active_idx].strip().lower()
        if package:
            rows[package] = active
    return rows


def subpackages(src_root: Path) -> list[str]:
    arcis = src_root / "arcis"
    if not arcis.is_dir():
        return []
    return sorted(
        p.name
        for p in arcis.iterdir()
        if p.is_dir() and not p.name.startswith((".", "__"))
    )


def check(repo_root: Path) -> list[str]:
    scope = repo_root / "SCOPE.md"
    if not scope.is_file():
        return ["SCOPE.md not found"]
    rows = find_ledger_rows(scope)
    errors = []
    for pkg in subpackages(repo_root / "src"):
        if pkg not in rows:
            errors.append(f"src/arcis/{pkg}: no ledger row in SCOPE.md §3")
        elif rows[pkg] != "yes":
            errors.append(f"src/arcis/{pkg}: ledger row exists but Active != yes")
    return errors


def main() -> int:
    repo = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent
    errors = check(repo)
    for e in errors:
        print(f"ledger: {e}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
