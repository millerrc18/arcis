"""AST guardrail: detect_drift and _handle/_emit functions must NOT call safe_send.

The watch-loop caller (watch.py) is responsible for emitting via safe_send.
The detector returns DriftFinding objects; it must not initiate notifications
itself — that would couple the detector to the notification system and create
a recursion hazard if the notification path calls the detector.

Scope: src/monitoring/manual_intervention_drift.py
"""
import ast
from pathlib import Path


_DETECTOR_FILE = (
    Path(__file__).parent.parent.parent
    / "src" / "monitoring" / "manual_intervention_drift.py"
)

_FORBIDDEN_CALLERS = frozenset([
    "detect_drift",
])
_FORBIDDEN_CALLER_PREFIXES = ("_handle", "_emit")


def test_drift_detector_no_safe_send_call():
    source = _DETECTOR_FILE.read_text(encoding="utf-8")
    tree = ast.parse(source)

    violations = []

    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        fn_name = node.name
        if fn_name not in _FORBIDDEN_CALLERS and not any(
            fn_name.startswith(p) for p in _FORBIDDEN_CALLER_PREFIXES
        ):
            continue
        # Walk this function's body for safe_send calls
        for child in ast.walk(node):
            if not isinstance(child, ast.Call):
                continue
            func = child.func
            # Detect safe_send(...) or xxx.safe_send(...)
            if isinstance(func, ast.Name) and func.id == "safe_send":
                violations.append((fn_name, getattr(child, "lineno", "?")))
            elif isinstance(func, ast.Attribute) and func.attr == "safe_send":
                violations.append((fn_name, getattr(child, "lineno", "?")))

    assert violations == [], (
        f"safe_send called inside detector function(s) — "
        f"the watch loop must call safe_send, not the detector. "
        f"Violations: {violations}"
    )
