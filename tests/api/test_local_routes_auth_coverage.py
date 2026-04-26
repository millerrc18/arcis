"""Coupling test: every local route mutation must require verify_local_token.

Pre-Sprint-0/Wave-3a, src/api/routes/*.py shipped 20 POST/PUT/DELETE
endpoints; only actions.py was gated through the verify_local_token dep
that #576 introduced. The remaining 19 POST/PUT/DELETE endpoints across
system.py, scan.py, training.py, logs.py, notes.py, review.py, and
shadow.py were unauth'd: any localhost process could halt trading,
rewrite config, trigger emails, kick training, mutate user notes, etc.

Cloud routes have a parity test (tests/test_cloud_routes_auth_coverage.py)
that AST-scans every cloud_routes/*.py decorator. Local routes had no
equivalent. This is the local mirror — same shape, same purpose: future
write endpoints can't drift unauth'd without either declaring the dep
or being added to an allowlist with rationale.

Detection method: AST walk. Regex was the cloud test's choice but AST
is more robust against multi-line decorators and quoted-string edge
cases, and the fix specs called for AST. We import each route module,
walk its AST, find every FunctionDef whose decorator is
`@router.{post,put,delete,patch}(...)`, and check the keyword argument
`dependencies` (or the router-level dependencies on the APIRouter
itself, for actions.py) for `verify_local_token`.

Allowlist: routes that intentionally serve anonymous traffic. Adding to
this list requires explicit reviewer sign-off.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

LOCAL_ROUTES_DIR = (
    Path(__file__).resolve().parent.parent.parent / "src" / "api" / "routes"
)

# Whitelist of (file, METHOD, path) tuples that intentionally serve
# anonymous traffic. Each entry must include a comment explaining why.
#
# Currently empty: every write endpoint in src/api/routes/ is gated
# through verify_local_token (either router-level on actions.py or
# decorator-level on the rest). GET endpoints are not in scope —
# the local API binds to 127.0.0.1, and reads expose dashboard data
# already visible to the operator. The cloud parity test enforces
# auth on cloud reads (Render is internet-facing); local reads are
# protected by the loopback bind alone.
#
# When adding a new write endpoint:
#   1. Add `dependencies=[Depends(verify_local_token)]` to its decorator,
#      OR
#   2. Add an entry here with a comment explaining the operational reason
#      it must remain anonymous, and get reviewer sign-off.
_ANONYMOUS_WRITE_ROUTES_ALLOWLIST: set[tuple[str, str, str]] = set()


def _route_files() -> list[Path]:
    """All routes/*.py except __init__ and dunder-prefixed."""
    return sorted(
        p for p in LOCAL_ROUTES_DIR.glob("*.py")
        if not p.name.startswith("_")
    )


def _decorator_is_router_method(deco: ast.expr) -> tuple[str, str] | None:
    """If `deco` is `@router.METHOD("PATH"...)`, return (METHOD, PATH).

    Returns None for unrelated decorators or shapes we don't recognize.
    """
    if not isinstance(deco, ast.Call):
        return None
    func = deco.func
    if not isinstance(func, ast.Attribute):
        return None
    if not isinstance(func.value, ast.Name):
        return None
    if func.value.id != "router":
        return None
    method = func.attr
    if method not in ("get", "post", "put", "delete", "patch"):
        return None
    if not deco.args:
        return None
    path_arg = deco.args[0]
    if isinstance(path_arg, ast.Constant) and isinstance(path_arg.value, str):
        return method, path_arg.value
    return None


def _decorator_has_verify_local_token(deco: ast.Call) -> bool:
    """Return True if `dependencies=[Depends(verify_local_token)]` is present.

    Looks for the `dependencies` keyword arg, then walks its list literal
    for any `Depends(...)` call whose argument is the Name `verify_local_token`.
    """
    for kw in deco.keywords:
        if kw.arg != "dependencies":
            continue
        if not isinstance(kw.value, ast.List):
            return False
        for elt in kw.value.elts:
            if not isinstance(elt, ast.Call):
                continue
            # Match: Depends(verify_local_token) or src.api.local_auth.Depends(...)
            depends_func = elt.func
            depends_name = None
            if isinstance(depends_func, ast.Name):
                depends_name = depends_func.id
            elif isinstance(depends_func, ast.Attribute):
                depends_name = depends_func.attr
            if depends_name != "Depends":
                continue
            if not elt.args:
                continue
            inner = elt.args[0]
            if isinstance(inner, ast.Name) and inner.id == "verify_local_token":
                return True
            if (
                isinstance(inner, ast.Attribute)
                and inner.attr == "verify_local_token"
            ):
                return True
    return False


def _router_assignment_has_verify_local_token(tree: ast.Module) -> bool:
    """Return True if `router = APIRouter(... dependencies=[Depends(verify_local_token)] ...)`.

    actions.py uses this pattern (#576) — the dep applies to every endpoint
    on that router rather than being repeated per-decorator.
    """
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        targets = node.targets
        if not (len(targets) == 1 and isinstance(targets[0], ast.Name)):
            continue
        if targets[0].id != "router":
            continue
        if not isinstance(node.value, ast.Call):
            continue
        # Reuse the keyword-walking helper by wrapping the assignment's
        # Call in the same shape; it ignores other keywords.
        if _decorator_has_verify_local_token(node.value):
            return True
    return False


def _walk_write_endpoints(
    src: str,
) -> tuple[list[tuple[int, str, str, bool]], bool]:
    """For one route file, return (endpoints, router_level_gate_present).

    endpoints is a list of (line_no, METHOD, PATH, gated) for every
    @router.{post,put,delete,patch} decorator. router_level_gate_present
    is True if the APIRouter() construction itself includes the dep.
    """
    tree = ast.parse(src)
    router_gated = _router_assignment_has_verify_local_token(tree)
    endpoints: list[tuple[int, str, str, bool]] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for deco in node.decorator_list:
            match = _decorator_is_router_method(deco)
            if match is None:
                continue
            method, path = match
            # GET is read-only; not in scope for write-endpoint gating.
            if method == "get":
                continue
            assert isinstance(deco, ast.Call)
            decorator_gated = _decorator_has_verify_local_token(deco)
            gated = decorator_gated or router_gated
            endpoints.append((deco.lineno, method.upper(), path, gated))
    return endpoints, router_gated


@pytest.mark.parametrize(
    "route_file", _route_files(), ids=lambda p: p.name,
)
def test_every_write_endpoint_requires_local_auth(route_file: Path) -> None:
    """Each @router.{post,put,delete,patch}(...) must include verify_local_token.

    Either as a per-decorator `dependencies=[Depends(verify_local_token)]`,
    or via the router-level dependency on the APIRouter() construction
    (actions.py uses the latter — #576).

    If a write endpoint is intentionally anonymous, add it to
    _ANONYMOUS_WRITE_ROUTES_ALLOWLIST with a reason comment.
    """
    src = route_file.read_text(encoding="utf-8")
    endpoints, _router_gated = _walk_write_endpoints(src)

    unprotected: list[str] = []
    for line_no, method, path, gated in endpoints:
        if gated:
            continue
        key = (route_file.name, method, path)
        if key in _ANONYMOUS_WRITE_ROUTES_ALLOWLIST:
            continue
        unprotected.append(f"{route_file.name}:{line_no} {method} {path}")

    assert not unprotected, (
        f"Unprotected write endpoints in {route_file.name}:\n  "
        + "\n  ".join(unprotected)
        + "\n\nFix: add `dependencies=[Depends(verify_local_token)]` to the "
        f"@router decorator (and import Depends + verify_local_token at the "
        f"top of the file). If anonymous access is intentional, add the "
        f"(file, METHOD, path) tuple to _ANONYMOUS_WRITE_ROUTES_ALLOWLIST in "
        f"tests/api/test_local_routes_auth_coverage.py with a comment "
        f"explaining the operational reason."
    )


def test_route_files_discovery_is_nonempty() -> None:
    """Sanity: the discovery glob found .py files. If this returns empty
    the parametrized test silently no-ops, which is an unsafe failure mode.
    """
    files = _route_files()
    assert len(files) >= 5, (
        f"Expected at least 5 route files in {LOCAL_ROUTES_DIR}, "
        f"found {len(files)}: {[p.name for p in files]}"
    )


def test_actions_router_dep_is_recognized() -> None:
    """Regression-lock: actions.py uses router-level deps (#576 pattern).
    The walker must recognize that as gating, otherwise we'd flag the 7
    correctly-protected endpoints there as unauth'd.
    """
    actions_path = LOCAL_ROUTES_DIR / "actions.py"
    src = actions_path.read_text(encoding="utf-8")
    endpoints, router_gated = _walk_write_endpoints(src)
    assert router_gated, (
        "actions.py router-level Depends(verify_local_token) is no longer "
        "detected by the AST walker. Either the routers/actions.py source "
        "moved away from the #576 pattern (problem) or the walker regressed."
    )
    # All actions.py write endpoints should be reported as gated.
    unprotected = [
        f"{m} {p} (line {ln})" for ln, m, p, gated in endpoints if not gated
    ]
    assert not unprotected, (
        "actions.py endpoints flagged as unauth'd despite router-level dep: "
        + ", ".join(unprotected)
    )


def test_decorator_dep_is_recognized() -> None:
    """Regression-lock: decorator-level Depends(verify_local_token) is detected.

    This guards against a future refactor of the AST walker that breaks
    the per-decorator dependency parsing (e.g. by changing the keyword
    name match or the Depends() detection).
    """
    sample = """
from fastapi import APIRouter, Depends
from src.api.local_auth import verify_local_token

router = APIRouter()

@router.post("/foo", dependencies=[Depends(verify_local_token)])
def foo():
    return {}

@router.delete("/bar", dependencies=[Depends(verify_local_token)])
def bar():
    return {}

@router.post("/unauth")
def unauth():
    return {}
"""
    endpoints, router_gated = _walk_write_endpoints(sample)
    assert not router_gated
    by_path = {(m, p): gated for _ln, m, p, gated in endpoints}
    assert by_path[("POST", "/foo")] is True
    assert by_path[("DELETE", "/bar")] is True
    assert by_path[("POST", "/unauth")] is False
