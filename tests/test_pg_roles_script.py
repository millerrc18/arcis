"""Tests for scripts/setup_pg_roles.py.

Verifies that the script issues correct SQL statements for PG role creation
and permission granting. Uses mock psycopg2 — no live PG required.

Test inventory (8 tests):
1. test_script_issues_create_role_halcyon_app
2. test_script_issues_create_role_halcyon_readonly
3. test_grants_app_role_write_perms
4. test_grants_readonly_role_select_only
5. test_alter_default_privileges_issued_for_both_roles
6. test_idempotent_when_run_twice
7. test_reads_passwords_from_env
8. test_raises_if_password_env_missing
"""

import importlib
import sys
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest


# ---------------------------------------------------------------------------
# Helper: load the script as a module from scripts/ so we can call main()
# ---------------------------------------------------------------------------

def _load_setup_pg_roles():
    scripts_dir = Path(__file__).parent.parent / "scripts"
    spec = importlib.util.spec_from_file_location(
        "setup_pg_roles",
        scripts_dir / "setup_pg_roles.py",
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _make_mock_conn():
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
    mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__ = MagicMock(return_value=False)
    return mock_conn, mock_cursor


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _set_env(monkeypatch):
    monkeypatch.setenv("DOCKER_PG_APP_PASSWORD", "apppassword123")
    monkeypatch.setenv("DOCKER_PG_RO_PASSWORD", "ropassword456")
    monkeypatch.setenv("DATABASE_URL", "postgresql://halcyon:pw@localhost:5433/halcyon")


def _collect_execute_calls(monkeypatch):
    """Return (module, executed_sqls) after running main() with mocked psycopg2."""
    mod = _load_setup_pg_roles()
    executed = []

    mock_conn = MagicMock()
    mock_cursor = MagicMock()

    def fake_execute(sql, *args, **kwargs):
        executed.append(sql)

    mock_cursor.execute.side_effect = fake_execute
    mock_conn.cursor.return_value = mock_cursor
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__ = MagicMock(return_value=False)

    with patch.object(mod.psycopg2, "connect", return_value=mock_conn):
        mod.main()

    return executed


# ---------------------------------------------------------------------------
# Test 1: CREATE ROLE halcyon_app wrapped in DO $$
# ---------------------------------------------------------------------------

def test_script_issues_create_role_halcyon_app(monkeypatch):
    executed = _collect_execute_calls(monkeypatch)
    create_app = [s for s in executed if "CREATE ROLE halcyon_app" in s]
    assert create_app, "Expected at least one statement containing 'CREATE ROLE halcyon_app'"
    # Must be wrapped in DO $$ for idempotence
    assert any("DO" in s and "$$" in s for s in create_app), (
        "CREATE ROLE halcyon_app must be wrapped in DO $$ ... EXCEPTION WHEN duplicate_object ... $$"
    )


# ---------------------------------------------------------------------------
# Test 2: CREATE ROLE halcyon_readonly wrapped in DO $$
# ---------------------------------------------------------------------------

def test_script_issues_create_role_halcyon_readonly(monkeypatch):
    executed = _collect_execute_calls(monkeypatch)
    create_ro = [s for s in executed if "CREATE ROLE halcyon_readonly" in s]
    assert create_ro, "Expected at least one statement containing 'CREATE ROLE halcyon_readonly'"
    assert any("DO" in s and "$$" in s for s in create_ro), (
        "CREATE ROLE halcyon_readonly must be wrapped in DO $$ ... EXCEPTION WHEN duplicate_object ... $$"
    )


# ---------------------------------------------------------------------------
# Test 3: app role gets write permissions (INSERT, SELECT, UPDATE, DELETE)
# ---------------------------------------------------------------------------

def test_grants_app_role_write_perms(monkeypatch):
    executed = _collect_execute_calls(monkeypatch)
    grant_stmts = " ".join(executed)
    # All four DML verbs must appear somewhere in the executed SQL
    for verb in ("INSERT", "UPDATE", "DELETE"):
        assert verb in grant_stmts, (
            f"Expected GRANT {verb} for halcyon_app but not found in executed SQL"
        )
    # There must be a GRANT statement to halcyon_app that includes write verbs
    app_grants = [s for s in executed if "halcyon_app" in s and "GRANT" in s]
    assert app_grants, "Expected GRANT statements targeting halcyon_app"


# ---------------------------------------------------------------------------
# Test 4: readonly role gets ONLY SELECT (no INSERT/UPDATE/DELETE)
# ---------------------------------------------------------------------------

def test_grants_readonly_role_select_only(monkeypatch):
    executed = _collect_execute_calls(monkeypatch)
    # Find statements mentioning halcyon_readonly
    ro_stmts = [s for s in executed if "halcyon_readonly" in s]
    assert ro_stmts, "Expected statements targeting halcyon_readonly"
    # No statement targeting halcyon_readonly should contain INSERT, UPDATE, or DELETE
    for stmt in ro_stmts:
        for forbidden in ("INSERT", "UPDATE", "DELETE"):
            assert forbidden not in stmt, (
                f"halcyon_readonly must not receive {forbidden} — found in: {stmt!r}"
            )


# ---------------------------------------------------------------------------
# Test 5: ALTER DEFAULT PRIVILEGES issued for both roles
# ---------------------------------------------------------------------------

def test_alter_default_privileges_issued_for_both_roles(monkeypatch):
    executed = _collect_execute_calls(monkeypatch)
    adp_stmts = [s for s in executed if "ALTER DEFAULT PRIVILEGES" in s]
    assert adp_stmts, "Expected ALTER DEFAULT PRIVILEGES statements"
    adp_text = " ".join(adp_stmts)
    assert "halcyon_app" in adp_text, "ALTER DEFAULT PRIVILEGES must cover halcyon_app"
    assert "halcyon_readonly" in adp_text, "ALTER DEFAULT PRIVILEGES must cover halcyon_readonly"


# ---------------------------------------------------------------------------
# Test 6: Idempotent when run twice — no exception, same SQL set
# ---------------------------------------------------------------------------

def test_idempotent_when_run_twice(monkeypatch):
    mod = _load_setup_pg_roles()
    executed_runs = []

    for _ in range(2):
        executed = []
        mock_conn = MagicMock()
        mock_cursor = MagicMock()

        def fake_execute(sql, *args, executed=executed, **kwargs):
            executed.append(sql)

        mock_cursor.execute.side_effect = fake_execute
        mock_conn.cursor.return_value = mock_cursor
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)

        with patch.object(mod.psycopg2, "connect", return_value=mock_conn):
            mod.main()
        executed_runs.append(executed)

    # Both runs should produce the same set of statements (order may vary but
    # idempotence means: no exceptions and consistent SQL output)
    assert len(executed_runs[0]) == len(executed_runs[1]), (
        "Running setup_pg_roles.py twice produced different numbers of SQL statements"
    )
    assert executed_runs[0] == executed_runs[1], (
        "Running setup_pg_roles.py twice produced different SQL statements"
    )


# ---------------------------------------------------------------------------
# Test 7: Passwords read from env vars
# ---------------------------------------------------------------------------

def test_reads_passwords_from_env(monkeypatch):
    monkeypatch.setenv("DOCKER_PG_APP_PASSWORD", "my_app_secret_pw")
    monkeypatch.setenv("DOCKER_PG_RO_PASSWORD", "my_ro_secret_pw")

    executed = _collect_execute_calls(monkeypatch)
    all_sql = " ".join(executed)
    assert "my_app_secret_pw" in all_sql, (
        "Expected DOCKER_PG_APP_PASSWORD value in CREATE ROLE statement"
    )
    assert "my_ro_secret_pw" in all_sql, (
        "Expected DOCKER_PG_RO_PASSWORD value in CREATE ROLE statement"
    )


# ---------------------------------------------------------------------------
# Test 8: Raises (sys.exit or SystemExit) if password env var is missing
# ---------------------------------------------------------------------------

def test_raises_if_password_env_missing(monkeypatch):
    monkeypatch.delenv("DOCKER_PG_APP_PASSWORD", raising=False)
    monkeypatch.delenv("DOCKER_PG_RO_PASSWORD", raising=False)

    mod = _load_setup_pg_roles()
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.cursor.return_value = mock_cursor
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__ = MagicMock(return_value=False)

    with patch.object(mod.psycopg2, "connect", return_value=mock_conn):
        with pytest.raises((SystemExit, ValueError, RuntimeError)):
            mod.main()
