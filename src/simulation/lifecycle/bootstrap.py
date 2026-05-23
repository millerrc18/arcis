"""FIRST-import environment scrub for the lifecycle simulator.

Importing this module (which the package __init__ does before anything else)
rewrites os.environ so the simulator can NEVER reach the production Postgres.

Incident 2026-05-22: a test routed to the production PG and wiped trade
tables. This module closes that vector for the simulator by:
  - popping ARCIS_DB_PATH and any prod-signature DATABASE_URL,
  - pinning DATABASE_URL to the safe test PG on 127.0.0.1:5434,
  - enabling the PG cutover gate + Alpaca paper mode,
  - disabling .env loading (so a sim subprocess can't re-read the operator's
    real .env — see the ARCIS_DISABLE_DOTENV guard in src/config/__init__.py),
  - pinning PYTHONHASHSEED for determinism.

`_PROD_SIGNATURES` / `_is_prod_pg_url` mirror tests/conftest.py:51 semantics
(copied, NOT imported — src must not depend on test code).

Called by: simulation.lifecycle (package __init__, imported first)
Calls: none
Owns tables: none
Config keys: none (reads/writes os.environ: DATABASE_URL, TEST_DATABASE_URL,
    ARCIS_DB_PATH, ARCIS_PG_CUTOVER_ENABLED, ALPACA_PAPER_TRADE,
    ARCIS_DISABLE_DOTENV, PYTHONHASHSEED)
Tests: tests/simulation/lifecycle/test_bootstrap.py (Task 2)
"""

import os

# Mirror of tests/conftest.py:51 — keep these in sync if the prod PG moves.
_PROD_SIGNATURES = ("localhost:5433", "127.0.0.1:5433", "halcyon_app:")

SIM_DATABASE_URL = "postgresql://test:test@127.0.0.1:5434/halcyon"


def _is_prod_pg_url(url: str) -> bool:
    """Return True when `url` matches any production-PG signature."""
    return bool(url) and any(sig in url for sig in _PROD_SIGNATURES)


def _scrub_environment() -> None:
    """Rewrite os.environ in place so the simulator targets the safe test PG.

    Both DATABASE_URL and TEST_DATABASE_URL are re-pinned to SIM_DATABASE_URL
    after any prod-signature scrub — fallback-pattern fixtures that read
    TEST_DATABASE_URL (24 sites repo-wide) must resolve to the sim URL, not
    empty (#98 review should-fix #3, spec §3.2 step 2 alignment).
    """
    os.environ.pop("ARCIS_DB_PATH", None)
    if _is_prod_pg_url(os.environ.get("DATABASE_URL", "")):
        os.environ.pop("DATABASE_URL", None)
    if _is_prod_pg_url(os.environ.get("TEST_DATABASE_URL", "")):
        os.environ.pop("TEST_DATABASE_URL", None)
    os.environ["DATABASE_URL"] = SIM_DATABASE_URL
    os.environ["TEST_DATABASE_URL"] = SIM_DATABASE_URL
    os.environ["ARCIS_PG_CUTOVER_ENABLED"] = "1"
    os.environ["ALPACA_PAPER_TRADE"] = "true"
    os.environ["ARCIS_DISABLE_DOTENV"] = "1"
    os.environ["PYTHONHASHSEED"] = "0"


def assert_safe_db_env() -> None:
    """Raise RuntimeError if DATABASE_URL/TEST_DATABASE_URL points at prod PG."""
    for var in ("DATABASE_URL", "TEST_DATABASE_URL"):
        url = os.environ.get(var, "")
        if _is_prod_pg_url(url):
            raise RuntimeError(
                f"{var} matches a production-PG signature ({url!r}); "
                "refusing to run the simulator against production."
            )


def scrubbed_env() -> dict:
    """Return a sanitized copy of os.environ for child-process `env=`.

    Guarantees the copy carries the safe 5434 URL + ARCIS_DISABLE_DOTENV=1
    and no prod-signature DATABASE_URL/TEST_DATABASE_URL, so a subprocess
    cannot re-acquire the production PG (closes the subprocess wipe-vector).
    """
    env = dict(os.environ)
    env.pop("ARCIS_DB_PATH", None)
    if _is_prod_pg_url(env.get("TEST_DATABASE_URL", "")):
        env.pop("TEST_DATABASE_URL", None)
    env["DATABASE_URL"] = SIM_DATABASE_URL
    env["TEST_DATABASE_URL"] = SIM_DATABASE_URL
    env["ARCIS_DISABLE_DOTENV"] = "1"
    return env


# Scrub on import — this is the whole point of the module.
_scrub_environment()
