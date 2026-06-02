"""Lifecycle-test env containment (defense-in-depth).

`src/simulation/lifecycle/bootstrap.py::_scrub_environment()` rewrites
`os.environ` IN PLACE — it pins DATABASE_URL/TEST_DATABASE_URL to the sim PG
(`postgresql://test:test@127.0.0.1:5434/halcyon`), sets ARCIS_PG_CUTOVER_ENABLED
/ ALPACA_PAPER_TRADE / ARCIS_DISABLE_DOTENV / PYTHONHASHSEED, and POPS
ARCIS_DB_PATH.

As of test-determinism #128 / T5 the scrub is NO LONGER an import side-effect:
the run entrypoints (run_smoke / run_full_gate) apply it via
`bootstrap.scoped_scrub()` (snapshot → scrub → run → restore), so the gate env
is active only during a run and self-restores afterward. That alone closes the
historical leak — the chronic CI failure class where ~130 engine-aware /
[postgres] tests read a leaked `:5434` URL at runtime and hit "connection
refused 127.0.0.1:5434" (the standard pg-tests CI job provisions PG on 5432).

This autouse fixture is retained as belt-and-suspenders: it snapshots
`os.environ` before each lifecycle test and fully restores it afterward, so even
a test that calls `_scrub_environment()` directly (e.g. test_bootstrap) cannot
leak the mutation into a later test in the same worker.
"""

import os

import pytest


@pytest.fixture(autouse=True)
def _contain_lifecycle_env_mutation():
    snapshot = dict(os.environ)
    try:
        yield
    finally:
        # Remove keys the test added, restore keys it changed or deleted.
        for key in list(os.environ.keys()):
            if key not in snapshot:
                del os.environ[key]
        for key, value in snapshot.items():
            if os.environ.get(key) != value:
                os.environ[key] = value
