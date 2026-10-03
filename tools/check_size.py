"""SCOPE.md §6.5: fail on any src/ file over 400 lines or any function
over 60 lines, measured with ast.

Usage: python tools/check_size.py [src-root]
Exits 0 when everything fits, 1 otherwise.
"""
import ast
import sys
from pathlib import Path

MAX_FILE_LINES = 400
MAX_FUNCTION_LINES = 60


def function_spans(tree: ast.AST) -> list[tuple[str, int]]:
    spans = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            spans.append((node.name, node.end_lineno - node.lineno + 1))
    return spans


def check(src_root: Path) -> list[str]:
    errors = []
    for path in sorted(src_root.rglob("*.py")):
        lines = path.read_text().splitlines()
        if len(lines) > MAX_FILE_LINES:
            errors.append(f"{path}: {len(lines)} lines (max {MAX_FILE_LINES})")
        try:
            tree = ast.parse("".join(line + "\n" for line in lines))
        except SyntaxError as e:
            errors.append(f"{path}: syntax error: {e}")
            continue
        for name, span in function_spans(tree):
            if span > MAX_FUNCTION_LINES:
                errors.append(f"{path}: function {name} is {span} lines (max {MAX_FUNCTION_LINES})")
    return errors


def main() -> int:
    default = Path(__file__).resolve().parent.parent / "src"
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else default
    if not src.is_dir():
        print(f"size: {src} not found, nothing to check")
        return 0
    errors = check(src)
    for e in errors:
        print(f"size: {e}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
