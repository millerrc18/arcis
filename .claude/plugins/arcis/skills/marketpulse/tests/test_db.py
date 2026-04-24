"""Smoke tests for marketpulse lib.db -- config, SQLite engine, DuckDB.

Uses plain asyncio.run() for async tests to avoid pytest-asyncio version
quirks.  Imports db.py via sys.path manipulation so we don't need
__init__.py files all the way up the tree.
"""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Make ``lib.db`` importable regardless of packaging setup.
# ---------------------------------------------------------------------------
_MP_ROOT = Path(__file__).resolve().parent.parent  # skills/marketpulse
if str(_MP_ROOT) not in sys.path:
    sys.path.insert(0, str(_MP_ROOT))

from lib.db import (  # noqa: E402
    Base,
    MarketPulseConfig,
    bars_glob,
    get_config,
    get_duckdb,
    get_engine,
    init_db,
    reset_config,
)


@pytest.fixture(autouse=True)
def _fresh_config(tmp_path: Path):
    """Reset the global singleton before each test and point at a temp dir."""
    reset_config()
    os.environ["MARKETPULSE_DATA_DIR"] = str(tmp_path)
    yield
    reset_config()
    os.environ.pop("MARKETPULSE_DATA_DIR", None)


# ---- Config ----------------------------------------------------------------

def test_config_defaults(tmp_path: Path):
    cfg = MarketPulseConfig(data_dir=tmp_path)
    assert cfg.concurrency == 10
    assert cfg.rate_limit == 50
    assert cfg.polygon_api_key == ""


def test_ensure_dirs(tmp_path: Path):
    cfg = MarketPulseConfig(data_dir=tmp_path / "mp_data")
    cfg.ensure_dirs()
    assert (tmp_path / "mp_data").is_dir()
    assert (tmp_path / "mp_data" / "bars").is_dir()
    assert (tmp_path / "mp_data" / "custom_lists").is_dir()


def test_db_url(tmp_path: Path):
    cfg = MarketPulseConfig(data_dir=tmp_path)
    assert cfg.db_url.startswith("sqlite+aiosqlite:///")
    assert "metadata.db" in cfg.db_url


def test_get_config_singleton(tmp_path: Path):
    cfg1 = get_config()
    cfg2 = get_config()
    assert cfg1 is cfg2
    assert cfg1.data_dir == tmp_path


# ---- SQLite engine ---------------------------------------------------------

def test_init_db_creates_file(tmp_path: Path):
    """init_db() should create metadata.db on disk."""

    async def _run():
        cfg = get_config()
        cfg.ensure_dirs()
        await init_db()
        engine = get_engine()
        await engine.dispose()

    asyncio.run(_run())
    assert (tmp_path / "metadata.db").exists()


def test_wal_mode(tmp_path: Path):
    """WAL journal mode should be enabled on the connection."""

    async def _run() -> str:
        cfg = get_config()
        cfg.ensure_dirs()
        engine = get_engine()
        async with engine.connect() as conn:
            result = await conn.exec_driver_sql("PRAGMA journal_mode")
            mode = result.scalar()
        await engine.dispose()
        return mode

    mode = asyncio.run(_run())
    assert mode == "wal", f"Expected WAL mode, got {mode}"


# ---- DuckDB ----------------------------------------------------------------

def test_duckdb_select_one():
    con = get_duckdb()
    result = con.execute("SELECT 1 AS value").fetchone()
    assert result == (1,)
    con.close()


def test_duckdb_independent_connections():
    """Each call should return a fresh independent connection."""
    c1 = get_duckdb()
    c2 = get_duckdb()
    assert c1 is not c2
    c1.close()
    c2.close()


# ---- bars_glob -------------------------------------------------------------

def test_bars_glob_ticker_only(tmp_path: Path):
    get_config()  # ensure singleton is initialised
    result = bars_glob("AAPL", "1min")
    assert result.endswith("ticker=AAPL/*.parquet") or \
        result.endswith("ticker=AAPL\\*.parquet")
    assert "timespan=1min" in result


def test_bars_glob_with_year_month(tmp_path: Path):
    get_config()
    result = bars_glob("AAPL", "1min", "2022-06")
    assert result.endswith("2022-06.parquet")
    assert "ticker=AAPL" in result


def test_bars_glob_wildcard_ticker(tmp_path: Path):
    get_config()
    result = bars_glob(None, "1min", "2022-06")
    assert "ticker=*" in result
    assert result.endswith("2022-06.parquet")


def test_bars_glob_uses_real_path(tmp_path: Path):
    """bars_glob must use the actual data_dir, not a literal '~' string."""
    get_config()
    result = bars_glob("MSFT", "day")
    assert "~" not in result
    assert str(tmp_path) in result
