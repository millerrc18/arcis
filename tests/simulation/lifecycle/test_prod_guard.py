"""Refuse-if-prod proof tests for install_prod_guard().

These prove the Task-1 safety foundation rejects production-PG access via
BOTH the psycopg2.connect attribute-patch boundary AND the resolved-DSN
(DATABASE_URL) boundary — the latter catching an aliased import that would
otherwise bypass an attribute-level patch.

SAFETY: every assertion is on the raised SimProdGuardError / DSN string.
No test ever lets a connection to 5433 actually run.
"""

import pytest

import psycopg2

from src.simulation.lifecycle.prod_guard import (
    SimProdGuardError,
    install_prod_guard,
)

PROD_DSN_127 = "postgresql://halcyon_app:x@127.0.0.1:5433/halcyon_app"
PROD_DSN_LOCALHOST = "postgresql://user:x@localhost:5433/halcyon"


@pytest.fixture
def guarded_connect(monkeypatch):
    """Install the guard over a sentinel psycopg2.connect and yield the guard.

    The sentinel raises if ever reached, proving the guard short-circuits
    BEFORE any real connection attempt to 5433.
    """

    def _never(*args, **kwargs):  # pragma: no cover - must never be called
        raise AssertionError("real psycopg2.connect reached — guard failed")

    monkeypatch.setattr(psycopg2, "connect", _never)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    install_prod_guard()
    return psycopg2.connect


def test_guard_rejects_127_prod_dsn_via_connect(guarded_connect):
    with pytest.raises(SimProdGuardError) as exc:
        guarded_connect(PROD_DSN_127)
    assert "127.0.0.1:5433" in str(exc.value)
    assert PROD_DSN_127 in str(exc.value)


def test_guard_rejects_localhost_prod_dsn_via_connect(guarded_connect):
    with pytest.raises(SimProdGuardError) as exc:
        guarded_connect(PROD_DSN_LOCALHOST)
    assert PROD_DSN_LOCALHOST in str(exc.value)


def test_guard_rejects_prod_dsn_via_aliased_import(guarded_connect, monkeypatch):
    """An aliased `from psycopg2 import connect` resolves the guarded callable.

    Binding the alias AFTER install proves the guard is the symbol any
    aliased import would capture — there is no escape via aliasing.
    """
    from psycopg2 import connect as aliased_connect

    with pytest.raises(SimProdGuardError) as exc:
        aliased_connect(PROD_DSN_127)
    assert PROD_DSN_127 in str(exc.value)


def test_guard_dsn_boundary_catches_prod_database_url(guarded_connect, monkeypatch):
    """The resolved-DSN boundary rejects a prod DATABASE_URL even when the
    dsn arg passed to connect is safe — proving boundary 2 (the DSN-resolution
    boundary db.py reads from DATABASE_URL) catches it independently.
    """
    monkeypatch.setenv("DATABASE_URL", PROD_DSN_LOCALHOST)
    safe_dsn = "postgresql://test:test@127.0.0.1:5434/halcyon"

    with pytest.raises(SimProdGuardError) as exc:
        guarded_connect(safe_dsn)
    assert "5433" in str(exc.value)
    assert PROD_DSN_LOCALHOST in str(exc.value)
