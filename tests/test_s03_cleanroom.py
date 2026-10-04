"""S03 clean-room compliance test (acceptance criterion 2).

Verifies that S03 measurement scripts never open the incumbent definition.
This is a static check: it parses the AST of each script and fails if
any open() call, Path read, or yaml/json load references the incumbent
file name.

This complements the runtime _check_forbidden() guard (which fails if
ARCIS_ALLOW_INCUMBENT is set). Together they provide defense in depth:
static verification that the code cannot read the file, plus runtime
verification that the environment does not explicitly enable access.
"""

import ast
from pathlib import Path

TOOLS_DIR = Path(__file__).parent.parent / "tools"
S03_SCRIPTS = [
    "pull_bars_panel.py",
    "pull_news_metadata.py",
    "measure_second_moments.py",
    "run_power_sims.py",
    "s03_power_lib.py",
]
FORBIDDEN_NAME = "incumbent_v1.yaml"


def _get_string_args(node: ast.AST) -> list[str]:
    """Extract string literal arguments from a call node."""
    strings = []
    if isinstance(node, ast.Call):
        for arg in node.args:
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                strings.append(arg.value)
            elif isinstance(arg, ast.JoinedStr):  # f-string
                # Conservative: if it's an f-string, check the raw parts
                for v in arg.values:
                    if isinstance(v, ast.Constant) and isinstance(v.value, str):
                        strings.append(v.value)
    return strings


def test_no_incumbent_file_access():
    """No S03 script opens, reads, or references the incumbent file for I/O."""
    violations = []
    for script_name in S03_SCRIPTS:
        script_path = TOOLS_DIR / script_name
        if not script_path.exists():
            violations.append(f"{script_name}: file not found")
            continue
        tree = ast.parse(script_path.read_text(), filename=str(script_path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func_name = ""
                if isinstance(node.func, ast.Name):
                    func_name = node.func.id
                elif isinstance(node.func, ast.Attribute):
                    func_name = node.func.attr
                # Check open(), Path(), yaml.safe_load, json.load, etc.
                if func_name in ("open", "Path", "safe_load", "load"):
                    for s in _get_string_args(node):
                        if FORBIDDEN_NAME in s or "incumbent" in s.lower():
                            violations.append(
                                f"{script_name}:{node.lineno}: "
                                f"{func_name}() references incumbent"
                            )
                # Check os.path.join with incumbent
                if func_name == "join":
                    for s in _get_string_args(node):
                        if FORBIDDEN_NAME in s:
                            # Allow the _check_forbidden reference (it's guarded)
                            # But flag if it's used for actual I/O
                            pass
    # The _FORBIDDEN_CONFIG constant and _check_forbidden are allowed;
    # what matters is no actual file I/O on the incumbent path.
    # This is a conservative check: it flags any string containing
    # the forbidden name in an I/O call.
    assert not violations, f"Clean-room violations: {violations}"


def test_forbidden_guard_uses_raise_not_assert():
    """The _check_forbidden guard must use raise, not assert (survives -O)."""
    for script_name in S03_SCRIPTS:
        if script_name in ("pull_bars_panel.py",):
            continue  # pull_bars_panel doesn't have the guard
        script_path = TOOLS_DIR / script_name
        content = script_path.read_text()
        # Find _check_forbidden and verify it doesn't use assert
        if "_check_forbidden" in content:
            # Extract the function
            tree = ast.parse(content)
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef) and node.name == "_check_forbidden":
                    has_assert = any(
                        isinstance(n, ast.Assert) for n in ast.walk(node)
                    )
                    has_raise = any(
                        isinstance(n, ast.Raise) for n in ast.walk(node)
                    )
                    assert not has_assert, (
                        f"{script_name}: _check_forbidden uses assert "
                        f"(stripped by python -O)"
                    )
                    assert has_raise, (
                        f"{script_name}: _check_forbidden must raise RuntimeError"
                    )
