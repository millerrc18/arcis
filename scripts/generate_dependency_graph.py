"""Generate a markdown import dependency graph for src/ modules."""

from __future__ import annotations

import ast
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
DOC = ROOT / "docs" / "dependency-graph.md"


def module_name(path: Path) -> str:
    rel = path.relative_to(ROOT).with_suffix("")
    return ".".join(rel.parts)


def local_modules() -> dict[str, Path]:
    modules: dict[str, Path] = {}
    for path in SRC.rglob("*.py"):
        if "__pycache__" in path.parts or path.name.endswith("_backup.py"):
            continue
        modules[module_name(path)] = path
    return modules


def imported_src_modules(path: Path, known: set[str]) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imports: set[str] = set()
    current = module_name(path)
    current_parts = current.split(".")

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.level:
                base_parts = current_parts[:-node.level]
                if node.module:
                    base_parts += node.module.split(".")
                base = ".".join(base_parts)
            else:
                base = node.module or ""

            if base.startswith("src"):
                if base in known:
                    imports.add(base)
                else:
                    prefix_matches = sorted(mod for mod in known if mod.startswith(f"{base}."))
                    if prefix_matches:
                        imports.add(base)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("src"):
                    if alias.name in known:
                        imports.add(alias.name)
    return imports


def find_cycles(graph: dict[str, set[str]]) -> list[list[str]]:
    visited: set[str] = set()
    stack: list[str] = []
    active: set[str] = set()
    cycles: set[tuple[str, ...]] = set()

    def visit(node: str) -> None:
        visited.add(node)
        stack.append(node)
        active.add(node)
        for neighbor in sorted(graph.get(node, set())):
            if neighbor not in visited:
                visit(neighbor)
            elif neighbor in active:
                idx = stack.index(neighbor)
                cycle = stack[idx:] + [neighbor]
                cycles.add(tuple(cycle))
        stack.pop()
        active.remove(node)

    for node in sorted(graph):
        if node not in visited:
            visit(node)

    return [list(cycle) for cycle in sorted(cycles)]


def main() -> None:
    modules = local_modules()
    known = set(modules)
    imports_from: dict[str, set[str]] = {}
    imported_by: dict[str, set[str]] = defaultdict(set)

    for mod, path in modules.items():
        deps = imported_src_modules(path, known)
        imports_from[mod] = deps
        for dep in deps:
            imported_by[dep].add(mod)

    cycles = find_cycles(imports_from)

    lines = [
        "# Import Dependency Graph",
        "",
        f"Generated from `{len(modules)}` active Python modules under `src/`.",
        "",
    ]

    for mod in sorted(modules):
        lines.append(f"## `{mod}`")
        lines.append("Imports from:")
        deps = sorted(imports_from.get(mod, set()))
        if deps:
            for dep in deps:
                lines.append(f"- `{dep}`")
        else:
            lines.append("- None")
        lines.append("Imported by:")
        parents = sorted(imported_by.get(mod, set()))
        if parents:
            for parent in parents:
                lines.append(f"- `{parent}`")
        else:
            lines.append("- None")
        lines.append("")

    lines.append("## Circular Dependencies")
    if cycles:
        for cycle in cycles:
            lines.append(f"- {' -> '.join(f'`{item}`' for item in cycle)}")
    else:
        lines.append("- None detected")
    lines.append("")

    DOC.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote dependency graph to {DOC}")


if __name__ == "__main__":
    main()
