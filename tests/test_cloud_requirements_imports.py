"""PR-gate test: cloud-deploy import drift guardrail.

AST-walks the transitive import graph reachable from src/api/cloud_app.py
and asserts every top-level third-party package is present in
requirements-cloud.txt.

Bug history (4 recurrences of this class):
  1. jsonschema — ModuleNotFoundError on startup
  2. numpy       — same
  3. requests    — same
  4. scipy       — Sprint 3 T1 deploy fix (#1007)

This test is the T7 Wave-1 BLOCKER; must pass on every PR before merge.
Sub-second runtime — pure AST, no imports of the packages under test.

Stop-list (packages whose transitive deps are NOT walked):
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# STOP-LIST — prefixes the walker must never descend into.
# These directories are not deployed to the cloud; their imports are irrelevant.
# ---------------------------------------------------------------------------
WALK_STOP_PREFIXES = (
    "tests/",
    "tests\\",
    "scripts/",
    "scripts\\",
)

# Repo root (two levels up from this file: tests/ → repo/)
_REPO = Path(__file__).resolve().parent.parent

# Path to the helper module
_HELPER = _REPO / "scripts" / "check_cloud_deploy_imports.py"


def _import_helper():
    """Import the check_cloud_deploy_imports module without polluting sys.modules."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "check_cloud_deploy_imports", _HELPER
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# Test 1 — current state is clean
# ---------------------------------------------------------------------------
class TestCloudAppImportsClean:
    def test_cloud_app_imports_clean(self):
        """cloud_app.py's transitive import graph has zero missing top-level packages.

        This is the primary PR gate.  A failure here means a new import was
        introduced that isn't in requirements-cloud.txt — the 5th recurrence of
        this bug class.
        """
        mod = _import_helper()
        ok, messages = mod.check_cloud_imports(repo=_REPO)
        assert ok, (
            "Cloud-deploy import drift detected!\n\n"
            + "\n".join(messages)
            + "\n\nAdd the missing package(s) to requirements-cloud.txt."
        )


# ---------------------------------------------------------------------------
# Test 2 — synthetic missing package is detected
# ---------------------------------------------------------------------------
class TestSyntheticMissingPkgDetected:
    def test_synthetic_missing_pkg_detected(self, monkeypatch):
        """Monkey-patching collect_external_imports to inject 'pandas' triggers failure.

        Validates that the check function correctly flags a package that is NOT
        in requirements-cloud.txt with a helpful error mentioning its name.
        """
        mod = _import_helper()
        original_collect = mod.collect_external_imports

        def _patched_collect(entry_file, repo):
            results = original_collect(entry_file, repo)
            # Inject a phantom 'import pandas' as if it came from a real file
            results.append(
                ("src/api/cloud_app.py", "import pandas", "pandas")
            )
            return results

        monkeypatch.setattr(mod, "collect_external_imports", _patched_collect)

        ok, messages = mod.check_cloud_imports(repo=_REPO)

        assert not ok, "Expected failure when 'pandas' (not in requirements-cloud.txt) is injected"
        full_output = "\n".join(messages)
        assert "pandas" in full_output, (
            f"Expected 'pandas' to appear in failure output, got:\n{full_output}"
        )


# ---------------------------------------------------------------------------
# Test 3 — transitive walk covers cloud_routes (scipy path)
# ---------------------------------------------------------------------------
class TestTransitiveWalkCoversCloudRoutes:
    def test_transitive_walk_covers_cloud_routes(self):
        """Imports inside src/api/cloud_routes/ are walked and their deps checked.

        Specifically: src/api/cloud_routes/analytics.py imports
        src/evaluation/statistics.py which imports scipy.  The walker must
        find this and either confirm scipy is in requirements-cloud.txt
        (correct) or flag it (would be the 4th recurrence of the bug).

        This test verifies the *walk reaches* cloud_routes, not the outcome.
        It asserts at minimum that packages from cloud_routes modules appear
        in the collected imports.
        """
        mod = _import_helper()
        repo = _REPO
        entry = repo / "src" / "api" / "cloud_app.py"

        results = mod.collect_external_imports(entry, repo)
        found_pkgs = {pkg for (_, _, pkg) in results}

        # numpy is used directly in kpis_compute.py (cloud_routes module);
        # its presence confirms that cloud_routes imports are walked.
        assert "numpy" in found_pkgs, (
            f"Expected 'numpy' (used in src/api/cloud_routes/kpis_compute.py) "
            f"in walked imports.  Found packages: {sorted(found_pkgs)}"
        )

        # scipy is the 4th-recurrence package — confirm it is walked
        assert "scipy" in found_pkgs, (
            f"Expected 'scipy' (used transitively via src/evaluation/statistics.py) "
            f"in walked imports.  Found packages: {sorted(found_pkgs)}"
        )


# ---------------------------------------------------------------------------
# Test 4 — stdlib imports are accepted (not flagged as missing)
# ---------------------------------------------------------------------------
class TestStdlibImportsAccepted:
    @pytest.mark.parametrize("stdlib_pkg", ["datetime", "json", "os", "logging", "re", "sys"])
    def test_stdlib_imports_accepted(self, stdlib_pkg, monkeypatch):
        """Standard-library packages must NOT trigger a missing-requirement failure.

        Verifies that sys.stdlib_module_names gates are working correctly —
        stdlib packages must pass through without being flagged even when
        injected as synthetic imports.
        """
        mod = _import_helper()
        original_collect = mod.collect_external_imports

        def _patched_collect(entry_file, repo):
            results = original_collect(entry_file, repo)
            # Inject the stdlib package as if it's a new import
            results.append(
                ("src/api/cloud_app.py", f"import {stdlib_pkg}", stdlib_pkg)
            )
            return results

        monkeypatch.setattr(mod, "collect_external_imports", _patched_collect)

        ok, messages = mod.check_cloud_imports(repo=_REPO)

        # The injected stdlib import must NOT cause a failure.
        # (The overall check might already be failing due to other issues,
        # but the stdlib package itself should not appear in violation messages.)
        full_output = "\n".join(messages)
        # If check fails, the stdlib package must not be listed as a violator
        if not ok:
            # Make sure the stdlib package we injected isn't the cause
            violation_lines = [
                line for line in messages
                if "missing top-level package" in line and stdlib_pkg in line
            ]
            assert not violation_lines, (
                f"stdlib package '{stdlib_pkg}' was incorrectly flagged as missing. "
                f"Full output:\n{full_output}"
            )
        # If check passes, that's fine too — stdlib imports shouldn't break anything
