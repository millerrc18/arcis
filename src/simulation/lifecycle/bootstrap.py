"""Environment scrub for the lifecycle simulator (scoped, NOT import-time).

The simulator must NEVER reach the production Postgres. This module rewrites
os.environ so the simulator targets the safe test PG on 127.0.0.1:5434, but
the scrub is applied ONLY for the duration of a smoke/full run via the
``scoped_scrub()`` context manager (snapshot → scrub → run → restore), NOT as
an import side-effect.

Why scoped, not import-time (test-determinism #128 / T5):
A module-level ``_scrub_environment()`` call popped ARCIS_DB_PATH the instant
this module was imported. That froze ``src.config.DB_PATH = None`` (config
resolves DB_PATH from ARCIS_DB_PATH at its OWN first import) for the rest of the
process, with two consequences: (1) run_smoke's organic scan reached
``connect_db`` with a None db_path → TypeError once the lifecycle conftest's
per-test env-restore took the gate env away; (2) any later import of a
``src.training.*`` module crashed at COLLECTION because
``src/training/training_stop.py`` reads ``os.path.dirname(DB_PATH)`` with
DB_PATH=None. Relocating the scrub into a scoped context manager removes both:
the gate env (DATABASE_URL=:5434 + ARCIS_PG_CUTOVER_ENABLED=1) is active during
the run (so connect_db routes to PG) and fully undone afterward (so it cannot
leak into the ~130 engine-aware tests the conftest protects).

Incident 2026-05-22 (preserved): a test routed to the production PG and wiped
trade tables. ``scoped_scrub()`` still closes that vector — DURING any smoke/full
run it:
  - pops ARCIS_DB_PATH and any prod-signature DATABASE_URL,
  - pins DATABASE_URL to the safe test PG on 127.0.0.1:5434,
  - enables the PG cutover gate + Alpaca paper mode,
  - disables .env loading (so a sim subprocess can't re-read the operator's
    real .env — see the ARCIS_DISABLE_DOTENV guard in src/config/__init__.py),
  - pins PYTHONHASHSEED for determinism.

`_PROD_SIGNATURES` / `_is_prod_pg_url` mirror tests/conftest.py:51 semantics
(copied, NOT imported — src must not depend on test code).

Called by: simulation.lifecycle entrypoints (run_smoke / run_full_gate)
Calls: none
Owns tables: none
Config keys: none (reads/writes os.environ: DATABASE_URL, TEST_DATABASE_URL,
    ARCIS_DB_PATH, ARCIS_PG_CUTOVER_ENABLED, ALPACA_PAPER_TRADE,
    ARCIS_DISABLE_DOTENV, PYTHONHASHSEED)
Tests: tests/simulation/lifecycle/test_bootstrap.py (Task 2),
    tests/simulation/lifecycle/test_entrypoints.py (T5)
"""

import contextlib
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


@contextlib.contextmanager
def scoped_scrub():
    """Apply the env scrub for the duration of a run, then fully restore it.

    Snapshots os.environ, calls ``_scrub_environment()``, yields, and on exit
    restores os.environ exactly (removing keys the scrub added, restoring keys
    it changed or popped). This keeps the prod-isolation INTENT active during a
    smoke/full run while guaranteeing zero leakage of the :5434 gate env into
    any code that runs after the run (test-determinism #128 / T5).
    """
    snapshot = dict(os.environ)
    _scrub_environment()
    try:
        yield
    finally:
        for key in list(os.environ.keys()):
            if key not in snapshot:
                del os.environ[key]
        for key, value in snapshot.items():
            if os.environ.get(key) != value:
                os.environ[key] = value


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
