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


def test_import_does_not_scrub_env(monkeypatch):
    """Importing bootstrap must NOT mutate os.environ (#128 / T5).

    The scrub was relocated out of module-level into scoped_scrub(); a bare
    (re)import must leave a seeded prod DATABASE_URL + ARCIS_DB_PATH untouched,
    so importing the simulator can never freeze src.config.DB_PATH=None or leak
    the :5434 gate env into unrelated tests.
    """
    monkeypatch.setenv("DATABASE_URL", PROD_DSN)
    monkeypatch.setenv("ARCIS_DB_PATH", "C:/some/prod.db")

    import src.simulation.lifecycle.bootstrap as bootstrap

    importlib.reload(bootstrap)

    assert os.environ["DATABASE_URL"] == PROD_DSN
    assert os.environ["ARCIS_DB_PATH"] == "C:/some/prod.db"


def test_scoped_scrub_pins_safe_env_then_restores(monkeypatch):
    """scoped_scrub() pins the safe state DURING the block, restores it after.

    Seeds a PROD DATABASE_URL + ARCIS_DB_PATH, enters scoped_scrub(): inside,
    the prod DATABASE_URL is overwritten with the 5434 URL, ARCIS_DB_PATH is
    popped, and paper/dotenv/hashseed are pinned. On exit os.environ is fully
    restored to the seeded prod state (no :5434 leak).
    """
    from src.simulation.lifecycle.bootstrap import scoped_scrub

    monkeypatch.setenv("DATABASE_URL", PROD_DSN)
    monkeypatch.setenv("ARCIS_DB_PATH", "C:/some/prod.db")

    with scoped_scrub():
        assert os.environ["DATABASE_URL"] == SIM_DSN
        assert "ARCIS_DB_PATH" not in os.environ
        assert os.environ["ALPACA_PAPER_TRADE"] == "true"
        assert os.environ["ARCIS_DISABLE_DOTENV"] == "1"
        assert os.environ["PYTHONHASHSEED"] == "0"

    assert os.environ["DATABASE_URL"] == PROD_DSN
    assert os.environ["ARCIS_DB_PATH"] == "C:/some/prod.db"


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
