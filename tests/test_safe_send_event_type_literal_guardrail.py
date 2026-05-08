"""Fix 4: AST-walk guardrail — safe_send event_type must always be a string literal.

Walks all safe_send(...) call sites in src/ and asserts that the first positional
argument is an ast.Constant (string literal). Fails on any call site where event_type
is a Name, Attribute, or any other dynamic expression.

Purpose: prevent a future PR from wiring safe_send(<user_input>, ...) which would
make the KeyError-on-unknown-type a crash vector inside the watch loop.
"""

import ast
import pathlib


_SRC_ROOT = pathlib.Path(__file__).parent.parent / "src"


def _collect_safe_send_calls(src_root: pathlib.Path):
    """Return list of (file, line, first_arg_type) for every safe_send() call in src/."""
    results = []
    for py_file in sorted(src_root.rglob("*.py")):
        try:
            source = py_file.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        try:
            tree = ast.parse(source, filename=str(py_file))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            # Match bare name `safe_send(...)` or attribute `telegram.safe_send(...)`
            if isinstance(func, ast.Name) and func.id == "safe_send":
                pass
            elif isinstance(func, ast.Attribute) and func.attr == "safe_send":
                pass
            else:
                continue
            # Found a safe_send call — check first positional arg
            if not node.args:
                results.append((py_file, node.lineno, "no_positional_arg"))
                continue
            first_arg = node.args[0]
            if isinstance(first_arg, ast.Constant) and isinstance(first_arg.value, str):
                results.append((py_file, node.lineno, "literal_ok"))
            else:
                results.append((py_file, node.lineno, type(first_arg).__name__))
    return results


def test_safe_send_event_type_is_always_literal():
    """Every safe_send() call in src/ must pass a string literal as event_type."""
    calls = _collect_safe_send_calls(_SRC_ROOT)
    violations = [
        f"{file}:{line} — event_type is {arg_type} (not a string literal)"
        for file, line, arg_type in calls
        if arg_type not in ("literal_ok",)
    ]
    assert not violations, (
        "safe_send() called with dynamic event_type at:\n"
        + "\n".join(violations)
    )


def test_safe_send_call_sites_exist():
    """Sanity: at least one safe_send() call exists in src/ (guardrail is live)."""
    calls = _collect_safe_send_calls(_SRC_ROOT)
    assert len(calls) > 0, "No safe_send() calls found in src/ — is the guardrail pointed at the right directory?"
