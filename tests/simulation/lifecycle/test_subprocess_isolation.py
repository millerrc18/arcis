"""Subprocess-isolation proof for the lifecycle DB-isolation guard (T21).

Closes CRITICAL-1 (2026-05-22 prod wipe): a CHILD process spawned by the
simulator must NOT be able to re-read the operator's real `.env` and route
itself back to the production Postgres. The mechanism under test is
`bootstrap.scrubbed_env()`, which carries `ARCIS_DISABLE_DOTENV=1` + the safe
5434 URL. With that flag set, `src/config` skips `load_dotenv`, so a child
spawned in a directory containing a prod-signature `.env` never reads it.

The test spawns a REAL python child (subprocess.run) whose script mirrors the
`src/config` dotenv guard exactly (consult ARCIS_DISABLE_DOTENV before calling
load_dotenv) and then prints the resolved DATABASE_URL. The child is given an
explicit `env=` every time — it NEVER inherits the test runner's environment.

CONTROL: the SAME child spawned WITHOUT the flag DOES resolve the 5433 prod URL
from the temp `.env`, proving the flag is what protects the protected case.

SAFETY: every assertion is on the resolved DSN STRING only. No branch — not
even the control — ever opens a connection to 5433 or 5434. The child script
prints the resolved DSN and exits; it never calls psycopg2.connect/connect_db.
"""

import subprocess
import sys
import textwrap

from src.simulation.lifecycle.bootstrap import scrubbed_env

PROD_DSN = "postgresql://halcyon_app:x@127.0.0.1:5433/halcyon_app"
SIM_DSN = "postgresql://test:test@127.0.0.1:5434/halcyon"

# Child script: mirrors the src/config dotenv guard (ARCIS_DISABLE_DOTENV !=
# "1" -> load_dotenv) using cwd-based discovery, then prints the resolved DSN.
# It NEVER connects — DSN-string resolution only (SCOPE_FENCE).
_CHILD_SCRIPT = textwrap.dedent(
    """
    import os
    from dotenv import load_dotenv
    if os.environ.get("ARCIS_DISABLE_DOTENV") != "1":
        load_dotenv(override=False)
    print(os.environ.get("DATABASE_URL", ""))
    """
)


def _write_prod_env(tmp_path):
    """Write a prod-signature .env into a tmp repo-root-shaped dir; return it."""
    repo_root = tmp_path / "fake_repo"
    repo_root.mkdir()
    (repo_root / ".env").write_text(
        f"DATABASE_URL={PROD_DSN}\n", encoding="utf-8"
    )
    return repo_root


def _run_child(env, cwd):
    """Spawn the DSN-resolving child with an explicit env + cwd."""
    return subprocess.run(
        [sys.executable, "-c", _CHILD_SCRIPT],
        env=env,
        cwd=str(cwd),
        capture_output=True,
        text=True,
    )


def test_scrubbed_env_child_ignores_temp_prod_dotenv(tmp_path):
    """A child run with scrubbed_env() resolves the 5434 URL, NOT the temp prod .env.

    scrubbed_env() carries ARCIS_DISABLE_DOTENV=1, so the child skips
    load_dotenv and never reads the prod-signature .env sitting in its cwd.
    """
    repo_root = _write_prod_env(tmp_path)
    env = scrubbed_env()
    assert env["ARCIS_DISABLE_DOTENV"] == "1"

    result = _run_child(env, repo_root)

    assert result.returncode == 0, result.stderr
    resolved = result.stdout.strip()
    assert resolved == SIM_DSN
    assert "5433" not in resolved
    assert PROD_DSN not in resolved


def test_control_without_flag_would_resolve_temp_prod_dotenv(tmp_path):
    """CONTROL: the SAME child WITHOUT the flag DOES resolve the temp 5433 URL.

    Proves the test is meaningful — the ARCIS_DISABLE_DOTENV=1 flag is the only
    thing protecting the guarded case. We strip the flag AND the safe
    DATABASE_URL from the env so load_dotenv (override=False) populates it from
    the temp prod .env. Still NO live connect — DSN string only.
    """
    repo_root = _write_prod_env(tmp_path)
    env = scrubbed_env()
    env.pop("ARCIS_DISABLE_DOTENV", None)
    env.pop("DATABASE_URL", None)

    result = _run_child(env, repo_root)

    assert result.returncode == 0, result.stderr
    resolved = result.stdout.strip()
    assert resolved == PROD_DSN
    assert "5433" in resolved
