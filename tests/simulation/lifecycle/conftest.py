"""Lifecycle-test env containment.

`src/simulation/lifecycle/bootstrap.py::_scrub_environment()` rewrites
`os.environ` IN PLACE at runtime — it pins DATABASE_URL/TEST_DATABASE_URL to
the sim PG (`postgresql://test:test@127.0.0.1:5434/halcyon`), sets
ARCIS_PG_CUTOVER_ENABLED / ALPACA_PAPER_TRADE / ARCIS_DISABLE_DOTENV /
PYTHONHASHSEED, and POPS ARCIS_DB_PATH. Several lifecycle tests invoke that
bootstrap in-process (test_bootstrap, test_entrypoints, full_gate, …).

Because the write happens inside production code (not the test), `monkeypatch`
cannot revert it: the mutated env LEAKS into every subsequent test in the same
pytest worker. The visible symptom is the chronic CI failure class — ~130
engine-aware / [postgres] tests whose `pg_conn`/`pg_wrapper` fixtures read
`os.environ["TEST_DATABASE_URL"]` at runtime, find the leaked `:5434` URL, and
get "connection refused 127.0.0.1:5434" because the standard pg-tests CI job
only provisions Postgres on 5432. (Collection-order dependent: a test fails only
when a lifecycle test ran before it in the same worker.)

This autouse fixture snapshots `os.environ` before each lifecycle test and fully
restores it afterward, containing the mutation to the test that triggered it.
The scrub still happens DURING the test (post-yield restore), so the lifecycle
tests' own assertions about the scrubbed env are unaffected.
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
