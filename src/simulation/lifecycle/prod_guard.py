"""Production-PG connection guard for the lifecycle simulator.

`install_prod_guard()` makes it impossible for any code path to open a
connection to the production Postgres while the simulator runs. It guards
TWO boundaries with NO escape hatch:

  1. The `psycopg2.connect` symbol (monkeypatched). src/utils/db.py:41 does
     `import psycopg2` unaliased and calls `psycopg2.connect(...)` at L631, so
     patching the module attribute catches that call site AND any
     `from psycopg2 import connect` alias that resolves the same callable.
  2. The DSN-resolution boundary: db.py reads DATABASE_URL at L621 before
     connecting at L631. We re-check the resolved DSN against the prod
     signatures so a prod URL is rejected before the wrapped connect runs.

Any prod-signature DSN (localhost:5433 / 127.0.0.1:5433 / halcyon_app:)
raises SimProdGuardError.

Called by: lifecycle simulator entrypoints (later tasks) via install_prod_guard()
Calls: psycopg2.connect (wrapped)
Owns tables: none
Config keys: none (reads os.environ DATABASE_URL at connect time)
Tests: tests/simulation/lifecycle/test_prod_guard.py (Task 2)
"""

import os

import psycopg2

_PROD_SIGNATURES = ("localhost:5433", "127.0.0.1:5433", "halcyon_app:")


class SimProdGuardError(RuntimeError):
    """Raised when a connection to the production Postgres is attempted."""


def _is_prod_pg_url(url: str) -> bool:
    return bool(url) and any(sig in url for sig in _PROD_SIGNATURES)


def _assert_dsn_safe(dsn) -> None:
    if isinstance(dsn, str) and _is_prod_pg_url(dsn):
        raise SimProdGuardError(
            f"Refusing prod-PG connection: DSN {dsn!r} matches a production "
            "signature. The lifecycle simulator must never reach production."
        )


def install_prod_guard() -> None:
    """Wrap psycopg2.connect and the resolved-DSN boundary against prod PG."""
    _original_connect = psycopg2.connect

    def _guarded_connect(dsn=None, *args, **kwargs):
        # Boundary 2: re-check the DSN db.py resolved from DATABASE_URL (L621).
        _assert_dsn_safe(os.environ.get("DATABASE_URL", ""))
        # Boundary 1: check the DSN actually passed to connect.
        _assert_dsn_safe(dsn)
        return _original_connect(dsn, *args, **kwargs)

    psycopg2.connect = _guarded_connect
