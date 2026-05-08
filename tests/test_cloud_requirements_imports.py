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

import os
import subprocess
import sys
import tempfile
import venv
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Configurable timeouts — override via env vars for slow CI runners.
# pip install timeout (scipy alone is ~80MB; throttled networks may exceed 180s).
# ---------------------------------------------------------------------------
PIP_TIMEOUT = int(os.environ.get("CLOUD_REQ_PIP_TIMEOUT", "180"))
IMPORT_TIMEOUT = int(os.environ.get("CLOUD_REQ_IMPORT_TIMEOUT", "120"))

# ---------------------------------------------------------------------------
# Subprocess helpers
# ---------------------------------------------------------------------------

def _run_or_kill(cmd, *, timeout, **kwargs):
    """subprocess.run with explicit child kill on TimeoutExpired.

    Per CPython docs, subprocess.run with timeout does NOT kill child processes
    on TimeoutExpired. This wrapper guarantees cleanup so test runs don't leak
    pip.exe/python.exe processes that hold venv file locks (especially on
    Windows where lingering handles delay tmp_path cleanup by ~60s).
    """
    # Popen doesn't accept capture_output; translate to stdout/stderr pipes.
    if kwargs.pop("capture_output", False):
        kwargs.setdefault("stdout", subprocess.PIPE)
        kwargs.setdefault("stderr", subprocess.PIPE)
    proc = subprocess.Popen(cmd, **kwargs)
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
        return subprocess.CompletedProcess(cmd, proc.returncode, stdout, stderr)
    except subprocess.TimeoutExpired:
        proc.kill()
        if os.name == "nt":
            # Windows: also kill the process tree (pip spawns child python.exe)
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=10,
            )
        proc.communicate()  # drain pipes after kill
        raise


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
        """Monkey-patching collect_external_imports to inject 'sqlalchemy' triggers failure.

        Validates that the check function correctly flags a package that is NOT
        in requirements-cloud.txt with a helpful error mentioning its name.
        Uses 'sqlalchemy' as the phantom package — it is not in requirements-cloud.txt
        and not in NON_CLOUD_PACKAGES, so it must trigger a violation.
        """
        mod = _import_helper()
        original_collect = mod.collect_external_imports

        def _patched_collect(entry_file, repo):
            results = original_collect(entry_file, repo)
            # Inject a phantom 'import sqlalchemy' as if it came from a real file
            results.append(
                ("src/api/cloud_app.py", "import sqlalchemy", "sqlalchemy")
            )
            return results

        monkeypatch.setattr(mod, "collect_external_imports", _patched_collect)

        ok, messages = mod.check_cloud_imports(repo=_REPO)

        assert not ok, "Expected failure when 'sqlalchemy' (not in requirements-cloud.txt) is injected"
        full_output = "\n".join(messages)
        assert "sqlalchemy" in full_output, (
            f"Expected 'sqlalchemy' to appear in failure output, got:\n{full_output}"
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


# ---------------------------------------------------------------------------
# Test 5 — Windows unicode crash: script exits 1 (not crash-encodes) on failure
# ---------------------------------------------------------------------------
class TestWindowsUnicodeFailureExitCode:
    def test_failure_exits_1_not_unicode_error(self, tmp_path):
        """Script must exit 1 (not crash with UnicodeEncodeError) when failure path is hit.

        Regression guard for Finding 1: on Windows cp1252 consoles, a Unicode
        arrow character in the hint message caused UnicodeEncodeError before
        sys.exit(1) was reached, masking all failures with exit 0.

        Injects a phantom missing package by writing a minimal requirements file
        that omits fastapi (always present in the real walk), then invokes the
        script via subprocess with PYTHONIOENCODING=cp1252 to simulate the
        Windows console encoding. The script must return exit code 1, not exit 0
        or crash with a non-zero code due to UnicodeEncodeError.
        """
        import os

        repo = _REPO
        # Write a requirements file that is missing packages reachable from cloud_app
        minimal_req = tmp_path / "requirements-minimal.txt"
        minimal_req.write_text("# empty — intentionally missing packages\n", encoding="utf-8")

        env = os.environ.copy()
        # Simulate Windows cp1252 console encoding — this is the exact scenario
        # where -> (U+2192) would cause UnicodeEncodeError before the fix
        env["PYTHONIOENCODING"] = "cp1252"

        result = subprocess.run(
            [
                sys.executable,
                str(_HELPER),
                "--req-file",
                str(minimal_req),
            ],
            capture_output=True,
            cwd=str(repo),
            env=env,
        )
        assert result.returncode == 1, (
            f"Expected exit code 1 when packages are missing under cp1252 encoding, "
            f"got {result.returncode}.\n"
            f"If returncode==0: UnicodeEncodeError crashed the output before sys.exit(1).\n"
            f"stdout: {result.stdout!r}\n"
            f"stderr: {result.stderr!r}"
        )
        stderr_text = result.stderr.decode("utf-8", errors="replace")
        assert "UnicodeEncodeError" not in stderr_text, (
            f"Script crashed with UnicodeEncodeError under cp1252 encoding.\n"
            f"The failure-path hint message must use only ASCII characters.\n"
            f"stderr: {stderr_text}"
        )


# ---------------------------------------------------------------------------
# Test 6 — Deep-transitive walker: jsonschema detected via platform chain
# ---------------------------------------------------------------------------
class TestDeepTransitiveWalkerJsonschema:
    def test_deep_transitive_jsonschema_in_walked_packages(self):
        """jsonschema must appear in the walked packages after walker depth fix.

        Regression guard for Finding 2: the original walker used a two-mode
        traversal — files inside src/api/ recurse; files outside src/api/ do NOT
        recurse further. jsonschema lives at
        src/platform/capability_registry/schemas.py, two hops outside src/api/:

            src/api/cloud_routes/system_index.py
              -> src/platform/capability_registry/__init__.py  [no-recurse under old logic]
                 -> src/platform/capability_registry/schemas.py  [never reached]
                    -> from jsonschema import Draft7Validator    [never found]

        After option-A fix (full transitive walk through all of src/), schemas.py
        must be reached and jsonschema must appear in the collected packages.
        """
        mod = _import_helper()
        repo = _REPO
        entry = repo / "src" / "api" / "cloud_app.py"

        results = mod.collect_external_imports(entry, repo)
        found_pkgs = {pkg for (_, _, pkg) in results}

        assert "jsonschema" in found_pkgs, (
            f"Expected 'jsonschema' (imported in "
            f"src/platform/capability_registry/schemas.py via Draft7Validator) "
            f"to appear in the walked package set after full transitive walk fix.\n"
            f"Found packages: {sorted(found_pkgs)}"
        )


# ---------------------------------------------------------------------------
# Network availability fixture for slow-lane tests
# ---------------------------------------------------------------------------

@pytest.fixture
def has_pypi_network():
    """Skip slow-lane tests when PyPI is unreachable."""
    import socket
    try:
        socket.create_connection(("pypi.org", 443), timeout=5)
    except OSError as e:
        pytest.skip(f"requires PyPI network access: {e}")


# ---------------------------------------------------------------------------
# Helper — build a minimal env dict for subprocess calls
# ---------------------------------------------------------------------------
def _clean_env() -> dict:
    """Return a minimal env dict that omits .env-derived runtime variables.

    Prevents worktree env-drift (feedback_worktree_env_drift): the subprocess
    must not inherit ARCIS_LOCAL_API_TOKEN, ARCIS_DB_PATH, or similar operator-
    machine env vars, so the venv test is hermetic in CI and fresh clones.
    Only PATH (needed to find the OS pip/python) and PYTHONPATH are forwarded.
    """
    env = {"PATH": os.environ.get("PATH", "")}
    for key in ("SYSTEMROOT", "SYSTEMDRIVE", "TEMP", "TMP", "HOMEDRIVE", "HOMEPATH"):
        if key in os.environ:
            env[key] = os.environ[key]
    # cloud_app validates DATABASE_URL/ARCIS_DB_PATH at import time
    # (src/config/__init__.py) — set a fake DATABASE_URL so the import-graph
    # check works hermetically without exposing real DB connections. Sprint 4
    # PR #1020 review surfaced this gap when the test was run with no env
    # vars set at all and the import raised RuntimeError before pytest could
    # observe ModuleNotFoundError-class failures (the actual test target).
    env["DATABASE_URL"] = "postgresql://fake:fake@localhost:5432/fake"
    return env


def _venv_bin(venv_dir: Path) -> Path:
    """Return the Scripts/ or bin/ dir inside venv_dir."""
    return venv_dir / ("Scripts" if os.name == "nt" else "bin")


# ---------------------------------------------------------------------------
# Test 7 — slow-lane positive: real venv, install requirements-cloud.txt,
#           confirm `from src.api.cloud_app import app` succeeds.
# ---------------------------------------------------------------------------
@pytest.mark.slow
class TestSlowLaneVenvImport:
    """Slow-lane: actually pip-install requirements-cloud.txt in a temp venv,
    confirm `from src.api.cloud_app import app` succeeds. ~30-60s runtime.

    INFORMATIONAL/CI-ONLY: T8 is NOT a PR merge gate. T7 fast-lane AST walker
    (TestCloudAppImportsClean) is the gating test. T8 provides defense-in-depth
    by exercising real pip resolution to catch transitive dependency drift that
    pure AST walking cannot detect (e.g. a package that installs fine but whose
    transitive pip dep conflicts in a clean venv).

    Marked @pytest.mark.slow — skipped in default sweep; opt-in via:
      python -m pytest tests/test_cloud_requirements_imports.py -m slow
      or: RUN_SLOW=1 python -m pytest tests/test_cloud_requirements_imports.py -m slow

    Requires PyPI network access. Override timeouts for slow CI runners via:
      CLOUD_REQ_PIP_TIMEOUT=300 CLOUD_REQ_IMPORT_TIMEOUT=180 pytest -m slow
    """

    def test_cloud_app_imports_in_clean_venv(self, tmp_path, has_pypi_network):
        """Builds a temp venv, installs requirements-cloud.txt only, imports cloud_app."""
        repo = _REPO
        req_file = repo / "requirements-cloud.txt"

        venv_dir = tmp_path / "venv"
        venv.create(str(venv_dir), with_pip=True)

        bin_dir = _venv_bin(venv_dir)
        pip_exe = bin_dir / ("pip.exe" if os.name == "nt" else "pip")
        python_exe = bin_dir / ("python.exe" if os.name == "nt" else "python")

        clean_env = _clean_env()

        install_cmd = [str(pip_exe), "install", "-r", str(req_file), "--quiet"]
        pip_result = _run_or_kill(
            install_cmd,
            capture_output=True,
            text=True,
            timeout=PIP_TIMEOUT,
            env=clean_env,
        )
        assert pip_result.returncode == 0, (
            f"pip install failed (exit {pip_result.returncode}).\n"
            f"stdout: {pip_result.stdout}\n"
            f"stderr: {pip_result.stderr}"
        )

        import_result = _run_or_kill(
            [str(python_exe), "-c", "from src.api.cloud_app import app"],
            capture_output=True,
            text=True,
            timeout=IMPORT_TIMEOUT,
            cwd=str(repo),
            env=clean_env,
        )
        assert import_result.returncode == 0, (
            f"Import failed in clean venv (exit {import_result.returncode}).\n"
            f"This means requirements-cloud.txt is missing a package that cloud_app needs.\n"
            f"stdout: {import_result.stdout}\n"
            f"stderr: {import_result.stderr}"
        )
        assert "ModuleNotFoundError" not in import_result.stderr, (
            f"ModuleNotFoundError detected in venv import.\n"
            f"stderr: {import_result.stderr}"
        )


# ---------------------------------------------------------------------------
# Test 8 — slow-lane negative / regression-lock: venv missing scipy triggers
#           ModuleNotFoundError.  Locks in 4th-recurrence bug class detection.
# ---------------------------------------------------------------------------
@pytest.mark.slow
class TestSlowLaneSyntheticMissingScipy:
    """Synthetic regression: create a temp requirements-cloud.txt missing scipy
    (which Sprint 3 #1007 hot-fixed), assert venv import fails with
    ModuleNotFoundError on scipy specifically.

    Locks in the 4th-recurrence bug class detection. If this test begins
    PASSING when scipy is absent, it means cloud_app no longer uses scipy
    transitively — which would be a notable architectural change and warrants
    removing this regression-lock.

    INFORMATIONAL/CI-ONLY: same as TestSlowLaneVenvImport — NOT a PR merge gate.

    Requires PyPI network access. Override timeouts for slow CI runners via:
      CLOUD_REQ_PIP_TIMEOUT=300 CLOUD_REQ_IMPORT_TIMEOUT=180 pytest -m slow
    """

    def test_missing_scipy_raises_module_not_found(self, tmp_path, has_pypi_network):
        """Builds a temp requirements-cloud.txt without scipy, attempts import, asserts failure."""
        repo = _REPO
        req_file = repo / "requirements-cloud.txt"

        stripped_req = tmp_path / "requirements-cloud-no-scipy.txt"
        original_lines = req_file.read_text(encoding="utf-8").splitlines(keepends=True)
        stripped_lines = [
            line for line in original_lines
            if not (
                line.strip().lower().startswith("scipy")
                or line.strip().lower().startswith("# scipy")
            )
        ]
        stripped_req.write_text("".join(stripped_lines), encoding="utf-8")

        venv_dir = tmp_path / "venv"
        venv.create(str(venv_dir), with_pip=True)

        bin_dir = _venv_bin(venv_dir)
        pip_exe = bin_dir / ("pip.exe" if os.name == "nt" else "pip")
        python_exe = bin_dir / ("python.exe" if os.name == "nt" else "python")

        clean_env = _clean_env()

        install_cmd = [str(pip_exe), "install", "-r", str(stripped_req), "--quiet"]
        pip_result = _run_or_kill(
            install_cmd,
            capture_output=True,
            text=True,
            timeout=PIP_TIMEOUT,
            env=clean_env,
        )
        assert pip_result.returncode == 0, (
            f"pip install failed even for the stripped requirements "
            f"(exit {pip_result.returncode}).\n"
            f"stdout: {pip_result.stdout}\n"
            f"stderr: {pip_result.stderr}"
        )

        import_result = _run_or_kill(
            [str(python_exe), "-c", "from src.api.cloud_app import app"],
            capture_output=True,
            text=True,
            timeout=IMPORT_TIMEOUT,
            cwd=str(repo),
            env=clean_env,
        )
        assert import_result.returncode != 0, (
            "Expected import to fail when scipy is absent, but it succeeded.\n"
            "If cloud_app no longer uses scipy transitively, remove this regression-lock."
        )
        combined = import_result.stdout + import_result.stderr
        assert "ModuleNotFoundError" in combined, (
            f"Expected 'ModuleNotFoundError' in subprocess output when scipy is absent.\n"
            f"stdout: {import_result.stdout}\n"
            f"stderr: {import_result.stderr}"
        )
        assert "scipy" in combined, (
            f"Expected 'scipy' to appear in the error message when scipy is absent.\n"
            f"stdout: {import_result.stdout}\n"
            f"stderr: {import_result.stderr}"
        )
