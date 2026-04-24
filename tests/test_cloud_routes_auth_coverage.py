"""Coupling test: every cloud route must require auth.

Pre-#632, src/api/cloud_routes/walkforward.py shipped 4 routes without
the `dependencies=[Depends(verify_auth)]` pattern that every other
router uses. Anonymous reads were possible on Render. This test scans
the source of every cloud_routes/*.py file and asserts every @router.get,
@router.post, @router.put, @router.delete, @router.patch decorator
includes a verify_auth dependency.

Exempted endpoints (must be explicitly listed):
- /healthz — Render's health-check probe; no secret to leak
"""
import re
from pathlib import Path

import pytest

# Whitelist of routes that intentionally serve anonymous traffic.
# Adding to this list requires explicit reviewer sign-off.
_ANONYMOUS_ROUTES_WHITELIST = {
    "/healthz",
}

CLOUD_ROUTES_DIR = Path(__file__).resolve().parent.parent / "src" / "api" / "cloud_routes"

# Match: @router.METHOD("PATH"[, ...])
_ROUTE_DECORATOR_RE = re.compile(
    r'@router\.(get|post|put|delete|patch)\(\s*["\']([^"\']+)["\']'
    r'(?P<rest>[^)]*)\)',
    re.MULTILINE,
)


def _route_files():
    return sorted(p for p in CLOUD_ROUTES_DIR.glob("*.py") if not p.name.startswith("_"))


@pytest.mark.parametrize("route_file", _route_files(), ids=lambda p: p.name)
def test_every_route_requires_auth(route_file):
    """Each @router.METHOD(...) must include verify_auth dependency."""
    src = route_file.read_text()
    unprotected = []
    for m in _ROUTE_DECORATOR_RE.finditer(src):
        method, path, rest = m.group(1), m.group(2), m.group("rest")
        if path in _ANONYMOUS_ROUTES_WHITELIST:
            continue
        if "verify_auth" not in rest:
            line_no = src[: m.start()].count("\n") + 1
            unprotected.append(f"{route_file.name}:{line_no} {method.upper()} {path}")
    assert not unprotected, (
        f"Unprotected routes found in {route_file.name}:\n  "
        + "\n  ".join(unprotected)
        + "\n\nFix: add `dependencies=[Depends(verify_auth)]` to the @router decorator. "
        f"If anonymous access is intentional, add the path to "
        f"_ANONYMOUS_ROUTES_WHITELIST in tests/test_cloud_routes_auth_coverage.py "
        f"with a comment explaining why."
    )
