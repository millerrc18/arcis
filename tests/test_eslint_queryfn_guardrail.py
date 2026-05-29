"""CI guardrail: ESLint custom rule ensures useQuery queryFn is never a bare
MemberExpression (api.method) that would receive QueryFunctionContext as first arg.

Sprint 3 T22 — E1.C ESLint custom rule + pytest fixture.

Two tests:
1. test_lint_passes_current_frontend — shells out to npm run lint:queryfn and
   asserts exit 0 (clean). Proves all T17-T21 wraps are present.

2. test_lint_fails_on_bare_queryfn — injects a synthetic JSX file with
   useQuery({queryFn: api.foo}) (bare MemberExpression) and asserts the lint
   command exits non-zero (rule is live and fires).
"""
from __future__ import annotations

import os
import subprocess
import tempfile

import pytest

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_FRONTEND_DIR = os.path.join(_REPO_ROOT, "frontend")


def _eslint_available() -> bool:
    """Return True if eslint is available in the frontend node_modules."""
    eslint_path = os.path.join(_FRONTEND_DIR, "node_modules", ".bin", "eslint")
    eslint_cmd = eslint_path + (".cmd" if os.name == "nt" else "")
    return os.path.exists(eslint_cmd) or os.path.exists(eslint_path)


def _run_npm_lint(env: dict | None = None):
    merged_env = {**os.environ, **(env or {})}
    return subprocess.run(
        "npm --prefix {prefix} run lint:queryfn".format(prefix=_FRONTEND_DIR),
        capture_output=True,
        text=True,
        env=merged_env,
        cwd=_REPO_ROOT,
        shell=True,
    )


def test_lint_passes_current_frontend():
    """All T17-T21 bare-queryFn sites are wrapped; lint must exit 0."""
    # DD-42 optional-dep: eslint is a frontend tool not installed in all CI
    # environments. Skip rather than fail when node_modules/.bin/eslint is absent.
    if not _eslint_available():
        pytest.skip("eslint not installed in node_modules — DD-42 optional-dep skip")
    result = _run_npm_lint()
    assert result.returncode == 0, (
        f"lint:queryfn failed on current frontend (expected 0, got {result.returncode}).\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )


def test_lint_fails_on_bare_queryfn():
    """Synthetic file with bare queryFn: api.foo triggers the ESLint rule."""
    # DD-42 optional-dep: eslint is a frontend tool not installed in all CI
    # environments. Skip rather than fail when node_modules/.bin/eslint is absent.
    if not _eslint_available():
        pytest.skip("eslint not installed in node_modules — DD-42 optional-dep skip")
    synthetic_jsx = """\
import { useQuery } from '@tanstack/react-query';
import api from '../api.js';
export default function BadComponent() {
  const { data } = useQuery({
    queryKey: ['test'],
    queryFn: api.foo,
  });
  return null;
}
"""
    synthetic_dir = os.path.join(_FRONTEND_DIR, "src", "_t22_synthetic_test")
    os.makedirs(synthetic_dir, exist_ok=True)
    synthetic_path = os.path.join(synthetic_dir, "SyntheticBareQueryFn.jsx")
    try:
        with open(synthetic_path, "w") as fh:
            fh.write(synthetic_jsx)
        result = _run_npm_lint()
    finally:
        import shutil
        shutil.rmtree(synthetic_dir, ignore_errors=True)

    assert result.returncode != 0, (
        "lint:queryfn should have FAILED on synthetic bare queryFn but exited 0.\n"
        "The ESLint rule is not detecting MemberExpression queryFn values.\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    combined = result.stdout + result.stderr
    assert "no-bare-queryfn-with-args" in combined or "queryFn" in combined, (
        f"Expected rule name in lint output but got:\nstdout: {result.stdout}\nstderr: {result.stderr}"
    )
