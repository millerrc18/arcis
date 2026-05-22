"""Refuse-if-prod proof tests for the lifecycle bootstrap env scrub.

Proves:
  - assert_safe_db_env() raises on a prod-signature env.
  - importing src.simulation.lifecycle.bootstrap scrubs ARCIS_DB_PATH and
    pins the safe 5434 URL + paper mode + dotenv-disable + hash seed, with
    override-wins ordering over a pre-existing prod DATABASE_URL.
  - scrubbed_env() carries the 5434 URL + ARCIS_DISABLE_DOTENV=1 and no
    prod-signature URL.

SAFETY: assertions are on env strings only — nothing connects to 5433/5434.
"""

import importlib
import os

import pytest

PROD_DSN = "postgresql://halcyon_app:x@127.0.0.1:5433/halcyon_app"
SIM_DSN = "postgresql://test:test@127.0.0.1:5434/halcyon"


def test_assert_safe_db_env_raises_on_prod_signature(monkeypatch):
    from src.simulation.lifecycle.bootstrap import assert_safe_db_env

    monkeypatch.setenv("DATABASE_URL", PROD_DSN)
    with pytest.raises(RuntimeError) as exc:
        assert_safe_db_env()
    assert "DATABASE_URL" in str(exc.value)


def test_assert_safe_db_env_raises_on_prod_test_database_url(monkeypatch):
    from src.simulation.lifecycle.bootstrap import assert_safe_db_env

    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("TEST_DATABASE_URL", "postgresql://x@localhost:5433/y")
    with pytest.raises(RuntimeError) as exc:
        assert_safe_db_env()
    assert "TEST_DATABASE_URL" in str(exc.value)


def test_assert_safe_db_env_passes_on_safe_env(monkeypatch):
    from src.simulation.lifecycle.bootstrap import assert_safe_db_env

    monkeypatch.setenv("DATABASE_URL", SIM_DSN)
    monkeypatch.delenv("TEST_DATABASE_URL", raising=False)
    assert assert_safe_db_env() is None


def test_import_scrubs_and_pins_safe_env(monkeypatch):
    """Importing the bootstrap module rewrites os.environ to the safe state.

    Seeds a PROD DATABASE_URL + ARCIS_DB_PATH first, then forces a fresh
    import so the module-level _scrub_environment() runs against that env.
    Override-wins: the prod DATABASE_URL is overwritten with the 5434 URL.
    """
    monkeypatch.setenv("DATABASE_URL", PROD_DSN)
    monkeypatch.setenv("ARCIS_DB_PATH", "C:/some/prod.db")

    import src.simulation.lifecycle.bootstrap as bootstrap

    importlib.reload(bootstrap)

    assert os.environ["DATABASE_URL"] == SIM_DSN
    assert "ARCIS_DB_PATH" not in os.environ
    assert os.environ["ALPACA_PAPER_TRADE"] == "true"
    assert os.environ["ARCIS_DISABLE_DOTENV"] == "1"
    assert os.environ["PYTHONHASHSEED"] == "0"


def test_scrubbed_env_carries_safe_url_and_no_prod(monkeypatch):
    from src.simulation.lifecycle.bootstrap import scrubbed_env

    monkeypatch.setenv("TEST_DATABASE_URL", PROD_DSN)
    monkeypatch.setenv("ARCIS_DB_PATH", "C:/some/prod.db")

    env = scrubbed_env()

    assert env["DATABASE_URL"] == SIM_DSN
    assert env["ARCIS_DISABLE_DOTENV"] == "1"
    assert "ARCIS_DB_PATH" not in env
    assert "5433" not in env["DATABASE_URL"]
    assert PROD_DSN not in env.get("TEST_DATABASE_URL", "")
