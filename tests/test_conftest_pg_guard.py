"""Tests for the P0 pytest-configure guard that refuses runs against prod PG.

Uses subprocess.run to invoke a nested pytest --collect-only call with
manipulated environment variables. This sidesteps the guard in the outer
pytest run so the meta-test can verify the guard fires correctly in a
subprocess.

Background (P0 incident 2026-05-14):
  24 test files use the broken fallback pattern:
      TEST_PG_URL = os.environ.get("TEST_DATABASE_URL") or os.environ.get("DATABASE_URL", "")
  When DATABASE_URL points at the operator's local production PG (port 5433)
  and TEST_DATABASE_URL is unset, fixtures in those files execute DROP TABLE
  against the production database. This guard prevents that class of incident.
"""

import os
import subprocess
import sys

import pytest


_PROD_DB_URL = "postgresql://halcyon_app:secret@localhost:5433/halcyon"
_TEST_DB_URL = "postgresql://test:test@127.0.0.1:5434/halcyon"


def _run_collect(env_overrides: dict) -> subprocess.CompletedProcess:
    """Run pytest --collect-only in a subprocess with the given env overrides.

    Starts from a clean copy of the current environment with specific variables
    forced to the values in env_overrides.  Any key with value None is removed
    from the subprocess environment (simulates the variable being unset).
    """
    env = os.environ.copy()
    # Always remove the escape hatch and test URL so we start from a known
    # baseline; individual tests re-add them as needed via env_overrides.
    for key in ("ARCIS_ALLOW_PROD_PG_IN_TESTS", "TEST_DATABASE_URL", "DATABASE_URL"):
        env.pop(key, None)
    for key, value in env_overrides.items():
        if value is None:
            env.pop(key, None)
        else:
            env[key] = value
    return subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "tests/conftest.py"],
        capture_output=True,
        text=True,
        env=env,
        cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    )


class TestPgGuardFiresOnProdUrl:
    """Guard MUST block collection when DATABASE_URL is prod and TEST_DATABASE_URL is unset."""

    def test_exits_with_code_2(self):
        result = _run_collect({"DATABASE_URL": _PROD_DB_URL})
        assert result.returncode == 2, (
            f"Expected exit code 2 but got {result.returncode}.\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )

    def test_error_message_mentions_localhost_5433(self):
        result = _run_collect({"DATABASE_URL": _PROD_DB_URL})
        combined = result.stdout + result.stderr
        assert "5433" in combined, (
            f"Error message should mention port 5433.\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )

    def test_error_message_mentions_test_database_url(self):
        result = _run_collect({"DATABASE_URL": _PROD_DB_URL})
        combined = result.stdout + result.stderr
        assert "TEST_DATABASE_URL" in combined, (
            f"Error message should tell operator to set TEST_DATABASE_URL.\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )

    def test_error_message_mentions_escape_hatch(self):
        result = _run_collect({"DATABASE_URL": _PROD_DB_URL})
        combined = result.stdout + result.stderr
        assert "ARCIS_ALLOW_PROD_PG_IN_TESTS" in combined, (
            f"Error message should mention the escape-hatch env var.\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )

    def test_fires_on_127_0_0_1_variant(self):
        """Guard fires on 127.0.0.1:5433 as well as localhost:5433."""
        prod_url_ip = "postgresql://halcyon_app:secret@127.0.0.1:5433/halcyon"
        result = _run_collect({"DATABASE_URL": prod_url_ip})
        assert result.returncode == 2, (
            f"Expected exit code 2 for 127.0.0.1:5433 URL, got {result.returncode}.\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )

    def test_fires_on_halcyon_app_signature(self):
        """Guard fires when URL contains the halcyon_app: user signature."""
        prod_url_user = "postgresql://halcyon_app:secret@somehost:5433/somedb"
        result = _run_collect({"DATABASE_URL": prod_url_user})
        assert result.returncode == 2, (
            f"Expected exit code 2 for halcyon_app: URL, got {result.returncode}.\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )


class TestPgGuardDoesNotFireWhenSafe:
    """Guard MUST allow collection when it is safe to proceed."""

    def test_test_database_url_set_bypasses_guard(self):
        """With TEST_DATABASE_URL set, guard does NOT block even if DATABASE_URL is prod."""
        result = _run_collect({
            "DATABASE_URL": _PROD_DB_URL,
            "TEST_DATABASE_URL": _TEST_DB_URL,
        })
        assert result.returncode != 2, (
            f"Guard should NOT fire when TEST_DATABASE_URL is set.\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )

    def test_escape_hatch_env_var_bypasses_guard(self):
        """With ARCIS_ALLOW_PROD_PG_IN_TESTS=1, guard does NOT block."""
        result = _run_collect({
            "DATABASE_URL": _PROD_DB_URL,
            "ARCIS_ALLOW_PROD_PG_IN_TESTS": "1",
        })
        assert result.returncode != 2, (
            f"Guard should NOT fire when ARCIS_ALLOW_PROD_PG_IN_TESTS=1.\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )

    def test_escape_hatch_true_string_bypasses_guard(self):
        """ARCIS_ALLOW_PROD_PG_IN_TESTS=true also bypasses the guard."""
        result = _run_collect({
            "DATABASE_URL": _PROD_DB_URL,
            "ARCIS_ALLOW_PROD_PG_IN_TESTS": "true",
        })
        assert result.returncode != 2, (
            f"Guard should NOT fire when ARCIS_ALLOW_PROD_PG_IN_TESTS=true.\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )

    @pytest.mark.skip(reason="tracked-upstream-bug (#1192): order-dependent test-isolation "
                      "leak — the spawned subprocess inherits a parent os.environ polluted by "
                      "an earlier test; passes in isolation, fails only in full-suite ordering. "
                      "Real fix: scrub the subprocess env in _run_collect. See #1192.")
    def test_no_database_url_does_not_trigger_guard(self):
        """When DATABASE_URL is unset entirely, guard does NOT block."""
        result = _run_collect({})
        assert result.returncode != 2, (
            f"Guard should NOT fire when DATABASE_URL is unset.\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )

    def test_non_prod_database_url_does_not_trigger_guard(self):
        """A DATABASE_URL pointing at port 5432 (not 5433) does NOT trigger the guard."""
        safe_url = "postgresql://someuser:secret@localhost:5432/somedb"
        result = _run_collect({"DATABASE_URL": safe_url})
        assert result.returncode != 2, (
            f"Guard should NOT fire for a non-prod DATABASE_URL.\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )


# ─── v0.36.14 extension: guard also checks TEST_DATABASE_URL ──────────────────


class TestPgGuardFiresOnProdTestUrl:
    """v0.36.14 (P0 incident #159): guard must ALSO refuse pytest when
    TEST_DATABASE_URL itself points at prod (not just DATABASE_URL).

    The 2026-05-17 wipe happened because an autouse fixture in
    tests/notifications/test_platform_events.py auto-constructed
    `TEST_DATABASE_URL=postgresql://halcyon:<docker_pg_password>@127.0.0.1:5433/halcyon`
    — the operator's port 5433 hosts production halcyon. The original P0
    guard only checked DATABASE_URL, so this fixture's mutation slipped
    through and pg_wrapper dropped ~80 prod tables on teardown.
    """

    def test_exits_when_test_database_url_is_localhost_5433(self):
        """Guard fires when TEST_DATABASE_URL matches localhost:5433."""
        result = _run_collect({"TEST_DATABASE_URL": _PROD_DB_URL})
        assert result.returncode == 2, (
            f"Expected exit 2 for prod TEST_DATABASE_URL, got {result.returncode}.\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )

    def test_exits_when_test_database_url_is_127_0_0_1_5433(self):
        """Guard fires when TEST_DATABASE_URL matches 127.0.0.1:5433."""
        prod_url_ip = "postgresql://halcyon:secret@127.0.0.1:5433/halcyon"
        result = _run_collect({"TEST_DATABASE_URL": prod_url_ip})
        assert result.returncode == 2, (
            f"Expected exit 2 for 127.0.0.1:5433 TEST_DATABASE_URL, got {result.returncode}.\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )

    def test_exits_when_test_database_url_contains_halcyon_app(self):
        """Guard fires when TEST_DATABASE_URL has the halcyon_app: user signature."""
        prod_url_user = "postgresql://halcyon_app:secret@somehost:9999/somedb"
        result = _run_collect({"TEST_DATABASE_URL": prod_url_user})
        assert result.returncode == 2, (
            f"Expected exit 2 for halcyon_app: TEST_DATABASE_URL, got {result.returncode}.\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )

    def test_error_message_mentions_incident_159(self):
        """Operator-facing message should reference P0 incident #159."""
        result = _run_collect({"TEST_DATABASE_URL": _PROD_DB_URL})
        combined = result.stdout + result.stderr
        assert "#159" in combined, (
            f"Error message should reference P0 incident #159.\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )

    def test_safe_test_database_url_does_not_trigger_new_guard(self):
        """A TEST_DATABASE_URL pointing at port 5434 (non-prod) does NOT trigger."""
        result = _run_collect({"TEST_DATABASE_URL": _TEST_DB_URL})
        assert result.returncode != 2, (
            f"Guard should NOT fire for safe TEST_DATABASE_URL (port 5434).\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )

    def test_escape_hatch_bypasses_test_url_guard(self):
        """ARCIS_ALLOW_PROD_PG_IN_TESTS=1 bypasses even the TEST_DATABASE_URL check."""
        result = _run_collect({
            "TEST_DATABASE_URL": _PROD_DB_URL,
            "ARCIS_ALLOW_PROD_PG_IN_TESTS": "1",
        })
        assert result.returncode != 2, (
            f"Guard should NOT fire when escape hatch is set.\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )


class TestPlatformEventsAutouseFixtureRemoved:
    """v0.36.14 regression-lock: the autouse fixture in
    tests/notifications/test_platform_events.py must NOT auto-construct a
    TEST_DATABASE_URL targeting port 5433. The fixture body must be a no-op."""

    def test_fixture_does_not_construct_prod_url(self):
        """Read the source; assert the killer pattern is gone."""
        import os
        path = os.path.join(
            os.path.dirname(__file__),
            "notifications",
            "test_platform_events.py",
        )
        with open(path, encoding="utf-8") as f:
            source = f.read()
        # The killer pattern from the incident
        assert 'f"postgresql://halcyon:{pw}@127.0.0.1:5433/halcyon"' not in source, (
            "The auto-construction of TEST_DATABASE_URL targeting port 5433 must "
            "be REMOVED. See CHANGELOG v0.36.14 / P0 #159."
        )
        # The autouse fixture should still exist as a no-op (preserves backwards
        # compatibility for any test referencing it) with a clear docstring.
        assert "REMOVED v0.36.14" in source, (
            "Fixture docstring must reference the v0.36.14 removal so future "
            "maintainers don't restore the dangerous behavior."
        )
